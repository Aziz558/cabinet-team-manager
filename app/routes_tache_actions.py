"""tache_actions — changer/terminer statut + photos profil (extrait de app/routes.py)."""
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

@app.route('/changer_statut_tache/<int:tache_id>', methods=['POST'])
@login_required
def changer_statut_tache(tache_id):
    """Changer librement le statut d'une tâche."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Isolation par \u00e9quipe : p\u00e9rim\u00e8tre requis
    if not _tache_accessible(tache, current_user):
        flash('Acc\u00e8s refus\u00e9 : cette t\u00e2che ne fait pas partie de votre p\u00e9rim\u00e8tre.', 'danger')
        return redirect(url_for('taches'))
    
    nouveau_statut = request.form.get('statut', '').strip()
    if nouveau_statut not in ('a_faire', 'en_cours', 'terminee'):
        flash('Statut invalide.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = nouveau_statut
    if nouveau_statut == 'terminee':
        tache.date_completion = datetime.utcnow()
        if not tache.date_prise_en_charge:
            tache.date_prise_en_charge = datetime.utcnow()
    elif nouveau_statut == 'en_cours' and not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    elif nouveau_statut == 'a_faire':
        tache.date_prise_en_charge = None
        tache.date_completion = None

    db.session.commit()
    # LIAISON tache -> checklist : une echeance fiscale terminee coche la case
    # correspondante, remise a « a faire » la decoche (cf. checklist_link).
    try:
        from .checklist_link import appliquer_tache_a_case
        if appliquer_tache_a_case(tache):
            db.session.commit()
    except Exception as _lk_e:
        db.session.rollback()
        app.logger.warning(f"Liaison tache->case: {_lk_e}")
    
    # Notifier le créateur (manager) du changement + email
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
            message=f"{collab_nom} a changé le statut de \"{tache.titre}\" à \"{nouveau_statut.replace('_', ' ')}\"",
            type_notification='systeme'
        )
        db.session.add(notif)
        db.session.commit()
        # Email au créateur : TOUJOURS (quelle que soit la priorité).
        # Un changement de statut est rare et important pour le manager.
        # (La condition priorite=='haute' ne s'applique qu'aux emails d'assignation.)
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                from app.integrations.brevo import send_email_via_brevo_api
                sujet = f"Changement de statut : {tache.titre}"
                corps = f"Bonjour {dest_user.prenom},\n\n{collab_nom} a changé le statut de la tâche \"{tache.titre}\" à \"{nouveau_statut.replace('_', ' ')}\".\n\nCabinet JMH"
                envoye = send_email_via_brevo_api(to_email=dest_user.email, subject=sujet, body=corps)
                app.logger.info(f"Email statut change to {dest_user.email}: {'OK' if envoye else 'ECHEC'}")
            except Exception as e:
                app.logger.warning(f"Email statut change error: {e}")
    
    flash(f'Statut changé à "{nouveau_statut.replace("_", " ")}".', 'success')
    return redirect(url_for('taches'))

@app.route('/terminer_tache/<int:tache_id>', methods=['POST'])
@login_required
def terminer_tache(tache_id):
    """Marquer une t\u00e2che comme termin\u00e9e."""
    tache = Tache.query.get_or_404(tache_id)
    
    # Isolation par \u00e9quipe : p\u00e9rim\u00e8tre requis
    if not _tache_accessible(tache, current_user):
        flash('Acc\u00e8s refus\u00e9 : cette t\u00e2che ne fait pas partie de votre p\u00e9rim\u00e8tre.', 'danger')
        return redirect(url_for('taches'))
    if tache.statut not in ('en_cours', 'a_faire'):
        flash('Cette t\u00e2che est d\u00e9j\u00e0 termin\u00e9e.', 'warning')
        return redirect(url_for('taches'))
    
    tache.statut = 'terminee'
    tache.date_completion = datetime.utcnow()
    if not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    # LIAISON tache -> checklist : terminer l'echeance coche la case correspondante
    try:
        from .checklist_link import appliquer_tache_a_case
        if appliquer_tache_a_case(tache):
            db.session.commit()
    except Exception as _lk_e:
        db.session.rollback()
        app.logger.warning(f"Liaison tache->case (terminer): {_lk_e}")
    
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
            message=f"{collab_nom} a terminé : {tache.titre}",
            type_notification='completion'
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
                        subject=f"Tâche terminée : {tache.titre}",
                        body=f"Bonjour {dest_user.prenom},\n\n{collab_nom} a terminé la tâche \"{tache.titre}\"."
                    )
                else:
                    from app.integrations.brevo import send_task_completed_email_brevo
                    send_task_completed_email_brevo(tache, collab_nom)
            except Exception as e:
                app.logger.warning(f"Send email failed: {e}")
    
    flash('Tâche marquée comme terminée.', 'success')
    return redirect(url_for('taches'))

@app.route('/upload_photo', methods=['POST'])
@app.route('/upload_photo/<int:user_id>', methods=['POST'])
@login_required
def upload_photo(user_id=None):
    """Upload photo de profil."""
    import os
    from werkzeug.utils import secure_filename
    
    target_user = current_user
    if user_id is not None:
        if current_user.role not in ('admin', 'manager'):
            return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
        target_user = User.query.get_or_404(user_id)
    
    if 'photo' not in request.files:
        return jsonify({'ok': False, 'message': 'Aucun fichier sélectionné.'}), 400
    
    file = request.files['photo']
    if file.filename == '':
        return jsonify({'ok': False, 'message': 'Aucun fichier sélectionné.'}), 400
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'ok': False, 'message': 'Format non autorisé. Utilisez PNG, JPG, JPEG ou GIF.'}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    if size > 5 * 1024 * 1024:
        return jsonify({'ok': False, 'message': 'Fichier trop volumineux. Maximum 5MB.'}), 400
    file.seek(0)
    
    # Sauvegarder dans la base de données (permanent)
    target_user.photo_data = file.read()
    target_user.photo_mimetype = f"image/{ext}"
    target_user.photo_profil = None  # plus besoin du fichier disque
    db.session.commit()
    
    msg = f'Photo de profil mise à jour pour {target_user.prenom} {target_user.nom}.'
    return jsonify({'ok': True, 'message': msg})
    
    flash(msg, 'success')
    if user_id:
        return redirect(url_for('fiche_membre', user_id=user_id))
    return redirect(url_for('profil'))

@app.route('/user_photo/<int:user_id>')
def user_photo(user_id):
    """Servir la photo de profil depuis la base de données."""
    user = User.query.get_or_404(user_id)
    if not user.photo_data:
        return redirect(url_for('static', filename='img/default-avatar.png'))
    from flask import Response
    return Response(user.photo_data, mimetype=user.photo_mimetype or 'image/png')

# ==========================
# API Notifications
# ==========================
