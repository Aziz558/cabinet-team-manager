"""dossiers_ops — mes vues, modifier/enrichir dossier, admin DB, prise en charge (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta
from .route_common import (prochaine_echeance_theorique, prochaine_echeance_par_nature,
                            _tache_accessible, _nettoyer_relations_dossier)

@app.route('/mes_dossiers')
@login_required
def mes_dossiers():
    return redirect(url_for('dossiers'))

@app.route('/mes_taches')
@login_required
def mes_taches():
    return redirect(url_for('taches'))

@app.route('/api/siren/<siren>')
@login_required
def api_siren(siren):
    """Extrait les infos officielles d'une entreprise depuis son SIREN
    (API recherche-entreprises.api.gouv.fr : INSEE + greffes/RNE, meme donnees
    qu'Infogreffe, sans cle API)."""
    from .siren_service import recherche_siren
    return jsonify(recherche_siren(siren))

@app.route('/modifier_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def modifier_dossier(dossier_id):
    """Modifie les caractéristiques d'un dossier et régénère les tâches fiscales associées."""
    dossier = Dossier.query.get_or_404(dossier_id)
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
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

        # Détecter si les paramètres fiscaux ont changé → régénération nécessaire
        params_fiscaux_changes = (
            dossier.regime_tva != (regime_tva or None) or
            dossier.frequence_tva != (frequence_tva or None) or
            dossier.date_limite_declaration != date_limite or
            dossier.date_acompte_1 != _parse_date(date_acompte_1) or
            dossier.date_acompte_2 != _parse_date(date_acompte_2) or
            dossier.regime_fiscale != (regime_fiscale or None) or
            dossier.has_cfe != has_cfe
        )

        dossier.numero_dossier = numero_dossier
        dossier.intitule = intitule
        dossier.collaborateur_id = int(collaborateur_id)
        dossier.equipe_id = int(equipe_id)
        dossier.regime_tva = regime_tva if regime_tva else None
        dossier.frequence_tva = frequence_tva if frequence_tva else None
        dossier.date_limite_declaration = date_limite
        dossier.date_acompte_1 = _parse_date(date_acompte_1)
        dossier.date_acompte_2 = _parse_date(date_acompte_2)
        dossier.regime_fiscale = regime_fiscale if regime_fiscale else None
        dossier.has_cfe = has_cfe
        dossier.forme_juridique = forme_juridique
        dossier.secteur_activite = secteur_activite
        # Referent social (peut etre retire = vide)
        nouveau_social = request.form.get('collaborateur_social_id', type=int) or None
        social_changed = (dossier.collaborateur_social_id != nouveau_social)
        dossier.collaborateur_social_id = nouveau_social
        # SIREN : normaliser + enrichir automatiquement si fourni
        siren_edit = re.sub(r'\D', '', request.form.get('siren') or '') or None
        # Champs "infos entreprise" soumis par le formulaire (values editees manuellement)
        def _f(name):
            return (request.form.get(name) or '').strip() or None
        form_infos = {
            'tva_intra': (_f('tva_intra'), 20), 'naf_code': (_f('naf_code'), 10),
            'effectif_label': (_f('effectif_label'), 40), 'categorie_entreprise': (_f('categorie_entreprise'), 5),
            'dirigeant': (_f('dirigeant'), 200), 'adresse_siege': (_f('adresse_siege'), 250),
        }
        if siren_edit and (len(siren_edit) != 9):
            flash('SIREN invalide : 9 chiffres attendus.', 'warning')
        elif siren_edit:
            from .siren_service import apply_siren_to_dossier
            if siren_edit != dossier.siren:
                ok, err = apply_siren_to_dossier(dossier, siren_edit, overwrite=True)
                if not ok:
                    flash(f'SIREN {siren_edit} : {err} (valeur enregistrée sans enrichissement).', 'warning')
                    dossier.siren = siren_edit
            else:
                # SIREN inchange : ne pas relancer l'API, garder les valeurs du formulaire
                pass
        # Appliquer les valeurs du formulaire (precedent sur l'enrichissement auto si editees)
        for _fld, (_val, _max) in form_infos.items():
            if _val:
                setattr(dossier, _fld, _val[:_max])
        dce = _f('date_creation_entreprise')
        if dce:
            try:
                dossier.date_creation_entreprise = datetime.strptime(dce, '%Y-%m-%d').date()
            except ValueError:
                pass
        # Token Pennylane : ne mettre à jour que si un nouveau token est fourni
        # (champ vide = conserver le token existant)
        token_val = (request.form.get('pennylane_api_token') or '').strip()
        if token_val:
            dossier.pennylane_api_token = token_val
        db.session.flush()

        # Régénérer les tâches deadlines si les paramètres fiscaux ont changé
        if params_fiscaux_changes:
            from .tva_scheduler import planifier_impots_dossier
            planifier_impots_dossier(dossier)

        # Referent social ajoute/modifie -> generer les taches DSN de l'horizon
        if social_changed and dossier.collaborateur_social_id:
            try:
                from .social_service import generer_taches_dsn
                generer_taches_dsn(dossier)
            except Exception as _dsn_e:
                app.logger.warning(f"Taches DSN a la modification: {_dsn_e}")

        db.session.commit()
        flash('Dossier modifié avec succès. Les tâches fiscales ont été mises à jour.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la modification du dossier {dossier_id}: {e}")
        flash(f'Erreur lors de la modification du dossier: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/enrichir_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def enrichir_dossier(dossier_id):
    """Re-ecoute l'API SIREN pour un dossier donne et complete ses infos entreprise."""
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    dossier = Dossier.query.get_or_404(dossier_id)
    if not dossier.siren:
        return jsonify({'ok': False, 'error': 'Ce dossier n’a pas de SIREN.'})
    from .siren_service import apply_siren_to_dossier
    overwrite = bool(request.form.get('overwrite')) if request.method == 'POST' else False
    ok, err = apply_siren_to_dossier(dossier, dossier.siren, overwrite=overwrite)
    if ok:
        db.session.commit()
        return jsonify({'ok': True, 'numero': dossier.numero_dossier})
    db.session.rollback()
    return jsonify({'ok': False, 'error': err or 'Échec de l’enrichissement.'})


@app.route('/enrichir_tous_dossiers', methods=['POST'])
@login_required
def enrichir_tous_dossiers():
    """Enrichit par lots tous les dossiers ayant un SIREN mais des infos entreprise
    incomplete (API publique rate-limitee ~7 req/s -> pause entre chaque appel)."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    import time as _t
    from .siren_service import apply_siren_to_dossier
    cibles = Dossier.query.filter(Dossier.siren.isnot(None), Dossier.siren != '').all()
    fait = erreur = 0
    for d in cibles:
        if len(d.siren or '') != 9:
            erreur += 1
            continue
        ok, err = apply_siren_to_dossier(d, d.siren, overwrite=False)
        if ok:
            fait += 1
        else:
            erreur += 1
        db.session.commit()
        _t.sleep(0.2)  # menage du quota public
    flash(f'Enrichissement SIREN : {fait} dossier(s) mis à jour'
          + (f', {erreur} en échec.' if erreur else '.'), 'success' if fait or not erreur else 'warning')
    return redirect(url_for('dossiers'))


# ==========================
# Export / Import de la base entiere (secours & migration) — admin uniquement
# ==========================

def _jsonable(v):
    import datetime as _dt
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    return v


def _retype(col, v):
    """Reconvertit les valeurs JSON selon le type de colonne SQLAlchemy."""
    from sqlalchemy import types as sqltypes
    import datetime as _dt
    if v is None:
        return None
    if isinstance(col.type, sqltypes.LargeBinary) and isinstance(v, str):
        return bytes.fromhex(v)
    if isinstance(v, str):
        if isinstance(col.type, (sqltypes.DateTime, sqltypes.TIMESTAMP)):
            try:
                return _dt.datetime.fromisoformat(v)
            except ValueError:
                return None
        if isinstance(col.type, sqltypes.Date):
            try:
                return _dt.date.fromisoformat(v[:10])
            except ValueError:
                return None
        if isinstance(col.type, sqltypes.Time):
            try:
                return _dt.time.fromisoformat(v)
            except ValueError:
                return None
    return v


@app.route('/admin/export_db')
@login_required
def admin_export_db():
    """Exporte TOUTE la base en JSON telechargeable (secours, transfert dev<->prod,
    migration vers un autre Postgres)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    import datetime as _dt
    md = db.metadata
    data = {}
    for t in md.sorted_tables:
        rows = db.session.execute(t.select()).mappings().all()
        data[t.name] = [[_jsonable(r[c.name]) for c in t.columns] for r in rows]
    payload = {
        'kind': 'jmh-orbit-db-export',
        'version': 1,
        'exported_at': _dt.datetime.utcnow().isoformat(),
        'dialect': db.engine.dialect.name,
        'column_order': {t.name: [c.name for c in t.columns] for t in md.sorted_tables},
        'tables': data,
    }
    import io
    from flask import send_file
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'))
    fname = f"jmh_orbit_backup_{_dt.datetime.utcnow():%Y%m%d_%H%M%S}.json"
    return send_file(buf, mimetype='application/json', as_attachment=True, download_name=fname)


@app.route('/admin/import_db', methods=['POST'])
@login_required
def admin_import_db():
    """Restaure un export /admin/export_db : VIDE la base courante puis re-insere.
    Exige confirm=OUI_ECRASER. Attention a la coherence des schemas (tables identiques)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    if request.form.get('confirm') != 'OUI_ECRASER':
        return jsonify({'ok': False,
                        'error': "Confirmation requise : champ confirm='OUI_ECRASER' — cette action VIDE la base existante."})
    f = request.files.get('backup')
    if not f:
        return jsonify({'ok': False, 'error': 'Fichier backup manquant.'})
    try:
        payload = json.loads(f.read().decode('utf-8'))
        assert payload.get('kind') == 'jmh-orbit-db-export'
        tables = {t.name: t for t in db.metadata.sorted_tables}
    except Exception:
        return jsonify({'ok': False, 'error': 'Fichier de backup invalide ou schema different.'})
    from sqlalchemy import text as _text
    dropped = []
    try:
        # desactive les FK (Postgres) pendant la recharge : drop des contraintes,
        # re-ajout en fin (fonctionne aussi bien que superuser ou owner, cf. Neon)
        if db.engine.dialect.name == 'postgresql':
            dropped = db.session.execute(_text(
                "SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS def "
                "FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace"
            )).fetchall()
            for tbl, conname, _def in dropped:
                db.session.execute(_text(f'ALTER TABLE {tbl} DROP CONSTRAINT "{conname}"'))
            db.session.commit()
        # 1) vider (ordre FK-inverse)
        for name in reversed(list(tables.keys())):
            db.session.execute(tables[name].delete())
        db.session.flush()
        # 2) reinserer (ordre parents d'abord)
        counts = {}
        for name, cols in payload.get('column_order', {}).items():
            t = tables.get(name)
            rows = payload.get('tables', {}).get(name)
            if t is None or rows is None:
                continue
            n = 0
            for row in rows:
                vals = {c: _retype(t.c[c], v) for c, v in zip(cols, row)}
                db.session.execute(t.insert().values(**vals))
                n += 1
            counts[name] = n
        db.session.commit()
        # 3) resequencer les clefs automatiques Postgres + retablir la verification FK
        if db.engine.dialect.name == 'postgresql':
            from sqlalchemy import text as _text
            for name, t in tables.items():
                pk = list(t.primary_key.columns.keys())
                if not pk:
                    continue
                try:
                    db.session.execute(_text(
                        f"SELECT setval(pg_get_serial_sequence('{name}', '{pk[0]}'), "
                        f"COALESCE((SELECT MAX({pk[0]}) FROM {name}), 1) + 1, false)"))
                except Exception:
                    db.session.rollback()
        app.logger.info(f'import_db: {counts}')
        return jsonify({'ok': True, 'tables': counts})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        # retablir TOUJOURS les contraintes FK droppees (sinon la base tourne sans integrite)
        if dropped:
            try:
                for tbl, conname, condef in dropped:
                    try:
                        db.session.execute(_text(f'ALTER TABLE {tbl} ADD CONSTRAINT "{conname}" {condef}'))
                    except Exception:
                        db.session.rollback()
                db.session.commit()
                app.logger.info(f'import_db: {len(dropped)} FK restaurees')
            except Exception:
                db.session.rollback()


@app.route('/regenerer_taches_dossier/<int:dossier_id>', methods=['POST'])
@login_required
def regenerer_taches_dossier(dossier_id):
    """Régénère les tâches fiscales (TVA, IS, CFE) d'un dossier."""
    dossier = Dossier.query.get_or_404(dossier_id)
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_impots_dossier
        planifier_impots_dossier(dossier)  # planifier fait ses propres commits internes
        flash(f"Tâches fiscales régénérées pour {dossier.numero_dossier}.", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur régénération dossier {dossier_id}: {e}")
        flash(f'Erreur lors de la régénération: {str(e)}', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/prendre_en_charge/<int:tache_id>', methods=['POST'])
@login_required
def prendre_en_charge(tache_id):
    """Prendre en charge une t\u00e2che (membre ou assign\u00e9)."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Isolation par \u00e9quipe : p\u00e9rim\u00e8tre requis
    if not _tache_accessible(tache, current_user):
        flash('Acc\u00e8s refus\u00e9 : cette t\u00e2che ne fait pas partie de votre p\u00e9rim\u00e8tre.', 'danger')
        return redirect(url_for('taches'))
    if tache.statut != 'a_faire':
        flash('Cette t\u00e2che n\u2019est pas en attente de prise en charge.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = 'en_cours'
    tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    
    # Notifier le créateur (manager) + in-app
    collab_nom = f"{current_user.prenom} {current_user.nom}"
    cree_par_id = tache.cree_par
    team_manager = None
    if not cree_par_id and tache.dossier and tache.dossier.equipe and tache.dossier.equipe.manager:
        team_manager = tache.dossier.equipe.manager
        cree_par_id = team_manager.id
    if cree_par_id and cree_par_id != current_user.id:
        notif = Notification(
            user_id=cree_par_id,
            tache_id=tache.id,
            message=f"{collab_nom} a pris en charge : {tache.titre}",
            type_notification='prise_en_charge'
        )
        db.session.add(notif)
        db.session.commit()
        # Email au créateur : TOUJOURS (quelle que soit la priorité).
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                if team_manager:
                    from app.integrations.brevo import send_email_via_brevo_api
                    send_email_via_brevo_api(
                        to_email=dest_user.email,
                        subject=f"Prise en charge : {tache.titre}",
                        body=f"Bonjour {dest_user.prenom},\n\n{collab_nom} a pris en charge la tâche \"{tache.titre}\"."
                    )
                else:
                    from app.integrations.brevo import send_task_taken_email_brevo
                    send_task_taken_email_brevo(tache, collab_nom)
            except Exception as e:
                app.logger.warning(f"Send email failed: {e}")
    
    flash('Tâche prise en charge.', 'success')
    return redirect(url_for('taches'))
