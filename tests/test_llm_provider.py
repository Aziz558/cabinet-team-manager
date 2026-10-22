"""llm_provider : Groq, fallback OpenRouter, relecture des réglages à chaque appel."""
from app.integrations.llm_provider import GroqProvider, LLMManager, OpenRouterProvider, get_llm_manager

CLE = 'gsk_TESTSECRET-0123456789'


class _Resp:
    def __init__(self, status, texte, data=None):
        self.status_code = status
        self.text = texte
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError('pas du JSON')
        return self._data


def test_groq_erreur_http_journalisee_sans_cle(monkeypatch):
    messages = []
    monkeypatch.setattr('app.integrations.llm_provider.requests.post',
                        lambda *a, **k: _Resp(401, '{"error": "invalid api key"}'))
    monkeypatch.setattr('app.integrations.llm_provider.logger.error',
                        lambda msg, *args: messages.append(msg % args if args else msg))
    prov = GroqProvider(api_key=CLE, model='llama-3.3-70b-versatile')
    assert prov.chat([{'role': 'user', 'content': 'hi'}]) is None
    texte = ' '.join(str(m) for m in messages)
    assert 'Groq' in texte
    assert 'HTTP 401' in texte
    assert CLE not in texte


def test_groq_reponse_valide(monkeypatch):
    ok = _Resp(200, '', {'choices': [{'message': {'content': '  Bonjour  '}}]})
    monkeypatch.setattr('app.integrations.llm_provider.requests.post', lambda *a, **k: ok)
    prov = GroqProvider(api_key=CLE, model='llama-3.3-70b-versatile')
    assert prov.chat([{'role': 'user', 'content': 'hi'}]) == 'Bonjour'


def test_groq_non_configure_repond_none(flask_app, monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with flask_app.app_context():
        from app import db
        from app.models import AppSetting
        AppSetting.query.filter_by(cle='GROQ_API_KEY').delete()
        db.session.commit()
        prov = GroqProvider()
        assert prov.is_configured() is False
        assert prov.chat([{'role': 'user', 'content': 'hi'}]) is None


def test_manager_relit_la_config_a_chaque_appel(flask_app):
    """Corrige le bug du singleton figé : une clé saisie dans les Réglages
    doit être prise en compte immédiatement, sans redémarrage."""
    with flask_app.app_context():
        assert get_llm_manager() is not get_llm_manager()


def test_fallback_openrouter_si_groq_echoue(flask_app, monkeypatch):
    with flask_app.app_context():
        ok = _Resp(200, '', {'choices': [{'message': {'content': 'Via OpenRouter'}}]})
        # Groq (et les providers du module llm_provider) échoue : 429 quota
        monkeypatch.setattr('app.integrations.llm_provider.requests.post',
                            lambda *a, **k: _Resp(429, '{"error": "rate limit"}'))
        # OpenRouter (module séparé) réussit
        monkeypatch.setattr('app.integrations.openrouter.requests.post', lambda *a, **k: ok)
        mgr = LLMManager()
        mgr.primary = GroqProvider(api_key=CLE, model='llama-3.3-70b-versatile')
        mgr.fallback = OpenRouterProvider(api_key='sk-or-TEST', model='m:free')
        assert mgr.chat([{'role': 'user', 'content': 'hi'}]) == 'Via OpenRouter'


def test_groq_api_key_est_considerer_secrete():
    from app.routes_api import _CLES_SECRETES
    assert 'GROQ_API_KEY' in _CLES_SECRETES


def test_page_reglages_contient_groq(admin_client):
    r = admin_client.get('/settings')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'groqForm' in html
    assert 'groqKey' in html
    assert 'LLM_PROVIDER_PRIMAIRE' in html
