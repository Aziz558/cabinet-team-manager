import sys
import os

APP_DIR = r"C:\Users\Mohamed Aziz JLASSI\Desktop\aziz gestion de cabinet\cabinet_team_manager"
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)
os.environ['SECRET_KEY'] = 'dev-secret'

from app import app, db
from app.models import PennyLaneSnapshot

with app.app_context():
    db.create_all()
    print('OK create_pennylane_snapshot_table')