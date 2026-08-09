from flask import render_template, request, redirect, url_for, flash, jsonify, send_from_directory, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from datetime import date, datetime
from sqlalchemy import desc
import csv
import io
import smtplib
import email
from app import app, db
from app.models import User, Dossier, Tache, Notification, CommentaireTache, Performance, AppSetting, Equipe
import os
from flask import send_from_directory
from app.integrations import inbound_mail

ADMIN_RESET_KEY = os.environ.get('ADMIN_RESET_KEY', 'cabinet-jmh-reset-2024')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

@app.route('/reset-admin', methods=['GET', 'POST'])
def reset_admin():
    if current_user.is_authenticated:
        flash('Déconnectez-vous avant de réinitialiser le compte admin.', 'warning')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        key = request.form.get('reset_key', '')
        new_password = request.form.get('new_password', '')
        if key != ADMIN_RESET_KEY:
            flash('Clé de réinitialisation invalide.', 'danger')
            return redirect(url_for('reset_admin'))
        if not new_password or len(new_password) < 4:
            flash('Le mot de passe doit contenir au moins 4 caractères.', 'danger')
            return redirect(url_for('reset_admin'))
        user = User.query.filter_by(email='admin@cabinet-jmh.com').first()
        if not user:
            flash('Compte admin introuvable.', 'danger')
            return redirect(url_for('login'))
        user.set_password(new_password)
        db.session.commit()
        flash('Mot de passe admin réinitialisé. Vous pouvez vous connecter.', 'success')
        return redirect(url_for('login'))
    return render_template('reset_admin.html')


# ============ EMAIL / INBOUND NOTIFICATIONS ============
def get_mail_config(equipe=None):
    """Return SMTP config for outgoing notifications only (not inbound)."""
    return {
        'MAIL_USERNAME': app.config.get('MAIL_USERNAME', ''),
        'MAIL_PASSWORD': app.config.get('MAIL_PASSWORD', ''),
        'MAIL_SERVER': app.config.get('MAIL_SERVER', 'smtp.office365.com'),
        'MAIL_PORT': app.config.get('MAIL_PORT', 587),
        'MAIL_DEFAULT_SENDER': app.config.get('MAIL_DEFAULT_SENDER', ''),
    }

def send_email_notification(to_email, subject, body, sender=None):
    """Send notification email via SMTP / Outlook."""
    try:
        config = get_mail_config()
        username = config['MAIL_USERNAME']
        password = config['MAIL_PASSWORD']
        if not username or not password:
            app.logger.warning("Mail not sent: MAIL_USERNAME/MAIL_PASSWORD not configured")
            return False, 'Mail non configuré'
        server_host = config['MAIL_SERVER']
        server_port = int(config['MAIL_PORT'])
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg['From'] = sender or config['MAIL_DEFAULT_SENDER'] or username
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(server_host, server_port, timeout=15)
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
        server.quit()
        return True, 'OK'
    except Exception as e:
        app.logger.error(f"send_email_notification error: {e}")
        return False, str(e)


def create_notification(user_id, message, type_notification='info', tache_id=None):
    """Create a notification record for a user."""
    try:
        notification = Notification(
            user_id=user_id,
            message=message,
            type_notification=type_notification,
            tache_id=tache_id,
            lu=False,
        )
        db.session.add(notification)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning(f"create_notification failed: {e}")



@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))
@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)



@app.route('/set-team/<int:equipe_id>')
@login_required
def set_team(equipe_id):
    """Set the current team in session for filtering dossiers/membres."""
    equipe = Equipe.query.get_or_404(equipe_id)
    if current_user.role != 'admin' and current_user.equipe_id != equipe_id:
        flash("Vous n'avez pas accès à cette équipe.", 'danger')
        return redirect(url_for('dashboard'))
    session['current_equipe_id'] = equipe_id
    flash(f"Contexte équipe: {equipe.nom}", 'info')
    return redirect(url_for('dashboard'))

@app.route('/api/equipes', methods=['GET'])
@login_required
def list_equipes():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    result = []
    for e in equipes:
        result.append({
            'id': e.id,
            'nom': e.nom,
            'description': e.description or '',
            'couleur': e.couleur,
            'icon': e.icon,
            'manager_id': e.manager_id,
            'manager_nom': e.manager.nom_complet() if e.manager else None,
            'manager_photo': e.manager.photo_profil if e.manager else 'default.png',
            'nb_membres': e.nb_membres(),
        })
    return jsonify({'ok': True, 'equipes': result})
@app.route('/equipes', methods=['GET', 'POST'])
@login_required
def equipes():
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        description = request.form.get('description', '').strip()
        couleur = request.form.get('couleur', '#FF8C00')
        icon = request.form.get('icon', 'bi-people')
        if not nom:
            flash('Le nom est requis.', 'danger')
        else:
            equipe = Equipe(nom=nom, description=description, couleur=couleur, icon=icon, manager_id=current_user.id)
            db.session.add(equipe)
            db.session.commit()
            flash('Équipe créée.', 'success')
            return redirect(url_for('equipes'))
    all_equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('equipes.html', equipes=all_equipes)
@app.route('/equipes/<int:equipe_id>/supprimer', methods=['POST'])
@login_required
def supprimer_equipe(equipe_id):
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    equipe = Equipe.query.get_or_404(equipe_id)
    # Détacher les membres de cette équipe
    try:
        User.query.filter_by(equipe_id=equipe.id).update({User.equipe_id: None})
    except Exception:
        pass
    db.session.delete(equipe)
    db.session.commit()
    flash(f'Équipe {equipe.nom} supprimée.', 'success')
    return redirect(url_for('equipes'))

@app.route('/equipes/<int:equipe_id>/email', methods=['POST'])
@login_required
def configurer_email_equipe(equipe_id):
    if current_user.role != 'admin':
        flash('Accès refusé — réservé à l\'administrateur.', 'danger')
        return redirect(url_for('equipes'))
    equipe = Equipe.query.get_or_404(equipe_id)
    equipe.equipe_email = request.form.get('equipe_email', '').strip() or None
    db.session.commit()
    flash(f'Email dédié configuré pour {equipe.nom}.', 'success')
    return redirect(url_for('equipes'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    equipe_nom = None
    equipe_icon = None
    equipe_couleur = None
    if request.args.get('equipe'):
        equipe_id = request.args.get('equipe')
        equipe = Equipe.query.get(equipe_id)
        if equipe:
            equipe_nom = equipe.nom
            equipe_icon = equipe.icon
            equipe_couleur = equipe.couleur
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
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('login.html', equipe_nom=equipe_nom, equipe_icon=equipe_icon, equipe_couleur=equipe_couleur)
# Global error handler for debugging
@app.errorhandler(Exception)
def handle_all_exceptions(e):
    app.logger.error(f"Unhandled exception: {type(e).__name__}: {e}", exc_info=True)
    return render_template('error.html', code=500, message=f"Erreur interne: {type(e).__name__}"), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            nom = request.form.get('nom', '').strip()
            prenom = request.form.get('prenom', '').strip()
            role = request.form.get('role', 'membre').strip()
            if not all([email, password, nom, prenom]):
                flash('Tous les champs sont requis.', 'danger')
            elif User.query.filter_by(email=email).first():
                flash('Cet email est déjà utilisé.', 'danger')
            elif role not in ['membre', 'manager', 'admin']:
                role = 'membre'
            else:
                user = User(email=email, nom=nom, prenom=prenom, role=role)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash('Account created! You can login.', 'success')
                return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            # Check if the error is about missing column equipe_id
            if "column users.equipe_id does not exist" in str(e):
                try:
                    # Add the column
                    db.session.execute(db.text("ALTER TABLE users ADD COLUMN equipe_id INTEGER"))
                    db.session.commit()
                    # Now retry the operation by re-executing the same POST logic
                    email = request.form.get('email', '').strip().lower()
                    password = request.form.get('password', '')
                    nom = request.form.get('nom', '').strip()
                    prenom = request.form.get('prenom', '').strip()
                    role = request.form.get('role', 'membre').strip()
                    if not all([email, password, nom, prenom]):
                        flash('Tous les champs sont requis.', 'danger')
                    elif User.query.filter_by(email=email).first():
                        flash('Cet email est déjà utilisé.', 'danger')
                    elif role not in ['membre', 'manager', 'admin']:
                        role = 'membre'
                    else:
                        user = User(email=email, nom=nom, prenom=prenom, role=role)
                        user.set_password(password)
                        db.session.add(user)
                        db.session.commit()
                        flash('Account created! You can login.', 'success')
                        return redirect(url_for('login'))
                except Exception as e2:
                    db.session.rollback()
                    app.logger.error(f"Migration error: {e2}")
                    return jsonify({'error': 'Migration failed', 'details': str(e2)}), 500
            else:
                app.logger.error(f"Registration error: {e}")
                return jsonify({'error': str(e), 'type': type(e).__name__}), 500
    return render_template('register.html')
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'info')
    return redirect(url_for('login'))
# ============ DASHBOARD ============

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role in ('admin', 'manager'):
        # Team-scoped data
        from flask import session
        equipe_id = session.get('current_equipe_id')
        if current_user.role == 'admin':
            # Admin sees data from the active team context (or all if no team selected)
            if equipe_id:
                equipe = Equipe.query.get(equipe_id)
                team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
                membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
                dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
                taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all()
            else:
                membres = User.query.filter_by(actif=True).all()
                dossiers = Dossier.query.all()
                taches = Tache.query.all()
        else:
            # Manager sees only their teams' data
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_user_ids = [current_user.id]
            for eq in mes_equipes:
                team_user_ids.extend([m.id for m in eq.membres.all()])
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
            taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all()

        # KPIs (team-scoped)
        today = date.today()
        if current_user.role == 'admin' and equipe_id:
            kpi = {
                'membres_actifs': len(membres),
                'dossiers_en_cours': len(dossiers),
                'taches_retard': len([t for t in taches if t.statut != 'terminee' and t.date_echeance < today]),
                'taches_haute_priorite': len([t for t in taches if t.priorite == 'haute' and t.statut == 'a_faire']),
            }
        else:
            kpi = {
                'membres_actifs': User.query.filter_by(actif=True, role='membre').count(),
                'dossiers_en_cours': Dossier.query.count(),
                'taches_retard': Tache.query.filter(Tache.statut != 'terminee', Tache.date_echeance < today).count(),
                'taches_haute_priorite': Tache.query.filter_by(priorite='haute', statut='a_faire').count(),
            }

        # Tâches du jour/semaine
        from datetime import timedelta
        week_end = today + timedelta(days=7)
        taches_jour = [t for t in taches if t.date_echeance == today and t.statut != 'terminee']
        taches_semaine = [t for t in taches if today < t.date_echeance <= week_end and t.statut != 'terminee']

        # Alertes deadlines
        alertes = []
        for d in dossiers:
            if d.date_limite_declaration:
                delta = (d.date_limite_declaration - today).days
                if delta < 0:
                    alertes.append({'type': 'danger', 'msg': f"Dossier {d.numero_dossier} en retard de {abs(delta)} jours"})
                elif delta <= 7:
                    alertes.append({'type': 'warning', 'msg': f"Dossier {d.numero_dossier} : deadline dans {delta} jours"})

        # Suggestions de tâches automatiques basées sur deadlines
        suggestions = []
        for d in dossiers:
            if d.date_limite_declaration:
                delta = (d.date_limite_declaration - today).days
                if 0 <= delta <= 14 and d.collaborateur_id:
                    suggestions.append({
                        'titre': f"Déclaration {d.regime_tva or 'fiscale'} - {d.numero_dossier}",
                        'dossier_id': d.id,
                        'assigne_a': d.collaborateur_id,
                        'priorite': 'haute' if delta <= 3 else 'moyenne',
                        'date_echeance': d.date_limite_declaration,
                    })

        return render_template(
            'dashboard_manager.html',
            membres=membres,
            dossiers=dossiers,
            taches=taches,
            kpi=kpi,
            taches_jour=taches_jour,
            taches_semaine=taches_semaine,
            today=today,
            alertes=alertes,
            suggestions=suggestions,
        )
    else:
        # Collaborateur view
        mes_dossiers = Dossier.query.filter_by(collaborateur_id=current_user.id).all()
        mes_taches = Tache.query.filter_by(assigne_a=current_user.id).all()
        taches_a_faire = [t for t in mes_taches if t.statut == 'a_faire']
        taches_en_cours = [t for t in mes_taches if t.statut == 'en_cours']
        taches_terminees = [t for t in mes_taches if t.statut == 'terminee']
        today = date.today()
        from datetime import timedelta
        week_end = today + timedelta(days=7)
        taches_jour = [t for t in mes_taches if t.date_echeance == today and t.statut != 'terminee']
        taches_semaine = [t for t in mes_taches if today < t.date_echeance <= week_end and t.statut != 'terminee']
        total = len(mes_taches)
        taux = round(len(taches_terminees) / total * 100) if total > 0 else 0
        taches_aujourdhui = len([t for t in mes_taches if t.date_echeance == today])
        kpi = {
            'taches_aujourdhui': taches_aujourdhui,
            'taches_a_faire': len(taches_a_faire),
            'taux_completion': taux,
            'total_taches': total,
        }
        return render_template(
            'dashboard_collaborateur.html',
            mes_dossiers=mes_dossiers,
            taches_a_faire=taches_a_faire,
            taches_en_cours=taches_en_cours,
            taches_terminees=taches_terminees,
            taches_jour=taches_jour,
            taches_semaine=taches_semaine,
            kpi=kpi,
            today=today
        )
# ============ MEMBRES ============

@app.route('/membres')
@login_required
def liste_membres():
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    membres = User.query.all()
    toutes_equipes = Equipe.query.order_by(Equipe.nom).all()
    # Manager ne voit que les équipes qu'il gère + équipes sans manager
    mes_equipes = Equipe.query.filter(
        (Equipe.manager_id == current_user.id) | (Equipe.manager_id == None)
    ).order_by(Equipe.nom).all() if current_user.role == 'manager' else toutes_equipes
    return render_template('membres.html', membres=membres, toutes_equipes=toutes_equipes, mes_equipes=mes_equipes)
@app.route('/membres/<int:user_id>/assigner-equipe', methods=['POST'])
@login_required
def assigner_equipe(user_id):
    """Admin assigns any user to any team."""
    if current_user.role != 'admin':
        flash('Accès refusé — réservé à l\'administrateur.', 'danger')
        return redirect(url_for('liste_membres'))
    user = User.query.get_or_404(user_id)
    equipe_id = request.form.get('equipe_id', '').strip()
    if equipe_id:
        equipe = Equipe.query.get(equipe_id)
        if equipe:
            user.equipe_id = equipe.id
        else:
            user.equipe_id = None
    else:
        user.equipe_id = None
    db.session.commit()
    flash(f'{user.prenom} {user.nom} assigné à l\'équipe.', 'success')
    return redirect(url_for('liste_membres'))
@app.route('/membres/<int:user_id>/assigner-equipe-manager', methods=['POST'])
@login_required
def assigner_equipe_manager(user_id):
    """Manager assigns a member to a team they manage (or unassigns)."""
    if current_user.role != 'manager':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('liste_membres'))
    user = User.query.get_or_404(user_id)
    equipe_id = request.form.get('equipe_id', '').strip()

    # Manager can only assign to teams they manage (or that are unassigned)
    mes_equipes = Equipe.query.filter(
        (Equipe.manager_id == current_user.id) | (Equipe.manager_id == None)
    ).all()
    mes_equipes_ids = [eq.id for eq in mes_equipes]

    if equipe_id and int(equipe_id) in mes_equipes_ids:
        user.equipe_id = int(equipe_id)
    else:
        user.equipe_id = None
    db.session.commit()
    flash(f'{user.prenom} {user.nom} classé dans l\'équipe.', 'success')
    return redirect(url_for('liste_membres'))
@app.route('/membres/ajouter', methods=['POST'])
@login_required
def ajouter_membre():
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    email = request.form.get('email', '').strip().lower()
    nom = request.form.get('nom', '').strip()
    prenom = request.form.get('prenom', '').strip()
    role = request.form.get('role', 'membre')
    poste = request.form.get('poste', '').strip()
    telephone = request.form.get('telephone', '').strip()
    mot_de_passe = request.form.get('mot_de_passe', '')

    if not all([email, nom, prenom, mot_de_passe]):
        flash('Email, nom, prénom et mot de passe sont requis.', 'danger')
        return redirect(url_for('liste_membres'))
    if User.query.filter_by(email=email).first():
        flash('Cet email existe déjà.', 'danger')
        return redirect(url_for('liste_membres'))

    user = User(email=email, nom=nom, prenom=prenom, role=role, poste=poste, telephone=telephone)
    user.set_password(mot_de_passe)
    db.session.add(user)
    db.session.commit()

    # Send welcome email
    subject = "Bienvenue sur l'application de gestion d'équipe"
    body = f"Bonjour {prenom},\n\nVotre compte a été créé.\nEmail: {email}\nMot de passe: {mot_de_passe}\n\nConnectez-vous: {request.host_url}login"
    send_email_notification(email, subject, body)

    flash(f'Membre {prenom} {nom} ajouté avec succès.', 'success')
    return redirect(url_for('liste_membres'))
@app.route('/membres/<int:user_id>/modifier', methods=['POST'])
@login_required
def modifier_membre(user_id):
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    user.nom = request.form.get('nom', user.nom).strip()
    user.prenom = request.form.get('prenom', user.prenom).strip()
    user.role = request.form.get('role', user.role)
    user.poste = request.form.get('poste', user.poste).strip()
    user.telephone = request.form.get('telephone', user.telephone).strip()
    db.session.commit()
    flash('Membre modifié.', 'success')
    return redirect(url_for('liste_membres'))
@app.route('/membres/<int:user_id>/supprimer', methods=['POST'])
@login_required
def supprimer_membre(user_id):
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'warning')
        return redirect(url_for('liste_membres'))
    try:
        Tache.query.filter_by(assigne_a=user.id).delete()
        Tache.query.filter_by(cree_par=user.id).update({Tache.cree_par: current_user.id})
        Notification.query.filter_by(user_id=user.id).delete()
        CommentaireTache.query.filter_by(user_id=user.id).delete()
    except Exception:
        pass
    db.session.delete(user)
    db.session.commit()
    flash(f'Membre {user.prenom} {user.nom} supprimé.', 'success')
    return redirect(url_for('liste_membres'))

@app.route('/membres/<int:user_id>')
@login_required
def fiche_membre(user_id):
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    # Performance calculations
    taches_terminees = Tache.query.filter_by(assigne_a=user.id, statut='terminee').all()
    total_terminees = len(taches_terminees)
    en_retard = sum(1 for t in taches_terminees if t.date_completion and t.date_completion.date() > t.date_echeance)
    taux_respect = round((total_terminees - en_retard) / total_terminees * 100, 1) if total_terminees > 0 else 0
    score = round(taux_respect * 0.6 + min(total_terminees * 2, 40), 1)  # simple scoring

    # Dossiers
    dossiers_en_cours = Dossier.query.filter_by(collaborateur_id=user.id).all()
    dossiers_termines = []

    # Tâches
    taches_membre = Tache.query.filter_by(assigne_a=user.id).order_by(Tache.date_echeance.desc()).limit(20).all()

    return render_template(
        'fiche_membre.html',
        user=user,
        dossiers_en_cours=dossiers_en_cours,
        dossiers_termines=dossiers_termines,
        taches_membre=taches_membre,
        total_terminees=total_terminees,
        en_retard=en_retard,
        taux_respect=taux_respect,
        score=score
    )
@app.route('/membres/<int:user_id>/photo', methods=['POST'])
@login_required
def upload_photo(user_id):
    if current_user.role != 'manager' and current_user.id != user_id:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if 'photo' not in request.files:
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('fiche_membre', user_id=user_id))
    file = request.files['photo']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'warning')
        return redirect(url_for('fiche_membre', user_id=user_id))
    if file and allowed_file(file.filename):
        filename = secure_filename(f"user_{user_id}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        # Delete old photo if not default
        if user.photo_profil and user.photo_profil != 'default.png':
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], user.photo_profil)
            if os.path.exists(old_path):
                os.remove(old_path)
        user.photo_profil = filename
        db.session.commit()
        flash('Photo mise à jour.', 'success')
    else:
        flash('Format non autorisé. Utilisez PNG, JPG ou GIF.', 'danger')
    return redirect(url_for('fiche_membre', user_id=user_id))
# ============ DOSSIERS ============

@app.route('/dossiers', methods=['GET', 'POST'])
@login_required
def dossiers():
    if current_user.role not in ('admin', 'manager'):
        # Collaborateur sees only their dossiers
        mes_dossiers = Dossier.query.filter_by(collaborateur_id=current_user.id).all()
        return render_template('dossiers.html', dossiers=mes_dossiers, membres=[], equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache)
    if request.method == 'POST':
        numero = request.form.get('numero_dossier', '').strip()
        intitule = request.form.get('intitule', '').strip()
        collaborateur_id = request.form.get('collaborateur_id', type=int)
        equipe_id = request.form.get('equipe_id', type=int)
        date_limite_str = request.form.get('date_limite_declaration', '').strip()
        date_limite = None
        if date_limite_str:
            date_limite = datetime.strptime(date_limite_str, '%Y-%m-%d').date()
        if not numero or not intitule:
            flash('Numéro et intitulé sont requis.', 'danger')
        elif Dossier.query.filter_by(numero_dossier=numero).first():
            flash('Ce numéro de dossier existe déjà.', 'danger')
        else:
            dossier = Dossier(
                numero_dossier=numero,
                intitule=intitule,
                collaborateur_id=collaborateur_id if collaborateur_id else None,
                equipe_id=equipe_id if equipe_id else None,
                regime_tva=request.form.get('regime_tva', '').strip() or None,
                frequence_tva=request.form.get('frequence_tva', 'trimestrielle').strip(),
                date_limite_declaration=date_limite
            )
            db.session.add(dossier)
            db.session.commit()
            # Planifier les tâches TVA automatiques
            if dossier.regime_tva in ('ca3', 'ca12'):
                try:
                    from app.tva_scheduler import planifier_taches_tva
                    planifier_taches_tva(dossier, dossier.frequence_tva)
                    flash('Tâches de TVA planifiées automatiquement.', 'info')
                except Exception as e:
                    app.logger.warning(f"TVA scheduling error: {e}")
            if collaborateur_id:
                collab = User.query.get(collaborateur_id)
                if collab:
                    msg = f"Un nouveau dossier vous a été assigné: {numero} - {intitule}"
                    create_notification(collab.id, msg, type_notification='assignation')
                    equipe = getattr(collab, 'equipe', None)
                    send_email_notification(collab.email, "Nouveau dossier assigné", msg, equipe=equipe)
            flash('Dossier créé avec succès.', 'success')
            return redirect(url_for('dossiers'))
    # Team-scoped: admin sees all, manager sees dossiers of their team members
    if current_user.role == 'admin':
        all_dossiers = Dossier.query.all()
        membres = User.query.filter_by(actif=True).all()
    else:
        # Manager sees only dossiers of members in their team(s)
        team_member_ids = [current_user.id]
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    # Team-scoped: admin sees active team's dossiers, manager sees dossiers of their team members
    equipe_id = session.get('current_equipe_id')
    current_equipe = None
    all_equipes_for_switch = []
    if equipe_id:
        current_equipe = Equipe.query.get(equipe_id)
    if current_user.role == 'admin':
        if equipe_id and current_equipe:
            team_member_ids = [m.id for m in current_equipe.membres.all()]
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all() if team_member_ids else []
            membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all() if team_member_ids else []
        else:
            all_dossiers = Dossier.query.all()
            membres = User.query.filter_by(actif=True).all()
    else:
        team_member_ids = [current_user.id]
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres, equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache, current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch)

@app.route('/dossiers/<int:dossier_id>/modifier', methods=['POST'])
@login_required
def modifier_dossier(dossier_id):
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    dossier = Dossier.query.get_or_404(dossier_id)
    dossier.numero_dossier = request.form.get('numero_dossier', dossier.numero_dossier).strip()
    dossier.intitule = request.form.get('intitule', dossier.intitule).strip()
    collaborateur_id = request.form.get('collaborateur_id', type=int)
    dossier.collaborateur_id = collaborateur_id if collaborateur_id else None
    dossier.regime_tva = request.form.get('regime_tva', dossier.regime_tva).strip() or None
    dossier.frequence_tva = request.form.get('frequence_tva', dossier.frequence_tva or 'trimestrielle').strip()
    equipe_id = request.form.get('equipe_id', type=int)
    dossier.equipe_id = equipe_id if equipe_id else None
    date_limite_str = request.form.get('date_limite_declaration', '').strip()
    if date_limite_str:
        dossier.date_limite_declaration = datetime.strptime(date_limite_str, '%Y-%m-%d').date()
    db.session.commit()
    # Re-planifier les tâches TVA si le régime a changé
    if dossier.regime_tva in ('ca3', 'ca12'):
        try:
            from app.tva_scheduler import planifier_taches_tva
            planifier_taches_tva(dossier, dossier.frequence_tva)
        except Exception as e:
            app.logger.warning(f"TVA scheduling error: {e}")
    flash('Dossier modifié.', 'success')
    return redirect(url_for('dossiers'))
@app.route('/dossiers/importer', methods=['POST'])
@login_required
def importer_dossiers():
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    if 'csv_file' not in request.files:
        flash('Aucun fichier fourni.', 'warning')
        return redirect(url_for('dossiers'))
    file = request.files['csv_file']
    if file.filename == '' or not file.filename.lower().endswith('.csv'):
        flash('Fichier CSV requis.', 'warning')
        return redirect(url_for('dossiers'))
    stream = io.StringIO(file.stream.read().decode('utf-8'))
    reader = csv.DictReader(stream)
    added = 0
    skipped = 0
    for row in reader:
        numero = (row.get('numero_dossier') or '').strip()
        intitule = (row.get('intitule') or '').strip()
        if not numero or not intitule:
            skipped += 1
            continue
        if Dossier.query.filter_by(numero_dossier=numero).first():
            skipped += 1
            continue
        collab_email = (row.get('collaborateur_email') or '').strip().lower()
        collaborateur_id = None
        if collab_email:
            u = User.query.filter_by(email=collab_email).first()
            if u:
                collaborateur_id = u.id
        regime = (row.get('regime_tva') or '').strip().lower()
        if regime not in {'ca3', 'ca12', 'exonere'}:
            regime = None
        date_limite = None
        raw_date = (row.get('date_limite_declaration') or '').strip()
        if raw_date:
            try:
                date_limite = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                date_limite = None
        dossier = Dossier(
            numero_dossier=numero,
            intitule=intitule,
            collaborateur_id=collaborateur_id,
            regime_tva=regime,
            date_limite_declaration=date_limite
        )
        db.session.add(dossier)
        added += 1
    db.session.commit()
    flash(f'Import terminé : {added} dossiers ajoutés, {skipped} ignorés.', 'success')
    return redirect(url_for('dossiers'))


@app.route('/tva-taches')
@login_required
def tva_taches():
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    equipe_id = session.get('current_equipe_id')
    if current_user.role == 'admin' and equipe_id:
        equipe = Equipe.query.get(equipe_id)
        team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
        tva_tasks = Tache.query.filter(Tache.titre.like('%TVA%'), Tache.assigne_a.in_(team_user_ids)).order_by(Tache.date_echeance).all()
        dossiers_equipe = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all() if team_user_ids else []
    elif current_user.role == 'manager':
        team_user_ids = [current_user.id]
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        for eq in mes_equipes:
            team_user_ids.extend([m.id for m in eq.membres.all()])
        tva_tasks = Tache.query.filter(Tache.titre.like('%TVA%'), Tache.assigne_a.in_(team_user_ids)).order_by(Tache.date_echeance).all()
        dossiers_equipe = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
    else:
        tva_tasks = Tache.query.filter(Tache.titre.like('%TVA%')).all()
        dossiers_equipe = Dossier.query.all()
    return render_template('tva_taches.html', tva_tasks=tva_tasks, dossiers=dossiers_equipe)


@app.route('/tva-planifier', methods=['POST'])
@login_required
def tva_planifier():
    if current_user.role != 'admin':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    dossier_id = request.form.get('dossier_id', type=int)
    dossier = Dossier.query.get_or_404(dossier_id)
    try:
        from app.tva_scheduler import planifier_taches_tva
        planifier_taches_tva(dossier, dossier.frequence_tva or 'trimestrielle')
        flash('Tâches TVA planifiées.', 'success')
    except Exception as e:
        app.logger.warning(f"TVA scheduling error: {e}")
        flash('Erreur de planification.', 'danger')
    return redirect(url_for('dossiers'))
# ============ TACHES ============

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    today = date.today()
    if current_user.role in ('admin', 'manager'):
        taches = Tache.query.filter(Tache.date_echeance == today, Tache.statut != 'terminee').all()
    else:
        taches = Tache.query.filter(Tache.assigne_a == current_user.id, Tache.date_echeance == today, Tache.statut != 'terminee').all()
    return render_template('taches.html', taches=taches, dossiers=[], membres=[], focus=today)
@app.route('/taches', methods=['GET', 'POST'])
@login_required
def taches():
    if current_user.role in ('admin', 'manager'):
        if request.method == 'POST':
            titre = request.form.get('titre', '').strip()
            description = request.form.get('description', '').strip()
            dossier_id = request.form.get('dossier_id', type=int)
            assigne_a = request.form.getlist('assigne_a')  # multi-select
            priorite = request.form.get('priorite', 'moyenne')
            date_echeance_str = request.form.get('date_echeance', '').strip()
            date_echeance = None
            if date_echeance_str:
                date_echeance = datetime.strptime(date_echeance_str, '%Y-%m-%d').date()
            if not titre or not date_echeance:
                flash('Titre et date d\'échéance requis.', 'danger')
            else:
                if not assigne_a:
                    assigne_a = [str(current_user.id)]
                tache = Tache(
                    titre=titre,
                    description=description,
                    dossier_id=dossier_id if dossier_id else None,
                    priorite=priorite,
                    date_echeance=date_echeance,
                    cree_par=current_user.id,
                    assigne_a=int(assigne_a[0])
                )
                db.session.add(tache)
                db.session.flush()
                for user_id in assigne_a[1:]:
                    clone = Tache(
                        titre=titre,
                        description=description,
                        dossier_id=dossier_id if dossier_id else None,
                        priorite=priorite,
                        date_echeance=date_echeance,
                        cree_par=current_user.id,
                        assigne_a=int(user_id)
                    )
                    db.session.add(clone)
                db.session.commit()
                for user_id in assigne_a:
                    user = User.query.get(int(user_id))
                    if user:
                        msg = f"Nouvelle tâche assignée: {titre} (Priorité: {priorite}, Échéance: {date_echeance.strftime('%d/%m/%Y')})"
                        create_notification(user.id, msg, type_notification='assignation')
                        equipe = getattr(current_user, 'equipe', None)
                        send_email_notification(user.email, f"Nouvelle tâche: {titre}", msg, equipe=equipe)
                flash('Tâche créée et notifications envoyées.', 'success')
                return redirect(url_for('taches'))
        all_taches = Tache.query.order_by(Tache.date_echeance.desc()).all()
        dossiers = Dossier.query.all()
        membres = User.query.filter_by(actif=True).all()
        return render_template('taches.html', taches=all_taches, dossiers=dossiers, membres=membres)
    # Collaborateur sees only their tasks
    mes_taches = Tache.query.filter_by(assigne_a=current_user.id).order_by(Tache.date_echeance.asc()).all()
    return render_template('taches.html', taches=mes_taches, dossiers=[], membres=[])
@app.route('/taches/<int:tache_id>/prendre_en_charge', methods=['POST'])
@login_required
def prendre_en_charge(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if tache.assigne_a != current_user.id:
        flash('Vous ne pouvez pas prendre en charge cette tâche.', 'danger')
        return redirect(url_for('dashboard'))
    if tache.statut == 'a_faire':
        tache.statut = 'en_cours'
        tache.date_prise_en_charge = datetime.utcnow()
        db.session.commit()
        # Notify manager
        create_notification(
            tache.cree_par,
            f"{current_user.prenom} {current_user.nom} a pris en charge la tâche: {tache.titre}",
            tache_id=tache.id,
            type_notification='prise_en_charge'
        )
        equipe = getattr(current_user, 'equipe', None)
        send_email_notification(
            User.query.get(tache.cree_par).email,
            f"Prise en charge: {tache.titre}",
            f"{current_user.prenom} {current_user.nom} a pris en charge la tâche: {tache.titre}"
        )
        flash('Tâche prise en charge.', 'success')
    return redirect(url_for('dashboard'))
@app.route('/taches/<int:tache_id>/terminer', methods=['POST'])
@login_required
def terminer_tache(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if tache.assigne_a != current_user.id and current_user.role != 'manager':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    if tache.statut != 'terminee':
        tache.statut = 'terminee'
        tache.date_completion = datetime.utcnow()
        db.session.commit()
        # Notify manager
        if tache.cree_par != current_user.id:
            create_notification(
                tache.cree_par,
                f"{current_user.prenom} {current_user.nom} a terminé la tâche: {tache.titre}",
                tache_id=tache.id,
                type_notification='completion'
            )
            equipe = getattr(current_user, 'equipe', None)
            send_email_notification(
                User.query.get(tache.cree_par).email,
                f"Tâche terminée: {tache.titre}",
                f"{current_user.prenom} {current_user.nom} a terminé la tâche: {tache.titre}"
            )
        flash('Tâche marquée comme terminée.', 'success')
    return redirect(url_for('dashboard'))
@app.route('/taches/<int:tache_id>/supprimer', methods=['POST'])
@login_required
def supprimer_tache(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if current_user.role != 'manager' and tache.assigne_a != current_user.id:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    # Nettoyer notifications et commentaires liés
    try:
        Notification.query.filter_by(tache_id=tache.id).delete()
        CommentaireTache.query.filter_by(tache_id=tache.id).delete()
    except Exception:
        pass
    db.session.delete(tache)
    db.session.commit()
    flash('Tâche supprimée.', 'success')
    return redirect(request.referrer or url_for('dashboard'))
@app.route('/taches/<int:tache_id>/commenter', methods=['POST'])
@login_required
def commenter_tache(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    message = request.form.get('message', '').strip()
    if message:
        commentaire = CommentaireTache(tache_id=tache.id, user_id=current_user.id, message=message)
        db.session.add(commentaire)
        db.session.commit()
        flash('Commentaire ajouté.', 'success')
    return redirect(request.referrer or url_for('dashboard'))
# ============ NOTIFICATIONS ============

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).limit(50).all()
    # Mark as read
    for n in notifs:
        if not n.lu:
            n.lu = True
    db.session.commit()
    return jsonify({'notifications': [{'id': n.id, 'message': n.message, 'type': n.type_notification, 'date': n.date_envoi.strftime('%d/%m/%Y %H:%M'), 'lu': n.lu} for n in notifs]})
@app.route('/notifications/non_lues')
@login_required
def notifications_non_lues():
    count = Notification.query.filter_by(user_id=current_user.id, lu=False).count()
    return jsonify({'count': count})
# ============ PROFIL ============

@app.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    if request.method == 'POST':
        # Photo upload
        if 'photo' in request.files and request.files.get('photo').filename:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                try:
                    filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                    upload_folder = app.config.get('UPLOAD_FOLDER')
                    if not upload_folder or not os.path.isdir(upload_folder):
                        os.makedirs(upload_folder, exist_ok=True)
                    filepath = os.path.join(upload_folder, filename)
                    file.save(filepath)
                    # Delete old photo if not default
                    if current_user.photo_profil and current_user.photo_profil != 'default.png':
                        old_path = os.path.join(upload_folder, current_user.photo_profil)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    current_user.photo_profil = filename
                    db.session.commit()
                    # Fetch request → JSON, regular form submit → redirect
                    if request.headers.get('Content-Type', '').startswith('multipart/form-data'):
                        return jsonify({'ok': True, 'message': 'Photo de profil mise à jour.', 'photo_url': url_for('uploaded_file', filename=filename)}), 200
                    flash('Photo de profil mise à jour.', 'success')
                    return redirect(url_for('profil'))
                except Exception as e:
                    app.logger.error(f"Photo upload error: {e}")
                    db.session.rollback()
                    if request.headers.get('Content-Type', '').startswith('multipart/form-data'):
                        return jsonify({'ok': False, 'message': str(e)}), 500
                    flash(f'Erreur lors du téléchargement: {e}', 'danger')
                    return redirect(url_for('profil'))
            else:
                flash('Format de fichier non autorisé.', 'danger')
                return redirect(url_for('profil'))
        else:
            # Regular profile update (name, phone, poste, password)
            current_user.nom = request.form.get('nom', current_user.nom).strip()
            current_user.prenom = request.form.get('prenom', current_user.prenom).strip()
            current_user.telephone = request.form.get('telephone', current_user.telephone).strip()
            current_user.poste = request.form.get('poste', current_user.poste).strip()
            # Change password if provided
            new_password = request.form.get('new_password', '').strip()
            if new_password:
                current_user.set_password(new_password)
            db.session.commit()
            flash('Profil mis à jour.', 'success')
            return redirect(url_for('profil'))
    return render_template('profil.html')
# ============ FICHIERS ============

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
# ============ ADMIN DEBUG ============\

@app.route('/admin/debug')
@login_required
def admin_debug():
    if current_user.role != 'admin':
        flash('Accès refusé. Compte admin requis.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('admin_debug.html')
@app.route('/api/admin/debug/run', methods=['POST'])
@login_required
def api_admin_debug_run():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé. Compte admin requis.'}), 403
    results = []
    # 1. Python syntax check on routes.py
    try:
        import ast
        with open(os.path.join(app.root_path, 'routes.py')) as f:
            ast.parse(f.read())
        results.append({'check': 'Syntaxe routes.py', 'status': 'ok', 'message': 'OK'})
    except Exception as e:
        results.append({'check': 'Syntaxe routes.py', 'status': 'error', 'message': str(e)})
    # 2. Database connection
    try:
        db.session.execute(db.text('SELECT 1'))
        results.append({'check': 'Connexion base de données', 'status': 'ok', 'message': 'OK'})
    except Exception as e:
        results.append({'check': 'Connexion base de données', 'status': 'error', 'message': str(e)})
    # 3. Missing template files
    try:
        import glob
        templates = glob.glob(os.path.join(app.root_path, '..', 'templates', '*.html'))
        results.append({'check': 'Templates', 'status': 'ok', 'message': f'{len(templates)} templates trouvés'})
    except Exception as e:
        results.append({'check': 'Templates', 'status': 'error', 'message': str(e)})
    # 4. Upload folder
    try:
        upload_folder = app.config.get('UPLOAD_FOLDER')
        exists = upload_folder and os.path.isdir(upload_folder)
        results.append({'check': 'Dossier uploads', 'status': 'ok' if exists else 'warning', 'message': f'Upload folder: {upload_folder} (exists={exists})'})
    except Exception as e:
        results.append({'check': 'Dossier uploads', 'status': 'error', 'message': str(e)})
    # 5. Cloudflare inbound config
    try:
        from app.integrations.inbound_mail import InboundMailClient
        client = InboundMailClient()
        inbound_enabled = client.is_configured()
        secret_configured = bool(client.get_webhook_secret())
        results.append({'check': 'Cloudflare inbound (webhook)', 'status': 'ok' if inbound_enabled else 'warning', 'message': f'Activé={inbound_enabled}, Secret={secret_configured}'})
    except Exception as e:
        results.append({'check': 'Cloudflare inbound (webhook)', 'status': 'error', 'message': str(e)})
    # 6. OpenRouter LLM config
    try:
        from app.integrations.openrouter import OpenRouterClient
        llm = OpenRouterClient()
        configured = llm.is_configured()
        results.append({'check': 'LLM (OpenRouter)', 'status': 'ok' if configured else 'warning', 'message': f'Configured={configured}'})
    except Exception as e:
        results.append({'check': 'LLM (OpenRouter)', 'status': 'error', 'message': str(e)})
    # 7. Static files missing
    try:
        missing = []
        for f in ['img/logo-jmh.png', 'css/style.css']:
            path = os.path.join(app.static_folder, f)
            if not os.path.exists(path):
                missing.append(f)
        results.append({'check': 'Fichiers statiques', 'status': 'ok' if not missing else 'warning', 'message': 'Manquants: ' + ', '.join(missing) if missing else 'Tous présents'})
    except Exception as e:
        results.append({'check': 'Fichiers statiques', 'status': 'error', 'message': str(e)})
    # 8. Routes accessibility
    try:
        from flask import url_for
        with app.test_request_context():
            routes_ok = 0
            routes_err = []
            routes_need_auth = 0
            for rule in app.url_map.iter_rules():
                if rule.arguments:
                    # Routes with path params (e.g. /membres/<int:user_id>)
                    continue
                try:
                    url_for(rule.endpoint)
                    routes_ok += 1
                except Exception:
                    routes_need_auth += 1  # Usually @login_required routes failing without context
            total = routes_ok + routes_need_auth
            results.append({'check': 'Routes accessibles', 'status': 'ok', 'message': f'{routes_ok}/{total} routes OK, {routes_need_auth} nécessitent une authentification'})
    except Exception as e:
        results.append({'check': 'Routes accessibles', 'status': 'error', 'message': str(e)})
    # 9. Model integrity (check all tables exist)
    try:
        from app.models import User, Dossier, Tache, Notification, SuggestionTache, AppSetting, Equipe, CommentaireTache, Performance
        results.append({'check': 'Modèles SQLAlchemy', 'status': 'ok', 'message': 'Tous importables'})
    except Exception as e:
        results.append({'check': 'Modèles SQLAlchemy', 'status': 'error', 'message': str(e)})
    # 10. Inbound webhook config
    try:
        from app.integrations.inbound_mail import InboundMailClient
        inbound = InboundMailClient()
        mode_row = AppSetting.query.filter_by(cle='MAILBOX_INBOUND_MODE').first()
        mode = (mode_row.valeur if mode_row else 'false').lower() == 'true'
        secret_ok = bool(inbound.secret)
        results.append({'check': 'Inbound webhook', 'status': 'ok' if mode else 'warning', 'message': f'mode={mode}, secret={secret_ok}'})
    except Exception as e:
        results.append({'check': 'Inbound webhook', 'status': 'error', 'message': str(e)})
    return jsonify({'ok': True, 'results': results})
@app.route('/api/admin/debug/run-active', methods=['POST'])
@login_required
def api_admin_debug_run_active():
    """Active debug: navigates pages, checks for 500s, white backgrounds, broken links."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé. Compte admin requis.'}), 403
    try:
        import subprocess, sys, os
        # Run the debug bot from the project root
        project_root = os.path.join(app.root_path, '..')
        result = subprocess.run(
            [sys.executable, os.path.join(project_root, 'active_debug.py'), '--url', request.host_url.rstrip('/')],
            capture_output=True, text=True, timeout=120, cwd=project_root
        )
        # Read the JSON report
        import json
        report_path = os.path.join(project_root, 'debug_report.json')
        results = []
        try:
            with open(report_path) as f:
                results = json.load(f)
        except Exception:
            pass
        # Also include stdout for human-readable summary
        return jsonify({
            'ok': True,
            'results': results,
            'stdout': result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout,
            'stderr': result.stderr[-1000:] if result.stderr else '',
        })
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'message': 'Diagnostic actif a expiré (120s)'}), 504
    except Exception as e:
        app.logger.error(f"Active debug error: {e}")
        return jsonify({'ok': False, 'message': str(e)}), 500
# ============ API / AJAX ============

@app.route('/api/equipe/stats')
@login_required
def api_equipe_stats():
    if current_user.role not in ('admin', 'manager'):
        return jsonify({}), 403
    membres = User.query.filter_by(actif=True, role='membre').all()
    stats = []
    for m in membres:
        stats.append({
            'id': m.id,
            'nom': m.nom_complet(),
            'photo': m.photo_profil,
            'dossiers_en_cours': m.nb_dossiers_en_cours(),
            'taches_en_retard': m.nb_taches_en_retard(),
            'taches_a_faire': m.nb_taches_a_faire()
        })
    return jsonify(stats)
@app.route('/api/suggestions', methods=['GET'])
@login_required
def api_suggestions():
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'suggestions': []}), 403
    suggestions = _build_suggestions()
    # Merge SuggestionTache records from mailbox processing
    try:
        from app.models import SuggestionTache
        from app import db
        total_count = db.session.query(SuggestionTache).count()
        all_statuses = db.session.query(SuggestionTache.statut).distinct().all()

        status_filter = request.args.get('status', 'en_attente')
        if status_filter == 'all':
            db_suggestions = SuggestionTache.query.order_by(SuggestionTache.date_creation.desc()).all()
        else:
            db_suggestions = SuggestionTache.query.filter_by(statut=status_filter).order_by(SuggestionTache.date_creation.desc()).all()

        for s in db_suggestions:
            suggestions.append({
                'id': s.id,
                'sujet': s.sujet,
                'sujet_suggere': s.titre_suggere,
                'description_suggeree': s.description_suggeree,
                'dossier_id': s.dossier_id,
                'dossier_nom': s.dossier.nom if s.dossier else None,
                'priorite_suggeree': s.priorite_suggeree,
                'statut': s.statut,
                'mail_uid': s.mail_uid,
                'date_creation': s.date_creation.strftime('%Y-%m-%d %H:%M') if s.date_creation else None,
                'source': 'mailbox',
            })

        return jsonify({'ok': True, 'suggestions': suggestions, 'count': len(suggestions), 'total_in_db': total_count, 'distinct_statuses': [s[0] for s in all_statuses]})
    except Exception as e:
        app.logger.error(f"Erreur api_suggestions db merge : {e}")
        # Still return deadline-based suggestions
        return jsonify({'ok': True, 'suggestions': suggestions, 'count': len(suggestions)})
@app.route('/api/suggestions/refresh', methods=['POST'])
@login_required
def api_suggestions_refresh():
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'suggestions': []}), 403
    suggestions = _build_suggestions()
    return jsonify({'suggestions': suggestions})
def _build_suggestions():
    suggestions = []

    # Suggestions depuis les deadlines des dossiers
    today = date.today()
    dossiers = Dossier.query.all()
    for d in dossiers:
        if d.date_limite_declaration:
            delta = (d.date_limite_declaration - today).days
            if 0 <= delta <= 14 and d.collaborateur_id:
                suggestions.append({
                    'titre': f"Déclaration {d.regime_tva or 'fiscale'} - {d.numero_dossier}",
                    'dossier_id': d.id,
                    'assigne_a': d.collaborateur_id,
                    'priorite': 'haute' if delta <= 3 else 'moyenne',
                    'date_echeance': d.date_limite_declaration.strftime('%Y-%m-%d'),
                    'source': 'deadline'
                })

    # Suggestions IA à partir des messages Teams
    try:
        from app.integrations import get_openrouter, get_teams as _teams_client
        llm = get_openrouter()
        teams_client = _teams_client()

        texts = []
        try:
            if teams_client.is_configured():
                for m in teams_client.fetch_recent_messages(limit=20):
                    texts.append(f"- TEAMS: {m.get('subject','')} | {m.get('body_preview','')}")
        except Exception:
            pass

        if llm.is_configured() and texts:
            prompt = (
                "Tu es un assistant comptable. A partir des messages suivants, propose 3 à 6 tâches concrètes "
                "au format JSON: [{\"titre\":\"...\",\"priorite\":\"haute|moyenne|basse\",\"date_echeance\":\"YYYY-MM-DD\"}].\n"
                + "\n".join(texts[:40])
            )
            raw = llm.chat([
                {"role": "system", "content": "Réponds uniquement par un JSON valide."},
                {"role": "user", "content": prompt},
            ])
            if raw:
                import json
                try:
                    items = json.loads(raw)
                    if isinstance(items, list):
                        for item in items[:6]:
                            if isinstance(item, dict) and item.get("titre"):
                                suggestions.append({
                                    'titre': item.get("titre"),
                                    'dossier_id': item.get("dossier_id"),
                                    'assigne_a': item.get("assigne_a"),
                                    'priorite': item.get("priorite", "moyenne"),
                                    'date_echeance': item.get("date_echeance"),
                                    'source': 'openrouter'
                                })
                except Exception:
                    pass
    except Exception:
        pass

    # Dedup
    seen = set()
    unique = []
    for s in suggestions:
        key = (s.get('titre'), s.get('dossier_id'), s.get('assigne_a'))
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique
@app.route('/init-db')
def init_db():
    db.create_all()
    return "Base de données initialisée."
# ============ SETTINGS / INTEGRATIONS ============

@app.route('/settings')
@login_required
def settings():
    settings_list = AppSetting.query.all()
    openrouter_model = ''
    for s in settings_list:
        if s.cle == 'OPENROUTER_MODEL' and s.valeur:
            openrouter_model = s.valeur
            break
    return render_template('settings.html', settings=settings_list, openrouter_model=openrouter_model)
@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        cle = data.get('cle', '').strip()
        valeur = data.get('valeur', '').strip()
        service = data.get('service', 'general').strip()
        type_valeur = data.get('type_valeur', 'string').strip()
        masque = bool(data.get('masque', False))

        if not cle:
            return jsonify({'error': 'Cle requise'}), 400

        setting = AppSetting.query.filter_by(cle=cle).first()
        if not setting:
            setting = AppSetting(cle=cle, service=service, type_valeur=type_valeur, masque=masque)
            db.session.add(setting)

        setting.valeur = valeur
        setting.service = service
        setting.type_valeur = type_valeur
        setting.masque = masque
        db.session.commit()
        return jsonify({'ok': True})

    settings = AppSetting.query.all()
    return jsonify([
        {
            'id': s.id,
            'cle': s.cle,
            'valeur': s.valeur if not s.masque else '',
            'service': s.service,
            'type_valeur': s.type_valeur,
            'masque': s.masque,
        }
        for s in settings
    ])
@app.route('/api/settings/<int:setting_id>', methods=['DELETE'])
@login_required
def delete_setting(setting_id):
    setting = AppSetting.query.get_or_404(setting_id)
    db.session.delete(setting)
    db.session.commit()
    return jsonify({'ok': True})
@app.route('/api/mail/test', methods=['POST'])
@login_required
def test_mail():
    data = request.get_json(silent=True) or {}
    subject = data.get('subject', 'Test Cabinet Team Manager')
    body = data.get('body', 'Ceci est un test d\'envoi d\'email depuis l\'application.')
    recipient = data.get('recipient', current_user.email)
    sender = data.get('sender') or None
    ok, msg = send_email_notification(recipient, subject, body, sender=sender)
    status = 200 if ok else 400
    return jsonify({'ok': ok, 'message': msg}), status
@app.route('/api/test/teams', methods=['POST'])
@login_required
def test_teams():
    try:
        from app.integrations.teams import TeamsClient
        client_id = AppSetting.query.filter_by(cle='TEAMS_CLIENT_ID').first()
        tenant_id = AppSetting.query.filter_by(cle='TEAMS_TENANT_ID').first()
        client_secret = AppSetting.query.filter_by(cle='TEAMS_CLIENT_SECRET').first()
        team_id = AppSetting.query.filter_by(cle='TEAMS_TEAM_ID').first()
        
        if not all([client_id, tenant_id, client_secret]) or not all([client_id.valeur, tenant_id.valeur, client_secret.valeur]):
            return jsonify({'ok': False, 'message': 'Identifiants Teams non configurés.'}), 400
        
        client = TeamsClient(
            client_id=client_id.valeur,
            tenant_id=tenant_id.valeur,
            client_secret=client_secret.valeur,
            team_id=team_id.valeur if team_id else None
        )
        
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Client Teams non configuré.'}), 400
        
        # Test token acquisition
        token = client._get_access_token()
        if not token:
            return jsonify({'ok': False, 'message': 'Impossible d\'obtenir le token d\'accès.'}), 400
        
        return jsonify({'ok': True, 'message': 'Connexion Teams OK. Token obtenu.'})
    except Exception as e:
        app.logger.error(f"Erreur test Teams: {e}")
        return jsonify({'ok': False, 'message': f'Échec: {e}'}), 400
@app.route('/api/openrouter/models', methods=['GET'])
@login_required
def openrouter_models():
    try:
        from app.integrations.openrouter import OpenRouterClient
        client = OpenRouterClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Clé API OpenRouter non configurée.', 'stage': 'config'}), 400
        provider = request.args.get('provider', '').strip() or None
        models = client.list_models(provider=provider)
        return jsonify({'ok': True, 'models': models, 'stage': 'models'})
    except Exception as e:
        app.logger.error(f"Erreur openrouter models: {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500
@app.route('/api/test/openrouter', methods=['POST'])
@login_required
def test_openrouter():
    try:
        from app.integrations.openrouter import OpenRouterClient
        client = OpenRouterClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Clé API OpenRouter non configurée.', 'stage': 'config'}), 400
        models = client.list_models()
        count = len(models)
        return jsonify({
            'ok': True,
            'message': f'Connexion OpenRouter OK. {count} modèle(s) disponible(s). Modèle par défaut : {client.model}',
            'count': count,
            'model': client.model,
            'stage': 'openrouter',
        })
    except Exception as e:
        app.logger.error(f"Erreur test OpenRouter: {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500
@app.route('/api/suggestions', methods=['GET'])
@login_required
def list_suggestions():
    try:
        from app.models import SuggestionTache
        from app import db
        status = request.args.get('status', 'en_attente')

        try:
            total_count = db.session.query(SuggestionTache).count()
            all_statuses = db.session.query(SuggestionTache.statut).distinct().all()
        except Exception as table_err:
            return jsonify({'ok': False, 'message': f'Table error: {table_err}', 'total_in_db': -1}), 500

        if status == 'all':
            suggestions = SuggestionTache.query.order_by(SuggestionTache.date_creation.desc()).all()
        else:
            suggestions = SuggestionTache.query.filter_by(statut=status).order_by(SuggestionTache.date_creation.desc()).all()
        result = []
        for s in suggestions:
            result.append({
                'id': s.id,
                'sujet': s.sujet,
                'titre_suggere': s.titre_suggere,
                'description_suggeree': s.description_suggeree,
                'dossier_id': s.dossier_id,
                'dossier_nom': s.dossier.nom if s.dossier else None,
                'priorite_suggeree': s.priorite_suggeree,
                'statut': s.statut,
                'mail_uid': s.mail_uid,
                'date_creation': s.date_creation.strftime('%Y-%m-%d %H:%M') if s.date_creation else None,
            })
        return jsonify({'ok': True, 'count': len(result), 'total_in_db': total_count, 'distinct_statuses': [s[0] for s in all_statuses], 'suggestions': result})
    except Exception as e:
        app.logger.error(f"Erreur list suggestions : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
@app.route('/api/suggestions/<int:suggestion_id>/validate', methods=['POST'])
@login_required
def validate_suggestion(suggestion_id):
    try:
        from app.models import SuggestionTache, Tache, Notification
        data = request.get_json() or {}
        suggestion = SuggestionTache.query.get_or_404(suggestion_id)
        suggestion.statut = 'validee'
        suggestion.valide_par = current_user.id
        suggestion.date_validation = datetime.utcnow()
        db.session.commit()

        # Create actual task from validated suggestion
        assignee_id = data.get('assignee')
        due_date = data.get('due_date')
        priority = data.get('priority', 'moyenne')
        dossier_id = data.get('dossier_id')

        if not assignee_id or not due_date:
            return jsonify({'ok': False, 'message': 'Collaborateur et date d\'échéance requis.'}), 400

        tache = Tache(
            titre=suggestion.titre_suggere,
            description=suggestion.description_suggeree,
            dossier_id=dossier_id,
            assigne_a=assignee_id,
            cree_par=current_user.id,
            priorite=priority,
            statut='a_faire',
            date_echeance=datetime.strptime(due_date, '%Y-%m-%d').date(),
        )
        db.session.add(tache)
        db.session.commit()

        # Create notification for assignee
        notification = Notification(
            user_id=assignee_id,
            tache_id=tache.id,
            message=f"Nouvelle tâche assignée: {tache.titre}",
            type_notification='assignation',
            lu=False,
        )
        db.session.add(notification)
        db.session.commit()

        # Send email notification to assignee
        assignee = User.query.get(assignee_id)
        if assignee:
            send_email_notification(
                to_email=assignee.email,
                subject=f"Nouvelle tâche: {tache.titre}",
                body=f"Bonjour {assignee.prenom},\n\nUne nouvelle tâche vous a été assignée:\n{tache.titre}\n\nDescription: {tache.description or 'Aucune'}\nÉchéance: {tache.date_echeance}\n\nCordialement,\nCabinet JMH"
            )

        return jsonify({'ok': True, 'message': 'Suggestion validée et tâche créée.', 'tache_id': tache.id})
    except Exception as e:
        app.logger.error(f"Erreur validate suggestion : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
@app.route('/api/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
def reject_suggestion(suggestion_id):
    try:
        from app.models import SuggestionTache
        suggestion = SuggestionTache.query.get_or_404(suggestion_id)
        suggestion.statut = 'rejetee'
        suggestion.valide_par = current_user.id
        suggestion.date_validation = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion rejetée.'})
    except Exception as e:
        app.logger.error(f"Erreur reject suggestion : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
@app.route('/suggestions')
@login_required
def suggestions_page():
    from app.models import User, Dossier
    users = User.query.filter_by(actif=True).all()
    dossiers = Dossier.query.order_by(Dossier.numero_dossier).all()
    return render_template('suggestions.html', users=users, dossiers=dossiers)
@app.route('/api/suggestions/reset', methods=['POST'])
@login_required
def reset_suggestions():
    try:
        from app.models import SuggestionTache, AppSetting
        from app import db
        # Delete all suggestions
        SuggestionTache.query.delete()
        # Delete all skip markers
        skipped = AppSetting.query.filter(AppSetting.cle.like('MAILBOX_SKIPPED_%')).all()
        for s in skipped:
            db.session.delete(s)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Toutes les suggestions ont été supprimées. Vous pouvez retraiter la boîte mail.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': f'Erreur: {e}'}), 500
@app.route('/api/mailbox/inbound', methods=['POST'])
def inbound_mail_webhook():
    """
    Cloudflare Email Routing inbound webhook.
    Le Worker Cloudflare POSTe les emails reçus vers cette route.
    Activation: active la route dans Paramètres > Réception par webhook inbound
    Secret optionnel: X-Webhook-Secret header verification
    """
    try:
        client = inbound_mail.InboundMailClient()

        # Verify secret if configured
        payload_bytes = request.get_data() or b""
        signature = request.headers.get("X-Webhook-Secret", "")
        if client.get_webhook_secret():
            if not client._verify_signature(payload_bytes, signature):
                app.logger.warning("Inbound webhook: signature invalide")
                return jsonify({'ok': False, 'message': 'Signature invalide'}), 403

        # Check if inbound mode is enabled
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Mode inbound non activé dans Paramètres'}), 501

        # Get payload
        payload = {}
        if request.content_type and "application/json" in request.content_type:
            payload = request.get_json(silent=True) or {}
        else:
            payload = request.form.to_dict() if request.form else {}

        # Normalize payload to standard fields expected by process_webhook
        normalized = {
            "from": payload.get("from", payload.get("sender", "")),
            "subject": payload.get("subject", ""),
            "body": payload.get("body", payload.get("body_plain", payload.get("text", ""))),
            "body_plain": payload.get("body_plain", payload.get("body-plain", "")),
            "body_html": payload.get("body_html", payload.get("body-html", "")),
            "to": payload.get("to", payload.get("recipient", "")),
            "recipient": payload.get("recipient", payload.get("to", "")),
            "message_id": payload.get("message_id", payload.get("Message-Id", "")),
            "timestamp": payload.get("timestamp", ""),
        }

        result = client.process_payload(normalized)
        app.logger.info("Inbound mail processed: %s", result)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Erreur inbound mailbox : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
@app.route('/mes-taches')
@login_required
def mes_taches():
    return render_template('mes_taches.html')
@app.route('/api/taches/mes-taches')
@login_required
def api_mes_taches():
    try:
        from app.models import Tache
        statut = request.args.get('statut', 'a_faire')
        taches = Tache.query.filter_by(assigne_a=current_user.id, statut=statut).order_by(Tache.date_echeance.asc()).all()
        result = []
        for t in taches:
            result.append({
                'id': t.id,
                'titre': t.titre,
                'description': t.description,
                'priorite': t.priorite,
                'statut': t.statut,
                'date_echeance': t.date_echeance.strftime('%Y-%m-%d') if t.date_echeance else '',
            })
        return jsonify({'ok': True, 'taches': result})
    except Exception as e:
        app.logger.error(f"Erreur mes taches : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
@app.route('/api/taches/<int:tache_id>/statut', methods=['POST'])
@login_required
def update_tache_statut(tache_id):
    try:
        from app.models import Tache
        data = request.get_json() or {}
        statut = data.get('statut')
        if statut not in ['a_faire', 'en_cours', 'terminee']:
            return jsonify({'ok': False, 'message': 'Statut invalide.'}), 400

        tache = Tache.query.get_or_404(tache_id)
        if tache.assigne_a != current_user.id:
            return jsonify({'ok': False, 'message': 'Non autorisé.'}), 403

        tache.statut = statut
        if statut == 'en_cours' and not tache.date_prise_en_charge:
            tache.date_prise_en_charge = datetime.utcnow()
        if statut == 'terminee' and not tache.date_completion:
            tache.date_completion = datetime.utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Statut mis à jour.'})
    except Exception as e:
        app.logger.error(f"Erreur update statut : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}'}), 500
