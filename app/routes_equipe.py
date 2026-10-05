"""equipe — equipes, notifications, membres, fiche (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/equipes', methods=['GET', 'POST'])
@login_required
def equipes():
    """Affiche la liste des \u00e9quipes + cr\u00e9ation d'\u00e9quipe (admin)."""
    if request.method == 'POST':
        # \u00c9conomie/mod\u00e9ration : cr\u00e9ation r\u00e9serv\u00e9e aux admins
        if current_user.role != 'admin':
            flash('Acc\u00e8s refus\u00e9.', 'danger')
            return redirect(url_for('equipes'))
        nom = (request.form.get('nom') or '').strip()
        description = (request.form.get('description') or '').strip()
        couleur = (request.form.get('couleur') or '#E07A5F').strip()
        icon = (request.form.get('icon') or 'bi-people').strip()
        if not nom:
            flash('Le nom de l\u2019\u00e9quipe est obligatoire.', 'danger')
            return redirect(url_for('equipes'))
        existante = Equipe.query.filter(db.func.lower(Equipe.nom) == nom.lower()).first()
        if existante:
            flash(f'Une \u00e9quipe \u00ab {existante.nom} \u00bb existe d\u00e9j\u00e0.', 'warning')
            return redirect(url_for('equipes'))
        equipe = Equipe(nom=nom, description=description or None, couleur=couleur, icon=icon)
        db.session.add(equipe)
        db.session.commit()
        flash(f'\u00c9quipe \u00ab {nom} \u00bb cr\u00e9\u00e9e avec succ\u00e8s.', 'success')
        return redirect(url_for('equipes'))
    equipes = Equipe.query.order_by(Equipe.nom).all()
    managers = User.query.filter(User.role.in_(('admin', 'manager')), User.actif == True).order_by(User.nom).all()
    return render_template('equipes.html', equipes=equipes, managers=managers)

@app.route('/notifications')
@login_required
def notifications_page():
    notifications = current_user.notifications.order_by(Notification.date_envoi.desc()).all() if hasattr(current_user, 'notifications') else []
    unread_count = sum(1 for n in notifications if not n.lu)
    return render_template('notifications.html', notifications=notifications, unread_count=unread_count)

@app.route('/notifications/non_lues')
@login_required
def notifications_non_lues():
    """API JSON pour les notifications non lues."""
    notifications = current_user.notifications.filter_by(lu=False).order_by(Notification.date_envoi.desc()).all() if hasattr(current_user, 'notifications') else []
    return jsonify({
        'count': len(notifications),
        'last_message': notifications[0].message if notifications else '',
        'notifications': [{'id': n.id, 'message': n.message, 'date': n.date_envoi.strftime('%d/%m/%Y %H:%M') if n.date_envoi else None} for n in notifications[:5]]
    })

@app.route('/set-team/<int:equipe_id>')
@login_required
def set_team(equipe_id):
    equipe = Equipe.query.get_or_404(equipe_id)
    session['current_equipe_id'] = equipe.id
    flash(f'\u00c9quipe s\u00e9lectionn\u00e9e : {equipe.nom}', 'success')
    return redirect(url_for('dossiers'))

# ==========================
# Routes membres
# ==========================
@app.route('/membres')
@login_required
def membres():
    """Page de gestion des membres - corrig\u00e9e avec toutes les variables attendues par le template."""
    from app.models import User, Equipe
    membres_list = User.query.filter_by(actif=True).order_by(User.nom).all()
    toutes_equipes = Equipe.query.order_by(Equipe.nom).all()
    mes_equipes = []
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
    return render_template('membres.html', membres=membres_list, toutes_equipes=toutes_equipes, mes_equipes=mes_equipes, title="Membres")

@app.route('/liste_membres')
@login_required
def liste_membres():
    return redirect(url_for('membres'))

@app.route('/fiche_membre/<int:user_id>', methods=['GET', 'POST'])
@login_required
def fiche_membre(user_id):
    """Page de fiche détaillée d'un membre."""
    user = User.query.get_or_404(user_id)
    from datetime import date
    from datetime import timedelta
    
    # Admin peut changer l'email
    if request.method == 'POST' and current_user.role == 'admin':
        new_email = request.form.get('email', '').strip()
        if new_email and new_email != user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != user.id:
                flash('Cet email est déjà utilisé.', 'danger')
            else:
                user.email = new_email
                db.session.commit()
                flash('Email mis à jour.', 'success')
        return redirect(url_for('fiche_membre', user_id=user.id))
    
    # Récupérer les dossiers du collaborateur
    dossiers_list = Dossier.query.filter_by(collaborateur_id=user.id).all()
    
    # Récupérer les tâches assignées
    taches_list = Tache.query.filter_by(assigne_a=user.id).order_by(Tache.date_echeance.desc()).all()
    
    # Calculer les stats
    dossiers_en_cours = [d for d in dossiers_list if not d.date_cloture]
    taches_terminees = [t for t in taches_list if t.statut in ('terminee', 'terminée')]
    taches_en_retard = [t for t in taches_list if t.statut not in ('terminee', 'terminée') and t.date_echeance and t.date_echeance < date.today()]
    total_taches = len(taches_list)
    
    taux_respect = 0
    if total_taches > 0:
        taux_respect = int(len(taches_terminees) / total_taches * 100)
    
    en_retard = len(taches_en_retard)
    score = max(0, min(100, taux_respect - en_retard * 5))
    
    return render_template('fiche_membre.html',
        membre=user,
        dossiers_en_cours=dossiers_en_cours,
        total_terminees=len(taches_terminees),
        taches_membre=taches_list[:20],
        taux_respect=taux_respect,
        en_retard=en_retard,
        score=score)

@app.route('/ajouter_membre', methods=['POST'])
@login_required
def ajouter_membre():
    """Ajoute un nouveau membre avec tous les champs du formulaire."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    try:
        prenom = request.form.get('prenom', '').strip()
        nom = request.form.get('nom', '').strip()
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '').strip()
        role = request.form.get('role', 'membre')
        poste = request.form.get('poste', '').strip()
        telephone = request.form.get('telephone', '').strip()

        if not prenom or not nom or not email or not mot_de_passe:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
            return redirect(url_for('membres'))

        if User.query.filter_by(email=email).first():
            flash('Cet email est d\u00e9j\u00e0 utilis\u00e9.', 'danger')
            return redirect(url_for('membres'))

        from werkzeug.security import generate_password_hash
        pole = request.form.get('pole', 'comptable')
        if pole not in ('comptable', 'social', 'les_deux'):
            pole = 'comptable'
        user = User(
            prenom=prenom,
            nom=nom,
            email=email,
            password_hash=generate_password_hash(mot_de_passe),
            role=role,
            pole=pole,
            poste=poste if poste else None,
            telephone=telephone if telephone else None,
            actif=True
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Membre {prenom} {nom} ajout\u00e9 avec succ\u00e8s.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur ajout membre: {e}")
        flash('Erreur lors de l\'ajout du membre.', 'danger')
    return redirect(url_for('membres'))

@app.route('/assigner_equipe', methods=['POST'])
@login_required
def assigner_equipe():
    """Assigner un membre \u00e0 une \u00e9quipe (admin seulement)."""
    if current_user.role != 'admin':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    # user_id arrive en query string (action du formulaire) OU en corps de POST
    user_id = request.form.get('user_id') or request.args.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'Équipe mise à jour pour {user.prenom} {user.nom}.', 'success')
        elif user:
            user.equipe_id = None
            db.session.commit()
            flash(f'Équipe retirée pour {user.prenom} {user.nom}.', 'info')
    return redirect(url_for('membres'))

@app.route('/assigner_equipe_manager', methods=['POST'])
@login_required
def assigner_equipe_manager():
    """Assigner un membre \u00e0 une \u00e9quipe (manager seulement)."""
    if current_user.role != 'manager':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user_id = request.form.get('user_id') or request.args.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'Équipe mise à jour pour {user.prenom} {user.nom}.', 'success')
    return redirect(url_for('membres'))

@app.route('/supprimer_membre/<int:user_id>', methods=['GET', 'POST'])
@login_required
def supprimer_membre(user_id):
    """Supprime un membre de façon définitive."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    user = User.query.get_or_404(user_id)
    if user.role == 'admin' and current_user.role != 'admin':
        flash('Seul un admin peut supprimer un autre admin.', 'danger')
        return redirect(url_for('membres'))
    try:
        # Nettoyer les dépendances avant suppression
        from app.models import Tache, Notification, CommentaireTache, Suggestion, Dossier, Equipe, Performance
        # 1. Réassigner les tâches assignées à cet utilisateur (mettre à None)
        Tache.query.filter_by(assigne_a=user_id).update({'assigne_a': None})
        Tache.query.filter_by(cree_par=user_id).update({'cree_par': None})
        # 2. Supprimer les notifications
        Notification.query.filter_by(user_id=user_id).delete()
        # 3. Réassigner les dossiers dont il est collaborateur
        Dossier.query.filter_by(collaborateur_id=user_id).update({'collaborateur_id': None})
        # 4. Réassigner les suggestions
        Suggestion.query.filter_by(cree_par=user_id).update({'cree_par': None})
        # 5. Si l'utilisateur est manager d'équipes, retirer la gestion
        Equipe.query.filter_by(manager_id=user_id).update({'manager_id': None})
        # 6. Supprimer les commentaires de tâches
        CommentaireTache.query.filter_by(user_id=user_id).delete()
        # 7. Supprimer les performances
        Performance.query.filter_by(user_id=user_id).delete()
        db.session.flush()
        db.session.delete(user)
        db.session.commit()
        flash(f'Membre {user.prenom} {user.nom} supprimé.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur suppression membre {user_id}: {e}")
        flash(f'Erreur lors de la suppression: {str(e)}', 'danger')
    return redirect(url_for('membres'))

# ==========================
# Suggestions
# ==========================
