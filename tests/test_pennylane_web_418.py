"""Pennylane web : gestion du blocage anti-bot (HTTP 418) et des ré-essais.

Contexte : « Vérifier maintenant » ne changeait aucun statut sur une partie des
dossiers, et la resynchro d'un dossier remontait « Pennylane HTTP 418 sur
vat_forms ». 418 = protection anti-bot de Pennylane, transitoire. Le code
n'effectuait AUCUNE nouvelle tentative et renvoyait `ok: True` même quand zéro
dossier avait été synchronisé.
"""

import json

from app.integrations import pennylane_web as pw


class _Rep:
    def __init__(self, status, payload=None, cookies=None):
        self.status_code = status
        self._payload = payload or {}
        self.cookies = cookies or []

    def json(self):
        return self._payload


def _session(monkeypatch):
    monkeypatch.setattr(pw, '_pl_session_cookies', 'session=abc', raising=False)
    monkeypatch.setattr(pw, '_pl_session_loaded', True, raising=False)


def test_418_est_reessaye_puis_annonce_comme_un_blocage(monkeypatch):
    """3 tentatives, puis un message qui distingue blocage et session expirée."""
    _session(monkeypatch)
    appels = []

    def faux_get(url, **kwargs):
        appels.append(url)
        return _Rep(418)

    monkeypatch.setattr(pw.requests, 'get', faux_get)
    import time as _t
    monkeypatch.setattr(_t, 'sleep', lambda *_: None)

    res = pw.fetch_vat_forms('23281030')

    assert len(appels) == 3, f'attendu 3 tentatives, obtenu {len(appels)}'
    assert res['ok'] is False
    assert res.get('bloque') is True
    assert '418' in res['message']
    assert 'session' in res['message'].lower()


def test_418_puis_200_finit_par_reussir(monkeypatch):
    """Un blocage passager ne doit plus faire échouer le dossier."""
    _session(monkeypatch)
    etat = {'n': 0}

    def faux_get(url, **kwargs):
        etat['n'] += 1
        if etat['n'] == 1:
            return _Rep(418)
        return _Rep(200, {'vat_returns': [{'period_start': '2026-10-01', 'status': 'filed'}],
                          'future_vat_returns': []})

    monkeypatch.setattr(pw.requests, 'get', faux_get)
    import time as _t
    monkeypatch.setattr(_t, 'sleep', lambda *_: None)

    res = pw.fetch_vat_forms('23281030')

    assert etat['n'] == 2, 'le second essai aurait dû être tenté'
    assert res['ok'] is True
    assert res['vat_returns'][0]['status'] == 'filed'


def test_200_repond_immediatement_sans_reessai(monkeypatch):
    """Cas nominal : une seule requête, aucun délai ajouté."""
    _session(monkeypatch)
    appels = []

    def faux_get(url, **kwargs):
        appels.append(url)
        return _Rep(200, {'vat_returns': [], 'future_vat_returns': []})

    monkeypatch.setattr(pw.requests, 'get', faux_get)
    res = pw.fetch_vat_forms('23281030')

    assert len(appels) == 1
    assert res['ok'] is True


def test_401_reste_une_session_expiree(monkeypatch):
    """401 ne doit pas être confondu avec un blocage : c'est la session."""
    _session(monkeypatch)
    appels = []

    def faux_get(url, **kwargs):
        appels.append(url)
        return _Rep(401)

    monkeypatch.setattr(pw.requests, 'get', faux_get)
    res = pw.fetch_vat_forms('23281030')

    assert len(appels) == 1, 'un 401 ne se réessaie pas'
    assert res['ok'] is False
    assert not res.get('bloque')
    assert 'expirée' in res['message'].lower()


def test_en_tetes_ressemblent_a_un_navigateur(monkeypatch):
    """Les en-têtes qui font passer l'appel pour un XHR légitime."""
    h = pw._headers()
    assert 'accept-language' in h
    assert h['origin'] == 'https://app.pennylane.com'
    assert h['sec-fetch-site'] == 'same-origin'
    assert 'Mozilla' in h['user-agent']
    # Jamais de secret dans les en-têtes : l'auth passe par les cookies.
    assert not any('token' in k.lower() for k in h)


def test_sync_all_renvoie_un_echec_quand_tout_est_bloque(flask_app, seed, monkeypatch):
    """Le bilan de « Vérifier maintenant » doit dire la vérité.

    Avant : `ok: True` même avec 0 dossier synchronisé -> toast vert et aucun
    statut modifié, sans explication. C'est exactement le symptôme rapporté.
    """
    from app import db
    from app.models import Dossier

    _session(monkeypatch)

    with flask_app.app_context():
        for did in (seed['d1'], seed['d2']):
            d = Dossier.query.get(did)
            d.pennylane_customer_id = '23281030'
        db.session.commit()

    monkeypatch.setattr(pw.requests, 'get', lambda url, **kw: _Rep(418))
    import time as _t
    monkeypatch.setattr(_t, 'sleep', lambda *_: None)

    with flask_app.app_context():
        res = pw.sync_checklist_tva()

    assert res['ok'] is False, "zéro dossier synchronisé ne peut pas être un succès"
    assert res['dossiers_ok'] == 0
    assert res['dossiers_total'] >= 2
    assert res.get('bloques', 0) >= 1
    assert '418' in res['message']
    assert 'anti-bot' in res['message']


def test_sync_all_reussit_si_un_dossier_repond(flask_app, seed, monkeypatch):
    """Un seul dossier OK suffit à un bilan positif (synchro partielle assumée)."""
    from app import db
    from app.models import Dossier

    _session(monkeypatch)

    with flask_app.app_context():
        d = Dossier.query.get(seed['d1'])
        d.pennylane_customer_id = '23281030'
        d2 = Dossier.query.get(seed['d2'])
        d2.pennylane_customer_id = None
        d2.pennylane_api_token = None
        db.session.commit()

    monkeypatch.setattr(pw.requests, 'get', lambda url, **kw: _Rep(200, {
        'vat_returns': [{'period_start': '2026-10-01', 'status': 'filed'}],
        'future_vat_returns': []}))
    import time as _t
    monkeypatch.setattr(_t, 'sleep', lambda *_: None)

    with flask_app.app_context():
        res = pw.sync_checklist_tva()

    assert res['ok'] is True
    assert res['dossiers_ok'] == 1
    assert res['synces'] == 1
