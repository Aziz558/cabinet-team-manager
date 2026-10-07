"""Tests de la page dashboard Pennylane : rendu, stats, filtres, endpoints."""
MARKERS = [
    'plStatsRow',          # cartes de stats
    'pl-grid-scroll',      # box fixe avec défilement
    'plSearch', 'plFilterCollab', 'plFilterRegime', 'plSort',  # toolbar
    'pl-badge-todo', 'pl-badge-late',
    'plToast', 'plGridSkeleton',
    'plSyncDossier', 'plMarquerTraite',
    'plNoResults', 'plRefreshData', 'pl-dossier-status',
]


def test_pennylane_page_dashboard(admin_client):
    """La page /pennylane rend le dashboard complet (stats + toolbar + grille)."""
    r = admin_client.get('/pennylane')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    missing = [m for m in MARKERS if m not in html]
    assert not missing, f'Marqueurs manquants dans le template : {missing}'


def test_pennylane_data_json(admin_client):
    """GET /pennylane/data renvoie stats réelles + compteurs par dossier."""
    r = admin_client.get('/pennylane/data')
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert set(j['stats']) == {'connectes', 'total', 'a_traiter', 'en_retard', 'sync_ok'}
    assert j['stats']['total'] >= 1
    assert isinstance(j['dossiers'], list)
    assert all({'id', 'a_traiter', 'en_retard'} <= set(d) for d in j['dossiers'])


def test_pennylane_marquer_traite(admin_client, seed):
    """POST marquer_traite : 0 item -> ok; scoping admin autorisé."""
    r = admin_client.post(f"/pennylane/dossier/{seed['d1']}/marquer_traite")
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True
    assert 'traité(s)' in j['message']


def test_pennylane_marquer_traite_membre_refuse(membre_client, seed):
    """Un membre sans droits sur le dossier (d2 = collab 'autre') est refusé (403)."""
    r = membre_client.post(f"/pennylane/dossier/{seed['d2']}/marquer_traite")
    assert r.status_code == 403
