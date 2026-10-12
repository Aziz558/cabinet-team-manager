"""Isolation par equipe : chaque manager ne voit que son equipe.

Liens inter-equipes autorises : les admins (vus de tous) et les referents
sociaux qui suivent un dossier d'un membre de l'equipe.
"""
import pytest


@pytest.fixture(scope='module')
def perim(flask_app, seed):
    from app import db
    from app.models import User, Equipe, Dossier
    with flask_app.app_context():
        def mk(email, nom, prenom, role='membre', pole='comptable'):
            u = User(email=email, nom=nom, prenom=prenom, role=role, pole=pole, actif=True)
            u.set_password('PerimTest123!')
            db.session.add(u)
            db.session.flush()
            return u

        hamza = mk('hamza@perim.local', 'Alpha', 'Hamza', role='manager')
        h1 = mk('lina@perim.local', 'Alpha', 'Lina')
        h2 = mk('omar@perim.local', 'Alpha', 'Omar')
        s_h = mk('sofia@perim.local', 'SocialA', 'Sofia', pole='social')
        mgr_b = mk('karim@perim.local', 'Beta', 'Karim', role='manager')
        b1 = mk('nadia@perim.local', 'Beta', 'Nadia')
        s_b = mk('tom@perim.local', 'SocialB', 'Tom', pole='social')

        eq_a = Equipe(nom='Equipe Perim Alpha', manager_id=hamza.id)
        eq_b = Equipe(nom='Equipe Perim Beta', manager_id=mgr_b.id)
        db.session.add_all([eq_a, eq_b])
        db.session.flush()
        h1.equipe_id = h2.equipe_id = eq_a.id
        b1.equipe_id = eq_b.id

        d_a = Dossier(numero_dossier='P-ALPHA-01', intitule='Dossier Perim Alpha',
                      collaborateur_id=h1.id, collaborateur_social_id=s_h.id, regime_tva='ca3')
        d_b = Dossier(numero_dossier='P-BETA-01', intitule='Dossier Perim Beta',
                      collaborateur_id=b1.id, collaborateur_social_id=s_b.id, regime_tva='ca3')
        db.session.add_all([d_a, d_b])
        db.session.commit()
        return {
            'hamza': hamza.id, 'h1': h1.id, 'h2': h2.id, 's_h': s_h.id,
            'mgr_b': mgr_b.id, 'b1': b1.id, 's_b': s_b.id,
            'd_a': d_a.id, 'd_b': d_b.id,
            'admin': User.query.filter_by(email='admin@test.local').first().id,
        }


def _ids_membres(flask_app, user_id):
    from app.models import User
    from app.route_common import membres_visibles_query
    with flask_app.app_context():
        return {u.id for u in membres_visibles_query(User.query.get(user_id)).all()}


def _ids_dossiers(flask_app, user_id):
    from app.models import User
    from app.route_common import dossiers_visibles_query
    with flask_app.app_context():
        return {d.id for d in dossiers_visibles_query(User.query.get(user_id)).all()}


def test_manager_voit_son_equipe_admins_et_referent_partage(flask_app, perim):
    ids = _ids_membres(flask_app, perim['hamza'])
    assert {perim['hamza'], perim['h1'], perim['h2'], perim['admin']} <= ids
    assert perim['s_h'] in ids, 'referent social d un dossier de son equipe : visible'


def test_manager_ne_voit_pas_les_autres_equipes(flask_app, perim):
    ids = _ids_membres(flask_app, perim['hamza'])
    assert perim['b1'] not in ids
    assert perim['mgr_b'] not in ids
    assert perim['s_b'] not in ids, 'referent social d une autre equipe : invisible'


def test_autre_manager_symetrique(flask_app, perim):
    ids = _ids_membres(flask_app, perim['mgr_b'])
    assert {perim['mgr_b'], perim['b1'], perim['s_b'], perim['admin']} <= ids
    assert perim['h1'] not in ids
    assert perim['h2'] not in ids
    assert perim['hamza'] not in ids
    assert perim['s_h'] not in ids


def test_dossiers_du_manager_limites_a_son_equipe(flask_app, perim):
    ids = _ids_dossiers(flask_app, perim['hamza'])
    assert perim['d_a'] in ids
    assert perim['d_b'] not in ids
    assert perim['d_b'] in _ids_dossiers(flask_app, perim['mgr_b'])
    assert perim['d_a'] not in _ids_dossiers(flask_app, perim['mgr_b'])


def test_membre_ne_voit_que_lui_meme(flask_app, perim):
    assert _ids_membres(flask_app, perim['h1']) == {perim['h1']}


def test_admin_voit_tout(flask_app, perim):
    ids = _ids_membres(flask_app, perim['admin'])
    assert {perim['hamza'], perim['h1'], perim['mgr_b'], perim['b1']} <= ids


def _login_as(flask_app, email, password='PerimTest123!'):
    c = flask_app.test_client()
    r = c.post('/login', data={'email': email, 'password': password}, follow_redirects=False)
    assert r.status_code in (200, 302), f'login KO ({r.status_code})'
    return c


def test_api_dossiers_membres_filtree_par_equipe(flask_app, perim):
    c = _login_as(flask_app, 'hamza@perim.local')
    j = c.get('/api/dossiers-membres').get_json()
    assert j['ok'] is True
    labels_membres = {m['label'] for m in j['membres']}
    assert 'Lina Alpha' in labels_membres
    assert 'Nadia Beta' not in labels_membres
    assert 'Karim Beta' not in labels_membres
    numeros = {d['label'].split(' — ')[0] for d in j['dossiers']}
    assert 'P-ALPHA-01' in numeros
    assert 'P-BETA-01' not in numeros


def test_membres_page_exclut_autre_equipe(flask_app, perim):
    c = _login_as(flask_app, 'hamza@perim.local')
    r = c.get('/membres')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'lina@perim.local' in html
    assert 'nadia@perim.local' not in html
    assert 'karim@perim.local' not in html


def test_avancement_membre_autre_equipe_refuse(flask_app, perim):
    c = _login_as(flask_app, 'hamza@perim.local')
    assert c.get(f"/suivi_avancement/api/membre/{perim['b1']}").status_code == 403
    assert c.get(f"/suivi_avancement/api/membre/{perim['h1']}").status_code == 200


def test_fiche_membre_autre_equipe_refusee(flask_app, perim):
    c = _login_as(flask_app, 'hamza@perim.local')
    assert c.get(f"/fiche_membre/{perim['b1']}").status_code == 302
    assert c.get(f"/fiche_membre/{perim['h1']}").status_code == 200
