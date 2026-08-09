from flask import Flask, render_template
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
        app.logger.warning(f"Migration error (equipe_id): {e}")
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
def inject_equipe():
    from flask import session
    current_equipe = None
    if current_user_is_authenticated():
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            current_equipe = Equipe.query.get(equipe_id)
        elif current_user.is_authenticated:
            # Default to user's assigned team
            current_equipe = current_user.equipe
    # Teams visible in the navbar team-switcher dropdown (admin sees all, manager sees their teams + unassigned)
    from flask import session
    if current_user_is_authenticated():
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

def current_user_is_authenticated():
    from flask_login import current_user
    return current_user.is_authenticated

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
