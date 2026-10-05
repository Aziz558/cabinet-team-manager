"""pennylane — integration Pennylane + error handlers (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/pennylane/tva_session', methods=['POST'])
@login_required
def pennylane_tva_session():
    """Enregistre (en mémoire uniquement) les cookies de session web Pennylane."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    payload = request.get_json(silent=True) or request.form
    cookies = (payload.get('cookies') or '').strip()
    firm_id = payload.get('firm_id') or 76917
    from app.integrations.pennylane_web import set_web_session, test_web_session
    set_web_session(cookies, firm_id)
    res = test_web_session()
    return jsonify(res)


@app.route('/pennylane/tva_session_status')
@login_required
def pennylane_tva_session_status():
    """Statut de la session web (pour l'UI)."""
    from app.integrations.pennylane_web import has_web_session, test_web_session
    if not has_web_session():
        return jsonify({'ok': False, 'configured': False, 'message': 'Session non configurée.'})
    if current_user.role != 'admin':
        return jsonify({'ok': True, 'configured': True, 'message': 'Session active.'})
    res = test_web_session()
    res['configured'] = True
    return jsonify(res)


@app.route('/pennylane/tva_sync', methods=['POST'])
@login_required
def pennylane_tva_sync():
    """Synchronise les statuts de déclaration TVA depuis l'espace web Pennylane."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    from app.integrations.pennylane_web import sync_checklist_tva
    res = sync_checklist_tva()
    return jsonify(res)


@app.route('/checklist/pl_sync_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def checklist_pl_sync_dossier(dossier_id):
    """Re-synchronise UN dossier depuis l'espace web Pennylane (bouton ⟳ de la grille).
    Accessible aux managers et admins (hamza peut relancer sans attendre l'heure :10)."""
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'message': 'Accès réservé aux managers.'}), 403
    from app.models import Dossier
    d = Dossier.query.get_or_404(dossier_id)
    if not (d.pennylane_customer_id or '').strip():
        # Auto-association via l'API Company (token du dossier puis global) :
        # le dossier a un token API dédié -> on retrouve le company ID tout seul.
        from app.integrations.pennylane import resolve_company_for_dossier
        res_auto = resolve_company_for_dossier(d)
        if res_auto.get('ok'):
            d.pennylane_customer_id = res_auto['company_id']
            db.session.commit()
            app.logger.info(f"Pennylane: dossier {d.numero_dossier} relié AUTO à company "
                            f"{res_auto['company_id']} via {res_auto.get('via')} (sync ⟳)")
        else:
            return jsonify({'ok': False,
                            'message': f"Dossier non relié et auto-association impossible : "
                                       f"{res_auto.get('message')}. Vérifiez le token API du dossier "
                                       f"ou faites l'association manuelle (admin)."}), 400
    from app.integrations.pennylane_web import has_web_session
    if not has_web_session():
        return jsonify({'ok': False, 'message': 'Session web Pennylane non configurée (page Intégration).'}), 400

    from app.integrations.pennylane_web import (fetch_vat_forms, _vat_taxe_for,
                                                _extract_period, _save_last_sync,
                                                FILED_STATUSES)
    from app.models import ChecklistEntry, TvaStatutPennylane
    from datetime import date as _date, datetime as _dt

    res = fetch_vat_forms(d.pennylane_customer_id)
    if not res['ok']:
        _save_last_sync(ok=False, message=f"{d.numero_dossier}: {res['message']}")
        return jsonify(res)
    if not (res['vat_returns'] or res['future_vat_returns']):
        _msg = (f"{d.numero_dossier} : Pennylane a répondu OK mais n'a retourné AUCUNE période "
                f"TVA — session à revérifier (page Intégration).")
        _save_last_sync(ok=False, message=_msg)
        return jsonify({'ok': False, 'message': _msg})

    taxe = _vat_taxe_for(d)
    statuts = 0
    forces_annules = 0
    synced = 0

    # Miroir + neutralisation des forçages manuels sur périodes connues de PL
    for vr in (res['vat_returns'] + res['future_vat_returns']):
        per = _extract_period(vr)
        if not per:
            continue
        y, mo = per
        if taxe == 'tva_trimestriel':
            mo = ((mo - 1) // 3) * 3 + 1
        st = (vr.get('status') or '').lower()
        st_row = TvaStatutPennylane.query.filter_by(dossier_id=d.id, annee=y, mois=mo).first()
        if not st_row:
            st_row = TvaStatutPennylane(dossier_id=d.id, annee=y, mois=mo)
            db.session.add(st_row)
        st_row.statut = st or 'unknown'
        st_row.deadline = vr.get('deadline') or None
        payable = vr.get('payable') or vr.get('amount_due') or vr.get('total_amount')
        try:
            st_row.montant = float(payable) if payable is not None else None
        except (TypeError, ValueError):
            st_row.montant = None
        st_row.date_sync = _dt.utcnow()
        statuts += 1
        old = ChecklistEntry.query.filter_by(dossier_id=d.id, taxe=taxe,
                                             annee=y, mois=mo, kind='depot').first()
        if old and old.pl_mode and not (old.declare or old.paye):
            db.session.delete(old)
            forces_annules += 1

    # Cases cochées : déclarations réellement faites dans PL
    for vr in res['vat_returns']:
        st = (vr.get('status') or '').lower()
        if st not in FILED_STATUSES:
            continue
        per = _extract_period(vr)
        if not per:
            continue
        y, mo = per
        if taxe == 'tva_trimestriel':
            mo = ((mo - 1) // 3) * 3 + 1
        e = ChecklistEntry.query.filter_by(dossier_id=d.id, taxe=taxe,
                                           annee=y, mois=mo, kind='depot').first()
        if not e:
            e = ChecklistEntry(dossier_id=d.id, taxe=taxe, annee=y, mois=mo, kind='depot')
            db.session.add(e)
        e.declare = True
        e.paye = (st == 'paid')
        e.pl_mode = True
        synced += 1

    db.session.commit()
    msg = (f"{d.numero_dossier} : {statuts} statut(s) Pennylane enregistré(s), "
           f"{synced} case(s) cochée(s), {forces_annules} forçage(s) manuel(s) annulé(s).")
    # LIAISON Pennylane -> taches : les cases cochees par la synchro terminent
    # les taches deadline correspondantes (ex. aout declare dans PL -> "Dépôt TVA
    # mensuel" termine).
    try:
        from .checklist_link import appliquer_case_a_taches as _lk
        n_lk = 0
        for vr in res['vat_returns']:
            if (vr.get('status') or '').lower() not in FILED_STATUSES:
                continue
            per = _extract_period(vr)
            if not per:
                continue
            y, mo = per
            if taxe == 'tva_trimestriel':
                mo = ((mo - 1) // 3) * 3 + 1
            n_lk += _lk(d.id, taxe, y, mo, 'depot', True)
        if n_lk:
            db.session.commit()
            msg += f" {n_lk} tâche(s) deadline auto-terminée(s)."
    except Exception as _lk_e:
        db.session.rollback()
        app.logger.warning(f"Liaison sync->taches {d.numero_dossier}: {_lk_e}")
    _save_last_sync(ok=True, message=msg)
    return jsonify({'ok': True, 'message': msg, 'statuts': statuts,
                    'synced': synced, 'forces_annules': forces_annules})


@app.route('/checklist/pl_sync_all', methods=['POST'])
@login_required
def checklist_pl_sync_all():
    """Resynchronise TOUS les dossiers reliés (bouton « Vérifier maintenant » de la grille).
    Accessible managers + admins — même logique que le passage automatique horaire."""
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'message': 'Accès réservé aux managers.'}), 403
    from app.integrations.pennylane_web import has_web_session, sync_checklist_tva
    if not has_web_session():
        return jsonify({'ok': False, 'message': 'Session web Pennylane non configurée (page Intégration).'}), 400
    res = sync_checklist_tva()
    return jsonify(res)


@app.route('/pennylane/associer_dossier', methods=['POST'])
@login_required
def pennylane_associer_dossier():
    """Relie manuellement un dossier à une company Pennylane (admin).
    Nécessaire quand le matching automatique par nom/SIRET échoue
    (ex. Pro Store : nom client PL différent de l'intitulé du dossier)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    from app.models import Dossier
    try:
        dossier_id = int(request.form.get('dossier_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Dossier invalide.'}), 400
    company_id = (request.form.get('company_id') or '').strip()
    if not dossier_id or not company_id:
        return jsonify({'ok': False, 'message': 'Dossier et company ID requis.'}), 400
    d = Dossier.query.get(dossier_id)
    if not d:
        return jsonify({'ok': False, 'message': 'Dossier introuvable.'}), 404
    d.pennylane_customer_id = company_id
    db.session.commit()
    app.logger.info(f"Pennylane: dossier {d.numero_dossier} (id {d.id}) relié manuellement à company {company_id}")
    return jsonify({'ok': True,
                    'message': f"Dossier {d.numero_dossier} relié à la company Pennylane {company_id}. "
                               f"Lance une synchro TVA pour récupérer les périodes."})


@app.route('/pennylane/auto_associer_dossier', methods=['POST'])
@login_required
def pennylane_auto_associer_dossier():
    """Retrouve AUTOMATIQUEMENT le company ID d'un dossier via l'API Company
    Pennylane (token du dossier en priorité, sinon token global du cabinet,
    match par nom normalisé + fallback /me) puis relie le dossier.
    Admin uniquement, comme l'association manuelle."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    from app.models import Dossier
    try:
        dossier_id = int(request.form.get('dossier_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Dossier invalide.'}), 400
    if not dossier_id:
        return jsonify({'ok': False, 'message': 'Dossier requis.'}), 400
    d = Dossier.query.get(dossier_id)
    if not d:
        return jsonify({'ok': False, 'message': 'Dossier introuvable.'}), 404
    from app.integrations.pennylane import resolve_company_for_dossier
    from app.integrations.pennylane_web import _save_last_sync
    res = resolve_company_for_dossier(d)
    if not res.get('ok'):
        msg = res.get('message') or 'Company introuvable.'
        _save_last_sync(ok=False, message=f"{d.numero_dossier}: auto-association échouée — {msg}")
        return jsonify({'ok': False, 'message': f"{d.numero_dossier} : {msg}"}), 400
    cid = res['company_id']
    if (d.pennylane_customer_id or '').strip() == cid:
        return jsonify({'ok': True,
                        'message': f"Dossier {d.numero_dossier} déjà relié à la company {cid}"
                                   f" ({res.get('company_name') or '?'})."})
    d.pennylane_customer_id = cid
    db.session.commit()
    app.logger.info(f"Pennylane: dossier {d.numero_dossier} (id {d.id}) relié AUTO à company {cid} via {res.get('via')}")
    _save_last_sync(ok=True,
                    message=f"{d.numero_dossier}: auto-association réussie → company {cid} "
                            f"({res.get('company_name') or '?'}, via {res.get('via')})")
    return jsonify({'ok': True,
                    'message': f"Dossier {d.numero_dossier} relié automatiquement à la company {cid}"
                               f" ({res.get('company_name') or '?'}). Lance une synchro TVA pour récupérer les périodes."})



@app.route('/pennylane/delier_dossier', methods=['POST'])
@login_required
def pennylane_delier_dossier():
    """Délie un dossier de sa company Pennylane (admin) et nettoie les traces
    de synchro : statuts TvaStatutPennylane + cases ChecklistEntry posées par la
    synchro (pl_mode=True). Les saisies 100% manuelles sont conservées.
    Utilisé pour tester l'affichage PL sur un autre dossier puis restaurer l'état."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    from app.models import Dossier, TvaStatutPennylane, ChecklistEntry
    try:
        dossier_id = int(request.form.get('dossier_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'message': 'Dossier invalide.'}), 400
    d = Dossier.query.get(dossier_id)
    if not d:
        return jsonify({'ok': False, 'message': 'Dossier introuvable.'}), 404
    if not (d.pennylane_customer_id or '').strip():
        return jsonify({'ok': False, 'message': f'{d.numero_dossier} n\'est relié à aucune company.'}), 400
    n_st = TvaStatutPennylane.query.filter_by(dossier_id=d.id).delete()
    n_ce = ChecklistEntry.query.filter_by(dossier_id=d.id, pl_mode=True).delete()
    d.pennylane_customer_id = None
    db.session.commit()
    app.logger.info(f"Pennylane: dossier {d.numero_dossier} (id {d.id}) délié — {n_st} statut(s), {n_ce} case(s) synchro supprimée(s)")
    return jsonify({'ok': True,
                    'message': f"Dossier {d.numero_dossier} délié ({n_st} statut(s) PL, {n_ce} case(s) synchro supprimée(s))."})


@app.route('/pennylane')
@login_required
def pennylane_page():
    """Page de configuration et statut de l'intégration Pennylane.
       Admin : configuration complète + vue globale.
       Manager : vue limitée aux dossiers de SES équipes (lecture seule)."""
    from app.integrations.pennylane import get_pennylane_token
    is_admin = current_user.role == 'admin'
    if not is_admin and current_user.role != 'manager':
        flash('Accès réservé aux administrateurs et managers.', 'danger')
        return redirect(url_for('dashboard'))

    # Scoping des dossiers : admin voit tout, manager voit les dossiers de ses équipes
    if is_admin:
        dossiers_pl = Dossier.query.order_by(Dossier.numero_dossier).all()
        equipes_list = Equipe.query.order_by(Equipe.nom).all()
    else:
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        equipe_ids = [eq.id for eq in mes_equipes]
        dossiers_pl = Dossier.query.filter(Dossier.equipe_id.in_(equipe_ids)).order_by(Dossier.numero_dossier).all()
        equipes_list = mes_equipes

    # Grouper les dossiers associés par équipe
    # Un dossier est "connecté" s'il a un customer_id OU un token API dédié
    dossiers_associes = [d for d in dossiers_pl if d.pennylane_customer_id or d.pennylane_api_token]
    dossiers_non_associes = [d for d in dossiers_pl if not (d.pennylane_customer_id or d.pennylane_api_token)]
    par_equipe = {}
    for d in dossiers_associes:
        nom_eq = d.equipe.nom if d.equipe else 'Sans équipe'
        par_equipe.setdefault(nom_eq, []).append(d)

    token = get_pennylane_token()
    configured = bool(token)
    test_result = None
    if configured and is_admin:
        try:
            from app.integrations.pennylane import test_connexion
            test_result = test_connexion()
        except Exception:
            test_result = {'ok': False, 'message': 'Erreur lors du test de connexion.'}
    # Dernier passage de la synchro TVA (auto ou manuel) — carte admin
    pl_last_sync = None
    if is_admin:
        try:
            import json as _json
            from app.models import AppSetting as _AppSetting
            _ls = _AppSetting.query.filter_by(cle='PENNYLANE_WEB_LAST_SYNC').first()
            if _ls and _ls.valeur:
                pl_last_sync = _json.loads(_ls.valeur)
        except Exception:
            pl_last_sync = None
    return render_template('pennylane.html', configured=configured, test_result=test_result,
                           pl_last_sync=pl_last_sync,
                           is_admin=is_admin,
                           dossiers_associes=dossiers_associes, dossiers_non_associes=dossiers_non_associes,
                           par_equipe=par_equipe, equipes_list=equipes_list,
                           total_dossiers=len(dossiers_pl),
                           token_masque=('••••' + token[-4:]) if configured and len(token) > 4 else ('••••' if configured else ''))


@app.route('/pennylane/config', methods=['POST'])
@login_required
def pennylane_config():
    """Sauvegarde le token Pennylane et teste la connexion."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    token = (request.form.get('api_token') or '').strip()
    from app.integrations.pennylane import save_pennylane_token, test_connexion
    save_pennylane_token(token)
    result = test_connexion(token) if token else {'ok': False, 'message': 'Token effacé.'}
    return jsonify(result)


@app.route('/pennylane/sync', methods=['POST'])
@login_required
def pennylane_sync():
    """Lance la synchronisation des dossiers avec les clients Pennylane."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès réservé aux administrateurs.'}), 403
    try:
        from app.integrations.pennylane import sync_dossiers_pennylane
        result = sync_dossiers_pennylane()
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'message': f'Erreur synchro: {str(e)}'})


@app.route('/pennylane/dossier/<int:dossier_id>')
@login_required
def pennylane_dossier(dossier_id):
    """Données Pennylane associées à un dossier (factures, écritures)."""
    dossier = Dossier.query.get_or_404(dossier_id)
    # Scoping par équipe/manager : chaque manager ne voit que les dossiers de SES équipes
    if current_user.role == 'admin':
        pass  # admin voit tout
    elif current_user.role == 'manager':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if dossier.equipe_id not in mes_equipes_ids:
            flash('Accès refusé : ce dossier ne fait pas partie de vos équipes.', 'danger')
            return redirect(url_for('dossiers'))
    else:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from app.integrations.pennylane import get_dossier_pennylane_data
        data = get_dossier_pennylane_data(dossier)
    except Exception as e:
        import traceback
        app.logger.error(f'pennylane_dossier {dossier_id}: {e}\n{traceback.format_exc()}')
        data = {'ok': False, 'message': str(e), 'factures': [], 'factures_fournisseurs': [],
                'ecritures': [], 'transactions': [], 'source_token': None}

    # Fusionner les 3 natures en une seule liste pour le tableau unifié
    lignes = []
    # Indexer les PennylaneItem (type, api_id) -> db_id
    pl_items_db = {(it.item_type, it.item_id): it.id
                   for it in PennylaneItem.query.filter_by(dossier_id=dossier.id).all()}
    for f in data.get('factures', []):
        lignes.append({
            'nature': 'vente',
            'nature_label': 'Vente',
            'numero': f.get('numero') or '—',
            'date': (f.get('date') or '')[:10],
            'libelle': f.get('numero') or '—',
            'montant': f.get('montant_ttc'),
            'statut_fr': f.get('statut_fr') or '',
            'statut_traitement': f.get('statut_traitement') or 'a_traiter',
            'item_id': f.get('id'),
            'db_id': pl_items_db.get(('facture_vente', str(f.get('id') or ''))),
            'ajout_date': str(f.get('ajout_date') or ''),
            'nouveau': f.get('nouveau', False),
        })
    for f in data.get('factures_fournisseurs', []):
        lignes.append({
            'nature': 'achat',
            'nature_label': 'Achat',
            'numero': f.get('numero') or '—',
            'date': (f.get('date') or '')[:10],
            'libelle': f.get('numero') or '—',
            'montant': f.get('montant_ttc'),
            'statut_fr': f.get('statut_fr') or '',
            'statut_traitement': f.get('statut_traitement') or 'a_traiter',
            'item_id': f.get('id'),
            'db_id': pl_items_db.get(('facture_achat', str(f.get('id') or ''))),
            'ajout_date': str(f.get('ajout_date') or ''),
            'nouveau': f.get('nouveau', False),
        })
    for t in data.get('transactions', []):
        lignes.append({
            'nature': 'banque',
            'nature_label': 'Flux bancaire',
            'numero': t.get('libelle') or '—',
            'date': (t.get('date') or '')[:10],
            'libelle': t.get('libelle') or '—',
            'montant': t.get('montant'),
            'statut_fr': t.get('statut_fr') or '',
            'statut_traitement': t.get('statut_traitement') or 'a_traiter',
            'item_id': t.get('id'),
            'db_id': pl_items_db.get(('transaction', str(t.get('id') or ''))),
            'ajout_date': str(t.get('ajout_date') or ''),
            'nouveau': t.get('nouveau', False),
        })
    # Extrait l'exercice (année) de la date d'émission
    for l in lignes:
        try:
            y = (l['date'] or '')[:4]
            l['exercice'] = int(y) if y.isdigit() and 2000 <= int(y) <= 2100 else None
        except (ValueError, IndexError):
            l['exercice'] = None

    # Filtre par exercice (défaut : année en cours, comme Pennylane)
    try:
        exercice_filtre = int(request.args.get('exercice') or str(date.today().year))
    except (ValueError, TypeError):
        exercice_filtre = date.today().year
    lignes_filtrees = [l for l in lignes if l['exercice'] == exercice_filtre]

    # Tri : les plus récents en premier
    lignes_filtrees.sort(key=lambda x: (x['date'] or ''), reverse=True)

    # Filtre par nature côté serveur ('', 'vente', 'achat', 'banque') — compteurs TOUJOURS justes
    nature_filtre = request.args.get('nature') or ''
    if nature_filtre not in ('', 'vente', 'achat', 'banque'):
        nature_filtre = ''
    lignes_affichees = [l for l in lignes_filtrees if not nature_filtre or l['nature'] == nature_filtre]

    def _ftab(sf):
        """Mapping statut Pennylane -> onglet (identique au data-ftab du template).
        3 statuts : À traiter (ex-Prétraité fusionné), Traité, Archivé."""
        if sf == 'Archivé':
            return 'archive'
        if sf in ('Traité', 'Avoir', 'Annulé'):
            return 'traite'
        # 'Prétraité' (anciennes chaînes en cache DB) fusionné dans À traiter
        return 'a_traiter'

    data['lignes'] = lignes_affichees
    data['exercice_actif'] = exercice_filtre
    data['nature_actif'] = nature_filtre
    data['nb_total'] = len(lignes_filtrees)
    data['nb_ventes'] = sum(1 for l in lignes_filtrees if l['nature'] == 'vente')
    data['nb_achats'] = sum(1 for l in lignes_filtrees if l['nature'] == 'achat')
    data['nb_banque'] = sum(1 for l in lignes_filtrees if l['nature'] == 'banque')
    # Compteurs d'onglets : dérivés du statut PENNYLANE (statut_fr), même mapping que data-ftab
    data['cnt_toutes'] = len(lignes_affichees)
    data['cnt_a_traiter'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) in ('a_traiter', 'pretraite'))
    data['cnt_traite'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'traite')
    data['cnt_archive'] = sum(1 for l in lignes_affichees if _ftab(l['statut_fr']) == 'archive')

    data['nb_a_traiter'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) in ('a_traiter', 'pretraite'))
    data['nb_traite'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'traite')
    data['nb_archive'] = sum(1 for l in lignes_filtrees if _ftab(l['statut_fr']) == 'archive')

    # JSON compact de toutes les lignes (rendu + filtres 100% client, zéro rechargement)
    data['lignes_json'] = json.dumps([{
        'n': l['nature'], 'f': _ftab(l['statut_fr']), 'sf': l['statut_fr'],
        'num': l['libelle'] or '—', 'd': (l['date'] or ''),
        'ad': (l['ajout_date'] or ''), 'm': l['montant'],
        'st': l['statut_traitement'] or 'a_traiter', 'id': l['db_id'],
        'nw': bool(l['nouveau']),
    } for l in lignes_filtrees], separators=(',', ':'), ensure_ascii=False)

    return render_template('pennylane_dossier.html', dossier=dossier, data=data)







@app.route('/pennylane/item/<int:item_db_id>/statut', methods=['POST'])
@login_required
def pennylane_item_statut(item_db_id):
    """Change le statut de traitement d'un item Pennylane (a_traiter / traite / ignore)."""
    from app.models import PennylaneItem
    item = PennylaneItem.query.get_or_404(item_db_id)
    dossier = Dossier.query.get_or_404(item.dossier_id)

    # Scoping : admin, manager de l'équipe du dossier, ou collaborateur du dossier
    if current_user.role != 'admin':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if item.dossier_id not in [d.id for d in Dossier.query.filter(
                Dossier.equipe_id.in_(mes_equipes_ids)).all()] and dossier.collaborateur_id != current_user.id:
            return jsonify({'ok': False, 'message': 'Accès refusé'}), 403

    statut = (request.json or {}).get('statut') if request.is_json else request.form.get('statut')
    if statut not in ('a_traiter', 'traite', 'ignore'):
        return jsonify({'ok': False, 'message': 'Statut invalide'}), 400

    item.statut = statut
    item.statut_par_id = current_user.id
    item.statut_date = datetime.utcnow()
    db.session.commit()
    try:
        from app.integrations.pennylane import invalidate_dossier_cache
        invalidate_dossier_cache(item.dossier_id)
    except Exception:
        pass
    return jsonify({'ok': True, 'statut': statut})


@app.route('/pennylane/items/statut_bulk', methods=['POST'])
@login_required
def pennylane_items_statut_bulk():
    """Change le statut de plusieurs items Pennylane en une fois."""
    from app.models import PennylaneItem
    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids') or []
    statut = payload.get('statut')
    if not ids or statut not in ('a_traiter', 'traite', 'ignore'):
        return jsonify({'ok': False, 'message': 'Paramètres invalides'}), 400

    items = PennylaneItem.query.filter(PennylaneItem.id.in_(ids)).all()
    updated = 0
    for item in items:
        dossier = Dossier.query.get_or_404(item.dossier_id)
        # Scoping : admin, manager de l'équipe du dossier, ou collaborateur du dossier
        if current_user.role != 'admin':
            mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
            dossiers_autorises = [d.id for d in Dossier.query.filter(
                Dossier.equipe_id.in_(mes_equipes_ids)).all()]
            if item.dossier_id not in dossiers_autorises and dossier.collaborateur_id != current_user.id:
                continue  # skip les items non autorisés
        item.statut = statut
        item.statut_par_id = current_user.id
        item.statut_date = datetime.utcnow()
        updated += 1
    db.session.commit()
    if updated:
        dossier_ids = {it.dossier_id for it in items}
        try:
            from app.integrations.pennylane import invalidate_dossier_cache
            for did in dossier_ids:
                invalidate_dossier_cache(did)
        except Exception:
            pass
    return jsonify({'ok': True, 'updated': updated})


@app.route('/pennylane/check/<int:dossier_id>', methods=['POST'])
@login_required
def pennylane_check(dossier_id):
    """Vérifie les nouveaux documents/transactions Pennylane d'un dossier (à la demande)."""
    dossier = Dossier.query.get_or_404(dossier_id)

    # Même scoping que pennylane_dossier
    if current_user.role != 'admin':
        mes_equipes_ids = [eq.id for eq in Equipe.query.filter_by(manager_id=current_user.id).all()]
        if dossier.equipe_id not in mes_equipes_ids and dossier.collaborateur_id != current_user.id:
            return jsonify({'ok': False, 'message': 'Accès refusé'}), 403

    from app.integrations.pennylane import get_dossier_pennylane_data
    data = get_dossier_pennylane_data(dossier, force_refresh=True)
    resp = {'ok': data.get('ok'),
            'nouveaux': data.get('nouveaux', []),
            'resume': data.get('resume_nouveaux', ''),
            'message': data.get('message', '')}
    # SONDE TEMPORAIRE (diagnostic compteurs) — à retirer après diagnostic
    if data.get('debug_probe'):
        resp['debug_probe'] = data['debug_probe']
    return resp


@app.route('/pennylane/probe', methods=['GET', 'POST'])
@login_required
def pennylane_probe():
    """Check de santé / diagnostic Pennylane (permanent).

    Usage :
      /pennylane/probe?probe=health                     -> état cookies + ventes Pro Store (23281030)
      /pennylane/probe?probe=dossiers                   -> liste dossiers + company_id associés
      /pennylane/probe?probe=diag&dossier=2             -> diag complet d'un dossier app
      /pennylane/probe?probe=diag&company_id=XXXX       -> diag complet d'une société Pennylane

    diag = compteurs VENTES (statuts bruts + count_summary UI) et BANQUE
    (statuts bruts API interne + fallback externe) — pour comparer à l'UI.
    """
    import requests as _rq
    from app.models import Dossier as _Dossier

    customer_id = request.args.get('company_id', '', type=str)
    probe_name = request.args.get('probe', 'health', type=str)
    out = {'probe': probe_name, 'company_id': customer_id or None}

    # ---- probe=dossiers : liste des dossiers + leur company_id ----
    if probe_name == 'dossiers':
        out['dossiers'] = [
            {'id': d.id, 'intitule': d.intitule,
             'company_id': d.pennylane_customer_id,
             'has_token': bool((d.pennylane_api_token or '').strip())}
            for d in _Dossier.query.order_by(_Dossier.id).all()]
        return out

    # ---- résolution company_id (direct ou via dossier app) ----
    dossier_ref = request.args.get('dossier', '', type=str)
    if dossier_ref and not customer_id:
        d = _Dossier.query.get(int(dossier_ref))
        if d is None:
            return {'probe': probe_name, 'err': f'dossier {dossier_ref} introuvable'}, 404
        customer_id = (d.pennylane_customer_id or '').strip()
        out['dossier'] = {'id': d.id, 'intitule': d.intitule}
    if not customer_id:
        customer_id = '23281030'
    out['company_id'] = customer_id

    try:
        from app.integrations import pennylane_web as _plw
        from app.integrations.pennylane import (
            _fetch_accountant_customer_invoices as _faci,
            _fetch_internal_transactions as _fitx,
        )
        _plw._load_from_db()
        _ck = _plw._parse_cookie_header(_plw._pl_session_cookies or '')
        out['cookies'] = len(_ck)
        out['session_ok'] = any('session' in k.lower() or 'jeancaisse' in k.lower() for k in _ck)

        if probe_name == 'diag':
            from collections import Counter as _C
            _year = str(datetime.utcnow().year)

            # --- VENTES : statuts bruts + compteur UI + scopes UI ---
            _ai = _faci(customer_id)
            out['ventes'] = {
                'nb': len(_ai),
                'statuts': dict(_C([(x.get('status') or '') for x in _ai])),
            }
            # crosstab BRUT (le helper transforme les statuts ; on relit les
            # champs originaux conservés) : status x payment_status x not_duplicate
            try:
                from app.integrations import pennylane_web as _plw2
                _ck2 = _ck
                _fltr = __import__('json').dumps(
                    [{'field': 'date', 'operator': 'between',
                      'value': [f'{_year}-01-01', f'{_year}-12-31']}],
                    separators=(',', ':'))
                _raw = []
                _pg = 1
                while _pg <= 6:
                    rr = _rq.get(
                        f'https://app.pennylane.com/companies/{customer_id}/'
                        f'accountants/customer_invoices',
                        params={'page': _pg, 'per_page': 300, 'sort': '-date',
                                'filter': _fltr},
                        headers={'accept': 'application/json',
                                 'user-agent': 'Mozilla/5.0',
                                 'x-reseller': 'pennylane'},
                        cookies=_ck2, timeout=30)
                    if rr.status_code != 200:
                        break
                    _lst = rr.json().get('invoices') or []
                    _raw.extend(_lst)
                    if not (rr.json().get('pagination') or {}).get('hasNextPage', len(_lst) >= 300):
                        break
                    _pg += 1
                _ct = _C()
                for x in _raw:
                    _ct[(x.get('status') or '', x.get('payment_status') or '',
                         bool(x.get('not_duplicate')))] += 1
                out['ventes']['crosstab_brut'] = {
                    f'{s} | {p} | nd={int(nd)}': c
                    for (s, p, nd), c in sorted(_ct.items())}
            except Exception as e:
                out['ventes']['crosstab_brut'] = f'err {e}'
            try:
                rr = _rq.get(
                    f'https://app.pennylane.com/companies/{customer_id}/'
                    f'accountants/customer_invoices/count_summary',
                    params={'period_start': f'{_year}-01-01',
                            'period_end': f'{_year}-12-31'},
                    headers={'accept': 'application/json', 'user-agent': 'Mozilla/5.0',
                             'x-reseller': 'pennylane'}, cookies=_ck, timeout=30)
                out['ventes']['count_summary_ui'] = rr.json()
            except Exception as e:
                out['ventes']['count_summary_ui'] = f'err {e}'

            # --- BANQUE : API interne (statuts officiels UI) ---
            _tx = _fitx(customer_id)
            out['banque'] = {
                'nb_interne': len(_tx),
                'statuts': dict(_C([(x.get('status') or '') for x in _tx])),
            }
            # --- BANQUE : fallback externe (ce que verrait l'app si interne échoue) ---
            try:
                _tok = None
                from app.integrations.pennylane import get_pennylane_token as _gpt
                _tok = _gpt()
                _ext = []
                _pg = 1
                while _pg <= 3:
                    rr = _rq.get('https://app.pennylane.com/api/v2/transactions',
                                 params={'limit': 100, 'page': _pg}, timeout=30,
                                 headers={'authorization': f'Bearer {_tok}'})
                    if rr.status_code != 200:
                        break
                    batch = (rr.json() or {}).get('transactions') or []
                    _ext.extend(batch)
                    if len(batch) < 100:
                        break
                    _pg += 1
                if customer_id:
                    _ext = [t for t in _ext
                            if str((t.get('company') or {}).get('id') or '') == customer_id]
                out['banque']['nb_externe'] = len(_ext)
                out['banque']['avec_categorie'] = sum(1 for t in _ext if t.get('categories'))
            except Exception as e:
                out['banque']['nb_externe'] = f'err {e}'
            return out

        # ---- probe=health (défaut) : check ventes simple ----
        _ai = _faci(customer_id)
        out['ventes_items'] = len(_ai)
        if _ai:
            from collections import Counter as _C
            out['ventes_status'] = dict(_C([(x.get('status') or '') for x in _ai]))
            out['has_fac1952'] = any((x.get('invoice_number') or '') == 'FAC202601952' for x in _ai)
        return out
    except Exception as e:
        return {'probe': probe_name, 'err': str(e)[:200]}, 500




# ==========================
# Error handlers
# ==========================
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', code=404, message="Page non trouvée."), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 error: {error}")
    try:
        db.session.rollback()
    except Exception:
        pass
    return render_template('error.html', code=500, message="Une erreur interne est survenue. Nos équipes ont été notifiées."), 500
