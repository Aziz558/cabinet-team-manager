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

    # Migrate: add photo_base64 column if missing
    try:
        inspector = db.inspect(db.engine)
        users_cols = [col['name'] for col in inspector.get_columns('users')]
        if 'photo_base64' not in users_cols:
            with db.engine.begin() as conn:
                conn.execute(db.text("ALTER TABLE users ADD COLUMN photo_base64 TEXT"))
                app.logger.info("✅ Added photo_base64 column to users table")
    except Exception as e:
        app.logger.warning(f"Migration error (photo_base64): {e}")

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
                cache_buster=_datetime.utcnow().timestamp)

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
