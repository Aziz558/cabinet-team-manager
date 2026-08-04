import os
import sys

APP_DIR = r"C:\Users\Mohamed Aziz JLASSI\Desktop\aziz gestion de cabinet\cabinet_team_manager"
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)
os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'

from app import app, db
from app.models import AppSetting

DEFAULT_SETTINGS = [
    {'cle': 'MAIL_SERVER', 'valeur': 'smtp.office365.com', 'service': 'mail', 'type_valeur': 'string'},
    {'cle': 'MAIL_PORT', 'valeur': '587', 'service': 'mail', 'type_valeur': 'string'},
    {'cle': 'MAIL_USE_TLS', 'valeur': 'true', 'service': 'mail', 'type_valeur': 'string'},
    {'cle': 'MAIL_USERNAME', 'valeur': '', 'service': 'mail', 'type_valeur': 'password', 'masque': True},
    {'cle': 'MAIL_PASSWORD', 'valeur': '', 'service': 'mail', 'type_valeur': 'password', 'masque': True},
    {'cle': 'MAIL_DEFAULT_SENDER', 'valeur': '', 'service': 'mail', 'type_valeur': 'string'},
    {'cle': 'OUTLOOK_CLIENT_ID', 'valeur': '', 'service': 'outlook', 'type_valeur': 'string'},
    {'cle': 'OUTLOOK_CLIENT_SECRET', 'valeur': '', 'service': 'outlook', 'type_valeur': 'password', 'masque': True},
    {'cle': 'OUTLOOK_TENANT_ID', 'valeur': '', 'service': 'outlook', 'type_valeur': 'string'},
    {'cle': 'OUTLOOK_MAILBOX_EMAIL', 'valeur': '', 'service': 'outlook', 'type_valeur': 'string'},
    {'cle': 'TEAMS_CLIENT_ID', 'valeur': '', 'service': 'teams', 'type_valeur': 'string'},
    {'cle': 'TEAMS_TENANT_ID', 'valeur': '', 'service': 'teams', 'type_valeur': 'string'},
    {'cle': 'TEAMS_CLIENT_SECRET', 'valeur': '', 'service': 'teams', 'type_valeur': 'password', 'masque': True},
    {'cle': 'TEAMS_TEAM_ID', 'valeur': '', 'service': 'teams', 'type_valeur': 'string'},
    {'cle': 'OPENROUTER_API_KEY', 'valeur': '', 'service': 'llm', 'type_valeur': 'password', 'masque': True},
    {'cle': 'OPENROUTER_MODEL', 'valeur': 'stepfun/step-3.7-flash:free', 'service': 'llm', 'type_valeur': 'string'},
    {'cle': 'OPENROUTER_PROVIDER', 'valeur': '', 'service': 'llm', 'type_valeur': 'string'},
    {'cle': 'OUTLOOK_GRAPH_REFRESH_TOKEN', 'valeur': '', 'service': 'outlook', 'type_valeur': 'string'},
    {'cle': 'OUTLOOK_GRAPH_EXPIRES_AT', 'valeur': '', 'service': 'outlook', 'type_valeur': 'string'},
    {'cle': 'MAILBOX_USER', 'valeur': '', 'service': 'mailbox', 'type_valeur': 'string'},
    {'cle': 'MAILBOX_PASSWORD', 'valeur': '', 'service': 'mailbox', 'type_valeur': 'password', 'masque': True},
    {'cle': 'MAILBOX_SERVER', 'valeur': 'imap.gmail.com', 'service': 'mailbox', 'type_valeur': 'string'},
    {'cle': 'MAILBOX_PORT', 'valeur': '993', 'service': 'mailbox', 'type_valeur': 'string'},
    {'cle': 'MAILBOX_USE_SSL', 'valeur': 'true', 'service': 'mailbox', 'type_valeur': 'string'},
    {'cle': 'MAILBOX_ALLOWED_SENDERS', 'valeur': '', 'service': 'mailbox', 'type_valeur': 'string'},
]

with app.app_context():
    for item in DEFAULT_SETTINGS:
        existing = AppSetting.query.filter_by(cle=item['cle']).first()
        if not existing:
            setting = AppSetting(**item)
            db.session.add(setting)
    db.session.commit()
    print(f"✅ {len(DEFAULT_SETTINGS)} paramètres initialisés.")
