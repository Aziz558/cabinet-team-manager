"""Pennylane web : refus métier (HTTP 422) vs panne de session.

Contexte prod (2026-11-07) : la synchro TVA globale a renvoyé
« 49/53 dossiers — 4 erreurs », les 4 étant des HTTP 422 sur vat_forms.
422 = Pennylane refuse la demande pour CETTE entreprise (pas de régime de TVA
configuré, ou entreprise hors périmètre du cabinet) : ce n'est pas la session
qui est morte, et ça ne doit ni compter comme une erreur de session, ni
déclencher l'alerte email à chaque passage horaire.
"""

from app.integrations import pennylane_web as pw


class _Rep:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.cookies = []
        self.headers = {'Content-Type': 'application/json; charset=utf-8'}
        self.text = '{}'
        self.url = 'https://app.pennylane.com/companies/1/accountants/declarations/vat_forms'

    def json(self):
        return self._payload


def _session(monkeypatch):
    monkeypatch.setattr(pw, '_pl_session_cookies', 'session=abc', raising=False)
    monkeypatch.setattr(pw, '_pl_session_loaded', True, raising=False)
    monkeypatch.setattr(pw, '_save_last_sync', lambda **kw: None, raising=False)


def test_422_est_un_refus_metier_pas_un_blocage(monkeypatch):
    _session(monkeypatch)
    monkeypatch.setattr(pw.requests, 'get', lambda url, **kw: _Rep(422))

    res = pw.fetch_vat_forms('23747600')

    assert res['ok'] is False
    assert res.get('dossier_ignore') is True
    assert not res.get('bloque')
    assert '422' in res['message']
    assert 'régime de TVA' in res['message']
    assert res['vat_returns'] == [] and res['future_vat_returns'] == []


def test_422_est_reessaye_avant_conclusion(monkeypatch):
    """Le 422 n'est pas dans la liste des codes à réessayer (418/429/5xx) :
    un seul appel suffit, on ne martèle pas Pennylane 3 fois."""
    _session(monkeypatch)
    appels = []

    def faux_get(url, **kw):
        appels.append(url)
        return _Rep(422)

    monkeypatch.setattr(pw.requests, 'get', faux_get)
    pw.fetch_vat_forms('23747600')
    assert len(appels) == 1


def test_alerte_email_pas_declenchee_sur_422(flask_app, seed, monkeypatch):
    """La synchro globale ne doit pas envoyer d'alerte si le seul souci est un 422."""
    from app import db
    from app.models import Dossier

    _session(monkeypatch)
    monkeypatch.setattr(pw.requests, 'get', lambda url, **kw: _Rep(422))
    alertes = []
    monkeypatch.setattr(pw, '_alerter_session', lambda m: alertes.append(m))

    with flask_app.app_context():
        for d in Dossier.query.all():
            d.pennylane_customer_id = '23747600'
        db.session.commit()

        res = pw.sync_checklist_tva()

    assert res['dossiers_total'] >= 1
    assert res['erreurs'] == [], f'les 422 ne sont pas des erreurs de session : {res["erreurs"]}'
    assert res['sans_tva'], 'les dossiers 422 doivent être listés dans sans_tva'
    assert alertes == [], f'aucune alerte attendue, obtenu {alertes}'

# --- Statuts Pennylane réels : aucun anglais brut dans l'interface -------------

def test_accepted_and_paid_est_traduit_et_compte_comme_declare():
    """Statut réel observé en prod (13 cellules TVA mensuelle) : il s'affichait
    en anglais brut et sa pastille restait au bleu par défaut."""
    assert pw.traduire_statut('accepted_and_paid') == 'Acceptée & payée'
    assert 'accepted_and_paid' in pw.FILED_STATUSES
    assert pw.pill_class('accepted_and_paid') == ' sym-pl-ok'


def test_statut_inconnu_humanise_jamais_de_snake_case():
    """Filet de sécurité : un nouveau statut Pennylane ne doit pas fuiter tel quel."""
    assert pw.traduire_statut('some_new_status') == 'some new status'
    assert pw.traduire_statut('') == ''
    assert pw.traduire_statut(None) == ''
