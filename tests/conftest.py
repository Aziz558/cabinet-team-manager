"""Configuration des tests : environnement isole AVANT l'import de l'app.

- Base SQLite temporaire hors repo (ORBIT_SQLITE_PATH)
- Schema construit par les migrations Alembic (valide la baseline a chaque suite)
- Pas de scheduler en arriere-plan (ORBIT_NO_SCHEDULER)
"""
import os
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Environnement AVANT tout import de app.*
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['USE_POSTGRES'] = 'false'
os.environ['ORBIT_SKIP_DB_INIT'] = '1'   # le schema vient des migrations, pas de create_all
os.environ['ORBIT_NO_SCHEDULER'] = '1'   # pas de taches de fond dans les tests
_fd, _db_path = tempfile.mkstemp(prefix='orbit_test_', suffix='.db')
os.close(_fd)
os.environ['ORBIT_SQLITE_PATH'] = _db_path

import pytest  # noqa: E402

MIGRATIONS_DIR = str(ROOT / 'migrations')


@pytest.fixture(scope='session')
def flask_app():
    from app import app
    app.config['TESTING'] = True
    with app.app_context():
        from flask_migrate import upgrade
        upgrade(directory=MIGRATIONS_DIR)  # baseline -> schema (teste la migration)
    yield app


@pytest.fixture(scope='session')
def seed(flask_app):
    """Donnees de base : 2 membres, 2 dossiers, 2 taches (perimetres differents)."""
    from app import db
    from app.models import User, Dossier, Tache
    from datetime import date, timedelta
    with flask_app.app_context():
        admin = User(email='admin@test.local', nom='Orbit', prenom='Admin', role='admin', actif=True)
        admin.set_password('AdminTest123!')
        membre = User(email='membre@test.local', nom='Dupont', prenom='Marie', role='membre', actif=True)
        membre.set_password('MembreTest123!')
        autre = User(email='autre@test.local', nom='Martin', prenom='Paul', role='membre', actif=True)
        autre.set_password('MembreTest123!')
        db.session.add_all([admin, membre, autre])
        db.session.flush()

        d1 = Dossier(numero_dossier='D-TEST-001', intitule='Dossier Alpha',
                     collaborateur_id=membre.id, regime_tva='ca3')
        d2 = Dossier(numero_dossier='D-TEST-002', intitule='Dossier Beta',
                     collaborateur_id=autre.id, regime_tva='ca12')
        t1 = Tache(titre='Preparer TVA trimestrielle', assigne_a=membre.id, cree_par=admin.id,
                   date_echeance=date.today() + timedelta(days=7))
        t2 = Tache(titre='Verifier facturation client', assigne_a=autre.id, cree_par=admin.id,
                   date_echeance=date.today() + timedelta(days=3))
        db.session.add_all([d1, d2, t1, t2])
        db.session.commit()
        return {
            'admin': ('admin@test.local', 'AdminTest123!'),
            'membre': ('membre@test.local', 'MembreTest123!'),
            'd1': d1.id, 'd2': d2.id, 't1': t1.id, 't2': t2.id,
        }


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


def _login(client, seed, key):
    email, pwd = seed[key]
    r = client.post('/login', data={'email': email, 'password': pwd}, follow_redirects=False)
    assert r.status_code in (200, 302), f'login KO ({r.status_code})'
    return client


@pytest.fixture()
def admin_client(client, seed):
    return _login(client, seed, 'admin')


@pytest.fixture()
def membre_client(client, seed):
    return _login(client, seed, 'membre')
