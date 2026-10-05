"""API /api/recherche-globale : garde-fous, resultats, perimetre par role."""


def test_non_auth_redirige_vers_login(client):
    r = client.get('/api/recherche-globale?q=test')
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_requete_courte_retourne_vide(admin_client):
    j = admin_client.get('/api/recherche-globale?q=a').get_json()
    assert j == {'ok': True, 'resultats': []}


def test_admin_trouve_dossiers_et_taches(admin_client, seed):
    j = admin_client.get('/api/recherche-globale?q=Alpha').get_json()
    assert j['ok']
    assert any(r['groupe'] == 'Dossiers' and 'D-TEST-001' in r['label'] for r in j['resultats'])
    assert any(r['lien'].startswith('/dossiers?q=') for r in j['resultats'])

    j = admin_client.get('/api/recherche-globale?q=TVA').get_json()
    assert any(r['groupe'] == 'Tâches' and r['lien'].startswith('/vue_tache/')
               for r in j['resultats'])

    j = admin_client.get('/api/recherche-globale?q=Dupont').get_json()
    assert any(r['groupe'] == 'Équipe' and r['lien'].startswith('/fiche_membre/')
               for r in j['resultats'])


def test_perimetre_membre(membre_client, seed):
    # Dossier d'un AUTRE membre -> exclu
    j = membre_client.get('/api/recherche-globale?q=Beta').get_json()
    assert all('D-TEST-002' not in r['label'] for r in j['resultats'])

    # Ses propres dossiers/taches -> inclus
    j = membre_client.get('/api/recherche-globale?q=Alpha').get_json()
    assert any('D-TEST-001' in r['label'] for r in j['resultats'])
    j = membre_client.get('/api/recherche-globale?q=TVA').get_json()
    assert any(r['groupe'] == 'Tâches' for r in j['resultats'])

    # Un membre ne cherche pas les autres membres de l'equipe
    j = membre_client.get('/api/recherche-globale?q=Martin').get_json()
    assert not any(r['groupe'] == 'Équipe' for r in j['resultats'])
