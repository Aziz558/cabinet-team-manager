"""Notifications in-app pour les échéances du jour et de demain (sans doublon)."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope='module')
def rappel_seed(flask_app):
    from app import db
    from app.models import User, Tache
    with flask_app.app_context():
        u = User(email='rappel.u@test.local', nom='RappelU', prenom='Test', role='membre', actif=True)
        u.set_password('RappelTest123!')
        db.session.add(u)
        db.session.flush()
        today = date.today()
        t_auj = Tache(titre='Rappel aujourdhui', assigne_a=u.id, cree_par=u.id,
                      date_echeance=today, statut='a_faire')
        t_dem = Tache(titre='Rappel demain', assigne_a=u.id, cree_par=u.id,
                      date_echeance=today + timedelta(days=1), statut='a_faire')
        t_loin = Tache(titre='Rappel dans 5 jours', assigne_a=u.id, cree_par=u.id,
                       date_echeance=today + timedelta(days=5), statut='a_faire')
        t_finie = Tache(titre='Rappel terminee', assigne_a=u.id, cree_par=u.id,
                        date_echeance=today, statut='terminee')
        db.session.add_all([t_auj, t_dem, t_loin, t_finie])
        db.session.commit()
        return {'uid': u.id, 'auj': t_auj.id, 'dem': t_dem.id,
                'loin': t_loin.id, 'finie': t_finie.id}


def _notifs(flask_app, uid):
    from app.models import Notification
    with flask_app.app_context():
        return Notification.query.filter_by(user_id=uid, type_notification='rappel_echeance').all()


def test_rappels_crees_pour_aujourdhui_et_demain_seulement(flask_app, rappel_seed):
    from app.rappels_notifications import creer_rappels_echeances
    with flask_app.app_context():
        n = creer_rappels_echeances()
    assert n >= 2
    taches = {x.tache_id for x in _notifs(flask_app, rappel_seed['uid'])}
    assert rappel_seed['auj'] in taches
    assert rappel_seed['dem'] in taches
    assert rappel_seed['loin'] not in taches, 'echeance a J+5 : pas de rappel'
    assert rappel_seed['finie'] not in taches, 'tache terminee : pas de rappel'


def test_pas_de_doublon_au_second_passage(flask_app, rappel_seed):
    from app.rappels_notifications import creer_rappels_echeances
    avant = len(_notifs(flask_app, rappel_seed['uid']))
    with flask_app.app_context():
        n = creer_rappels_echeances()
    assert n == 0
    assert len(_notifs(flask_app, rappel_seed['uid'])) == avant


def test_message_indique_la_date_et_le_delai(flask_app, rappel_seed):
    msgs = [x.message for x in _notifs(flask_app, rappel_seed['uid'])]
    assert any("aujourd'hui" in m and 'Rappel aujourdhui' in m for m in msgs)
    assert any('demain' in m and 'Rappel demain' in m for m in msgs)
