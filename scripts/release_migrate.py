"""Applique les migrations Alembic au demarrage du service (Render, local).

Logique :
- Base vierge (aucune table) -> flask db upgrade (cree tout via la baseline).
- Base existante SANS alembic_version (bases creees avant Flask-Migrate via
  db.create_all) -> flask db stamp head : le schema courant est considere
  conforme aux models, les prochaines migrations partiront de la.
- Base avec alembic_version -> flask db upgrade normal (migrations de prod).

Appele par render.yaml avant gunicorn :
    python scripts/release_migrate.py && gunicorn ...
"""
import os
import sys

# Racine du projet + environnement "outillage" AVANT l'import de l'app :
# on laisse les migrations construire le schema (pas de create_all parasite).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['ORBIT_SKIP_DB_INIT'] = '1'
os.environ['ORBIT_NO_SCHEDULER'] = '1'


def main():
    from app import app, db
    from flask_migrate import stamp, upgrade
    from sqlalchemy import inspect

    with app.app_context():
        tables = inspect(db.engine).get_table_names()
        if 'alembic_version' in tables:
            print(f'[migrate] alembic_version presente ({len(tables)} tables) -> upgrade')
            upgrade()
        elif tables:
            print(f"[migrate] {len(tables)} tables sans alembic_version -> stamp head (schema preexistant = models)")
            stamp()
        else:
            print('[migrate] base vierge -> upgrade (baseline)')
            upgrade()
    return 0


if __name__ == '__main__':
    sys.exit(main())
