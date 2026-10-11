"""Checklist : filtres collaborateur / mois / statut (grille TVA).

Les filtres sont appliqués côté navigateur ; le serveur fournit la liste
des collaborateurs (data.collabs) et les attributs data-* nécessaires.
"""

GRILLE_URL = '/checklist?etape=grille&type=fiscale&freq=recurrentes&taxe=tva_mensuel&annee=2026'


def test_grille_charge_avec_filtres(admin_client, seed):
    """La grille TVA mensuelle se rend (200) avec la barre de filtres."""
    r = admin_client.get(GRILLE_URL)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'id="clFilters"' in html
    assert 'data-f="mois"' in html
    assert 'data-f="statut"' in html
    assert 'data-f="moi"' in html


def test_collaborateurs_listes_dans_filtre(admin_client, seed):
    """Chaque collaborateur présent dans la grille a son chip."""
    html = admin_client.get(GRILLE_URL).get_data(as_text=True)
    assert 'data-f="collab"' in html
    assert 'Dupont' in html


def test_mois_et_statut_dans_les_cellules(admin_client, seed):
    """En-têtes de mois et lignes portent les attributs que le JS filtre."""
    html = admin_client.get(GRILLE_URL).get_data(as_text=True)
    assert 'data-mois="12"' in html
    assert 'data-collab=' in html


def test_filtre_statut_invalide_ignore(admin_client, seed):
    """Une valeur de statut inconnue dans l'URL n'arrête pas le rendu."""
    r = admin_client.get(GRILLE_URL + '&statut=n_importe_quoi&mois=3,99')
    assert r.status_code == 200
