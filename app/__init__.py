from flask import Flask
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
        # Log but don't crash
        app.logger.warning(f"Could not create default team: {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Make date available in templates
app.jinja_env.globals['date'] = _date