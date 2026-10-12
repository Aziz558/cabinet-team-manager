"""Assistant : création de tâche confirmée, périmètre d'assignation et résumé du jour (sans LLM)."""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope='module')
def tk(flask_app, seed):
    from app import db
    from app.models import User, Equipe
    with flask_app.app_context():
        def mk(email, nom, prenom, role='membre'):
            u = User(email=email, nom=nom, prenom=prenom, role=role, actif=True)
            u.set_password('TkTest123!')
            db.session.add(u)
            db.session.flush()
            return u

        mgr = mk('tk.mgr@test.local', 'MgrTk', 'Hamza', role='manager')
        mem = mk('tk.mem@test.local', 'MembreTk', 'Lina')
        autre = mk('tk.autre@test.local', 'AutreTk', 'Nadia')
        eq = Equipe(nom='Equipe Tk', manager_id=mgr.id)
        db.session.add(eq)
        db.session.flush()
        mem.equipe_id = eq.id
        db.session.commit()
        return {'mgr': mgr.id, 'mem': mem.id, 'autre': autre.id}


def _client(flask_app, email):
    c = flask_app.test_client()
    r = c.post('/login', data={'email': email, 'password': 'TkTest123!'}, follow_redirects=False)
    assert r.status_code in (200, 302), f'login KO ({r.status_code})'
    return c


def _valide(**kw):
    base = {'titre': 'Relancer client', 'description': 'Pièces manquantes',
            'assigne_a_id': None, 'priorite': 'haute',
            'date_echeance': (date.today() + timedelta(days=2)).isoformat()}
    base.update(kw)
    return base


def test_creation_refusee_sans_connexion(flask_app):
    r = flask_app.test_client().post('/api/assistant/creer_tache', json=_valide())
    assert r.status_code in (302, 401)


def test_membre_ne_peut_assigner_qu_a_lui(flask_app, tk):
    c = _client(flask_app, 'tk.mem@test.local')
    r = c.post('/api/assistant/creer_tache', json=_valide(assigne_a_id=tk['autre']))
    assert r.status_code == 403
    assert r.get_json()['ok'] is False


def test_creation_confirmee_par_membre_pour_lui(flask_app, tk):
    from app.models import Tache
    c = _client(flask_app, 'tk.mem@test.local')
    r = c.post('/api/assistant/creer_tache', json=_valide(titre='Tache membre seule'))
    assert r.status_code == 200 and r.get_json()['ok'] is True
    with flask_app.app_context():
        t = Tache.query.filter_by(titre='Tache membre seule').first()
        assert t is not None
        assert t.assigne_a == tk['mem'] and t.cree_par == tk['mem']
        assert t.statut == 'a_faire' and t.priorite == 'haute'


def test_manager_assigne_dans_son_equipe(flask_app, tk):
    from app.models import Tache
    c = _client(flask_app, 'tk.mgr@test.local')
    r = c.post('/api/assistant/creer_tache',
               json=_valide(titre='Tache equipe', assigne_a_id=tk['mem']))
    assert r.status_code == 200
    with flask_app.app_context():
        assert Tache.query.filter_by(titre='Tache equipe', assigne_a=tk['mem']).first()


def test_manager_refuse_assignation_hors_equipe(flask_app, tk):
    from app.models import Tache
    c = _client(flask_app, 'tk.mgr@test.local')
    r = c.post('/api/assistant/creer_tache',
               json=_valide(titre='Tache hors equipe', assigne_a_id=tk['autre']))
    assert r.status_code == 403
    with flask_app.app_context():
        assert Tache.query.filter_by(titre='Tache hors equipe').first() is None


def test_date_et_titre_obligatoires(flask_app, tk):
    c = _client(flask_app, 'tk.mem@test.local')
    assert c.post('/api/assistant/creer_tache', json=_valide(date_echeance='')).status_code == 403
    assert c.post('/api/assistant/creer_tache', json=_valide(titre='  ')).status_code == 403



def test_proposition_llm_retenue_si_valide(flask_app, tk):
    from app.assistant_service import extraire_proposition_tache
    from app.models import User
    with flask_app.app_context():
        user = User.query.get(tk['mgr'])
        raw = ('Je propose cette tâche.\n<TACHE>{"titre": "Relance TVA", "assigne_a_id": %d, '
               '"priorite": "urgente", "date_echeance": "%s"}</TACHE>'
               % (tk['mem'], (date.today() + timedelta(days=3)).isoformat()))
        texte, tache = extraire_proposition_tache(raw, user)
        assert '<TACHE>' not in texte
        assert tache['titre'] == 'Relance TVA'
        assert tache['priorite'] == 'moyenne', 'priorite inconnue remplacee par moyenne'
        assert tache['assigne_a_id'] == tk['mem']


def test_proposition_llm_hors_perimetre_ignoree(flask_app, tk):
    from app.assistant_service import extraire_proposition_tache
    from app.models import User
    with flask_app.app_context():
        user = User.query.get(tk['mem'])
        raw = ('OK.\n<TACHE>{"titre": "X", "assigne_a_id": %d, "date_echeance": "%s"}</TACHE>'
               % (tk['autre'], date.today().isoformat()))
        texte, tache = extraire_proposition_tache(raw, user)
        assert tache is None
        assert 'Tâche non proposée' in texte


def test_proposition_llm_sans_date_ignoree(flask_app, tk):
    from app.assistant_service import extraire_proposition_tache
    from app.models import User
    with flask_app.app_context():
        user = User.query.get(tk['mem'])
        texte, tache = extraire_proposition_tache('<TACHE>{"titre": "Sans date"}</TACHE>', user)
        assert tache is None


def test_resume_du_jour_contient_les_compteurs(flask_app, tk):
    from app.models import Tache, User
    from app import db
    from app.assistant_service import resume_du_jour
    with flask_app.app_context():
        user = User.query.get(tk['mem'])
        db.session.add(Tache(titre='Echeance du jour', assigne_a=tk['mem'], cree_par=tk['mem'],
                             date_echeance=date.today(), statut='a_faire'))
        db.session.commit()
        r = resume_du_jour(user)
        assert r['nb_du_jour'] >= 1
        assert any(t['titre'] == 'Echeance du jour' for t in r['du_jour'])
        assert all(t['titre'] != 'Tache hors equipe' for t in r['du_jour'] + r['en_retard'])


def test_resume_route_sans_llm(flask_app, tk, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé')
    monkeypatch.setattr('app.integrations.openrouter.OpenRouterClient.chat', interdit)
    c = _client(flask_app, 'tk.mem@test.local')
    r = c.get('/api/assistant/resume')
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and 'nb_du_jour' in body['resume']
