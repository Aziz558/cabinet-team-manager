"""Synchro TVA en arrière-plan : réponse immédiate + suivi fiable.

Le bouton « Vérifier maintenant » appelait `sync_checklist_tva()` dans la
requête HTTP. Sur 53 dossiers, Render coupait la connexion avant la fin : le
navigateur recevait un corps vide et `r.json()` levait « Unexpected end of
JSON input », sans qu'aucun bilan ne soit affiché. Le POST doit maintenant
répondre en 202 et l'UI interroger /checklist/pl_sync_status.
"""

import threading
from datetime import datetime, timedelta, timezone

from app.integrations import pl_sync_job as job


def _quand(minutes_ecoulees):
    return ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ecoulees))
            .isoformat().replace('+00:00', 'Z'))


def test_verrou_orphalin_est_leve(monkeypatch):
    monkeypatch.setattr(job, '_lire',
                        lambda: {'running': True, 'quand': _quand(3 * 24 * 60)})
    etat = job.status()
    assert etat['running'] is False
    assert etat['perime'] is True


def test_job_recent_reste_en_cours(monkeypatch):
    monkeypatch.setattr(job, '_lire', lambda: {'running': True, 'quand': _quand(1)})
    assert job.status()['running'] is True


def test_bilan_disponible_apres_fin(monkeypatch):
    monkeypatch.setattr(job, '_lire',
                        lambda: {'running': False, 'quand': _quand(1),
                                 'resultat': {'ok': True, 'dossiers_ok': 53}})
    assert job.status()['resultat']['dossiers_ok'] == 53


def test_date_invalide_ne_bloque_pas(monkeypatch):
    for q in (None, 'pas-une-date', _quand(-60)):
        monkeypatch.setattr(job, '_lire', lambda q=q: {'running': True, 'quand': q})
        assert job.status()['running'] is False


def test_start_repond_sans_attendre_la_synchro(monkeypatch):
    monkeypatch.setattr(job, '_running', False)
    monkeypatch.setattr(job, '_lire', lambda: {})
    monkeypatch.setattr(job, '_save', lambda payload: None)

    class _ThreadInerte:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, 'Thread', _ThreadInerte)
    res = job.start()
    assert res['ok'] is True
    assert res['en_cours'] is True


def test_start_refuse_un_deuxieme_job(monkeypatch):
    monkeypatch.setattr(job, '_running', True)
    res = job.start()
    assert res['en_cours'] is True
    assert 'déjà' in res['message']


def test_route_repond_202_et_statut_suit(admin_client, monkeypatch):
    from app.integrations import pennylane_web as pw
    monkeypatch.setattr(pw, 'has_web_session', lambda: True)
    monkeypatch.setattr(job, 'start',
                        lambda: {'ok': True, 'en_cours': True, 'message': 'lancé'})
    r = admin_client.post('/checklist/pl_sync_all')
    assert r.status_code == 202
    assert r.get_json()['en_cours'] is True

    monkeypatch.setattr(job, 'status',
                        lambda: {'running': False, 'resultat': {'ok': True}})
    s = admin_client.get('/checklist/pl_sync_status')
    assert s.status_code == 200
    assert s.get_json()['resultat']['ok'] is True


def test_statut_refuse_aux_membres(membre_client):
    assert membre_client.get('/checklist/pl_sync_status').status_code == 403
