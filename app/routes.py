from flask import render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from datetime import date, datetime
from sqlalchemy import desc
import csv
import io
import smtplib
import email
from app import app, db, mail
from app.models import User, Dossier, Tache, Notification, CommentaireTache, Performance, AppSetting, Equipe
from flask_mail import Message
import os


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}


def get_mail_config():
    username = AppSetting.query.filter_by(cle='MAIL_USERNAME').first()
    password = AppSetting.query.filter_by(cle='MAIL_PASSWORD').first()
    server = AppSetting.query.filter_by(cle='MAIL_SERVER').first()
    port = AppSetting.query.filter_by(cle='MAIL_PORT').first()
    use_tls = AppSetting.query.filter_by(cle='MAIL_USE_TLS').first()
    default_sender = AppSetting.query.filter_by(cle='MAIL_DEFAULT_SENDER').first()

    return {
        'MAIL_USERNAME': (username.valeur if username else '') or app.config.get('MAIL_USERNAME', ''),
        'MAIL_PASSWORD': (password.valeur if password else '') or app.config.get('MAIL_PASSWORD', ''),
        'MAIL_SERVER': (server.valeur if server else '') or app.config.get('MAIL_SERVER', 'smtp.office365.com'),
        'MAIL_PORT': int((port.valeur if port else '') or app.config.get('MAIL_PORT', 587)),
        'MAIL_USE_TLS': (use_tls.valeur if use_tls else 'true').lower() == 'true',
        'MAIL_DEFAULT_SENDER': (default_sender.valeur if default_sender else '') or app.config.get('MAIL_DEFAULT_SENDER', ''),
    }


def send_email_notification(to_email, subject, body, sender=None):
    try:
        config = get_mail_config()
        username = config.get('MAIL_USERNAME') or app.config.get('MAIL_USERNAME', '')
        password = config.get('MAIL_PASSWORD') or app.config.get('MAIL_PASSWORD', '')
        server_host = config.get('MAIL_SERVER') or app.config.get('MAIL_SERVER', 'smtp.office365.com')
        server_port = config.get('MAIL_PORT', app.config.get('MAIL_PORT', 587))
        use_tls = config.get('MAIL_USE_TLS', app.config.get('MAIL_USE_TLS', True))
        default_sender = config.get('MAIL_DEFAULT_SENDER') or app.config.get('MAIL_DEFAULT_SENDER', '')

        if not username:
            return False, 'MAIL_USERNAME non configuré. Allez dans Paramètres.'
        if not password:
            return False, 'MAIL_PASSWORD vide. Allez dans Paramètres.'

        from_email = sender or default_sender or username

        app.logger.info(
            "SMTP test: server=%s port=%s username=%s sender=%s recipient=%s",
            server_host,
            server_port,
            username,
            from_email,
            to_email,
        )

        msg = Message(subject, recipients=[to_email], body=body, sender=from_email)
        smtp = smtplib.SMTP(server_host, server_port, timeout=20)
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(username, password)
        smtp.sendmail(from_email, [to_email], msg.as_string())
        smtp.quit()
        return True, f'Email envoyé à {to_email}'
    except Exception as e:
        app.logger.error(f"Erreur envoi mail: {e}")
        # Fallback vers Brevo API en cas d'échec SMTP
        try:
            from app.integrations.brevo import send_email_via_brevo_api
            api_key = AppSetting.query.filter_by(cle='BREVO_API_KEY').first()
            if api_key and api_key.valeur:
                app.logger.info("SMTP échoué, bascule vers Brevo API")
                ok = send_email_via_brevo_api(to_email=to_email, subject=subject, body=body)
                if ok:
                    return True, f'Email envoyé à {to_email} via Brevo API'
        except Exception as e2:
            app.logger.error(f"Brevo API fallback also failed: {e2}")
        return False, f'Échec: {e}'


def create_notification(user_id, message, tache_id=None, type_notification='info'):
    notif = Notification(
        user_id=user_id,
        message=message,
        tache_id=tache_id,
        type_notification=type_notification
    )
    db.session.add(notif)
    db.session.commit()
    return notif


# ============ AUTH ============

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)


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


@app.route('/api/equipes', methods=['POST'])
@login_required
def create_equipe():
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'message': 'Non autorisé'}), 403
    nom = request.json.get('nom', '').strip()
    if not nom:
        return jsonify({'ok': False, 'message': 'Nom requis'}), 400
    couleur = request.json.get('couleur', '#E07A5F')
    icon = request.json.get('icon', 'bi-people')
    description = request.json.get('description', '')
    manager_id = request.json.get('manager_id')
    equipe = Equipe(nom=nom, couleur=couleur, icon=icon, description=description, manager_id=manager_id)
    db.session.add(equipe)
    db.session.commit()
    return jsonify({'ok': True, 'id': equipe.id, 'message': 'Équipe créée'})


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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        nom = request.form.get('nom', '').strip()
        prenom = request.form.get('prenom', '').strip()
        role = request.form.get('role', 'membre').strip()
        if not all([email, password, nom, prenom]):
            flash('Tous les champs sont requis.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé.', 'danger')
        elif role not in ['membre', 'manager']:
            role = 'membre'
        else:
            user = User(email=email, nom=nom, prenom=prenom, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Account created! You can login.', 'success')
            return redirect(url_for('login'))
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
    if current_user.role == 'manager':
        membres = User.query.filter_by(actif=True).all()
        dossiers = Dossier.query.all()
        taches = Tache.query.all()

        # KPIs
        kpi = {
            'membres_actifs': User.query.filter_by(actif=True, role='membre').count(),
            'dossiers_en_cours': Dossier.query.count(),
            'taches_retard': Tache.query.filter(Tache.statut != 'terminee', Tache.date_echeance < date.today()).count(),
            'taches_haute_priorite': Tache.query.filter_by(priorite='haute', statut='a_faire').count(),
        }

        # Tâches du jour/semaine
        today = date.today()
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
        return render_template(
            'dashboard_collaborateur.html',
            mes_dossiers=mes_dossiers,
            taches_a_faire=taches_a_faire,
            taches_en_cours=taches_en_cours,
            taches_terminees=taches_terminees,
            today=date.today()
        )


# ============ MEMBRES ============

@app.route('/membres')
@login_required
def liste_membres():
    if current_user.role != 'manager':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    membres = User.query.all()
    return render_template('membres.html', membres=membres)


@app.route('/membres/ajouter', methods=['POST'])
@login_required
def ajouter_membre():
    if current_user.role != 'manager':
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
    if current_user.role != 'manager':
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


@app.route('/membres/<int:user_id>/desactiver', methods=['GET', 'POST'])
@login_required
def desactiver_membre(user_id):
    if current_user.role != 'manager':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Vous ne pouvez pas désactiver votre propre compte.', 'warning')
        return redirect(url_for('liste_membres'))
    user.actif = not user.actif
    db.session.commit()
    status = 'réactivé' if user.actif else 'désactivé'
    flash(f'Membre {status} avec succès.', 'success')
    return redirect(url_for('liste_membres'))


@app.route('/membres/<int:user_id>')
@login_required
def fiche_membre(user_id):
    if current_user.role != 'manager':
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
    if current_user.role == 'manager':
        if request.method == 'POST':
            numero = request.form.get('numero_dossier', '').strip()
            intitule = request.form.get('intitule', '').strip()
            collaborateur_id = request.form.get('collaborateur_id', type=int)
            date_limite_str = request.form.get('date_limite', '').strip()
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
                    regime_tva=request.form.get('regime_tva', '').strip() or None,
                    date_limite_declaration=datetime.strptime(request.form.get('date_limite_declaration', ''), '%Y-%m-%d').date() if request.form.get('date_limite_declaration') else None
                )
                db.session.add(dossier)
                db.session.commit()
                if collaborateur_id:
                    collab = User.query.get(collaborateur_id)
                    if collab:
                        msg = f"Un nouveau dossier vous a été assigné: {numero} - {intitule}"
                        create_notification(collab.id, msg, type_notification='assignation')
                        send_email_notification(collab.email, "Nouveau dossier assigné", msg)
                flash('Dossier créé avec succès.', 'success')
                return redirect(url_for('dossiers'))
        all_dossiers = Dossier.query.all()
        membres = User.query.filter_by(actif=True).all()
        return render_template('dossiers.html', dossiers=all_dossiers, membres=membres)
    else:
        # Collaborateur sees only their dossiers
        mes_dossiers = Dossier.query.filter_by(collaborateur_id=current_user.id).all()
        return render_template('dossiers.html', dossiers=mes_dossiers, membres=[])


@app.route('/dossiers/<int:dossier_id>/modifier', methods=['POST'])
@login_required
def modifier_dossier(dossier_id):
    if current_user.role != 'manager':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dashboard'))
    dossier = Dossier.query.get_or_404(dossier_id)
    dossier.numero_dossier = request.form.get('numero_dossier', dossier.numero_dossier).strip()
    dossier.intitule = request.form.get('intitule', dossier.intitule).strip()
    collaborateur_id = request.form.get('collaborateur_id', type=int)
    dossier.collaborateur_id = collaborateur_id if collaborateur_id else None
    dossier.regime_tva = request.form.get('regime_tva', dossier.regime_tva).strip() or None
    date_limite_str = request.form.get('date_limite_declaration', '').strip()
    if date_limite_str:
        dossier.date_limite_declaration = datetime.strptime(date_limite_str, '%Y-%m-%d').date()
    db.session.commit()
    flash('Dossier modifié.', 'success')
    return redirect(url_for('dossiers'))


@app.route('/dossiers/importer', methods=['POST'])
@login_required
def importer_dossiers():
    if current_user.role != 'manager':
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


# ============ TACHES ============

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    today = date.today()
    if current_user.role == 'manager':
        taches = Tache.query.filter(Tache.date_echeance == today, Tache.statut != 'terminee').all()
    else:
        taches = Tache.query.filter(Tache.assigne_a == current_user.id, Tache.date_echeance == today, Tache.statut != 'terminee').all()
    return render_template('taches.html', taches=taches, dossiers=[], membres=[], focus=today)


@app.route('/taches', methods=['GET', 'POST'])
@login_required
def taches():
    if current_user.role == 'manager':
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
                        send_email_notification(user.email, f"Nouvelle tâche: {titre}", msg)
                flash('Tâche créée et notifications envoyées.', 'success')
                return redirect(url_for('taches'))
        all_taches = Tache.query.order_by(Tache.date_echeance.desc()).all()
        dossiers = Dossier.query.all()
        membres = User.query.filter_by(actif=True).all()
        return render_template('taches.html', taches=all_taches, dossiers=dossiers, membres=membres)
    else:
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
            send_email_notification(
                User.query.get(tache.cree_par).email,
                f"Tâche terminée: {tache.titre}",
                f"{current_user.prenom} {current_user.nom} a terminé la tâche: {tache.titre}"
            )
        flash('Tâche marquée comme terminée.', 'success')
    return redirect(url_for('dashboard'))


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


# ============ API / AJAX ============

@app.route('/api/equipe/stats')
@login_required
def api_equipe_stats():
    if current_user.role != 'manager':
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
    if current_user.role != 'manager':
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
    if current_user.role != 'manager':
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

    # Suggestions depuis Outlook
    try:
        from app.integrations import get_outlook
        outlook = get_outlook()
        if outlook.is_configured():
            for item in outlook.suggest_tasks_from_mails():
                suggestions.append({
                    'titre': item.get('titre', 'Action mail'),
                    'dossier_id': item.get('dossier_id'),
                    'assigne_a': item.get('assigne_a'),
                    'priorite': item.get('priorite', 'moyenne'),
                    'date_echeance': item.get('date_echeance'),
                    'source': 'outlook'
                })
    except Exception:
        pass

    # Suggestions depuis Teams
    try:
        from app.integrations import get_teams
        teams = get_teams()
        if teams.is_configured():
            for item in teams.suggest_tasks_from_messages():
                suggestions.append({
                    'titre': item.get('titre', 'Action Teams'),
                    'dossier_id': item.get('dossier_id'),
                    'assigne_a': item.get('assigne_a'),
                    'priorite': item.get('priorite', 'moyenne'),
                    'date_echeance': item.get('date_echeance'),
                    'source': 'teams'
                })
    except Exception:
        pass

    # Suggestions IA à partir des mails et messages Teams
    try:
        from app.integrations import get_openrouter, get_outlook as _outlook_client, get_teams as _teams_client
        llm = get_openrouter()
        outlook_client = _outlook_client()
        teams_client = _teams_client()

        texts = []
        try:
            if outlook_client.is_configured():
                for m in outlook_client.fetch_recent_mails(limit=20):
                    texts.append(f"- MAIL: {m.get('subject','')} | {m.get('body_preview','')}")
        except Exception:
            pass
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


@app.route('/api/test/outlook', methods=['POST'])
@login_required
def test_outlook():
    try:
        from app.integrations.outlook import OutlookMailClient
        client_id = AppSetting.query.filter_by(cle='OUTLOOK_CLIENT_ID').first()
        tenant_id = AppSetting.query.filter_by(cle='OUTLOOK_TENANT_ID').first()
        client_secret = AppSetting.query.filter_by(cle='OUTLOOK_CLIENT_SECRET').first()
        mailbox_email = AppSetting.query.filter_by(cle='OUTLOOK_MAILBOX_EMAIL').first()

        if not all([client_id, tenant_id, client_secret]) or not all([client_id.valeur, tenant_id.valeur, client_secret.valeur]):
            return jsonify({'ok': False, 'message': 'Identifiants Outlook non configurés.'}), 400

        client = OutlookMailClient(
            client_id=client_id.valeur,
            tenant_id=tenant_id.valeur,
            client_secret=client_secret.valeur,
            mailbox_email=mailbox_email.valeur if mailbox_email else None
        )

        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Client Outlook non configuré.'}), 400

        # Test token acquisition
        token = client._get_access_token()
        if not token:
            return jsonify({'ok': False, 'message': 'Impossible d\'obtenir le token d\'accès.'}), 400

        return jsonify({'ok': True, 'message': 'Connexion Outlook OK. Token obtenu.'})
    except Exception as e:
        app.logger.error(f"Erreur test Outlook: {e}")
        return jsonify({'ok': False, 'message': f'Échec: {e}'}), 400


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


@app.route('/api/test/mailbox', methods=['POST'])
@login_required
def test_mailbox():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            return jsonify({'ok': False, 'message': 'IMAP search UNSEEN failed', 'stage': 'imap'}), 500

        ids = data[0].split() if data[0] else []
        total_unseen = len(ids)
        samples = []
        allowed = getattr(client, 'allowed_senders', [])
        for num in ids[:5]:
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = msg_data[0][1]
            mail = email.message_from_bytes(raw)
            subject = client._decode_mime_words(mail.get("Subject"))
            from_addr = client._extract_email_from(client._decode_mime_words(mail.get("From")))
            samples.append({
                'uid': num.decode() if isinstance(num, bytes) else str(num),
                'subject': subject,
                'raw_from': client._decode_mime_words(mail.get("From")),
                'from': from_addr,
                'allowed': client._is_sender_allowed(from_addr),
            })

        allowed_samples = [s for s in samples if s['allowed']]

        app.logger.info(
            "Mailbox debug: total_unseen=%s allowed_senders=%s samples=%s",
            total_unseen,
            allowed,
            [
                {
                    "subject": s["subject"],
                    "raw_from": s["raw_from"],
                    "from": s["from"],
                    "allowed": s["allowed"],
                }
                for s in samples
            ],
        )

        return jsonify({
            'ok': True,
            'message': f'{total_unseen} e-mail(s) non lu(s) détecté(s).',
            'count': total_unseen,
            'stage': 'imap',
            'allowed_senders': allowed,
            'samples': allowed_samples,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/api/test/mailbox/debug', methods=['POST'])
@login_required
def test_mailbox_debug():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            return jsonify({'ok': False, 'message': 'IMAP search UNSEEN failed', 'stage': 'imap'}), 500

        ids = data[0].split() if data[0] else []
        total_unseen = len(ids)
        samples = []
        allowed = getattr(client, 'allowed_senders', [])
        for num in ids[:50]:
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = msg_data[0][1]
            mail = email.message_from_bytes(raw)
            subject = client._decode_mime_words(mail.get("Subject"))
            raw_from = client._decode_mime_words(mail.get("From"))
            from_addr = client._extract_email_from(raw_from)
            date_hdr = client._decode_mime_words(mail.get("Date"))
            samples.append({
                'uid': num.decode() if isinstance(num, bytes) else str(num),
                'subject': subject,
                'raw_from': raw_from,
                'from': from_addr,
                'date': date_hdr,
                'allowed': client._is_sender_allowed(from_addr),
                'allowed_senders': allowed,
            })

        # Sort by date descending (most recent first)
        samples.sort(key=lambda s: s.get('date') or '', reverse=True)

        return jsonify({
            'ok': True,
            'message': f'{total_unseen} e-mail(s) non lu(s) détecté(s).',
            'count': total_unseen,
            'stage': 'imap',
            'samples': samples,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox debug : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/api/test/mailbox/senders', methods=['GET'])
@login_required
def test_mailbox_senders():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        imap.select(client.mailbox)
        typ, data = imap.search(None, "ALL")
        if typ != "OK":
            return jsonify({'ok': False, 'message': 'IMAP search ALL failed', 'stage': 'imap'}), 500

        ids = data[0].split() if data[0] else []
        ids = list(reversed(ids))[:50]
        samples = []
        allowed = getattr(client, 'allowed_senders', [])
        for num in ids:
            typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = msg_data[0][1]
            mail = email.message_from_bytes(raw)
            subject = client._decode_mime_words(mail.get("Subject"))
            raw_from = client._decode_mime_words(mail.get("From"))
            from_addr = client._extract_email_from(raw_from)
            date_hdr = client._decode_mime_words(mail.get("Date"))
            samples.append({
                'uid': num.decode() if isinstance(num, bytes) else str(num),
                'subject': subject,
                'raw_from': raw_from,
                'from': from_addr,
                'date': date_hdr,
                'allowed': client._is_sender_allowed(from_addr),
                'allowed_senders': allowed,
            })

        samples.sort(key=lambda s: s.get('date') or '', reverse=True)
        return jsonify({
            'ok': True,
            'stage': 'imap',
            'allowed_senders': allowed,
            'samples': samples,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox senders : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/api/test/mailbox/search', methods=['POST'])
@login_required
def test_mailbox_search():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        selected_mailbox = getattr(client, 'mailbox', 'unknown')

        # Get total message count
        typ, data = imap.search(None, "ALL")
        total_ids = data[0].split() if data[0] else []
        total_count = len(total_ids)

        # Get unseen count
        typ, data = imap.search(None, "UNSEEN")
        unseen_ids = data[0].split() if data[0] else []
        unseen_count = len(unseen_ids)

        # Search by allowed sender
        allowed = getattr(client, 'allowed_senders', [])
        results = []
        for sender in allowed:
            typ, data = imap.search(None, 'UNSEEN', 'FROM', sender)
            if typ != "OK":
                continue
            ids = data[0].split() if data[0] else []
            results.append({
                'sender': sender,
                'count': len(ids),
                'uids': [num.decode() if isinstance(num, bytes) else str(num) for num in ids[:10]],
            })

        return jsonify({
            'ok': True,
            'message': f'Recherche par expéditeur autorisé : {len(allowed)} expéditeur(s) configuré(s).',
            'allowed_senders': allowed,
            'selected_mailbox': selected_mailbox,
            'total_messages': total_count,
            'unseen_messages': unseen_count,
            'results': results,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox search : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/api/test/mailbox/folders', methods=['GET'])
@login_required
def test_mailbox_folders():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        typ, data = imap.list()
        folders = []
        if typ == "OK":
            for line in data:
                if not line:
                    continue
                parts = line.decode('utf-8', errors='replace').split('"')
                if len(parts) >= 3:
                    folders.append(parts[-2].strip() if len(parts) >= 3 else parts[-1].strip())

        return jsonify({
            'ok': True,
            'folders': folders,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox folders : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/api/test/mailbox/folder-scan', methods=['POST'])
@login_required
def test_mailbox_folder_scan():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        imap = client._connect()
        allowed = getattr(client, 'allowed_senders', [])
        folder_name = request.json.get('folder') if request.is_json else None
        configured = getattr(client, 'mailbox', None)
        candidates = []
        if folder_name:
            candidates.append(folder_name)
        if configured and configured not in candidates:
            candidates.append(configured)
        for f in ["INBOX", '"[Gmail]/All Mail"', "[Gmail]/All Mail"]:
            if f not in candidates:
                candidates.append(f)

        folder_results = []
        for folder in candidates:
            if not folder:
                continue
            try:
                typ, data = imap.select(folder)
                if typ != "OK":
                    continue
            except Exception:
                continue
            try:
                typ, data = imap.search(None, "ALL")
            except Exception:
                continue
            if typ != "OK":
                continue
            all_ids = data[0].split() if data[0] else []

            # Find allowed emails by searching FROM each allowed sender
            allowed_samples = []
            for sender in allowed:
                try:
                    typ2, data2 = imap.search(None, 'FROM', sender)
                except Exception:
                    continue
                if typ2 != "OK":
                    continue
                sender_ids = data2[0].split() if data2[0] else []
                for num in sender_ids[:10]:
                    typ3, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                    if typ3 != "OK":
                        continue
                    raw = msg_data[0][1]
                    mail = email.message_from_bytes(raw)
                    subject = client._decode_mime_words(mail.get("Subject"))
                    raw_from = client._decode_mime_words(mail.get("From"))
                    from_addr = client._extract_email_from(raw_from)
                    allowed_samples.append({
                        'subject': subject,
                        'raw_from': raw_from,
                        'from': from_addr,
                        'allowed': True,
                    })

            # Also show last 5 general samples
            general_samples = []
            for num in all_ids[-5:]:
                typ2, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                if typ2 != "OK":
                    continue
                raw = msg_data[0][1]
                mail = email.message_from_bytes(raw)
                subject = client._decode_mime_words(mail.get("Subject"))
                raw_from = client._decode_mime_words(mail.get("From"))
                from_addr = client._extract_email_from(raw_from)
                general_samples.append({
                    'subject': subject,
                    'raw_from': raw_from,
                    'from': from_addr,
                    'allowed': client._is_sender_allowed(from_addr),
                })

            folder_results.append({
                'folder': folder,
                'count': len(all_ids),
                'allowed_count': len(allowed_samples),
                'allowed_samples': allowed_samples,
                'samples': general_samples,
            })

        return jsonify({
            'ok': True,
            'message': 'Scan des dossiers IMAP avec échantillons et statut d\'autorisation.',
            'allowed_senders': allowed,
            'folder_results': folder_results,
        })
    except Exception as e:
        app.logger.error(f"Erreur test mailbox folder-scan : {e}")
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
        from app.integrations.mailbox import send_task_assignment_email
        send_task_assignment_email(tache, assignee_id)

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


@app.route('/api/mailbox/process', methods=['POST'])
@login_required
def process_mailbox():
    try:
        from app.integrations.mailbox import MailboxClient
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400
        count = client.process_new_messages(max_emails=3)
        return jsonify({'ok': True, 'message': f'{count} mail(s) traité(s).', 'count': count})
    except Exception as e:
        app.logger.error(f"Erreur process mailbox : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


@app.route('/mailbox')
@login_required
def mailbox_page():
    return render_template('mailbox.html')


@app.route('/api/mailbox/process-debug', methods=['POST'])
@login_required
def process_mailbox_debug():
    try:
        from app.integrations.mailbox import MailboxClient
        from app.models import SuggestionTache
        client = MailboxClient()
        if not client.is_configured():
            return jsonify({'ok': False, 'message': 'Identifiants de la boîte mail non configurés.', 'stage': 'config'}), 400

        # Step 1: fetch unseen
        mails = client.fetch_unseen(limit=5)
        fetch_info = {
            'fetched_count': len(mails),
            'sample_uids': [m.get('uid') for m in mails[:5]],
            'sample_subjects': [m.get('subject') for m in mails[:5]],
            'allowed_senders': getattr(client, 'allowed_senders', []),
        }

        # Step 2: check already processed
        already_processed = []
        for m in mails:
            uid = m.get('uid')
            if SuggestionTache.query.filter_by(mail_uid=uid).first():
                already_processed.append(uid)

        # Step 3: attempt extraction on first mail
        extraction_result = None
        suggestion_created = False
        error_detail = None
        if mails:
            m = mails[0]
            try:
                from app.integrations.openrouter import OpenRouterClient
                llm = OpenRouterClient()
                llm_configured = llm.is_configured()
                llm_result = None
                if llm_configured:
                    llm_result = client._analyze_with_llm(m['subject'], m['body'])
                client_id = None
                task_desc = None
                if llm_result:
                    client_id = llm_result.get('client_id')
                    task_desc = llm_result.get('task')
                if not client_id or not task_desc:
                    client_id = client_id or client._resolve_client(m['subject'], m['body'])
                    task_desc = task_desc or client._extract_task(m['subject'], m['body'])
                extraction_result = {
                    'uid': m.get('uid'),
                    'subject': m.get('subject'),
                    'body_preview': (m.get('body') or '')[:200],
                    'llm_configured': llm_configured,
                    'llm_result': llm_result,
                    'client_id': client_id,
                    'task_desc': task_desc,
                }
                if task_desc:
                    client._create_suggestion(
                        subject=m['subject'],
                        body=m['body'],
                        dossier_id=client_id,
                        titre_suggere=m['subject'][:200],
                        description_suggeree=task_desc,
                        mail_uid=m.get('uid'),
                    )
                    suggestion_created = True
            except Exception as e:
                error_detail = str(e)

        return jsonify({
            'ok': True,
            'stage': 'debug',
            'fetch_info': fetch_info,
            'already_processed': already_processed,
            'extraction_result': extraction_result,
            'suggestion_created': suggestion_created,
            'error_detail': error_detail,
        })
    except Exception as e:
        app.logger.error(f"Erreur process mailbox debug : {e}")
        return jsonify({'ok': False, 'message': f'Échec : {e}', 'stage': 'error'}), 500


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


