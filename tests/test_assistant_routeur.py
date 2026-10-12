"""Routeur par règles de l'assistant : questions factuelles sans appel LLM."""
import pytest

from app.assistant_service import detecter_intention


@pytest.mark.parametrize('message, attendu', [
    ('Quelles sont mes tâches en retard ?', 'retard'),
    ('Qu\u2019est-ce que j\u2019ai demain ?', 'demain'),
    ('Échéances aujourd\u2019hui', 'jour'),
    ('Fais-moi un résumé', 'resume'),
    ('Bilan de ma journée', 'resume'),
    ('Comment fonctionne la TVA mensuelle ?', None),
    ('Rédige un email à Lina', None),
    ('', None),
])
def test_detection_intention(message, attendu):
    assert detecter_intention(message) == attendu


def test_routeur_repond_sans_llm(flask_app, seed, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé pour une question factuelle')
    monkeypatch.setattr('app.integrations.openrouter.OpenRouterClient.chat', interdit)
    c = flask_app.test_client()
    email, pwd = seed['membre']
    c.post('/login', data={'email': email, 'password': pwd})
    r = c.post('/api/assistant/message', json={'message': 'Quelles sont mes tâches en retard ?'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True and body['source'] == 'regles'
    assert 'retard' in body['reponse'].lower()


def test_question_libre_passe_par_le_llm(flask_app, seed, monkeypatch):
    appels = []
    monkeypatch.setattr('app.integrations.openrouter.OpenRouterClient.is_configured', lambda self: True)
    monkeypatch.setattr('app.integrations.openrouter.OpenRouterClient.chat',
                        lambda self, messages: appels.append(messages) or 'Réponse du modèle')
    c = flask_app.test_client()
    email, pwd = seed['membre']
    c.post('/login', data={'email': email, 'password': pwd})
    r = c.post('/api/assistant/message', json={'message': 'Explique la TVA mensuelle'})
    assert r.status_code == 200
    assert len(appels) == 1
    assert r.get_json()['reponse'] == 'Réponse du modèle'
