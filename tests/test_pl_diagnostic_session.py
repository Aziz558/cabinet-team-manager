"""Quand Pennylane renvoie du HTML au lieu de JSON, dire la VRAIE cause.

En prod le 07/11/2026 : 27 cookies enregistrés, mais `vat_forms` répondait
HTTP 200 avec une page HTML. L'appli affichait « Réponse non JSON » et
0/53 dossiers synchronisés, sans jamais expliquer si c'était une session
morte, un collage d'un autre site ou un blocage anti-bot.
"""

from app.integrations import pennylane_web as pw


class _RepHTML:
    """Réponse HTTP 200 dont le corps n'est pas du JSON."""

    def __init__(self, url, content_type='text/html; charset=utf-8', status=200):
        self.status_code = status
        self.url = url
        self.headers = {'Content-Type': content_type}
        self.text = '<html><body>Veuillez vous connecter</body></html>'
        self.history = []
        self.cookies = []

    def json(self):
        raise ValueError('Expecting value: line 1 column 1 (char 0)')


def _session(monkeypatch, cookies='_jeancaisse_session=abc; my_csrf_token=xyz'):
    monkeypatch.setattr(pw, '_pl_session_cookies', cookies, raising=False)
    monkeypatch.setattr(pw, '_pl_session_loaded', True, raising=False)


def _get(monkeypatch, reponse):
    monkeypatch.setattr(pw.requests, 'get', lambda url, **kwargs: reponse)
    import time as _t
    monkeypatch.setattr(_t, 'sleep', lambda *_: None)


def test_redirection_vers_login_dit_de_recoller_les_cookies(monkeypatch):
    _session(monkeypatch)
    _get(monkeypatch, _RepHTML('https://app.pennylane.com/login'))
    res = pw.fetch_vat_forms('23281030')
    assert res['ok'] is False
    assert res['bloque'] is True       # disjoncteur : ne pas insister 53 fois
    assert 'NON RECONNUE' in res['message']
    assert 'Copier la valeur' in res['message']
    assert res['diagnostic']['redirection_login'] is True


def test_page_html_anti_bot_est_expliquee(monkeypatch):
    _session(monkeypatch)
    _get(monkeypatch, _RepHTML('https://app.pennylane.com/companies/23281030/accountants/declarations/vat_forms'))
    res = pw.fetch_vat_forms('23281030')
    assert res['ok'] is False
    assert 'page HTML' in res['message']
    assert 'anti-bot' in res['message']
    assert res['diagnostic']['content_type'].startswith('text/html')
    # Extrait textuel uniquement : aucune balise, aucun attribut.
    assert res['diagnostic']['extrait'] == 'Veuillez vous connecter'
    assert '<' not in res['diagnostic']['extrait']


def test_cookies_d_un_autre_site_sont_detectes(monkeypatch):
    """Le nettoyeur accepte 27 cookies étrangers : il faut les nommer."""
    _session(monkeypatch, 'intercom-id=abc; ajs_anonymous_id=xyz')
    monkeypatch.setattr(pw, 'fetch_vat_forms',
                        lambda *a, **k: {'ok': False, 'message': 'Réponse non JSON',
                                         'vat_returns': [], 'future_vat_returns': []})
    res = pw.test_web_session()
    assert res['ok'] is False
    assert '_jeancaisse_session' in res['message']
    assert res['session_pennylane'] is False
    assert res['nb_cookies'] == 2
    assert res['cles'] == ['ajs_anonymous_id', 'intercom-id']
    # Aucune valeur de cookie ne doit jamais apparaître dans le diagnostic.
    assert 'abc' not in res['message']


def test_session_valide_reste_verte(monkeypatch):
    _session(monkeypatch)
    monkeypatch.setattr(pw, 'fetch_vat_forms',
                        lambda *a, **k: {'ok': True, 'vat_returns': [{'status': 'filed'}],
                                         'future_vat_returns': []})
    res = pw.test_web_session()
    assert res['ok'] is True
    assert res['session_pennylane'] is True
    assert 'Session OK' in res['message']
