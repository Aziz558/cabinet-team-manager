from flask import Flask, render_template
from flask_login import current_user
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
import os
from datetime import date as _date

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates'),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

basedir = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or f'sqlite:///{os.path.join(basedir, "..", "instance", "app.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Validate DB URL before initializing SQLAlchemy
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
if db_uri and db_uri.startswith('postgresql://'):
    try:
        from urllib.parse import urlparse
        parsed = urlparse(db_uri)
        if not parsed.hostname:
            app.logger.warning("DATABASE_URL has no hostname; falling back to SQLite")
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "..", "instance", "app.db")}'
    except Exception as e:
        app.logger.warning(f"Cannot parse DATABASE_URL: {e}; falling back to SQLite")
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "..", "instance", "app.db")}'

app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.office365.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', ''))

app.config['UPLOAD_FOLDER'] = os.path.join(basedir, '..', 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Veuillez vous connecter.'
mail = Mail(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

from app import routes  # noqa: F401
from app.models import User, AppSetting, SuggestionTache, Equipe  # noqa: F401

with app.app_context():
    db.create_all()
    # Add missing columns to existing tables (for migration)
    try:
        inspector = db.inspect(db.engine)
        if 'users' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('users')]
            if 'equipe_id' not in columns:
                with db.engine.begin() as conn:
                    conn.execute(db.text("ALTER TABLE users ADD COLUMN equipe_id INTEGER"))
                    app.logger.info("Added equipe_id column to users table")
    except Exception as e:
        app.logger.warning(f"Migration error (users.equipe_id): {e}")
    # Add missing columns to dossiers
    try:
        inspector = db.inspect(db.engine)
        if 'dossiers' in inspector.get_table_names():
            dossiers_cols = [col['name'] for col in inspector.get_columns('dossiers')]
            if 'frequence_tva' not in dossiers_cols:
                with db.engine.begin() as conn:
                    conn.execute(db.text("ALTER TABLE dossiers ADD COLUMN frequence_tva VARCHAR(20) DEFAULT 'trimestrielle'"))
                    app.logger.info("Added frequence_tva column to dossiers table")
            if 'equipe_id' not in dossiers_cols:
                with db.engine.begin() as conn:
                    conn.execute(db.text("ALTER TABLE dossiers ADD COLUMN equipe_id INTEGER"))
                    app.logger.info("Added equipe_id column to dossiers table")
    except Exception as e:
        app.logger.warning(f"Migration error (dossiers): {e}")
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
    # Add team mailbox columns if missing
    try:
        inspector = db.inspect(db.engine)
        if 'equipes' in inspector.get_table_names():
            equipes_cols = [col['name'] for col in inspector.get_columns('equipes')]
            with db.engine.begin() as conn:
                if 'equipe_email' not in equipes_cols:
                    conn.execute(db.text("ALTER TABLE equipes ADD COLUMN equipe_email VARCHAR(200)"))
                    app.logger.info("Added equipe_email column")
                if 'equipe_email_password' not in equipes_cols:
                    conn.execute(db.text("ALTER TABLE equipes ADD COLUMN equipe_email_password VARCHAR(200)"))
                    app.logger.info("Added equipe_email_password column")
                if 'equipe_mailbox' not in equipes_cols:
                    conn.execute(db.text("ALTER TABLE equipes ADD COLUMN equipe_mailbox VARCHAR(200)"))
                    app.logger.info("Added equipe_mailbox column")
    except Exception as e:
        app.logger.warning(f"Migration error (equipes mailbox): {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Make date available in templates
app.jinja_env.globals['date'] = _date

# Context processor — makes current_equipe available in all templates
@app.context_processor
def inject_equipe():
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
            all_equipes_for_switch = Equipe.query.filter_by(equipe_id=current_user.equipe_id).all() if current_user.equipe_id else []
    else:
        all_equipes_for_switch = []
    return dict(current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch)

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
