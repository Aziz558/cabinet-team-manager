"""Persistance de l'état de vérification Pennylane, et sonde /health.

Deux défauts corrigés ici, tous deux invisibles en développement :

1. ``_allchk_save`` était appelée dans le ``finally`` du thread de fond, donc
   APRÈS la sortie du ``with app_context()``. L'upsert échouait silencieusement
   (« Working outside of application context ») : l'état restait bloqué sur
   ``running: true`` et plus aucune vérification ne pouvait démarrer pendant
   45 minutes. Ce test exécute l'écriture depuis un vrai thread, comme en prod.

2. ``/health`` doit rester une sonde fiable : elle ne doit exposer aucun secret
   et doit savoir reconnaître la classe de worker gunicorn réellement chargée.
"""

import json
import sys
import threading
import types

from flask import has_app_context

import app as app_package  # le paquet, pour atteindre _orbit_worker_gunicorn
from app.integrations import pennylane as pl

PAYLOAD = {'running': False, 'faits': 3, 'dossiers': 3, 'nouveaux': 0, 'erreurs': 0}


def _lire_etat():
    from app.models import AppSetting
    s = AppSetting.query.filter_by(cle=pl.ALLCHK_KEY).first()
    return json.loads(s.valeur) if s else None


def test_allchk_save_persiste_depuis_un_thread_sans_contexte(flask_app):
    """Le cas exact de la prod : thread de fond, aucun contexte applicatif."""
    temoin = {}

    def _dans_le_thread():
        temoin['sans_contexte'] = not has_app_context()
        pl._allchk_save(dict(PAYLOAD, running=False, faits=17))
        temoin['erreur'] = None

    fil = threading.Thread(target=_dans_le_thread)
    fil.start()
    fil.join(timeout=10)

    assert not fil.is_alive(), 'le thread de sauvegarde ne doit pas rester bloqué'
    assert temoin['sans_contexte'] is True, 'le test doit tourner hors contexte applicatif'

    with flask_app.app_context():
        etat = _lire_etat()
        assert etat is not None, (
            "l'état n'a pas été persisté : _allchk_save échoue hors contexte "
            "applicatif, le verrou « running » resterait actif 45 min")
        assert etat['running'] is False
        assert etat['faits'] == 17
        assert etat['quand'], 'la trace horaire doit être renseignée'

        # On ne laisse pas de trace dans la base partagée par la suite de tests.
        from app import db
        from app.models import AppSetting
        db.session.delete(AppSetting.query.filter_by(cle=pl.ALLCHK_KEY).first())
        db.session.commit()


def test_allchk_save_reste_utilisable_dans_un_contexte_existant(flask_app):
    """Appel depuis une requête HTTP (contexte déjà présent) : pas de double push."""
    with flask_app.app_context():
        pl._allchk_save(dict(PAYLOAD, running=True, faits=1))
        etat = _lire_etat()
        assert etat is not None and etat['running'] is True
        from app import db
        from app.models import AppSetting
        db.session.delete(AppSetting.query.filter_by(cle=pl.ALLCHK_KEY).first())
        db.session.commit()


# --- Sonde /health ---------------------------------------------------------

def test_health_repond_sans_authentification(flask_app):
    r = flask_app.test_client().get('/health')
    assert r.status_code == 200
    assert r.mimetype == 'application/json'
    corps = r.get_json()
    assert corps['statut'] == 'ok'
    for cle in ('worker', 'threads', 'base', 'python', 'planificateur', 'pid', 'forke'):
        assert cle in corps, f'clé {cle} absente de /health'
    assert corps['base'] in ('sqlite', 'postgresql', 'indisponible')
    assert isinstance(corps['threads'], int) and corps['threads'] >= 1
    # Hors gunicorn --preload : le process n'a pas été forké après import.
    assert corps['forke'] is False


def test_health_n_expose_aucun_secret(flask_app):
    """La sonde est publique : ni chaîne de connexion, ni identifiant, ni clé."""
    corps = flask_app.test_client().get('/health').get_data(as_text=True)
    for interdit in ('postgresql://', 'postgres://', 'DATABASE_URL', 'password',
                     'PASSWORD', 'SECRET', 'token', 'cookies'):
        assert interdit not in corps, f'fuite potentielle dans /health : {interdit}'


def test_health_reconnait_la_classe_de_worker(monkeypatch):
    """Sert à vérifier depuis l'extérieur que le déploiement utilise bien gthread."""
    for module in ('gunicorn.workers.sync', 'gunicorn.workers.gthread',
                   'gunicorn.workers.ggevent'):
        monkeypatch.delitem(sys.modules, module, raising=False)

    assert app_package._orbit_worker_gunicorn() is None, 'hors gunicorn : inconnu'

    monkeypatch.setitem(sys.modules, 'gunicorn.workers.gthread',
                        types.ModuleType('gunicorn.workers.gthread'))
    assert app_package._orbit_worker_gunicorn() == 'gthread'

    monkeypatch.delitem(sys.modules, 'gunicorn.workers.gthread', raising=False)
    monkeypatch.setitem(sys.modules, 'gunicorn.workers.sync',
                        types.ModuleType('gunicorn.workers.sync'))
    monkeypatch.setitem(sys.modules, 'gunicorn.workers.base',
                        types.ModuleType('gunicorn.workers.base'))
    assert app_package._orbit_worker_gunicorn() == 'sync', (
        'la classe de base gunicorn ne doit pas masquer la classe concrète')
