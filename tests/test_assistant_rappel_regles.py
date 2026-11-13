"""Rappels demandés en langage naturel : « rappelle-moi demain à 10h de … ».

Bug d'origine : « RAPPELER MOI DEMAIN DE CA A 10H » était absorbé par le routeur
par intention (mot-clé « demain ») qui répondait la liste des échéances au lieu
de proposer le rappel.
"""
from datetime import date, timedelta

import pytest

from app.assistant_service import detecter_intention, detecter_rappel

HIST = [
    {'role': 'user', 'content': 'QULLES SONT LES FRS A RELANCER ?'},
    {'role': 'assistant',
     'content': 'Les fournisseurs à relancer pour Pro Store sont :\n- LAVIUDA\n- MANOMANO'},
]


def test_rappel_ne_part_pas_dans_les_echeances():
    assert detecter_intention('RAPPELER MOI DEMAIN DE CA A 10H') is None


def test_rappel_reprend_le_contexte_precedent():
    r = detecter_rappel('RAPPELER MOI DEMAIN DE CA A 10H', None, HIST)
    assert r and r['rappel']
    prop = r['rappel']
    assert prop['date_echeance'] == (date.today() + timedelta(days=1)).isoformat()
    assert 'fournisseurs' in prop['titre'].lower()
    assert '10h' in prop['titre']
    assert 'LAVIUDA' in prop['message'] and 'MANOMANO' in prop['message']


def test_rappel_sujet_explicite_et_heure():
    r = detecter_rappel('rappelle-moi lundi 9h de appeler le client Dupont', None, HIST)
    prop = r['rappel']
    assert prop['titre'].startswith('Appeler le client Dupont')
    assert '(09h)' in prop['titre']
    assert prop['date_echeance'] == (date.today() + timedelta(days=(0 - date.today().weekday()) % 7 or 7)).isoformat()


def test_rappel_sans_date_demande_la_date():
    r = detecter_rappel('rappelle moi de ca', None, HIST)
    assert r['rappel'] is None
    assert 'quelle date' in r['reponse'].lower()


def test_rappel_sans_contexte_demande_l_objet():
    r = detecter_rappel('rappelle-moi demain', None, [])
    assert r['rappel'] is None
    assert 'objet' in r['reponse']


def test_rappel_a_la_voie_rapide_sans_llm(flask_app, seed, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé pour une demande de rappel')
    monkeypatch.setattr('app.integrations.openrouter.OpenRouterClient.chat', interdit)
    c = flask_app.test_client()
    email, pwd = seed['membre']
    c.post('/login', data={'email': email, 'password': pwd})
    r = c.post('/api/assistant/message',
               json={'message': 'RAPPELER MOI DEMAIN DE CA A 10H', 'historique': HIST})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and body['source'] == 'regles'
    assert body['rappel'] and body['rappel']['date_echeance'] == (date.today() + timedelta(days=1)).isoformat()
    assert 'échéance(s) demain' not in body['reponse']


def test_rappel_confirme_puis_cree(flask_app, seed):
    c = flask_app.test_client()
    email, pwd = seed['membre']
    c.post('/login', data={'email': email, 'password': pwd})
    r = c.post('/api/assistant/message',
               json={'message': 'rappelle-moi demain à 10h des fournisseurs à relancer', 'historique': []})
    prop = r.get_json()['rappel']
    assert prop
    c2 = c.post('/api/assistant/creer_rappel', json=prop)
    assert c2.status_code == 200 and c2.get_json()['ok'] is True
    from app.models import Rappel, User
    with flask_app.app_context():
        u = User.query.filter_by(email='membre@test.local').first()
        rp = Rappel.query.filter_by(user_id=u.id, source='assistant').order_by(Rappel.id.desc()).first()
        assert rp is not None and '10h' in rp.titre
