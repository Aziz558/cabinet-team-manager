import sys
sys.path.insert(0, '.')
from app import app, db
from app.models import Tache, Dossier, User, Equipe
with app.app_context():
    from sqlalchemy import text
    result = db.session.execute(text('SELECT id, numero_dossier, intitule, date_limite_declaration FROM dossiers'))
    rows = result.fetchall()
    print('Total dossiers:', len(rows))
    for row in rows:
        print('Dossier:', row)
    result = db.session.execute(text('SELECT id, titre, dossier_id, statut FROM taches'))
    rows = result.fetchall()
    print('Total taches:', len(rows))
    for row in rows:
        print('Tache:', row)