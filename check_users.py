from app import app, db
from app.models import User

with app.app_context():
    print('users:', User.query.count())
    for u in User.query.all():
        print(u.email, u.role, u.prenom, u.nom)
