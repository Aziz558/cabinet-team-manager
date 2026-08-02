import sys
import os
import sqlite3

APP_DIR = r"C:\Users\Mohamed Aziz JLASSI\Desktop\aziz gestion de cabinet\cabinet_team_manager"
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

# Force fresh import
os.environ['SECRET_KEY'] = 'dev-secret-key-change-in-production'

from app import app, db
from app.models import User

# Ensure instance folder exists
os.makedirs(os.path.join(APP_DIR, 'instance'), exist_ok=True)

# Create all tables
with app.app_context():
    db.create_all()
    print("Tables created/verified")
    
    # Create default admin user if none exists
    if User.query.first() is None:
        admin = User(
            nom='Admin',
            prenom='Cabinet',
            email='admin@cabinet.com',
            mot_de_passe='admin123',
            role='manager',
            actif=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Created admin: admin@cabinet.com / admin123")
    else:
        print("Users already exist")

print("\nServer should be ready at http://127.0.0.1:5000/")
print("Login: admin@cabinet.com / admin123 (or create your own)")