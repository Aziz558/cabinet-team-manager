"""notifications — notifications, commentaires, vue tache (extrait de app/routes.py)."""
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

@app.route('/notification/test', methods=['POST'])
@login_required
def notification_test():
    """Test d'envoi de notification."""
    return jsonify({'ok': True})

def get_mail_config():
    """Retourne la configuration mail depuis les settings ou l'environnement."""
    from flask import current_app
    config = {}
    # Essayer les settings DB d'abord
    try:
        from app.models import AppSetting
        for key in ['MAIL_SERVER', 'MAIL_PORT', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER']:
            setting = AppSetting.query.filter_by(cle=key).first()
            config[key] = setting.valeur.strip() if setting and setting.valeur else ''
    except Exception:
        pass
    # Fallback sur config Flask
    if not config.get('MAIL_SERVER'):
        config['MAIL_SERVER'] = current_app.config.get('MAIL_SERVER', '')
        config['MAIL_PORT'] = current_app.config.get('MAIL_PORT', '587')
        config['MAIL_USERNAME'] = current_app.config.get('MAIL_USERNAME', '')
        config['MAIL_PASSWORD'] = current_app.config.get('MAIL_PASSWORD', '')
        config['MAIL_DEFAULT_SENDER'] = current_app.config.get('MAIL_DEFAULT_SENDER', config.get('MAIL_USERNAME', ''))
    return config

@app.route('/api/notifications')
@login_required
def api_notifications():
    """Liste des notifications de l'utilisateur connecté."""
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.date_envoi.desc()).limit(50).all()
    return jsonify({
        'ok': True,
        'notifications': [{
            'id': n.id,
            'type': n.type_notification or 'info',
            'message': n.message,
            'lu': n.lu,
            'date': n.date_envoi.strftime('%d/%m/%Y %H:%M') if n.date_envoi else '',
            'tache_id': n.tache_id,
        } for n in notifs]
    })

@app.route('/api/notifications/mark-all-read', methods=['POST'])
@login_required
def api_notifications_mark_all_read():
    """Marquer toutes les notifications comme lues."""
    Notification.query.filter_by(user_id=current_user.id, lu=False).update({'lu': True})
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def api_notification_read(notif_id):
    """Marquer une notification comme lue."""
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != current_user.id:
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    notif.lu = True
    db.session.commit()
    return jsonify({'ok': True})

# ==========================
# API Commentaires sur les tâches
# ==========================
@app.route('/api/commentaires/<int:tache_id>', methods=['GET', 'POST'])
@login_required
def api_commentaires(tache_id):
    """Lister et ajouter des commentaires sur une tâche."""
    tache = Tache.query.get_or_404(tache_id)
    
    if request.method == 'GET':
        comments = CommentaireTache.query.filter_by(tache_id=tache.id).order_by(CommentaireTache.date_creation).all()
        return jsonify({
            'ok': True,
            'commentaires': [{
                'id': c.id,
                'user_id': c.user_id,
                'user_nom': f"{c.user.prenom} {c.user.nom}",
                'message': c.message,
                'date': c.date_creation.strftime('%d/%m/%Y %H:%M') if c.date_creation else '',
            } for c in comments]
        })
    
    # POST: ajouter un commentaire
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'ok': False, 'message': 'Message requis'}), 400
    
    comment = CommentaireTache(
        tache_id=tache.id,
        user_id=current_user.id,
        message=message,
    )
    db.session.add(comment)
    
    # Créer notification pour l'assigné de la tâche
    if tache.assigne_a and tache.assigne_a != current_user.id:
        notif = Notification(
            user_id=tache.assigne_a,
            tache_id=tache.id,
            message=f"Nouveau commentaire sur \"{tache.titre}\" par {current_user.prenom} {current_user.nom}",
            type_notification='systeme'
        )
        db.session.add(notif)
    # Notifier aussi le créateur si différent
    if tache.cree_par and tache.cree_par != current_user.id and tache.cree_par != tache.assigne_a:
        notif2 = Notification(
            user_id=tache.cree_par,
            tache_id=tache.id,
            message=f"Nouveau commentaire sur \"{tache.titre}\" par {current_user.prenom} {current_user.nom}",
            type_notification='systeme'
        )
        db.session.add(notif2)
    
    db.session.commit()
    
    # Envoyer un email de notification aux personnes concernées
    comment_nom = f"{current_user.prenom} {current_user.nom}"
    comment_msg = f"Un nouveau commentaire a été ajouté sur la tâche \"{tache.titre}\" par {comment_nom} :\n\n\"{message}\""
    from app.integrations.brevo import send_email_via_brevo_api
    # À l'assigné de la tâche
    if tache.assigne_a and tache.assigne_a != current_user.id:
        assigne = User.query.get(tache.assigne_a)
        if assigne and assigne.email:
            try:
                send_email_via_brevo_api(
                    to_email=assigne.email,
                    subject=f"Commentaire sur : {tache.titre}",
                    body=f"Bonjour {assigne.prenom},\n\n{comment_msg}\n\nConsultez la tâche sur https://cabinet-team-manager.onrender.com/taches"
                )
            except Exception as e:
                app.logger.warning(f"Send comment email failed (assigne): {e}")
    # Au créateur de la tâche (si différent)
    if tache.cree_par and tache.cree_par != current_user.id and tache.cree_par != tache.assigne_a:
        createur = User.query.get(tache.cree_par)
        if createur and createur.email:
            try:
                send_email_via_brevo_api(
                    to_email=createur.email,
                    subject=f"Commentaire sur : {tache.titre}",
                    body=f"Bonjour {createur.prenom},\n\n{comment_msg}\n\nConsultez la tâche sur https://cabinet-team-manager.onrender.com/taches"
                )
            except Exception as e:
                app.logger.warning(f"Send comment email failed (createur): {e}")
    
    return jsonify({'ok': True, 'commentaire': {
        'id': comment.id,
        'user_id': comment.user_id,
        'user_nom': f"{current_user.prenom} {current_user.nom}",
        'message': comment.message,
        'date': comment.date_creation.strftime('%d/%m/%Y %H:%M') if comment.date_creation else '',
    }})

@app.route('/vue_tache/<int:tache_id>')
@login_required
def vue_tache(tache_id):
    """Vue d\u00e9taill\u00e9e d'une t\u00e2che avec commentaires."""
    tache = Tache.query.get_or_404(tache_id)
    # Isolation par \u00e9quipe : un utilisateur ne voit que ses t\u00e2ches ou celles de son p\u00e9rim\u00e8tre
    if not _tache_accessible(tache, current_user):
        flash('Acc\u00e8s refus\u00e9 : cette t\u00e2che ne fait pas partie de votre p\u00e9rim\u00e8tre.', 'danger')
        return redirect(url_for('taches'))
    commentaires = CommentaireTache.query.filter_by(tache_id=tache.id).order_by(CommentaireTache.date_creation).all()
    return render_template('vue_tache.html', tache=tache, commentaires=commentaires)

@app.route('/voir_taches_dossier/<int:dossier_id>')
@login_required
def voir_taches_dossier(dossier_id):
    # Rediriger vers la page des tâches avec le dossier pré-filtré
    return redirect(url_for('taches', dossier=dossier_id))
