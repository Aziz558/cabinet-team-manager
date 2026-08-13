from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager
import os

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nom = db.Column(db.String(80), nullable=False)
    prenom = db.Column(db.String(80), nullable=False)
    photo_profil = db.Column(db.String(200), default='default.png')
    role = db.Column(db.String(20), nullable=False, default='membre')  # admin | manager | membre
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipes.id'), nullable=True)
    poste = db.Column(db.String(120))  # e.g., "Comptable", "Auditeur"
    telephone = db.Column(db.String(20))
    actif = db.Column(db.Boolean, default=True)
    date_arrivee = db.Column(db.Date, default=date.today)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    dossiers_assignes = db.relationship('Dossier', backref='collaborateur', lazy='dynamic')
    taches_assignees = db.relationship('Tache', foreign_keys='Tache.assigne_a', backref='assigne', lazy='dynamic')
    taches_creees = db.relationship('Tache', foreign_keys='Tache.cree_par', backref='createur', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', order_by='desc(Notification.date_envoi)')
    commentaires = db.relationship('CommentaireTache', backref='user', lazy='dynamic')
    performances = db.relationship('Performance', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def nom_complet(self):
        return f"{self.prenom} {self.nom}"

    def nb_dossiers_en_cours(self):
        return Dossier.query.filter_by(collaborateur_id=self.id).count()

    def nb_taches_en_retard(self):
        return Tache.query.filter(
            Tache.assigne_a == self.id,
            Tache.statut != 'terminee',
            Tache.date_echeance < date.today()
        ).count()

    def nb_taches_a_faire(self):
        return Tache.query.filter_by(assigne_a=self.id, statut='a_faire').count()

    def photo_display_src(self):
        try:
            if self.email == 'admin@cabinet-jmh.com':
                return url_for('static', filename='uploads/admin.png')
            if self.photo_profil:
                return url_for('static', filename='uploads/' + self.photo_profil)
        except Exception:
            pass
        return None

    def __repr__(self):
        return f'<User {self.email}>'


class Dossier(db.Model):
    __tablename__ = 'dossiers'
    id = db.Column(db.Integer, primary_key=True)
    numero_dossier = db.Column(db.String(50), unique=True, nullable=False, index=True)
    intitule = db.Column(db.String(200), nullable=False)
    collaborateur_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    regime_tva = db.Column(db.String(50))  # ca3 | ca12 | exonere
    date_limite_declaration = db.Column(db.Date)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_cloture = db.Column(db.DateTime)
    frequence_tva = db.Column(db.String(20), default='trimestrielle')  # mensuelle | trimestrielle
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipes.id'), nullable=True)

    taches = db.relationship('Tache', backref='dossier', lazy='dynamic')
    equipe = db.relationship('Equipe', backref='dossiers', lazy=True)

    def __repr__(self):
        return f'<Dossier {self.numero_dossier}>'


class Tache(db.Model):
    __tablename__ = 'taches'
    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=True)
    assigne_a = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    cree_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    priorite = db.Column(db.String(20), default='moyenne')  # haute | moyenne | basse
    statut = db.Column(db.String(30), default='a_faire')  # a_faire | en_cours | terminee
    date_echeance = db.Column(db.Date, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_prise_en_charge = db.Column(db.DateTime)
    date_completion = db.Column(db.DateTime)

    notifications = db.relationship('Notification', backref='tache', lazy='dynamic')
    commentaires = db.relationship('CommentaireTache', backref='tache', lazy='dynamic', order_by='desc(CommentaireTache.date_creation)')

    def est_en_retard(self):
        if self.statut == 'terminee':
            return False
        return self.date_echeance < date.today()

    def jours_restants(self):
        if self.statut == 'terminee':
            return 0
        delta = (self.date_echeance - date.today()).days
        return delta

    def __repr__(self):
        return f'<Tache {self.titre}>'


class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tache_id = db.Column(db.Integer, db.ForeignKey('taches.id'), nullable=True)
    message = db.Column(db.Text, nullable=False)
    lu = db.Column(db.Boolean, default=False)
    type_notification = db.Column(db.String(30), default='info')  # assignation | prise_en_charge | completion | systeme
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Notification {self.id}>'


class CommentaireTache(db.Model):
    __tablename__ = 'commentaires_taches'
    id = db.Column(db.Integer, primary_key=True)
    tache_id = db.Column(db.Integer, db.ForeignKey('taches.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Commentaire {self.id}>'


class Performance(db.Model):
    __tablename__ = 'performance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    periode = db.Column(db.String(20), nullable=False)  # hebdomadaire | mensuel | annuel
    date_debut = db.Column(db.Date, nullable=False)
    date_fin = db.Column(db.Date, nullable=False)
    dossiers_termines = db.Column(db.Integer, default=0)
    taches_terminees = db.Column(db.Integer, default=0)
    taches_en_retard = db.Column(db.Integer, default=0)
    taux_respect_delai = db.Column(db.Float, default=0.0)  # pourcentage
    score_performance = db.Column(db.Float, default=0.0)  # note sur 100
    date_calcul = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Performance user={self.user_id} score={self.score_performance}>'


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    id = db.Column(db.Integer, primary_key=True)
    cle = db.Column(db.String(120), unique=True, nullable=False, index=True)
    valeur = db.Column(db.Text, nullable=True)
    type_valeur = db.Column(db.String(20), default='string')  # string | json | password
    service = db.Column(db.String(50), default='general')  # outlook | teams | mail | general
    masque = db.Column(db.Boolean, default=False)
    date_modification = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<AppSetting {self.cle}>'


class Equipe(db.Model):
    __tablename__ = 'equipes'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    couleur = db.Column(db.String(20), default='#E07A5F')  # terracotta par défaut
    icon = db.Column(db.String(50), default='bi-people')  # bootstrap icon class
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    # Team-specific email for Cloudflare Email Routing inbound (optional)
    equipe_email = db.Column(db.String(200), nullable=True)  # e.g. equipe-compta@ton-domaine.com

    manager = db.relationship('User', foreign_keys=[manager_id], backref='equipe_dirigee')
    membres = db.relationship('User', foreign_keys='User.equipe_id', backref='equipe', lazy='dynamic')

    def nb_membres(self):
        return self.membres.filter_by(actif=True).count()

    def __repr__(self):
        return f'<Equipe {self.nom}>'


class PhotoUtilisateur(db.Model):
    __tablename__ = 'photos'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    photo_data = db.Column(db.Text, nullable=True)  # base64 data: data:image/png;base64,...
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='photos')

    def __repr__(self):
        return f'<Photo {self.filename} for user {self.user_id}>'


class SuggestionTache(db.Model):
    __tablename__ = 'suggestions_taches'
    id = db.Column(db.Integer, primary_key=True)
    sujet = db.Column(db.String(200), nullable=False)
    corps = db.Column(db.Text, nullable=False)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=True)
    titre_suggere = db.Column(db.String(200), nullable=False)
    description_suggeree = db.Column(db.Text, nullable=False)
    statut = db.Column(db.String(20), default='en_attente')  # en_attente | validee | rejetee
    cree_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    valide_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_validation = db.Column(db.DateTime, nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    mail_uid = db.Column(db.String(64), nullable=True, unique=True)
    priorite_suggeree = db.Column(db.String(20), default='moyenne')  # haute | moyenne | basse

    dossier = db.relationship('Dossier', backref='suggestions')
    createur = db.relationship('User', foreign_keys=[cree_par], backref='suggestions_creees')
    validateur = db.relationship('User', foreign_keys=[valide_par], backref='suggestions_validees')

    def __repr__(self):
        return f'<SuggestionTache {self.id}>'
