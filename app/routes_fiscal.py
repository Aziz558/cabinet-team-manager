"""fiscal — page fiscal + creation dossier + config equipes (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/fiscal')
@login_required
def fiscal():
    """Tableau de bord fiscal d\u00e9di\u00e9"""
    current_equipe = None
    all_equipes_for_switch = []
    membres = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()

    def _add_counts(item):
        """Ajoute les compteurs nb_a_faire, nb_terminee, a_retard et tax_tasks_visible à un item."""
        tasks = item.get('tax_tasks', [])
        now = date.today()
        horizon_3m = now + timedelta(days=95)
        
        # Visible tasks: only within 3 months horizon + past/terminated
        visible = [t for t in tasks if t.date_echeance and (t.date_echeance <= horizon_3m or t.statut in ('terminee', 'terminée'))]
        item['tax_tasks_visible'] = visible
        
        nb_a_faire = sum(1 for t in visible if t.statut == 'a_faire')
        nb_terminee = sum(1 for t in visible if t.statut in ('terminee', 'terminée'))
        a_retard = sum(1 for t in visible if t.statut not in ('terminee', 'terminée') and t.date_echeance and t.date_echeance < now)
        item['nb_a_faire'] = nb_a_faire
        item['nb_terminee'] = nb_terminee
        item['a_retard'] = a_retard
        return item
    
    dossier_data = []
    tva_dossiers = []
    ca3_dossiers = []
    ca12_dossiers = []
    is_dossiers = []
    cfe_dossiers = []

    # --- Classification fiscale ROBUSTE (mots entiers, insensible aux accents) ---
    # Avant : `'IS' in t.titre.upper()` matchait aussi MISE, SAISIE, AVIS, PRISE...
    # et `d.regime_tva == 'ca3'` ne matchait jamais (le formulaire stocke
    # 'mensuel'/'trimestriel'/'annuel'). On centralise ici la logique.
    import re as _fiscal_re
    _FISCAL_ACCENTS = str.maketrans('ÉÈÊËÀÂÎÏÔÛÜÇ', 'EEEEAAIIOOUC')
    _FISCAL_DONE = ('terminee', 'terminée', 'termines', 'terminés', 'termine', 'achevee', 'achevée')

    def _fiscal_kind(titre):
        """Types fiscaux d'une tâche, testés sur MOT ENTIER (TVA, CA3, CA12, IS, CFE, ACOMPTE)."""
        t = (titre or '').upper().translate(_FISCAL_ACCENTS)

        def _has(mot):
            return _fiscal_re.search(r'(?<![A-Z0-9])' + mot + r'(?![A-Z0-9])', t) is not None

        return {
            'tva': _has('TVA'),
            'ca3': _has('CA3'),
            'ca12': _has('CA12'),
            'is': _has('IS') or _has('ACOMPTE') or _has('ACOMPTES'),
            'cfe': _has('CFE'),
        }

    def _fiscal_subset(item, include, exclude=()):
        """Copie de l'item limitée aux tâches des types demandés,
        avec les compteurs RECALCULÉS sur ce sous-ensemble (sinon la colonne
        TÂCHES du sous-onglet affichait le total toutes taxes confondues)."""
        kinds = item.get('_kinds', {})

        def _keep(t):
            k = kinds.get(t.id, {})
            return any(k.get(x) for x in include) and not any(k.get(x) for x in exclude)

        subset = [t for t in item.get('_all_tasks', []) if _keep(t)]
        copy = dict(item)
        copy['tax_tasks'] = subset
        _add_counts(copy)
        return copy

    def _regime_ca(_regime, famille):
        """Le formulaire stocke 'mensuel'/'trimestriel'/'annuel', les anciennes
        données 'ca3'/'ca12' : on accepte les deux."""
        r = (_regime or '').lower()
        if famille == 'ca3':
            return r in ('ca3', 'mensuel', 'trimestriel') or r.startswith('ca3')
        return r in ('ca12', 'annuel') or r.startswith('ca12')
    
    for d in all_dossiers:
        tasks = Tache.query.filter(Tache.dossier_id == d.id).all()
        # Classification robuste (mots entiers + accents) : remplace le test naïf
        kinds = {t.id: _fiscal_kind(t.titre) for t in tasks}
        tax_tasks = [t for t in tasks if any(kinds[t.id].values())]
        pending_tasks = [t for t in tax_tasks if (t.statut or '') not in _FISCAL_DONE]
        next_deadline = min([t.date_echeance for t in pending_tasks if t.date_echeance]) if pending_tasks else None
        if any(t.statut == 'a_faire' for t in tax_tasks):
            status = 'a_faire'
            status_label = 'À faire'
            status_class = 'text-danger'
        elif any(t.statut == 'en_cours' for t in tax_tasks):
            status = 'en_cours'
            status_label = 'En cours'
            status_class = 'text-warning'
        else:
            status = 'terminee'
            status_label = 'Terminé'
            status_class = 'text-success'
        
        item = {
            'dossier': d,
            'regime_fiscale': d.regime_fiscale,
            'has_cfe': d.has_cfe,
            'next_deadline': next_deadline,
            'status': status,
            'status_label': status_label,
            'status_class': status_class,
            'tax_tasks': tax_tasks,
            '_all_tasks': tasks,
            '_kinds': kinds
        }
        dossier_data.append(item)
        
        _add_counts(item)
        
        # TVA tasks (only TVA, CA3, CA12)
        tva_tasks = [t for t in tasks if kinds[t.id]['tva'] or kinds[t.id]['ca3'] or kinds[t.id]['ca12']]
        if tva_tasks:
            tva_dossiers.append(_fiscal_subset(item, ('tva', 'ca3', 'ca12')))
        
        # CA3 tasks
        if _regime_ca(d.regime_tva, 'ca3') or any(kinds[t.id]['ca3'] for t in tasks):
            ca3_dossiers.append(_fiscal_subset(item, ('tva', 'ca3'), ('ca12',)))
        
        # CA12 tasks
        if _regime_ca(d.regime_tva, 'ca12') or any(kinds[t.id]['ca12'] for t in tasks):
            ca12_dossiers.append(_fiscal_subset(item, ('ca12',)))
        
        # IS tasks
        if d.regime_fiscale == 'IS' or any(kinds[t.id]['is'] for t in tasks):
            is_dossiers.append(_fiscal_subset(item, ('is',)))
        
        # CFE tasks
        if d.has_cfe or any(kinds[t.id]['cfe'] for t in tasks):
            cfe_dossiers.append(_fiscal_subset(item, ('cfe',)))
    
    return render_template('fiscal.html', dossier_data=dossier_data, 
        tva_dossiers=tva_dossiers, ca3_dossiers=ca3_dossiers, ca12_dossiers=ca12_dossiers,
        is_dossiers=is_dossiers, cfe_dossiers=cfe_dossiers,
        current_equipe=current_equipe,
        all_equipes_for_switch=all_equipes_for_switch, Tache=Tache, db=db,
        horizon_3m=date.today() + timedelta(days=95))


@app.route('/ajouter_dossier', methods=['POST'])
@login_required
def ajouter_dossier():
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        numero_dossier = request.form.get('numero_dossier', '').strip()
        intitule = request.form.get('intitule', '').strip()
        collaborateur_id = request.form.get('collaborateur_id')
        equipe_id = request.form.get('equipe_id')
        regime_tva = request.form.get('regime_tva')
        frequence_tva = request.form.get('frequence_tva')
        date_limite_declaration = request.form.get('date_limite_declaration')
        date_acompte_1 = request.form.get('date_acompte_1')
        date_acompte_2 = request.form.get('date_acompte_2')
        regime_fiscale = request.form.get('regime_fiscale')
        has_cfe = ('has_cfe' in request.form)
        forme_juridique = (request.form.get('forme_juridique') or '').strip() or None
        secteur_activite = (request.form.get('secteur_activite') or '').strip() or None
        siren = re.sub(r'\D', '', request.form.get('siren') or '') or None
        # referent social (facultatif)
        collab_social = request.form.get('collaborateur_social_id', type=int) or None
        # honoraires: tolerer les formats francais ("1 200,50", espaces insécables)
        hon_raw = re.sub(r'[\s\u202f\xa0]', '', request.form.get('honoraires_mensuel') or '').replace(',', '.')
        try:
            honoraires_mensuel = float(hon_raw) if hon_raw else None
        except ValueError:
            honoraires_mensuel = None
        pennylane_api_token = (request.form.get('pennylane_api_token') or '').strip() or None

        if not numero_dossier or not intitule or not collaborateur_id or not equipe_id:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
            return redirect(url_for('dossiers'))

        date_limite = None
        if date_limite_declaration:
            try:
                date_limite = datetime.strptime(date_limite_declaration, '%Y-%m-%d').date()
            except ValueError:
                flash('Format de date invalide.', 'danger')
                return redirect(url_for('dossiers'))

        def _parse_date(v):
            if not v:
                return None
            try:
                return datetime.strptime(v, '%Y-%m-%d').date()
            except ValueError:
                return None

        nouveau_dossier = Dossier(
            numero_dossier=numero_dossier,
            intitule=intitule,
            collaborateur_id=int(collaborateur_id),
            equipe_id=int(equipe_id),
            regime_tva=regime_tva if regime_tva else None,
            frequence_tva=frequence_tva if frequence_tva else None,
            date_limite_declaration=date_limite,
            date_acompte_1=_parse_date(date_acompte_1),
            date_acompte_2=_parse_date(date_acompte_2),
            regime_fiscale=regime_fiscale if regime_fiscale else None,
            has_cfe=has_cfe,
            forme_juridique=forme_juridique,
            secteur_activite=secteur_activite,
            siren=siren,
            honoraires_mensuel=honoraires_mensuel,
            collaborateur_social_id=collab_social,
            pennylane_api_token=pennylane_api_token
        )
        db.session.add(nouveau_dossier)
        db.session.flush()

        # Enrichissement SIREN : complete les champs restes vides (sans ecraser la saisie)
        if siren:
            from .siren_service import apply_siren_to_dossier
            if len(siren) == 9:
                ok, err = apply_siren_to_dossier(nouveau_dossier, siren, overwrite=False)
                if not ok:
                    app.logger.warning(f'Enrichissement SIREN {siren} (dossier {numero_dossier}): {err}')

        # Referent social -> generer les taches DSN qui tombent dans l'horizon
        if nouveau_dossier.collaborateur_social_id:
            try:
                from .social_service import generer_taches_dsn
                generer_taches_dsn(nouveau_dossier)
            except Exception as _dsn_e:
                app.logger.warning(f"Taches DSN a la creation: {_dsn_e}")

        # Planifier les imp\u00f4ts pour ce dossier
        from .tva_scheduler import planifier_impots_dossier
        planifier_impots_dossier(nouveau_dossier)

        db.session.commit()
        flash('Dossier cr\u00e9\u00e9 avec succ\u00e8s et les t\u00e2ches fiscales ont \u00e9t\u00e9 g\u00e9n\u00e9r\u00e9es.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la création du dossier: {e}")
        flash(f'Erreur lors de la création du dossier: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

# ==========================
# Routes \u00e9quipes fonctionnelles
# ==========================
@app.route('/changer_manager_equipe', methods=['POST'])
@login_required
def changer_manager_equipe():
    if current_user.role != 'admin':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('equipes'))
    equipe_id = request.form.get('equipe_id') or request.args.get('equipe_id')
    manager_id = (request.form.get('manager_id') or '').strip()
    if equipe_id:
        equipe = Equipe.query.get(int(equipe_id))
        if equipe:
            # manager_id vide = retirer le responsable (option \u00ab Aucun \u00bb)
            equipe.manager_id = int(manager_id) if manager_id else None
            db.session.commit()
            flash(f'Manager de l\u2019\u00e9quipe {equipe.nom} mis \u00e0 jour.', 'success')
    return redirect(url_for('equipes'))

@app.route('/configurer_email_equipe', methods=['POST'])
@login_required
def configurer_email_equipe():
    """Enregistre l'email d\u00e9di\u00e9 d'une \u00e9quipe (routing Cloudflare -> /api/mailbox/inbound)."""
    if current_user.role != 'admin':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('equipes'))
    equipe_id = request.form.get('equipe_id') or request.args.get('equipe_id')
    equipe_email = (request.form.get('equipe_email') or '').strip()
    equipe = Equipe.query.get(int(equipe_id)) if equipe_id else None
    if not equipe:
        flash('\u00c9quipe introuvable.', 'danger')
        return redirect(url_for('equipes'))
    equipe.equipe_email = equipe_email or None
    db.session.commit()
    if equipe_email:
        flash(f'Email d\u00e9di\u00e9 de l\u2019\u00e9quipe {equipe.nom} enregistr\u00e9 : {equipe_email}', 'success')
    else:
        flash(f'Email d\u00e9di\u00e9 de l\u2019\u00e9quipe {equipe.nom} retir\u00e9.', 'info')
    return redirect(url_for('equipes'))

# ==========================
# Pennylane — déclarations TVA (session web)
# ==========================
