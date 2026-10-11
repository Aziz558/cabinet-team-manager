"""Accès du compte membre : Checklist, Avancement et Pennylane (lecture seule).

Périmètre : un membre ne voit que ses propres dossiers (collaborateur_id = lui-même)
et ses propres tâches. Aucune écriture Pennylane (statut, synchro, marquer traité).
"""


def test_membre_menu_contient_avancement_checklist_pennylane(membre_client):
    html = membre_client.get('/dashboard').get_data(as_text=True)
    assert 'href="/suivi_avancement"' in html
    assert 'href="/checklist"' in html
    assert 'href="/pennylane"' in html


def test_membre_acces_checklist(membre_client):
    r = membre_client.get('/checklist')
    assert r.status_code == 200


def test_membre_acces_avancement(membre_client):
    r = membre_client.get('/suivi_avancement')
    assert r.status_code == 200


def test_membre_acces_pennylane_page_lecture_seule(membre_client):
    """La page Pennylane s'ouvre pour un membre, sans actions d'écriture ni admin."""
    r = membre_client.get('/pennylane')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="plCheckNewBtn"' not in html      # bouton « Vérifier les nouveaux documents » (rendu)
    assert 'id="plTvaBar"' not in html           # synchro TVA ciblée (rendu)


def test_membre_pennylane_data_limite_a_ses_dossiers(membre_client, seed):
    j = membre_client.get('/pennylane/data').get_json()
    assert j['ok'] is True
    ids = {d['id'] for d in j['dossiers']}
    assert seed['d1'] in ids          # dossier dont il est collaborateur
    assert seed['d2'] not in ids      # dossier d'un autre membre exclu


def test_membre_pennylane_dossier_autre_refuse(membre_client, seed):
    """Un membre ne peut pas ouvrir le détail Pennylane d'un dossier qui ne lui est pas attribué."""
    r = membre_client.get(f"/pennylane/dossier/{seed['d2']}")
    assert r.status_code == 302


def test_membre_pennylane_dossier_propre_lecture_seule(membre_client, seed):
    r = membre_client.get(f"/pennylane/dossier/{seed['d1']}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="btn-sync-tva"' not in html
    assert 'id="btn-check-pl"' not in html
    assert 'id="bulk-bar"' not in html


def test_membre_ecritures_pennylane_refusees(membre_client, seed):
    """Aucune écriture Pennylane pour le membre, même sur son propre dossier."""
    assert membre_client.post(f"/pennylane/dossier/{seed['d1']}/marquer_traite").status_code == 403
    assert membre_client.post('/pennylane/items/statut_bulk',
                              json={'ids': [1], 'statut': 'traite'}).status_code == 403
    assert membre_client.post('/pennylane/item/1/statut',
                              json={'statut': 'traite'}).status_code == 403
