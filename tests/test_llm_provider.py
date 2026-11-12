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


# ---------------------------------------------------------------------------
# Liste déroulante des modèles (auto-chargée depuis l'API du provider)
# ---------------------------------------------------------------------------

def _resp_modeles(ids):
    return _Resp(200, '', {'data': [{'id': i} for i in ids]})


def test_lister_modeles_nvidia_filtre_non_chat_et_trie(flask_app, monkeypatch):
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.setenv('NVIDIA_API_KEY', 'nvapi-TEST-0123456789')
    monkeypatch.setattr(lp.requests, 'get', lambda *a, **k: _resp_modeles([
        'meta/llama-3.3-70b-instruct', 'nvidia/nv-embedqa-e5-v5',
        'meta/llama-3.1-8b-instruct', 'nvidia/llama-3.1-nemoguard-8b-content-safety',
    ]))
    with flask_app.app_context():
        ids, source = lp.lister_modeles('nvidia')
    assert source == 'api'
    assert ids == ['meta/llama-3.1-8b-instruct', 'meta/llama-3.3-70b-instruct']


def test_lister_modeles_cache_et_refresh(flask_app, monkeypatch):
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.setenv('GROQ_API_KEY', CLE)
    appels = []
    monkeypatch.setattr(lp.requests, 'get',
                        lambda *a, **k: appels.append(1) or _resp_modeles(['llama-3.3-70b-versatile']))
    with flask_app.app_context():
        ids1, source1 = lp.lister_modeles('groq')
        ids2, source2 = lp.lister_modeles('groq')
        ids3, source3 = lp.lister_modeles('groq', refresh=True)
    assert (source1, source2, source3) == ('api', 'cache', 'api')
    assert ids1 == ids2 == ids3 == ['llama-3.3-70b-versatile']
    assert len(appels) == 2


def test_lister_modeles_sans_cle(flask_app, monkeypatch):
    import pytest
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    with flask_app.app_context():
        from app import db
        from app.models import AppSetting
        AppSetting.query.filter_by(cle='NVIDIA_API_KEY').delete()
        db.session.commit()
        with pytest.raises(RuntimeError, match='absente'):
            lp.lister_modeles('nvidia')
        # OpenRouter : liste publique, fonctionne sans clé.
        monkeypatch.setattr(lp.requests, 'get', lambda *a, **k: _resp_modeles(['m/a', 'm/b']))
        ids, _ = lp.lister_modeles('openrouter')
        assert ids == ['m/a', 'm/b']


def test_lister_modeles_gemini_filtre_generatecontent(flask_app, monkeypatch):
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.setenv('GEMINI_API_KEY', 'gm-TEST-0123456789')
    payload = {'models': [
        {'name': 'models/gemini-1.5-flash', 'supportedGenerationMethods': ['generateContent']},
        {'name': 'models/text-embedding-004', 'supportedGenerationMethods': ['embedContent']},
        {'name': 'models/gemini-1.5-pro', 'supportedGenerationMethods': ['generateContent', 'countTokens']},
    ]}
    monkeypatch.setattr(lp.requests, 'get', lambda *a, **k: _Resp(200, '', payload))
    with flask_app.app_context():
        ids, _ = lp.lister_modeles('gemini')
    assert ids == ['gemini-1.5-flash', 'gemini-1.5-pro']


def test_api_llm_models_admin(flask_app, admin_client, monkeypatch):
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.setenv('NVIDIA_API_KEY', 'nvapi-TEST-0123456789')
    monkeypatch.setattr(lp.requests, 'get', lambda *a, **k: _resp_modeles(['meta/llama-3.1-8b-instruct']))
    r = admin_client.get('/api/llm/models?provider=nvidia')
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert j['models'] == ['meta/llama-3.1-8b-instruct']
    assert 'nvapi-TEST' not in r.get_data(as_text=True)


def test_api_llm_models_refuse_membre(membre_client):
    r = membre_client.get('/api/llm/models?provider=nvidia')
    assert r.status_code == 403


def test_api_llm_models_erreur_provider_inconnu(admin_client):
    r = admin_client.get('/api/llm/models?provider=inconnu')
    assert r.status_code == 502
    assert r.get_json()['ok'] is False


def test_api_llm_models_erreur_http_sans_fuite_cle(flask_app, admin_client, monkeypatch):
    from app.integrations import llm_provider as lp
    monkeypatch.setattr(lp, '_MODELES_CACHE', {})
    monkeypatch.setenv('GROQ_API_KEY', CLE)
    monkeypatch.setattr(lp.requests, 'get', lambda *a, **k: _Resp(401, '{"error": "invalid key ' + CLE + '"}'))
    r = admin_client.get('/api/llm/models?provider=groq')
    assert r.status_code == 502
    assert CLE not in r.get_data(as_text=True)


def test_page_reglages_listes_deroulantes_modeles(admin_client):
    r = admin_client.get('/settings')
    html = r.get_data(as_text=True)
    for ident in ('orModel', 'nvidiaModel', 'geminiModel', 'groqModel'):
        assert f'<select id="{ident}"' in html
        assert f'{ident}Refresh' in html
    assert 'configurerSelectModeles' in html
    assert '/api/llm/models' in html
