import os
import sys

APP_DIR = r"C:\Users\Mohamed Aziz JLASSI\Desktop\aziz gestion de cabinet\cabinet_team_manager"
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)
os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'

from app import app, db
from app.models import AppSetting

with app.app_context():
    db.create_all()
    print("MIGRATE_OK")
