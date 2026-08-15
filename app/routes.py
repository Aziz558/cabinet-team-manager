from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache
from sqlalchemy import or_
import os
from datetime import date, datetime

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dossiers'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dossiers'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.actif:
                flash('Votre compte est désactivé. Contactez le manager.', 'danger')
                return redirect(url_for('login'))
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash(f'Bienvenue, {user.prenom} !', 'success')
            return redirect(next_page or url_for('dossiers'))
        else:
            flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'info')
    return redirect(url_for('login'))

@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)

@app.route('/dashboard')
@login_required
def dashboard():
    # Redirect to dossiers as the main page after login
    return redirect(url_for('dossiers'))

@app.route('/dossiers')
@login_required
def dossiers():
    """Affiche la liste des dossiers selon le rôle de l'utilisateur."""
    # Initialize variables for template
    current_equipe = None
    all_equipes_for_switch = []
    
    if current_user.role == 'admin':
        from flask import session
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            # No current equipe selected, show all
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        # Manager can see and switch between their managed teams
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        # For now, current_equipe is None (could be first team if desired)
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        # Regular member: can see teams they're part of
        # Get teams where user is a member
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None  # Could be first team if desired
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres, equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache, current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db)

@app.route('/tva-taches')
@login_required
def tva_taches():
    """Affiche la liste des tâches TVA avec filtrage par statut."""
    statut_filter = request.args.get('statut', 'all')
    query = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        )
    )
    if statut_filter != 'all':
        query = query.filter_by(statut=statut_filter)
    tva_taches = query.order_by(Tache.date_echeance.asc(), Tache.titre.asc()).all()
    total_taches = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        )
    ).count()
    taches_a_faire = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        ),
        Tache.statut == 'a_faire'
    ).count()
    taches_en_cours = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        ),
        Tache.statut == 'en_cours'
    ).count()
    taches_terminees = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        ),
        Tache.statut == 'terminee'
    ).count()
    return render_template(
        'tva_taches.html',
        tva_taches=tva_taches,
        statut_filter=statut_filter,
        total_taches=total_taches,
        taches_a_faire=taches_a_faire,
        taches_en_cours=taches_en_cours,
        taches_terminees=taches_terminees,
    )

@app.route('/tva-planifier', methods=['POST'])
@login_required
def planifier_taches_tva():
    """Endpoint pour déclencher la planification des tâches TVA pour tous les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_taches_tva
        planifier_taches_tva(current_user)
        flash('Planification des tâches TVA terminée avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la planification des tâches TVA: {e}")
        flash('Erreur lors de la planification des tâches TVA.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/notifications')
@login_required
def notifications_page():
    notifications = current_user.notifications.order_by(Notification.date_envoi.desc()).all() if hasattr(current_user, 'notifications') else []
    unread_count = sum(1 for n in notifications if not n.lu)
    return render_template(
        'notifications.html',
        notifications=notifications,
        unread_count=unread_count,
    )
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