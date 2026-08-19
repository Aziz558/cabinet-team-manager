from flask import Flask, render_template
from flask_login import current_user
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os
from datetime import date as _date, datetime as _datetime

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates'),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
use_postgres = False
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
    use_postgres = True
if database_url and database_url.startswith('postgresql://'):
    if '?' not in database_url:
        database_url += '?sslmode=require'
    else:
        database_url += '&sslmode=require'

# For Render free tier, use a writable SQLite path by default
# PostgreSQL can be enabled later by setting USE_POSTGRES=true
db_path = os.path.join(basedir, '..', 'data', 'app.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)
if os.environ.get('USE_POSTGRES', 'false').lower() == 'true' and database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    if use_postgres:
        app.logger.info(f"Using SQLite instead of PostgreSQL. Set USE_POSTGRES=true to enable PostgreSQL.")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, '..', 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter.'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Auto-migrate DB schema on startup
try:
    from migrate_schema import migrate_description_column
    migrate_description_column()
except Exception as e:
    print(f"⚠️ Schema migration failed: {e}")

# Ensure DB tables exist and migrate
try:
    with app.app_context():
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        for c in inspector.get_columns('suggestions_taches'):
            if c['name'] == 'description_suggeree' and 'varchar' in str(c['type']).lower():
                db.session.execute(text("ALTER TABLE suggestions_taches ALTER COLUMN description_suggeree TYPE TEXT"))
                print("✅ Migrated description_suggeree: varchar -> TEXT")
            if c['name'] == 'mail_uid' and 'varchar' in str(c['type']).lower() and '50' in str(c['type']):
                db.session.execute(text("ALTER TABLE suggestions_taches ALTER COLUMN mail_uid TYPE VARCHAR(100)"))
                print("✅ Migrated mail_uid: varchar(50) -> varchar(100)")
        db.session.commit()
except Exception as e:
    print(f"⚠️ Schema init failed: {e}")
    try:
        db.session.rollback()
    except:
        pass

from app import routes  # noqa: F401
from app.models import User, AppSetting, SuggestionTache, Equipe  # noqa: F401

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all failed: {e}")
    # Migrate team email column if missing (Cloudflare Email Routing only)
    try:
        inspector = db.inspect(db.engine)
        if 'equipes' in inspector.get_table_names():
            equipes_cols = [col['name'] for col in inspector.get_columns('equipes')]
            with db.engine.begin() as conn:
                if 'equipe_email' not in equipes_cols:
                    conn.execute(db.text("ALTER TABLE equipes ADD COLUMN equipe_email VARCHAR(200)"))
                    app.logger.info("Added equipe_email column")
    except Exception as e:
        app.logger.warning(f"Migration error (equipes mailbox): {e}")

    # Ensure dossiers table has regime_fiscale and has_cfe columns
    try:
        inspector = db.inspect(db.engine)
        if 'dossiers' in inspector.get_table_names():
            dossiers_cols = [c['name'] for c in inspector.get_columns('dossiers')]
            with db.engine.begin() as conn:
                if 'regime_fiscale' not in dossiers_cols:
                    conn.execute(db.text("ALTER TABLE dossiers ADD COLUMN regime_fiscale VARCHAR(10)"))
                    app.logger.info("Added regime_fiscale column to dossiers")
                if 'has_cfe' not in dossiers_cols:
                    conn.execute(db.text("ALTER TABLE dossiers ADD COLUMN has_cfe BOOLEAN DEFAULT FALSE"))
                    app.logger.info("Added has_cfe column to dossiers")
    except Exception as e:
        app.logger.warning(f"Migration error (dossiers columns): {e}")

    # Ensure taches table has cree_par as nullable
    try:
        inspector = db.inspect(db.engine)
        if 'taches' in inspector.get_table_names():
            taches_cols = [c['name'] for c in inspector.get_columns('taches')]
            taches_meta = {c['name']: c for c in inspector.get_columns('taches')}
            # Check if cree_par column exists and is NOT NULL
            if 'cree_par' in taches_cols:
                col_info = taches_meta['cree_par']
                # PostgreSQL column is nullable by default; check if constraint exists
                # We try to alter column to drop NOT NULL if it exists
                try:
                    with db.engine.begin() as conn:
                        # PostgreSQL syntax
                        conn.execute(db.text("ALTER TABLE taches ALTER COLUMN cree_par DROP NOT NULL"))
                        app.logger.info("Made cree_par nullable in taches table")
                except Exception as alter_err:
                    app.logger.warning(f"Could not alter cree_par (may already be nullable): {alter_err}")
            # Also make assigne_a nullable
            if 'assigne_a' in taches_cols:
                try:
                    with db.engine.begin() as conn:
                        conn.execute(db.text("ALTER TABLE taches ALTER COLUMN assigne_a DROP NOT NULL"))
                        app.logger.info("Made assigne_a nullable in taches table")
                except Exception as alter_err:
                    app.logger.warning(f"Could not alter assigne_a (may already be nullable): {alter_err}")
    except Exception as e:
        app.logger.warning(f"Migration error (taches column): {e}")

    # Ensure taches table has new columns (frequence_repetition, template_id, photo_data, photo_mimetype)
    try:
        inspector = db.inspect(db.engine)
        if 'taches' in inspector.get_table_names():
            taches_cols = [c['name'] for c in inspector.get_columns('taches')]
            for col in ['frequence_repetition', 'fin_repetition', 'template_id']:
                if col not in taches_cols:
                    try:
                        with db.engine.begin() as conn:
                            if col == 'template_id':
                                conn.execute(db.text(f"ALTER TABLE taches ADD COLUMN {col} INTEGER REFERENCES taches(id)"))
                            elif col == 'fin_repetition':
                                conn.execute(db.text(f"ALTER TABLE taches ADD COLUMN {col} DATE"))
                            else:
                                conn.execute(db.text(f"ALTER TABLE taches ADD COLUMN {col} VARCHAR(20)"))
                            app.logger.info(f"Added column {col} to taches")
                    except Exception as e2:
                        app.logger.warning(f"Could not add {col}: {e2}")
        if 'users' in inspector.get_table_names():
            users_cols = [c['name'] for c in inspector.get_columns('users')]
            for col in ['photo_data', 'photo_mimetype']:
                if col not in users_cols:
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(db.text(f"ALTER TABLE users ADD COLUMN {col} BYTEA" if col == 'photo_data' else f"ALTER TABLE users ADD COLUMN {col} VARCHAR(50)"))
                            app.logger.info(f"Added column {col} to users")
                    except Exception as e2:
                        app.logger.warning(f"Could not add {col}: {e2}")
    except Exception as e:
        app.logger.warning(f"Migration error (new columns): {e}")

    # Create default team if none exists
    try:
        admin_user = User.query.filter_by(role='admin').first()
        if not Equipe.query.first():
            default_team = Equipe(
                nom="Équipe Cabinet JMH",
                description="Équipe par défaut du cabinet",
                couleur="#E07A5F",
                icon="bi-people",
                manager_id=admin_user.id if admin_user else None
            )
            db.session.add(default_team)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning(f"Could not create default team: {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Make date available in templates
app.jinja_env.globals['date'] = _date

# Context processor — makes current_equipe available in all templates
@app.context_processor
def inject_globals():
    from flask import session
    current_equipe = None
    if current_user.is_authenticated:
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            current_equipe = Equipe.query.get(equipe_id)
        # Default to user's assigned team
        if current_user.equipe:
            current_equipe = current_user.equipe
    # Teams visible in the navbar team-switcher dropdown (admin sees all, manager sees their teams + unassigned)
    from flask import session
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
        elif current_user.role == 'manager':
            all_equipes_for_switch = Equipe.query.filter(
                (Equipe.manager_id == current_user.id) | (Equipe.manager_id == None)
            ).order_by(Equipe.nom).all()
        else:
            all_equipes_for_switch = Equipe.query.filter(
                Equipe.id == current_user.equipe_id
            ).all() if current_user.equipe_id else []
    else:
        all_equipes_for_switch = []
    return dict(current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch,
                cache_buster=int(_datetime.utcnow().timestamp()))

# Global error handlers to avoid silent 500s
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

# Reconnect DB pool on cold start / SSL drop
@app.before_request
def reconnect_db_on_ssl_error():
    from sqlalchemy.exc import OperationalError
    try:
        db.session.execute(db.text("SELECT 1"))
    except OperationalError:
        db.session.rollback()
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception:
            pass
    except Exception:
        db.session.rollback()

# Global exception handler for debugging
@app.errorhandler(Exception)
def handle_all_exceptions(e):
    app.logger.error(f"Unhandled exception: {type(e).__name__}: {e}", exc_info=True)
    try:
        db.session.rollback()
    except Exception:
        pass
    return render_template('error.html', code=500, message=f"Erreur interne: {type(e).__name__}"), 500

# APScheduler for daily notifications
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from datetime import date as dt_date
    
    def envoyer_notifications_quotidiennes():
        """Envoyer les notifications pour les tâches fiscales arrivant à échéance aujourd'hui."""
        with app.app_context():
            try:
                from app.models import Tache
                from app.integrations.brevo import send_task_assigned_email_brevo
                fiscal_keywords = ['tva', 'is ', 'cfe ', 'acompte', 'dépôt', 'préparation', 'déclaration', 'prépa']
                tasks = Tache.query.filter(Tache.date_echeance == dt_date.today()).all()
                sent = 0
                for t in tasks:
                    titre = (t.titre or '').lower()
                    is_fiscal = any(kw in titre for kw in fiscal_keywords)
                    if is_fiscal and t.assigne_a and t.statut != 'terminee':
                        try:
                            send_task_assigned_email_brevo(t, t.assigne_a)
                            sent += 1
                        except Exception as e:
                            app.logger.warning(f"Send due notification failed: {e}")
                if sent:
                    app.logger.info(f"Sent {sent} daily due notifications")
            except Exception as e:
                app.logger.error(f"Daily notification error: {e}")
        
        # Générer les tâches récurrentes
        generer_taches_recurrentes()
    
    def generer_taches_recurrentes():
        """Créer les prochaines occurrences des tâches récurrentes terminées ou dépassées."""
        with app.app_context():
            try:
                from app.models import Tache
                from app import db
                from datetime import timedelta
                
                today = dt_date.today()
                # Chercher les tâches récurrentes terminées ou dont l'échéance est passée
                recurring_taches = Tache.query.filter(
                    Tache.frequence_repetition.isnot(None),
                    Tache.frequence_repetition != '',
                ).all()
                
                for t in recurring_taches:
                    # Déterminer si on doit créer la prochaine occurrence
                    should_create = False
                    if t.statut == 'terminee' and t.date_completion:
                        should_create = True
                    elif t.date_echeance and t.date_echeance < today:
                        should_create = True
                    
                    if not should_create:
                        continue
                    
                    # Calculer la prochaine date d'échéance
                    next_date = None
                    if t.frequence_repetition == 'daily':
                        next_date = (t.date_echeance or today) + timedelta(days=1)
                    elif t.frequence_repetition == 'weekly':
                        next_date = (t.date_echeance or today) + timedelta(weeks=1)
                    elif t.frequence_repetition == 'monthly':
                        m = (t.date_echeance or today).month + 1
                        y = (t.date_echeance or today).year
                        if m > 12: m = 1; y += 1
                        try:
                            next_date = dt_date(y, m, (t.date_echeance or today).day)
                        except ValueError:
                            next_date = dt_date(y, m, min((t.date_echeance or today).day, 28))
                    elif t.frequence_repetition == 'yearly':
                        try:
                            next_date = dt_date((t.date_echeance or today).year + 1, (t.date_echeance or today).month, (t.date_echeance or today).day)
                        except ValueError:
                            next_date = dt_date((t.date_echeance or today).year + 1, (t.date_echeance or today).month, 28)
                    
                    if next_date and next_date <= today + timedelta(days=7):  # seulement si dans la semaine à venir
                        # Créer la nouvelle occurrence
                        new_t = Tache(
                            titre=t.titre,
                            description=t.description,
                            dossier_id=t.dossier_id,
                            assigne_a=t.assigne_a,
                            priorite=t.priorite,
                            statut='a_faire',
                            date_echeance=next_date,
                            cree_par=t.cree_par,
                            frequence_repetition=t.frequence_repetition,
                            template_id=t.template_id or t.id,
                        )
                        db.session.add(new_t)
                        # Notifier
                        if new_t.assigne_a:
                            notif = Notification(
                                user_id=new_t.assigne_a,
                                tache_id=new_t.id,
                                message=f"Nouvelle occurrence : {new_t.titre}",
                                type_notification='assignation'
                            )
                            db.session.add(notif)
                        app.logger.info(f"Créé occurrence récurrente: {new_t.titre} -> {next_date}")
                
                db.session.commit()
            except Exception as e:
                app.logger.error(f"Recurring tasks error: {e}")
    
    def regenerer_taches_fiscales():
        """Régénérer les tâches fiscales pour le mois suivant."""
        with app.app_context():
            try:
                from app.tva_scheduler import planifier_tous_les_dossiers
                count = planifier_tous_les_dossiers()
                app.logger.info(f"Monthly fiscal refresh: {count} dossiers traités")
            except Exception as e:
                app.logger.error(f"Monthly fiscal refresh error: {e}")
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(envoyer_notifications_quotidiennes, 'cron', hour=8, minute=0)
    scheduler.add_job(generer_taches_recurrentes, 'cron', hour=7, minute=0)
    scheduler.add_job(regenerer_taches_fiscales, 'cron', day=1, hour=6, minute=0)  # 1er du mois à 06:00
    scheduler.start()
    app.logger.info("APScheduler started: daily at 08:00, monthly fiscal refresh on 1st")
except Exception as e:
    app.logger.warning(f"APScheduler not available: {e}")
