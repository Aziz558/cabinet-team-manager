from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from sqlalchemy.orm import deferred
import os

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nom = db.Column(db.String(80), nullable=False)
    prenom = db.Column(db.String(80), nullable=False)
    photo_profil = db.Column(db.String(200), default='default.png')
    # photo_data est DECALEE (deferred) : la colonne BYTEA n'est chargee depuis la
    # base que si le code y accede explicitement (route /user_photo). Sans ce
    # defer, CHAQUE query renvoyant des User (dashboard, listes, taches, equipes)
    # ramenait le binaire complet de toutes les photos -> consommation massive du
    # quota de transfert reseau Neon (5 Go/mois) et base neutralisee.
    # Ne PAS lire `user.photo_data` hors de la route photo : utiliser
    # `photo_mimetype` / `a_une_photo` comme indicateur leger.
    photo_data = deferred(db.Column(db.LargeBinary, nullable=True))
    photo_mimetype = db.Column(db.String(50), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='membre')  # admin | manager | membre
    pole = db.Column(db.String(20), default='comptable')  # comptable | social | juridique | les_deux
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipes.id'), nullable=True)
    poste = db.Column(db.String(120))  # e.g., "Comptable", "Auditeur"
    telephone = db.Column(db.String(20))
    actif = db.Column(db.Boolean, default=True)
    date_arrivee = db.Column(db.Date, default=date.today)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    dossiers_assignes = db.relationship('Dossier', foreign_keys='Dossier.collaborateur_id', backref='collaborateur', lazy='dynamic')
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

    @property
    def dans_pole_social(self):
        """True si le membre appartient au pole social (ou les deux)."""
        return (self.pole or 'comptable') in ('social', 'les_deux')

    @property
    def dans_pole_juridique(self):
        """True si le membre appartient au pole juridique (ou les deux)."""
        return (self.pole or 'comptable') in ('juridique', 'les_deux')

    @property
    def a_des_dossiers_avec_referent_social(self):
        """True si le membre est collaborateur comptable d'au moins un dossier
        dont le volet paie est suivi par le pole social (droit de lecture du
        suivi social, pour valider le volet « ecritures »)."""
        from app.models import Dossier as _D
        return _D.query.filter(
            _D.collaborateur_id == self.id,
            _D.collaborateur_social_id.isnot(None),
        ).first() is not None

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
        """Retourne l'URL de la photo de profil ou un avatar généré."""
        try:
            # Photo stockée en DB (permanente). On teste photo_mimetype (varchar
            # legere) et JAMAIS photo_data : lire photo_data declencherait le
            # chargement du BYTEA depuis Neon pour chaque membre affiche.
            if self.photo_mimetype:
                from flask import url_for
                return url_for('user_photo', user_id=self.id)
            # Photo uploadée via fichier (legacy)
            if self.photo_profil and self.photo_profil != 'default.png':
                import os
                from flask import current_app
                photo_path = os.path.join(current_app.static_folder, 'uploads', self.photo_profil)
                if os.path.exists(photo_path):
                    return '/static/uploads/' + self.photo_profil
        except Exception:
            pass
        
        # Fallback : avatar généré avec les initiales
        try:
            name = f"{self.prenom or ''} {self.nom or ''}".strip()
            encoded = name.replace(' ', '+')
            return f"https://ui-avatars.com/api/?name={encoded}&background=FF8C00&color=fff&size=128&font-size=0.5&bold=true"
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
    date_acompte_1 = db.Column(db.Date)  # CA12 : acompte juillet (optionnel, sinon jour de date_limite)
    date_acompte_2 = db.Column(db.Date)  # CA12 : acompte décembre (optionnel, sinon jour de date_limite)
    pennylane_customer_id = db.Column(db.String(64), nullable=True)  # ID client Pennylane associé
    pennylane_api_token = db.Column(db.String(256), nullable=True)  # Token API Pennylane spécifique au dossier (optionnel)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_cloture = db.Column(db.DateTime)
    frequence_tva = db.Column(db.String(20))  # mensuelle | trimestrielle | None
    regime_fiscale = db.Column(db.String(10))  # IS | IRPP
    has_cfe = db.Column(db.Boolean, default=False)
    forme_juridique = db.Column(db.String(20))  # SAS | SARL | SCI | SA | EURL | Autre
    secteur_activite = db.Column(db.String(60))  # libellé libre pour analytics
    siren = db.Column(db.String(9), nullable=True, index=True)  # n° SIREN (extraction auto Infogreffe/INSEE)
    honoraires_mensuel = db.Column(db.Float, nullable=True)  # honoraires mensuels € pour rentabilité
    collaborateur_social_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # référent pole social (distinct du comptable)
    charge_juridique_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # chargé/responsable juridique du dossier
    # --- Champs enrichis automatiquement depuis le SIREN (API recherche-entreprises) ---
    tva_intra = db.Column(db.String(20), nullable=True)          # n° TVA intracommunautaire (FR..)
    naf_code = db.Column(db.String(10), nullable=True)           # code NAF / APE (ex: 70.10Z)
    effectif_label = db.Column(db.String(40), nullable=True)     # tranche d'effectif salarié
    categorie_entreprise = db.Column(db.String(5), nullable=True)  # GE | ETI | PME | micro
    date_creation_entreprise = db.Column(db.Date, nullable=True)  # création de l'entreprise (INSEE)
    dirigeant = db.Column(db.String(200), nullable=True)          # dirigeant principal
    adresse_siege = db.Column(db.String(250), nullable=True)      # adresse du siège
    etat_administratif = db.Column(db.String(5), nullable=True)   # A = actif, R = radié...
    enrichi_le = db.Column(db.DateTime, nullable=True)            # dernière extraction SIREN
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipes.id'), nullable=True)

    taches = db.relationship('Tache', backref='dossier', lazy='dynamic')
    equipe = db.relationship('Equipe', backref='dossiers', lazy=True)
    social = db.relationship('User', foreign_keys=[collaborateur_social_id])
    charge_juridique = db.relationship('User', foreign_keys=[charge_juridique_id])

    def __repr__(self):
        return f'<Dossier {self.numero_dossier}>'


class Tache(db.Model):
    __tablename__ = 'taches'
    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=True)
    assigne_a = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    cree_par = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    priorite = db.Column(db.String(20), default='moyenne')  # haute | moyenne | basse
    statut = db.Column(db.String(30), default='a_faire')  # a_faire | en_cours | terminee
    date_echeance = db.Column(db.Date, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_prise_en_charge = db.Column(db.DateTime)
    date_completion = db.Column(db.DateTime)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.statut:
            self.statut = 'a_faire'

    notifications = db.relationship('Notification', backref='tache', lazy='dynamic')
    commentaires = db.relationship('CommentaireTache', backref='tache', lazy='dynamic', order_by='CommentaireTache.date_creation')
    
    # Champs pour tâches récurrentes
    frequence_repetition = db.Column(db.String(20), nullable=True)  # daily | weekly | monthly | yearly
    fin_repetition = db.Column(db.Date, nullable=True)  # date de fin de répétition
    template_id = db.Column(db.Integer, db.ForeignKey('taches.id'), nullable=True)  # ID de la tâche modèle
    # Origine de l'état « terminée » : manuel | auto_checklist | auto_pennylane (NULL = inconnu/historique)
    statut_source = db.Column(db.String(20), nullable=True)

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


class Rappel(db.Model):
    """Rappel utilisateur : notification in-app immédiate, puis email J+1 si non lu,
    et email à la date d'échéance. Créable via l'assistant IA ou manuellement."""
    __tablename__ = 'rappels'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    titre = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    date_echeance = db.Column(db.Date, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_envoi_notification = db.Column(db.DateTime, nullable=True)
    lu = db.Column(db.Boolean, default=False)  # marqué comme "NOTE" / consulté
    date_lu = db.Column(db.DateTime, nullable=True)
    email_j1_envoye = db.Column(db.Boolean, default=False)
    email_echeance_envoye = db.Column(db.Boolean, default=False)
    archive = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(30), default='manuel')  # manuel | assistant
    user = db.relationship('User', backref='rappels')

    def __repr__(self):
        return f'<Rappel {self.id} user={self.user_id} echeance={self.date_echeance}>'


class PennylaneItem(db.Model):
    """Item Pennylane (facture client/fournisseur, transaction) vu pour un dossier.
       Permet de détecter les NOUVEAUX items et de suivre leur traitement."""
    __tablename__ = 'pennylane_items'
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=False, index=True)
    item_type = db.Column(db.String(30), nullable=False)  # facture_vente | facture_achat | transaction
    item_id = db.Column(db.String(64), nullable=False, index=True)  # ID Pennylane de l'item
    reference = db.Column(db.String(120))            # n° facture ou libellé transaction
    montant = db.Column(db.Float, nullable=True)
    date_item = db.Column(db.String(30))             # date de la facture/transaction (string API)
    vu_premiere_fois = db.Column(db.DateTime, default=datetime.utcnow)
    digest_envoye = db.Column(db.Boolean, nullable=False, default=False)  # True = deja inclus dans un recapitulatif mail
    statut = db.Column(db.String(20), default='a_traiter')  # a_traiter | traite | ignore
    api_statut = db.Column(db.String(30), nullable=True)    # statut brut Pennylane (affected, paid, draft...)
    statut_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    statut_date = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('dossier_id', 'item_type', 'item_id', name='uq_pl_item'),
    )

    def __repr__(self):
        return f'<PennylaneItem dossier={self.dossier_id} {self.item_type} {self.item_id}>'


class ChecklistEntry(db.Model):
    """Case de checklist métier : état déclarée/payée d'une obligation pour un dossier.
    taxe: tva_mensuel | tva_trimestriel | tva_ca12 | is | cfe
    mois: 1..12 (5=déclaration mai, 7/12=acomptes CA12) ; kind: depot|acompte|declaration"""
    __tablename__ = 'checklist_entries'
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=False, index=True)
    taxe = db.Column(db.String(20), nullable=False)
    annee = db.Column(db.Integer, nullable=False)
    mois = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    declare = db.Column(db.Boolean, default=False)
    paye = db.Column(db.Boolean, default=False)
    pl_mode = db.Column(db.Boolean, default=False)  # True = état imposé par la synchro Pennylane
    source = db.Column(db.String(20), nullable=True)  # checklist | tache | pennylane (NULL = historique)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_modif = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('dossier_id', 'taxe', 'annee', 'mois', 'kind', name='uq_checklist_entry'),
    )

    def __repr__(self):
        return f'<ChecklistEntry d={self.dossier_id} {self.taxe} {self.annee}-{self.mois} {self.kind}>'


class DsnSuivi(db.Model):
    """Suivi DSN + écritures de paie par dossier et période (mois principal déclaré).
    mois/annee = la PERIODE déclarée (la DSN de janvier = 2026-01, exigible le 5 ou 15 fév.).
    Statuts DSN : a_deposer -> deposee -> validee | rejetee (motif saisi).
    Écritures de paie (Silae) : non_passees -> pretes -> integrees (compta Pennylane faite)."""
    __tablename__ = 'dsn_suivi'
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=False, index=True)
    annee = db.Column(db.Integer, nullable=False, index=True)
    mois = db.Column(db.Integer, nullable=False)          # période déclarée 1..12
    dsn_statut = db.Column(db.String(20), default='a_deposer')  # a_deposer|deposee|validee|rejetee
    dsn_date_depot = db.Column(db.Date, nullable=True)
    dsn_motif = db.Column(db.String(250), nullable=True)      # motif de rejet / remarque
    ecritures_statut = db.Column(db.String(20), default='non_passees')  # non_passees|pretes|integrees
    ecritures_date = db.Column(db.DateTime, nullable=True)
    notifie_compta = db.Column(db.Boolean, default=False)     # notif "prête" déjà envoyée au compta
    modifie_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_modif = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('dossier_id', 'annee', 'mois', name='uq_dsn_suivi'),
    )

    # seuil effectif URSSAF : 5 du mois M+1 si >= 50 salaries, sinon 15
    SEUIL_GRAND_EFFECTIF = 50

    def date_exigibilite(self, effectif_nbre=None):
        """Date limite de dépôt (M+1, le 5 si gros effectif sinon le 15), reportée
        au jour ouvré suivant si week-end."""
        from .tva_scheduler import next_working_day
        y, m = (self.annee + 1, 1) if self.mois == 12 else (self.annee, self.mois + 1)
        jour = self.SEUIL_GRAND_EFFECTIF_JOUR(effectif_nbre)
        try:
            d = date(y, m, jour)
        except ValueError:
            d = date(y, m, 28)
        return next_working_day(d)

    @staticmethod
    def SEUIL_GRAND_EFFECTIF_JOUR(effectif_nbre):
        return 5 if (effectif_nbre or 0) >= 50 else 15

    def __repr__(self):
        return f'<DsnSuivi d={self.dossier_id} {self.annee}-{self.mois} {self.dsn_statut}/{self.ecritures_statut}>'


class TvaStatutPennylane(db.Model):
    """Miroir brut des statuts de déclarations TVA lus dans l'espace web Pennylane
    (endpoint interne vat_forms, synchro session web).
    Une ligne par (dossier, année, mois) — reflète ce que Pennylane affiche.
    Statuts bruts réels observés : 'to_do' (à déclarer), 'ready' (prêt),
    'ongoing' (envoyée, pas encore acceptée), 'accepted' (acceptée),
    'filed'/'paid' (faite/payée dans PL) + deadline et montant payable.
    'En retard' = calcul auto (to_do + deadline dépassée)."""
    __tablename__ = 'tva_statuts_pennylane'
    id = db.Column(db.Integer, primary_key=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=False, index=True)
    annee = db.Column(db.Integer, nullable=False, index=True)
    mois = db.Column(db.Integer, nullable=False)  # 1..12 (1er mois du trimestre si CA3 trim.)
    statut = db.Column(db.String(30), default='to_do')  # brut Pennylane
    deadline = db.Column(db.String(20), nullable=True)   # '2026-09-24'
    montant = db.Column(db.Float, nullable=True)         # payable
    date_sync = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('dossier_id', 'annee', 'mois', name='uq_tva_statut_pl'),
    )

    @property
    def statut_fr(self):
        from app.integrations.pennylane_web import traduire_statut
        return traduire_statut(self.statut)

    @property
    def statut_affiche(self):
        """Statut affiché : to_do avec deadline dépassée => 'En retard' (calcul auto)."""
        if (self.statut or '') in ('to_do', 'unknown', '') and self.deadline:
            try:
                dd = datetime.strptime(str(self.deadline)[:10], '%Y-%m-%d').date()
                if dd < date.today():
                    return 'En retard'
            except Exception:
                pass
        return self.statut_fr

    def __repr__(self):
        return f'<TvaStatutPennylane d={self.dossier_id} {self.annee}-{self.mois} {self.statut}>'


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

    # Aliases compatibilité avec les routes qui attendent 'Suggestion'
    @property
    def titre(self):
        return self.titre_suggere
    
    @property
    def description(self):
        return self.description_suggeree
    
    @property
    def priorite(self):
        return self.priorite_suggeree
    
    @property
    def source(self):
        return 'email'
    
    @property
    def assigne_a(self):
        return self.cree_par
    
    @property
    def date_echeance(self):
        return None  # Pas de date d'échéance directe sur SuggestionTache

# Alias pour compatibilité avec les routes (suggestions_page, api_suggestions, etc.)
Suggestion = SuggestionTache


# ===========================================================================
# Suivi nouveaux dossiers (onboarding) — remplace le classeur Excel cabinet.
# Les définitions d'étapes vivent dans app/onboarding_steps.py (données pures).
# ===========================================================================
class OnboardingDossier(db.Model):
    __tablename__ = 'onboarding_dossiers'
    id = db.Column(db.Integer, primary_key=True)
    auteur = db.Column(db.String(80), nullable=True)               # colonne AUTEUR du fichier
    nom_dossier = db.Column(db.String(200), nullable=False)
    nom_client = db.Column(db.String(200), nullable=True)
    mail = db.Column(db.String(200), nullable=True)
    telephone = db.Column(db.String(40), nullable=True)
    ec_chef_mission = db.Column(db.String(80), nullable=True)      # EC / chef de mission
    etablissement = db.Column(db.String(120), nullable=True)
    type_dossier = db.Column(db.String(20), nullable=False, default='creation')  # creation | reprise | revision
    polyacte = db.Column(db.Boolean, default=False)
    honoraires_an = db.Column(db.Float, nullable=True)             # honoraires /an (compta+jurid) HT
    date_debut_mission = db.Column(db.Date, nullable=True)
    social = db.Column(db.Boolean, default=False)                  # Social (oui/non)
    collab_comptable = db.Column(db.String(80), nullable=True)
    collab_social = db.Column(db.String(80), nullable=True)
    collab_juridique = db.Column(db.String(80), nullable=True)
    statut = db.Column(db.String(20), nullable=False, default='en_cours')  # en_cours | termine
    commentaires = db.Column(db.Text, nullable=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=True)  # lien optionnel au dossier client
    cree_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_modif = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Responsables du dossier (pré-remplis depuis les réglages, modifiables par dossier) ;
    # les champs texte collab_* restent la source libre (import Excel).
    chef_mission_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    expert_comptable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resp_juridique_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resp_social_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    dossier = db.relationship('Dossier', foreign_keys=[dossier_id])
    cree_par = db.relationship('User', foreign_keys=[cree_par_id])
    chef_mission = db.relationship('User', foreign_keys=[chef_mission_id])
    expert_comptable = db.relationship('User', foreign_keys=[expert_comptable_id])
    resp_juridique = db.relationship('User', foreign_keys=[resp_juridique_id])
    resp_social = db.relationship('User', foreign_keys=[resp_social_id])
    steps = db.relationship('OnboardingEtape', backref='onboarding', cascade='all, delete-orphan', lazy='selectin')

    def etape(self, code):
        for s in self.steps:
            if s.code == code:
                return s
        return None

    def etapes_applicables(self):
        """[(code, libellé, phase)] filtrées selon le type de dossier."""
        from .onboarding_steps import etapes_pour_type
        return etapes_pour_type(self.type_dossier or 'creation')

    def progression(self):
        """(faites, total) sur les étapes applicables."""
        app = self.etapes_applicables()
        total = len(app)
        faites = sum(1 for c, _l, _p in app if self.etape(c) and self.etape(c).est_fait)
        return faites, total

    def pourcentage(self):
        f, t = self.progression()
        return round(100 * f / t) if t else 100

    def phase_progression(self, phase):
        app = [(c, l, p) for c, l, p in self.etapes_applicables() if p == phase]
        faites = sum(1 for c, _l, _p in app if self.etape(c) and self.etape(c).est_fait)
        return faites, len(app)

    def prochaine_etape(self):
        """Première étape applicable non faite, dans l'ordre du pipeline."""
        for c, l, p in self.etapes_applicables():
            s = self.etape(c)
            if not s or not s.est_fait:
                return c, l, p
        return None

    def jours_attente(self):
        """Jours écoulés depuis la dernière étape faite (ou la création du suivi)."""
        dates = [s.date_fait for s in self.steps if s.date_fait]
        ref = max(dates) if dates else (self.date_debut_mission or (self.date_creation or datetime.utcnow()).date())
        if isinstance(ref, datetime):
            ref = ref.date()
        return (date.today() - ref).days

    def __repr__(self):
        return f'<OnboardingDossier {self.nom_dossier}>'


class OnboardingEtape(db.Model):
    __tablename__ = 'onboarding_etapes'
    __table_args__ = (db.UniqueConstraint('dossier_onb_id', 'code', name='uq_onb_etape'),)
    id = db.Column(db.Integer, primary_key=True)
    dossier_onb_id = db.Column(db.Integer, db.ForeignKey('onboarding_dossiers.id'), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False)
    date_fait = db.Column(db.Date, nullable=True)          # NULL = à faire (comme la saisie de date Excel)
    sans_date = db.Column(db.Boolean, default=False)       # « X » du modèle Excel : fait sans date connue
    fait_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    commentaire = db.Column(db.String(500), nullable=True) # texte libre saisi dans la cellule
    date_modif = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    fait_par = db.relationship('User', foreign_keys=[fait_par_id])

    @property
    def est_fait(self):
        return bool(self.date_fait or self.sans_date)

    def __repr__(self):
        return f'<OnboardingEtape {self.code} {self.date_fait}>'


class OnboardingDepart(db.Model):
    __tablename__ = 'onboarding_dossiers_partis'
    id = db.Column(db.Integer, primary_key=True)
    auteur = db.Column(db.String(80), nullable=True)
    nom_dossier = db.Column(db.String(200), nullable=False)
    nom_client = db.Column(db.String(200), nullable=True)
    mail = db.Column(db.String(200), nullable=True)
    telephone = db.Column(db.String(40), nullable=True)
    ec_chef_mission = db.Column(db.String(80), nullable=True)
    etablissement = db.Column(db.String(120), nullable=True)
    collaborateur = db.Column(db.String(80), nullable=True)
    cause_depart = db.Column(db.String(200), nullable=True)
    date_depart = db.Column(db.Date, nullable=True)
    mail_deontologie_recu = db.Column(db.Date, nullable=True)
    envoi_documents = db.Column(db.Date, nullable=True)
    mail_facturation = db.Column(db.Date, nullable=True)   # stop facturation + désactivation Pennylane
    commentaires = db.Column(db.Text, nullable=True)
    dossier_id = db.Column(db.Integer, db.ForeignKey('dossiers.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    dossier = db.relationship('Dossier', foreign_keys=[dossier_id])

    def __repr__(self):
        return f'<OnboardingDepart {self.nom_dossier}>'


class OnboardingMail(db.Model):
    """Trace des mails automatiques liés au suivi (envoyés ou en erreur)."""
    __tablename__ = 'onboarding_mails'
    id = db.Column(db.Integer, primary_key=True)
    dossier_onb_id = db.Column(db.Integer, db.ForeignKey('onboarding_dossiers.id'), nullable=True)
    depart_id = db.Column(db.Integer, db.ForeignKey('onboarding_dossiers_partis.id'), nullable=True)
    type_mail = db.Column(db.String(40), nullable=False)   # ldm_facturation | identite | deontologie | facturation_depart | rappel
    destinataire = db.Column(db.String(200), nullable=False)
    sujet = db.Column(db.String(300), nullable=True)
    statut = db.Column(db.String(20), nullable=False, default='envoye')  # envoye | erreur
    erreur = db.Column(db.Text, nullable=True)
    envoye_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<OnboardingMail {self.type_mail} -> {self.destinataire}>'


class OnboardingActionMail(db.Model):
    """Action automatique configurable par étape du suivi : quand l'étape est
    cochée, un ou plusieurs mails (modèle + destinataires) sont envoyés.
    Configurable depuis Paramètres ; seeds = anciens mails codés en dur."""
    __tablename__ = 'onboarding_actions_mail'
    id = db.Column(db.Integer, primary_key=True)
    etape_code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    actif = db.Column(db.Boolean, default=False, nullable=False)
    sujet = db.Column(db.String(300), nullable=True)
    corps = db.Column(db.Text, nullable=True)
    # JSON : liste de tokens destinataires ['client', 'resp:resp_juridique',
    # 'user:12', 'email:a@b.c', 'setting:ONBOARDING_MAIL_FACTURATION']
    destinataires = db.Column(db.Text, nullable=True)
    maj_le = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def tokens(self):
        import json as _json
        try:
            vals = _json.loads(self.destinataires or '[]')
            return [str(v) for v in vals if str(v).strip()]
        except Exception:
            return []


class AnnuaireCategorie(db.Model):
    """Catégories de contacts hors cabinet (Client, Notaire, Ancien EC…),
    gérées depuis l'application sans toucher au code."""
    __tablename__ = 'annuaire_categories'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(80), unique=True, nullable=False)
    couleur = db.Column(db.String(20), nullable=True)   # token couleur (success/info/orange…)
    ordre = db.Column(db.Integer, default=0)
    fiches = db.relationship('FicheAnnuaire', backref='categorie', lazy='dynamic')

    def __repr__(self):
        return f'<AnnuaireCategorie {self.nom}>'


class FicheAnnuaire(db.Model):
    """Fiche contact hors cabinet (clients, notaires, intervenants externes…)
    — l'équivalent « fiche membre » pour les personnes hors du cabinet."""
    __tablename__ = 'annuaire_fiches'
    id = db.Column(db.Integer, primary_key=True)
    categorie_id = db.Column(db.Integer, db.ForeignKey('annuaire_categories.id'), nullable=True)
    nom = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    telephone = db.Column(db.String(40), nullable=True)
    organisation = db.Column(db.String(200), nullable=True)
    note = db.Column(db.Text, nullable=True)
    actif = db.Column(db.Boolean, default=True)
    cree_par_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    cree_par = db.relationship('User', foreign_keys=[cree_par_id])

    def __repr__(self):
        return f'<FicheAnnuaire {self.nom}>'
