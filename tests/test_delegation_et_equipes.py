"""Delegation de taches (manager -> admin, admin -> tout le monde) et
affectation d'equipe depuis la page Membres.

Couvre la demande Aziz : le manager peut deleguer aux comptes admin, l'admin
cree des taches pour tout le monde, chacun suit ses taches deleguees, et le
changement d'equipe d'un membre ne produit plus d'erreur.
"""
import pytest


@pytest.fixture(scope='module')
def dlg(flask_app, seed):
    from app import db
    from app.models import User, Equipe
    with flask_app.app_context():
        def mk(email, nom, prenom, role='membre'):
            u = User(email=email, nom=nom, prenom=prenom, role=role, actif=True)
            u.set_password('DelegTest123!')
            db.session.add(u)
            db.session.flush()
            return u

        mgr = mk('mgr@dlg.local', 'Chef', 'Mona', role='manager')
        m1 = mk('m1@dlg.local', 'Un', 'Alice')
        m2 = mk('m2@dlg.local', 'Deux', 'Bob')
        mgr2 = mk('mgr2@dlg.local', 'Autre', 'Karim', role='manager')
        x1 = mk('x1@dlg.local', 'Externe', 'Nina')

        eq_mgr = Equipe(nom='Equipe Dlg Mona', manager_id=mgr.id)
        eq_autre = Equipe(nom='Equipe Dlg Karim', manager_id=mgr2.id)
        db.session.add_all([eq_mgr, eq_autre])
        db.session.flush()
        m1.equipe_id = m2.equipe_id = eq_mgr.id
        x1.equipe_id = eq_autre.id
        db.session.commit()
        return {
            'mgr': mgr.id, 'm1': m1.id, 'm2': m2.id,
            'mgr2': mgr2.id, 'x1': x1.id,
            'eq_mgr': eq_mgr.id, 'eq_autre': eq_autre.id,
            'admin': User.query.filter_by(email='admin@test.local').first().id,
        }


def _login_as(flask_app, email, password):
    c = flask_app.test_client()
    r = c.post('/login', data={'email': email, 'password': password}, follow_redirects=False)
    assert r.status_code in (200, 302)
    return c


def _client_mgr(flask_app):
    return _login_as(flask_app, 'mgr@dlg.local', 'DelegTest123!')


def _tache(flask_app, titre):
    from app.models import Tache
    with flask_app.app_context():
        return Tache.query.filter_by(titre=titre).first()


def test_manager_delegue_une_tache_a_un_admin(flask_app, dlg):
    titre = 'Delegation manager vers admin'
    c = _client_mgr(flask_app)
    r = c.post('/taches', data={'titre': titre, 'assigne_a': str(dlg['admin']),
                                'priorite': 'moyenne', 'statut': 'a_faire',
                                'date_echeance': '2030-12-01'})
    assert r.status_code == 302, r.get_data(as_text=True)[:2000]
    t = _tache(flask_app, titre)
    assert t is not None, 'la tache doit etre creee'
    assert t.assigne_a == dlg['admin']
    assert t.cree_par == dlg['mgr']


def test_manager_suit_les_taches_qu_il_a_deleguees(flask_app, dlg):
    """La liste /taches du manager inclut la tache deleguee a l'admin."""
    titre = 'Delegation suivie par le manager'
    c = _client_mgr(flask_app)
    c.post('/taches', data={'titre': titre, 'assigne_a': str(dlg['admin']),
                            'priorite': 'moyenne', 'statut': 'a_faire',
                            'date_echeance': '2030-12-01'})
    html = c.get('/taches').get_data(as_text=True)
    assert titre in html


def test_manager_ne_peut_pas_assigner_hors_equipe(flask_app, dlg):
    titre = 'Assignation interdite hors equipe'
    c = _client_mgr(flask_app)
    r = c.post('/taches', data={'titre': titre, 'assigne_a': str(dlg['x1']),
                                'priorite': 'moyenne', 'statut': 'a_faire',
                                'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    assert _tache(flask_app, titre) is None


def test_admin_cree_une_tache_pour_tout_le_monde(flask_app, dlg, admin_client):
    titre = 'Tache admin pour autre equipe'
    r = admin_client.post('/taches', data={'titre': titre, 'assigne_a': str(dlg['x1']),
                                           'priorite': 'moyenne', 'statut': 'a_faire',
                                           'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    t = _tache(flask_app, titre)
    assert t is not None
    assert t.assigne_a == dlg['x1']


def test_manager_change_l_equipe_d_un_membre_sans_erreur(flask_app, dlg):
    c = _client_mgr(flask_app)
    r = c.post(f"/assigner_equipe_manager?user_id={dlg['m2']}",
               data={'user_id': str(dlg['m2']), 'equipe_id': str(dlg['eq_mgr'])})
    assert r.status_code == 302
    from app.models import User
    with flask_app.app_context():
        assert User.query.get(dlg['m2']).equipe_id == dlg['eq_mgr']


def test_manager_ne_peut_pas_affecter_a_une_autre_equipe(flask_app, dlg):
    c = _client_mgr(flask_app)
    c.post(f"/assigner_equipe_manager?user_id={dlg['m2']}",
           data={'user_id': str(dlg['m2']), 'equipe_id': str(dlg['eq_autre'])})
    from app.models import User
    with flask_app.app_context():
        assert User.query.get(dlg['m2']).equipe_id == dlg['eq_mgr']


def test_manager_retire_un_membre_de_son_equipe(flask_app, dlg):
    c = _client_mgr(flask_app)
    c.post(f"/assigner_equipe_manager?user_id={dlg['m2']}",
           data={'user_id': str(dlg['m2']), 'equipe_id': ''})
    from app.models import User
    with flask_app.app_context():
        assert User.query.get(dlg['m2']).equipe_id is None


def test_admin_change_l_equipe_et_id_invalide_sans_500(flask_app, dlg, admin_client):
    from app.models import User
    r = admin_client.post(f"/assigner_equipe?user_id={dlg['x1']}",
                          data={'user_id': str(dlg['x1']), 'equipe_id': str(dlg['eq_mgr'])})
    assert r.status_code == 302
    with flask_app.app_context():
        assert User.query.get(dlg['x1']).equipe_id == dlg['eq_mgr']
    r = admin_client.post(f"/assigner_equipe?user_id={dlg['x1']}",
                          data={'user_id': str(dlg['x1']), 'equipe_id': '999999'})
    assert r.status_code == 302, 'un id d equipe inconnu ne doit pas produire de 500'
    with flask_app.app_context():
        assert User.query.get(dlg['x1']).equipe_id == dlg['eq_mgr']