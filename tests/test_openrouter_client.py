"""OpenRouterClient : une erreur HTTP est journalisée (statut + corps), jamais la clé."""
import logging

from app.integrations.openrouter import OpenRouterClient

CLE = 'sk-or-v1-TESTSECRET-0123456789'


class _Resp:
    def __init__(self, status, texte):
        self.status_code = status
        self.text = texte

    def json(self):
        raise ValueError('pas du JSON')


def test_erreur_http_journalisee_sans_cle(monkeypatch, caplog):
    monkeypatch.setattr('app.integrations.openrouter.requests.post',
                        lambda *a, **k: _Resp(401, '{"error": "invalid api key"}'))
    client = OpenRouterClient(api_key=CLE, model='m:free')
    with caplog.at_level(logging.ERROR, logger='app.integrations.openrouter'):
        assert client.chat([{'role': 'user', 'content': 'hi'}]) is None
    texte = caplog.text
    assert 'HTTP 401' in texte
    assert 'invalid api key' in texte
    assert CLE not in texte


def test_reponse_valide_renvoie_le_texte(monkeypatch):
    class _Ok(_Resp):
        def json(self):
            return {'choices': [{'message': {'content': '  Bonjour  '}}]}

    monkeypatch.setattr('app.integrations.openrouter.requests.post',
                        lambda *a, **k: _Ok(200, ''))
    client = OpenRouterClient(api_key=CLE, model='m:free')
    assert client.chat([{'role': 'user', 'content': 'hi'}]) == 'Bonjour'
