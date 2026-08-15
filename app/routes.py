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
    if current_user.role == 'manager':
        # TODO: Implement real dashboard data for manager
        kpi = {
            'membres_actifs': 0,
            'dossiers_en_cours': 0,
            'taches_retard': 0,
            'taches_haute_priorite': 0,
            'taux_completion': 0,
            'total_taches': 0
        }
        alertes = []
        suggestions = []
        membres = []
        taches_jour = []
        taches_semaine = []
        return render_template('dashboard_manager.html', kpi=kpi, alertes=alertes, suggestions=suggestions, membres=membres, taches_jour=taches_jour, taches_semaine=taches_semaine)
    else:
        # TODO: Implement real dashboard data for collaborateur
        kpi = {
            'taches_aujourdhui': 0,
            'taux_completion': 0,
            'total_taches': 0
        }
        taches_jour = []
        taches_semaine = []
        return render_template('dashboard_collaborateur.html', kpi=kpi, taches_jour=taches_jour, taches_semaine=taches_semaine)

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
        from .tva_scheduler import planifier_impots_dossier
        from app.models import Dossier
        dossiers = Dossier.query.all()
        for dossier in dossiers:
            planifier_impots_dossier(dossier)
        flash('Planification des impôts (TVA, IS, CFE) terminée avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la planification des impôts: {e}")
        flash('Erreur lors de la planification des impôts.', 'danger')
    return redirect(url_for('dossiers'))


@app.route('/taches')
@login_required
def taches():
    """Affiche la liste des tâches selon le rôle de l'utilisateur."""
    # Initialize variables for template (same as dossiers)
    current_equipe = None
    all_equipes_for_switch = []
    membres = []

    if current_user.role == 'admin':
        from flask import session
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            # For tasks, we want tasks assigned to members of the selected equipe
            all_taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all() if team_user_ids else []
        else:
            # No current equipe selected, show all tasks
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_taches = Tache.query.all()
    elif current_user.role == 'manager':
        # Manager can see and switch between their managed teams
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        # For now, current_equipe is None (could be first team if desired)
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    else:
        # Regular member: can see tasks assigned to them or their equipes?
        # Get teams where user is a member
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None  # Could be first team if desired
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    return render_template('taches.html', taches=all_taches, membres=membres, equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache, current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db)

@app.route('/equipes')
@login_required
def equipes():
    """Affiche la liste des équipes."""
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('equipes.html', equipes=equipes)

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

@app.route('/set-team/<int:equipe_id>')
@login_required
def set_team(equipe_id):
    equipe = Equipe.query.get_or_404(equipe_id)
    session['current_equipe_id'] = equipe.id
    flash(f'Équipe sélectionnée : {equipe.nom}', 'success')
    return redirect(url_for('dossiers'))


# --- Routes de secours pour endpoints manquants (éviter les BuildError) ---
@app.route('/ajouter_membre')
@login_required
def ajouter_membre():
    flash('Fonctionnalité d\'ajout de membre non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/api/suggestions')
@login_required
def api_suggestions():
    return jsonify({'error': 'Not implemented'}), 501

@app.route('/assigner_equipe', methods=['POST'])
@login_required
def assigner_equipe():
    flash('Fonctionnalité d\'assignment d\'équipe non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/assigner_equipe_manager', methods=['POST'])
@login_required
def assigner_equipe_manager():
    flash('Fonctionnalité d\'assignment de manager non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/changer_manager_equipe', methods=['POST'])
@login_required
def changer_manager_equipe():
    flash('Fonctionnalité de changement de manager non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/configurer_email_equipe', methods=['GET', 'POST'])
@login_required
def configurer_email_equipe():
    flash('Fonctionnalité de configuration d\'email d\'équipe non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/liste_membres')
@login_required
def liste_membres():
    return redirect(url_for('membres'))

@app.route('/mes_dossiers')
@login_required
def mes_dossiers():
    return redirect(url_for('dossiers'))

@app.route('/mes_taches')
@login_required
def mes_taches():
    return redirect(url_for('taches'))

@app.route('/modifier_dossier/<int:dossier_id>')
@login_required
def modifier_dossier(dossier_id):
    flash('Fonctionnalité de modification de dossier non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/prendre_en_charge/<int:tache_id>')
@login_required
def prendre_en_charge(tache_id):
    flash('Fonctionnalité de prise en charge non encore implémentée.', 'info')
    return redirect(url_for('taches'))

@app.route('/settings')
@login_required
def settings():
    return redirect(url_for('profil'))

@app.route('/suggestions')
@login_required
def suggestions_page():
    return redirect(url_for('suggestions'))

@app.route('/supprimer_dossier/<int:dossier_id>')
@login_required
def supprimer_dossier(dossier_id):
    flash('Fonctionnalité de suppression de dossier non encore implémentée.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/supprimer_equipe/<int:equipe_id>')
@login_required
def supprimer_equipe(equipe_id):
    flash('Fonctionnalité de suppression d\'équipe non encore implémentée.', 'info')
    return redirect(url_for('equipes'))

@app.route('/supprimer_membre/<int:user_id>')
@login_required
def supprimer_membre(user_id):
    flash('Fonctionnalité de suppression de membre non encore implémentée.', 'info')
    return redirect(url_for('membres'))

@app.route('/supprimer_tache/<int:tache_id>')
@login_required
def supprimer_tache(tache_id):
    flash('Fonctionnalité de suppression de tâche non encore implémentée.', 'info')
    return redirect(url_for('taches'))

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    return redirect(url_for('taches'))

@app.route('/terminer_tache/<int:tache_id>')
@login_required
def terminer_tache(tache_id):
    flash('Fonctionnalité de terminaison de tâche non encore implémentée.', 'info')
    return redirect(url_for('taches'))

@app.route('/upload_photo', methods=['POST'])
@login_required
def upload_photo():
    flash('Fonctionnalité d\'upload de photo non encore implémentée.', 'info')
    return redirect(url_for('profil'))

@app.route('/voir_taches_dossier/<int:dossier_id>')
@login_required
def voir_taches_dossier(dossier_id):
    return redirect(url_for('taches'))

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/reset-admin', methods=['GET', 'POST'])
def reset_admin():
    if request.method == 'POST':
        reset_key = request.form.get('reset_key')
        new_password = request.form.get('new_password')
        from flask import flash, redirect, url_for
        # The key from memory: cabinet-jmh-reset-2024
        if reset_key == 'cabinet-jmh-reset-2024':
            # Update admin password
            from app.models import User
            admin = User.query.filter_by(email='admin@cabinet-jmh.com').first()
            if admin:
                from werkzeug.security import generate_password_hash
                from app import db
                admin.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Mot de passe admin réinitialisé avec succès.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Compte admin introuvable.', 'danger')
        else:
            flash('Clé de réinitialisation invalide.', 'danger')
    return render_template('reset_admin.html')

@app.route('/admin_debug')
@login_required
def admin_debug():
    if current_user.role != 'admin':
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dossiers'))
    return render_template('admin_debug.html')


# Error handlers
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