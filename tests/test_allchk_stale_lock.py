"""Vérification globale des nouveaux documents : verrou orphelin.

Contexte prod (constaté le 07/11/2026) : l'état persisté
``PENNYLANE_NEWDOCS_CHECK`` valait ``running: True`` avec un `quand` au
09/10/2026, soit 29 jours d'immobilité. Render avait tué le thread daemon
avant son `finally` ; toutes les ouvertures suivantes de /pennylane lisaient
« déjà en cours » et ne relançaient jamais la détection. Résultat : les
compteurs « à traiter / traité / archivé » affichaient un mois de retard.

Ce test verrouille la correction : un `running` ancien, sans date, invalide
ou dans le futur n'est jamais considéré comme un passage en cours.
"""

import threading
from datetime import datetime, timedelta, timezone

from app.integrations import pennylane as pl


def _quand(minutes_ecoulees):
    return ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ecoulees))
            .isoformat().replace('+00:00', 'Z'))


def _etat(running, minutes_ecoulees=2):
    return {'running': running, 'faits': 53, 'dossiers': 53,
            'nouveaux': 0, 'erreurs': 0, 'quand': _quand(minutes_ecoulees)}


class _ThreadInerte:
    """Remplace threading.Thread pour ne pas lancer la vraie boucle réseau."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def test_verrou_orphelin_est_ecarte(monkeypatch):
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 29 * 24 * 60))
    assert pl.allchk_running() is False


def test_passage_recent_reste_bloquant(monkeypatch):
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 2))
    assert pl.allchk_running() is True


def test_trace_rafraichie_pendant_le_passage(monkeypatch):
    """53 dossiers prennent du temps : chaque _allchk_save rajeunit `quand`."""
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 44))
    assert pl.allchk_running() is True
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 46))
    assert pl.allchk_running() is False


def test_aucun_passage_en_cours(monkeypatch):
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(False, 2))
    assert pl.allchk_running() is False


def test_date_absente_invalide_ou_future_ne_bloque_pas(monkeypatch):
    monkeypatch.setattr(pl, 'allchk_status', lambda: {'running': True})
    assert pl.allchk_running() is False
    monkeypatch.setattr(pl, 'allchk_status',
                        lambda: {'running': True, 'quand': 'pas-une-date'})
    assert pl.allchk_running() is False
    monkeypatch.setattr(pl, 'allchk_status',
                        lambda: {'running': True, 'quand': _quand(-120)})
    assert pl.allchk_running() is False


def test_statut_public_ne_ment_pas_a_l_ui(monkeypatch):
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 29 * 24 * 60))
    public = pl.allchk_status_public()
    assert public['running'] is False
    assert public['perime'] is True
    assert 'interrompue' in public['message']


def test_relance_autorisee_apres_verrou_orphelin(monkeypatch):
    monkeypatch.setattr(pl, '_ALLCHK_RUNNING', False)
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 29 * 24 * 60))
    monkeypatch.setattr(pl, '_allchk_save', lambda payload: None)
    monkeypatch.setattr(threading, 'Thread', _ThreadInerte)
    assert pl.check_all_dossiers_async().get('launched') is True


def test_relance_refusee_si_passage_recent(monkeypatch):
    monkeypatch.setattr(pl, '_ALLCHK_RUNNING', False)
    monkeypatch.setattr(pl, 'allchk_status', lambda: _etat(True, 1))
    assert pl.check_all_dossiers_async() == {'launched': False, 'running': True}
