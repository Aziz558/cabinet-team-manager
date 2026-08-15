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
                flash('Votre compte est d\u00e9sactiv\u00e9. Contactez le manager.', 'danger')
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
    flash('D\u00e9connexion r\u00e9ussie.', 'info')
    return redirect(url_for('login'))

@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'manager':
        # Compute real KPIs for manager
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))

        membres_actifs = User.query.filter(User.id.in_(team_member_ids), User.actif==True).count()
        all_dossiers_ids = [d.id for d in Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()]
        dossiers_en_cours = len(all_dossiers_ids)
        
        taches_retard = 0
        taches_haute_priorite = 0
        total_taches = 0
        if all_dossiers_ids:
            taches_query = Tache.query.filter(Tache.dossier_id.in_(all_dossiers_ids))
            total_taches = taches_query.count()
            taches_retard = taches_query.filter(Tache.date_echeance < date.today(), Tache.statut != 'terminee').count()
            taches_haute_priorite = taches_query.filter_by(priorite='haute', statut='a_faire').count()
        
        taux_completion = 0
        if total_taches > 0:
            terminees = Tache.query.filter(Tache.dossier_id.in_(all_dossiers_ids), Tache.statut == 'terminee').count()
            taux_completion = int(terminees / total_taches * 100)

        kpi = {
            'membres_actifs': membres_actifs,
            'dossiers_en_cours': dossiers_en_cours,
            'taches_retard': taches_retard,
            'taches_haute_priorite': taches_haute_priorite,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }

        # Alertes : tâches en retard
        alertes = []
        if all_dossiers_ids:
            taches_en_retard = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance < date.today(),
                Tache.statut != 'terminee'
            ).order_by(Tache.date_echeance.asc()).limit(5).all()
            for t in taches_en_retard:
                d = Dossier.query.get(t.dossier_id)
                alertes.append({'tache': t, 'dossier': d})

        # Suggestions
        suggestions = []
        try:
            from app.models import Suggestion
            suggestions = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))\
                .order_by(Suggestion.date_creation.desc()).limit(10).all()
        except Exception:
            suggestions = []

        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).order_by(User.nom).all()
        
        taches_jour = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today()
        ).order_by(Tache.priorite.desc()).all()
        
        from datetime import timedelta
        week_end = date.today() + timedelta(days=7)
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end)
        ).order_by(Tache.date_echeance.asc()).all()

        return render_template('dashboard_manager.html', kpi=kpi, alertes=alertes,
            suggestions=suggestions, membres=membres, taches_jour=taches_jour,
            taches_semaine=taches_semaine)
    else:
        # Dashboard collaborateur
        team_member_ids = [current_user.id]
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))
        
        total_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).count()
        taches_auj = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today()
        ).count()
        terminees = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.statut == 'terminee'
        ).count()
        taux_completion = int(terminees / total_taches * 100) if total_taches > 0 else 0

        from datetime import timedelta
        week_end = date.today() + timedelta(days=7)
        taches_jour = Tache.query.filter(
            Tache.assigne_a == current_user.id,
            Tache.date_echeance == date.today()
        ).order_by(Tache.priorite.desc()).all()
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end)
        ).order_by(Tache.date_echeance.asc()).all()

        kpi = {
            'taches_aujourdhui': taches_auj,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }
        return render_template('dashboard_collaborateur.html', kpi=kpi,
            taches_jour=taches_jour, taches_semaine=taches_semaine)

@app.route('/dossiers')
@login_required
def dossiers():
    """Affiche la liste des dossiers selon le r\u00f4le de l'utilisateur."""
    current_equipe = None
    all_equipes_for_switch = []

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
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    
    # Pre-calculate TVA task data for each dossier to avoid Jinja template errors
    for d in all_dossiers:
        d._tva_taches = [t for t in d.taches if t.titre and ('TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper())]
        d._tva_taches_count = len(d._tva_taches)
        d._tva_taches_restantes = sum(1 for t in d._tva_taches if t.statut not in ('terminee', 'terminée'))
    
    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db)

@app.route('/tva-taches')
@login_required
def tva_taches():
    """Affiche la liste des t\u00e2ches TVA avec filtrage par statut."""
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

    base_filter = db.or_(
        Tache.titre.like('%TVA%'),
        Tache.titre.like('%CA3%'),
        Tache.titre.like('%ca3%'),
        Tache.titre.like('%CA12%'),
        Tache.titre.like('%ca12%')
    )
    total_taches = Tache.query.filter(base_filter).count()
    taches_a_faire = Tache.query.filter(base_filter, Tache.statut == 'a_faire').count()
    taches_en_cours = Tache.query.filter(base_filter, Tache.statut == 'en_cours').count()
    taches_terminees = Tache.query.filter(base_filter, Tache.statut == 'terminee').count()

    return render_template('tva_taches.html', tva_taches=tva_taches,
        statut_filter=statut_filter, total_taches=total_taches,
        taches_a_faire=taches_a_faire, taches_en_cours=taches_en_cours,
        taches_terminees=taches_terminees)

@app.route('/planifier_tous_impots', methods=['POST'])
@login_required
def planifier_tous_impots():
    """Endpoint pour planifier les impôts de TOUS les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_tous_les_dossiers
        planifier_tous_les_dossiers()
        flash('Planification des impôts pour tous les dossiers terminée avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur planification tous impôts: {e}")
        flash('Erreur lors de la planification.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/tva-planifier', methods=['POST'])
@login_required
def planifier_taches_tva():
    """Endpoint pour d\u00e9clencher la planification des t\u00e2ches TVA pour tous les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_impots_dossier
        from app.models import Dossier
        dossiers = Dossier.query.all()
        for dossier in dossiers:
            planifier_impots_dossier(dossier)
        flash('Planification des imp\u00f4ts (TVA, IS, CFE) termin\u00e9e avec succ\u00e8s.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la planification des imp\u00f4ts: {e}")
        flash('Erreur lors de la planification des imp\u00f4ts.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/taches')
@login_required
def taches():
    """Affiche la liste des t\u00e2ches selon le r\u00f4le de l'utilisateur."""
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
            all_taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all() if team_user_ids else []
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_taches = Tache.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    return render_template('taches.html', taches=all_taches, membres=membres,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db)

@app.route('/equipes')
@login_required
def equipes():
    """Affiche la liste des \u00e9quipes."""
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('equipes.html', equipes=equipes)

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

@app.route('/fiche_membre/<int:user_id>')
@login_required
def fiche_membre(user_id):
    """Page de fiche d\u00e9taill\u00e9e d'un membre."""
    user = User.query.get_or_404(user_id)
    from datetime import date
    taches_en_cours = Tache.query.filter_by(assigne_a=user.id).filter(Tache.statut != 'terminee').count()
    dossiers_assignes = Dossier.query.filter_by(collaborateur_id=user.id).count()
    return render_template('fiche_membre.html', membre=user, taches_en_cours=taches_en_cours, dossiers_assignes=dossiers_assignes)

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
        user = User(
            prenom=prenom,
            nom=nom,
            email=email,
            password_hash=generate_password_hash(mot_de_passe),
            role=role,
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
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user_id = request.form.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'\u00c9quipe mise \u00e0 jour pour {user.prenom} {user.nom}.', 'success')
        elif user:
            user.equipe_id = None
            db.session.commit()
            flash(f'\u00c9quipe retir\u00e9e pour {user.prenom} {user.nom}.', 'info')
    return redirect(url_for('membres'))

@app.route('/assigner_equipe_manager', methods=['POST'])
@login_required
def assigner_equipe_manager():
    """Assigner un membre \u00e0 une \u00e9quipe (manager seulement)."""
    if current_user.role != 'manager':
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user_id = request.form.get('user_id')
    equipe_id = request.form.get('equipe_id')
    if user_id:
        user = User.query.get(int(user_id))
        if user and equipe_id:
            user.equipe_id = int(equipe_id)
            db.session.commit()
            flash(f'\u00c9quipe mise \u00e0 jour pour {user.prenom} {user.nom}.', 'success')
    return redirect(url_for('membres'))

@app.route('/supprimer_membre/<int:user_id>')
@login_required
def supprimer_membre(user_id):
    """Supprime un membre de fa\u00e7on d\u00e9finitive."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('membres'))
    user = User.query.get_or_404(user_id)
    if user.role == 'admin' and current_user.role != 'admin':
        flash('Seul un admin peut supprimer un autre admin.', 'danger')
        return redirect(url_for('membres'))
    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'Membre {user.prenom} {user.nom} supprim\u00e9.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur suppression membre: {e}")
        flash('Erreur lors de la suppression.', 'danger')
    return redirect(url_for('membres'))

# ==========================
# Suggestions
# ==========================
@app.route('/suggestions')
@login_required
def suggestions_page():
    """Page de suggestions - version corrigée."""
    from app.models import Suggestion, User, Equipe
    from app import db
    
    if current_user.role == 'admin':
        suggestions_list = Suggestion.query.order_by(Suggestion.date_creation.desc()).all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        suggestions_list = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).all()
    else:
        suggestions_list = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).all()
    
    # Pass users and dossiers for the modal form
    all_users = User.query.filter_by(actif=True).order_by(User.nom).all()
    all_dossiers = Dossier.query.order_by(Dossier.numero_dossier).all()
    
    return render_template('suggestions.html', suggestions=suggestions_list, users=all_users, dossiers=all_dossiers)

@app.route('/api/suggestions', methods=['GET'])
@login_required
def api_suggestions():
    """API pour récupérer les suggestions au format JSON."""
    try:
        from app.models import Suggestion
        status_filter = request.args.get('status', 'all')
        
        if current_user.role == 'admin':
            query = Suggestion.query
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            query = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))
        else:
            query = Suggestion.query.filter_by(cree_par=current_user.id)
        
        if status_filter in ('en_attente', 'validee', 'rejetee'):
            query = query.filter_by(statut=status_filter)
        
        items = query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        
        return jsonify({
            'ok': True,
            'suggestions': [{
                'id': s.id,
                'titre': s.titre,
                'titre_suggere': s.titre_suggere or s.titre,
                'sujet': s.sujet,
                'description_suggeree': s.description_suggeree or s.description,
                'priorite_suggeree': s.priorite_suggeree or s.priorite or 'moyenne',
                'statut': s.statut or 'en_attente',
                'date_creation': s.date_creation.strftime('%d/%m/%Y') if s.date_creation else None,
                'date_echeance': s.date_echeance.strftime('%d/%m/%Y') if s.date_echeance else None,
                'dossier_nom': f"{s.dossier.numero_dossier} - {s.dossier.intitule}" if s.dossier_id else None,
                'dossier_id': s.dossier_id,
                'assigne_a': s.assigne_a,
                'source': s.source,
                'mail_uid': s.mail_uid
            } for s in items]
        })
    except Exception as e:
        app.logger.error(f"api_suggestions error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh', methods=['POST'])
@login_required
def api_suggestions_refresh():
    """Endpoint pour rafraîchir les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            items = Suggestion.query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            items = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).limit(20).all()
        else:
            items = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).limit(20).all()
        return jsonify({'ok': True, 'suggestions': [{'id': s.id, 'titre': s.titre} for s in items]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/validate', methods=['POST'])
@login_required
def api_suggestions_validate(suggestion_id):
    """Valider une suggestion et créer la tâche correspondante."""
    try:
        from app.models import Suggestion, Tache
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        data = request.get_json() or {}
        
        assignee = data.get('assignee') or suggestion.assigne_a
        due_date = data.get('due_date')
        if due_date:
            due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
        priority = data.get('priority') or suggestion.priorite or 'moyenne'
        dossier_id = data.get('dossier_id') or suggestion.dossier_id
        
        titre = suggestion.titre_suggere or suggestion.titre or 'Tâche depuis suggestion'
        description = suggestion.description_suggeree or suggestion.description or ''
        
        nouvelle_tache = Tache(
            titre=titre,
            description=description,
            assigne_a=int(assignee) if assignee else None,
            dossier_id=int(dossier_id) if dossier_id else None,
            priorite=priority,
            date_echeance=due_date,
            statut='a_faire',
            cree_par=current_user.id
        )
        db.session.add(nouvelle_tache)
        suggestion.statut = 'validee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Tâche créée avec succès'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"validate suggestion error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
def api_suggestions_reject(suggestion_id):
    """Rejeter une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        suggestion.statut = 'rejetee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion rejetée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reanalyze', methods=['POST'])
@login_required
def api_suggestions_reanalyze(suggestion_id):
    """Relancer l'analyse IA sur une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        # Pour l'instant, juste marquer comme ré-analysé
        suggestion.statut = 'en_attente'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Analyse relancée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/delete', methods=['DELETE'])
@login_required
def api_suggestions_delete(suggestion_id):
    """Supprimer une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        db.session.delete(suggestion)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion supprimée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/reset', methods=['POST'])
@login_required
def api_suggestions_reset():
    """Réinitialiser toutes les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            Suggestion.query.delete()
            db.session.commit()
            return jsonify({'ok': True, 'message': 'Toutes les suggestions ont été supprimées'})
        else:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh_mailbox', methods=['POST'])
@login_required
def api_suggestions_refresh_mailbox():
    """Scanner la mailbox pour générer de nouvelles suggestions."""
    try:
        # Pour l'instant, retourne un message indiquant que la fonctionnalité n'est pas encore implémentée
        return jsonify({'ok': True, 'message': 'Scan de la mailbox non implémenté. Aucune nouvelle suggestion.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ==========================
# Routes s\u00e9curit\u00e9 (stubs fonctionnels)
# ==========================
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
    flash('Fonctionnalit\u00e9 de modification de dossier non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/prendre_en_charge/<int:tache_id>')
@login_required
def prendre_en_charge(tache_id):
    flash('Fonctionnalit\u00e9 de prise en charge non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('taches'))

@app.route('/settings')
@login_required
def settings():
    return redirect(url_for('profil'))

@app.route('/supprimer_dossier/<int:dossier_id>')
@login_required
def supprimer_dossier(dossier_id):
    flash('Fonctionnalit\u00e9 de suppression de dossier non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('dossiers'))

@app.route('/supprimer_equipe/<int:equipe_id>')
@login_required
def supprimer_equipe(equipe_id):
    flash('Fonctionnalit\u00e9 de suppression d\'\u00e9quipe non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('equipes'))

@app.route('/supprimer_tache/<int:tache_id>')
@login_required
def supprimer_tache(tache_id):
    flash('Fonctionnalit\u00e9 de suppression de t\u00e2che non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('taches'))

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    return redirect(url_for('taches'))

@app.route('/terminer_tache/<int:tache_id>')
@login_required
def terminer_tache(tache_id):
    flash('Fonctionnalit\u00e9 de terminaison de t\u00e2che non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('taches'))

@app.route('/upload_photo', methods=['POST'])
@login_required
def upload_photo():
    flash('Fonctionnalit\u00e9 d\'upload de photo non encore impl\u00e9ment\u00e9e.', 'info')
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
        if reset_key == 'cabinet-jmh-reset-2024':
            admin = User.query.filter_by(email='admin@cabinet-jmh.com').first()
            if admin:
                from werkzeug.security import generate_password_hash
                admin.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Mot de passe admin r\u00e9initialis\u00e9 avec succ\u00e8s.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Compte admin introuvable.', 'danger')
        else:
            flash('Cl\u00e9 de r\u00e9initialisation invalide.', 'danger')
    return render_template('reset_admin.html')

@app.route('/admin_debug')
@login_required
def admin_debug():
    if current_user.role != 'admin':
        flash('Acc\u00e8s r\u00e9serv\u00e9 aux administrateurs.', 'danger')
        return redirect(url_for('dossiers'))
    return render_template('admin_debug.html')

# ==========================
# Tableau de bord fiscal
# ==========================
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

    dossier_data = []
    tva_dossiers = []
    ca3_dossiers = []
    ca12_dossiers = []
    is_dossiers = []
    cfe_dossiers = []
    
    for d in all_dossiers:
        tasks = Tache.query.filter(Tache.dossier_id == d.id).all()
        tax_tasks = [t for t in tasks if (
                     'TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper() or
                      'IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper() or 'CFE' in t.titre.upper())]
        pending_tasks = [t for t in tax_tasks if t.statut != 'terminee']
        next_deadline = min([t.date_echeance for t in pending_tasks]) if pending_tasks else None
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
            'tax_tasks': tax_tasks
        }
        dossier_data.append(item)
        
        # TVA tasks (only TVA, CA3, CA12)
        tva_tasks = [t for t in tasks if 'TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper()]
        if tva_tasks:
            tva_dossiers.append({**item, 'tax_tasks': tva_tasks})
        
        # CA3 tasks
        if d.regime_tva == 'ca3' or any('CA3' in t.titre.upper() for t in tasks):
            ca3_filtered = [t for t in tasks if ('TVA' in t.titre.upper() or 'CA3' in t.titre.upper()) and 'CA12' not in t.titre.upper()]
            ca3_dossiers.append({**item, 'tax_tasks': ca3_filtered})
        
        # CA12 tasks
        if d.regime_tva == 'ca12' or any('CA12' in t.titre.upper() for t in tasks):
            ca12_filtered = [t for t in tasks if 'CA12' in t.titre.upper()]
            ca12_dossiers.append({**item, 'tax_tasks': ca12_filtered})
        
        # IS tasks
        if d.regime_fiscale == 'IS' or any('IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper() for t in tasks):
            is_filtered = [t for t in tasks if 'IS' in t.titre.upper() or 'ACOMPTE' in t.titre.upper()]
            is_dossiers.append({**item, 'tax_tasks': is_filtered})
        
        # CFE tasks
        if d.has_cfe or any('CFE' in t.titre.upper() for t in tasks):
            cfe_filtered = [t for t in tasks if 'CFE' in t.titre.upper()]
            cfe_dossiers.append({**item, 'tax_tasks': cfe_filtered})
    
    return render_template('fiscal.html', dossier_data=dossier_data, 
        tva_dossiers=tva_dossiers, ca3_dossiers=ca3_dossiers, ca12_dossiers=ca12_dossiers,
        is_dossiers=is_dossiers, cfe_dossiers=cfe_dossiers,
        current_equipe=current_equipe,
        all_equipes_for_switch=all_equipes_for_switch, Tache=Tache, db=db)


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
        regime_fiscale = request.form.get('regime_fiscale')
        has_cfe = ('has_cfe' in request.form)

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

        nouveau_dossier = Dossier(
            numero_dossier=numero_dossier,
            intitule=intitule,
            collaborateur_id=int(collaborateur_id),
            equipe_id=int(equipe_id),
            regime_tva=regime_tva if regime_tva else None,
            frequence_tva=frequence_tva if frequence_tva else None,
            date_limite_declaration=date_limite,
            regime_fiscale=regime_fiscale if regime_fiscale else None,
            has_cfe=has_cfe
        )
        db.session.add(nouveau_dossier)
        db.session.flush()

        # Planifier les imp\u00f4ts pour ce dossier
        from .tva_scheduler import planifier_impots_dossier
        planifier_impots_dossier(nouveau_dossier)

        db.session.commit()
        flash('Dossier cr\u00e9\u00e9 avec succ\u00e8s et les t\u00e2ches fiscales ont \u00e9t\u00e9 g\u00e9n\u00e9r\u00e9es.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Erreur lors de la cr\u00e9ation du dossier: {e}")
        flash('Erreur lors de la cr\u00e9ation du dossier.', 'danger')
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
    equipe_id = request.form.get('equipe_id')
    manager_id = request.form.get('manager_id')
    if equipe_id and manager_id:
        equipe = Equipe.query.get(int(equipe_id))
        if equipe:
            equipe.manager_id = int(manager_id)
            db.session.commit()
            flash(f'Manager de l\'\u00e9quipe {equipe.nom} mis \u00e0 jour.', 'success')
    return redirect(url_for('equipes'))

@app.route('/configurer_email_equipe', methods=['GET', 'POST'])
@login_required
def configurer_email_equipe():
    flash('Fonctionnalit\u00e9 de configuration d\'email d\'\u00e9quipe non encore impl\u00e9ment\u00e9e.', 'info')
    return redirect(url_for('equipes'))

# ==========================
# Error handlers
# ==========================
def not_found(error):
    return render_template('error.html', code=404, message="Page non trouv\u00e9e."), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"500 error: {error}")
    try:
        db.session.rollback()
    except Exception:
        pass
    return render_template('error.html', code=500, message="Une erreur interne est survenue. Nos \u00e9quipes ont \u00e9t\u00e9 notifi\u00e9es."), 500
