"""Modification et suppression d'une tâche par son créateur.

Demande Aziz : un collaborateur qui a créé une tâche (pour lui-même ou son
manager) doit pouvoir la corriger ou la supprimer en cas d'erreur, tout en
conservant le mécanisme de notification (in-app, et email si priorité haute).
"""
import pytest


@pytest.fixture(scope='module')
def ed(flask_app, seed):
    from app import db
    from app.models import User, Equipe, Dossier
    with flask_app.app_context():
        def mk(email, nom, prenom, role='membre'):
            u = User(email=email, nom=nom, prenom=prenom, role=role, actif=True)
            u.set_password('EditTest123!')
            db.session.add(u)
            db.session.flush()
            return u

        mgr = mk('mged@edit.local', 'Chef', 'Mona', role='manager')
        m1 = mk('m1ed@edit.local', 'Un', 'Alice')
        m2 = mk('m2ed@edit.local', 'Deux', 'Bob')
        eq = Equipe(nom='Equipe Edit', manager_id=mgr.id)
        db.session.add(eq)
        db.session.flush()
        m1.equipe_id = m2.equipe_id = eq.id
        d = Dossier(numero_dossier='P-EDIT-01', intitule='Dossier Edit',
                    collaborateur_id=m1.id, regime_tva='ca3')
        db.session.add(d)
        db.session.commit()
        return {'mgr': mgr.id, 'm1': m1.id, 'm2': m2.id, 'eq': eq.id, 'dossier': d.id}


def _login_as(flask_app, email, password='EditTest123!'):
    c = flask_app.test_client()
    r = c.post('/login', data={'email': email, 'password': password}, follow_redirects=False)
    assert r.status_code in (200, 302)
    return c


def _client_collab(flask_app):
    return _login_as(flask_app, 'm1ed@edit.local')


def _client_bob(flask_app):
    return _login_as(flask_app, 'm2ed@edit.local')


def _client_mgr(flask_app):
    return _login_as(flask_app, 'mged@edit.local')


def _tache_id(flask_app, titre):
    from app.models import Tache
    with flask_app.app_context():
        t = Tache.query.filter_by(titre=titre).first()
        return t.id if t else None


def _creer(client, titre, assigne_a, priorite='moyenne'):
    return client.post('/taches', data={'titre': titre, 'assigne_a': str(assigne_a),
                                        'priorite': priorite, 'statut': 'a_faire',
                                        'date_echeance': '2030-12-01'})


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------

def test_collaborateur_modifie_sa_propre_tache(flask_app, ed):
    c = _client_collab(flask_app)
    _creer(c, 'Tache a corriger', ed['m1'], 'basse')
    tid = _tache_id(flask_app, 'Tache a corriger')
    r = c.post(f'/modifier_tache/{tid}', data={'titre': 'Tache corrigee',
                                               'assigne_a': str(ed['m1']),
                                               'priorite': 'moyenne',
                                               'date_echeance': '2030-12-31'})
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        t = Tache.query.get(tid)
        assert t.titre == 'Tache corrigee'
        assert t.priorite == 'moyenne'
        assert t.date_echeance.strftime('%Y-%m-%d') == '2030-12-31'


def test_collaborateur_ne_peut_pas_modifier_tache_d_autrui(flask_app, ed):
    c2 = _client_bob(flask_app)
    _creer(c2, 'Tache de Bob', ed['m2'])
    tid = _tache_id(flask_app, 'Tache de Bob')
    c1 = _client_collab(flask_app)
    r = c1.post(f'/modifier_tache/{tid}', data={'titre': 'Pirate',
                                                'assigne_a': str(ed['m1']),
                                                'priorite': 'haute',
                                                'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        assert Tache.query.get(tid).titre == 'Tache de Bob', 'pas de modification'


def test_collaborateur_ne_peut_pas_assigner_hors_perimetre_a_la_modification(flask_app, ed):
    c = _client_collab(flask_app)
    _creer(c, 'Tache perimetre', ed['m1'])
    tid = _tache_id(flask_app, 'Tache perimetre')
    r = c.post(f'/modifier_tache/{tid}', data={'titre': 'Tache perimetre',
                                               'assigne_a': str(ed['m2']),
                                               'priorite': 'moyenne',
                                               'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        assert Tache.query.get(tid).assigne_a == ed['m1'], 'assignation refusee'


def test_manager_modifie_une_tache_de_son_equipe(flask_app, ed):
    c = _client_mgr(flask_app)
    _creer(c, 'Tache manager a editer', ed['m1'])
    tid = _tache_id(flask_app, 'Tache manager a editer')
    r = c.post(f'/modifier_tache/{tid}', data={'titre': 'Tache manager editee',
                                               'assigne_a': str(ed['m2']),
                                               'priorite': 'moyenne',
                                               'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        t = Tache.query.get(tid)
        assert t.titre == 'Tache manager editee'
        assert t.assigne_a == ed['m2']


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

def test_collaborateur_supprime_sa_propre_tache(flask_app, ed):
    c = _client_collab(flask_app)
    _creer(c, 'Tache a supprimer', ed['m1'])
    tid = _tache_id(flask_app, 'Tache a supprimer')
    r = c.post(f'/supprimer_tache/{tid}')
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        assert Tache.query.get(tid) is None


def test_collaborateur_ne_peut_pas_supprimer_tache_d_autrui(flask_app, ed):
    c2 = _client_bob(flask_app)
    _creer(c2, 'Tache de Bob a proteger', ed['m2'])
    tid = _tache_id(flask_app, 'Tache de Bob a proteger')
    c1 = _client_collab(flask_app)
    r = c1.post(f'/supprimer_tache/{tid}')
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache
        assert Tache.query.get(tid) is not None, 'suppression refusee'


def test_suppression_par_collaborateur_notifie_l_assigne(flask_app, ed):
    c = _client_collab(flask_app)
    _creer(c, 'Tache supprimee pour le manager', ed['mgr'])
    tid = _tache_id(flask_app, 'Tache supprimee pour le manager')
    c.post(f'/supprimer_tache/{tid}')
    with flask_app.app_context():
        from app.models import Notification
        msgs = [n.message for n in Notification.query.filter_by(user_id=ed['mgr']).all()]
        assert any('Tâche supprimée' in m for m in msgs)


# ---------------------------------------------------------------------------
# Notifications conservées
# ---------------------------------------------------------------------------

def test_reassignation_notifie_le_nouvel_assigne_et_mail_si_urgent(flask_app, ed, monkeypatch):
    appels = []
    monkeypatch.setattr('app.integrations.brevo.send_task_assigned_email_brevo',
                        lambda t, uid: appels.append(uid) or True)
    c = _client_mgr(flask_app)
    _creer(c, 'Reassignation urgente', ed['m1'], 'haute')
    tid = _tache_id(flask_app, 'Reassignation urgente')
    r = c.post(f'/modifier_tache/{tid}', data={'titre': 'Reassignation urgente',
                                               'assigne_a': str(ed['m2']),
                                               'priorite': 'haute',
                                               'date_echeance': '2030-12-01'})
    assert r.status_code == 302
    with flask_app.app_context():
        from app.models import Tache, Notification
        assert Tache.query.get(tid).assigne_a == ed['m2']
        notifs = Notification.query.filter_by(user_id=ed['m2'], tache_id=tid).all()
        assert any('Nouvelle tâche assignée' in n.message for n in notifs)
    assert ed['m2'] in appels, 'priorite haute -> mail au nouvel assigne'


def test_modification_collaborateur_notifie_son_manager(flask_app, ed, monkeypatch):
    monkeypatch.setattr('app.integrations.brevo.send_tache_creee_manager_email_brevo',
                        lambda t, uid, auteur: True)
    c = _client_collab(flask_app)
    _creer(c, 'Tache collab a editer', ed['m1'])
    tid = _tache_id(flask_app, 'Tache collab a editer')
    c.post(f'/modifier_tache/{tid}', data={'titre': 'Tache collab editee',
                                           'assigne_a': str(ed['m1']),
                                           'priorite': 'moyenne',
                                           'date_echeance': '2030-12-01'})
    with flask_app.app_context():
        from app.models import Notification
        msgs = [n.message for n in Notification.query.filter_by(user_id=ed['mgr']).all()
                if 'modifié' in n.message]
        assert msgs, 'le manager doit être informé de la modification'


# ---------------------------------------------------------------------------
# Boutons visibles dans l'interface
# ---------------------------------------------------------------------------

def test_boutons_modifier_supprimer_pour_le_createur_collaborateur(flask_app, ed):
    c = _client_collab(flask_app)
    _creer(c, 'Tache avec boutons', ed['m1'])
    html = c.get('/taches').get_data(as_text=True)
    assert 'btn-editer' in html
    assert '/supprimer_tache/' in html
