"""Rayon « Modèles » : listing Drive (lecture seule), repli local, page accessible
à tous les rôles, et lien de téléchargement du repli local."""
import pytest


@pytest.fixture(autouse=True)
def _vide_cache():
    from app import assistant_archive
    assistant_archive._CACHE_MODELES.update(t=0.0, data=None)
    yield
    assistant_archive._CACHE_MODELES.update(t=0.0, data=None)


def _settings(etranger=None):
    """Faux _setting : valeurs par défaut, éventuellement surchargées."""
    def _s(cle, default=''):
        if etranger and cle in etranger:
            return etranger[cle]
        return default
    return _s


def test_repli_local_liste_les_fichiers(monkeypatch, tmp_path):
    from app import assistant_archive
    dossier = tmp_path / 'modeles'
    dossier.mkdir()
    (dossier / 'Lettre de mission.pdf').write_bytes(b'%PDF-1.4 test')
    monkeypatch.setattr(assistant_archive, '_setting',
                        _settings({'ARCHIVE_LOCAL_DIR': str(tmp_path)}))

    res = assistant_archive.lister_modeles(force=True)

    assert res['ok'] is True
    assert res['source'] == 'local'
    assert [f['nom'] for f in res['fichiers']] == ['Lettre de mission.pdf']
    f = res['fichiers'][0]
    assert f['taille'] > 0
    assert f['lien'].startswith('/assistant/modeles/fichier/')
    assert '%20' in f['lien']          # nom encodé dans l'URL


def test_sans_configuration_message_drive(monkeypatch):
    from app import assistant_archive
    monkeypatch.setattr(assistant_archive, '_setting', _settings())
    res = assistant_archive.lister_modeles(force=True)
    assert res['ok'] is False
    assert 'google drive' in res['message'].lower()
    assert res['dossier_url'].endswith(assistant_archive.MODELES_FOLDER_DEFAUT)


def test_listing_drive_avec_rayons(monkeypatch):
    from app import assistant_archive

    class FauxDrive:
        def __init__(self, sa, dossier):
            self.root = dossier

        def ping(self):
            return {'id': self.root, 'name': 'Modèles'}

        def list_children(self, folder_id=None):
            if folder_id is None:
                return [
                    {'id': 'd1', 'name': 'Plaquettes', 'mimeType': assistant_archive._FOLDER_MIME},
                    {'id': 'f0', 'name': 'Sommaire.pdf', 'mimeType': 'application/pdf',
                     'size': '2048', 'modifiedTime': '2026-11-01T10:00:00Z',
                     'webViewLink': 'https://drive.google.com/file/d/f0/view'},
                ]
            return [
                {'id': 'f1', 'name': 'LDM.docx', 'size': '4096',
                 'mimeType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 'modifiedTime': '2026-10-30T09:00:00Z',
                 'webViewLink': 'https://drive.google.com/file/d/f1/view'},
                {'id': 'f2', 'name': 'Bon de commande',
                 'mimeType': 'application/vnd.google-apps.document'},
            ]

    monkeypatch.setattr(assistant_archive, 'DriveBackend', FauxDrive)
    monkeypatch.setattr(assistant_archive, '_setting',
                        _settings({'GOOGLE_DRIVE_SA_JSON': '{"client_email": "x", "private_key": "y"}'}))

    res = assistant_archive.lister_modeles(force=True)

    assert res['ok'] is True and res['source'] == 'drive'
    assert res['rayons'] == [{'id': 'd1', 'nom': 'Plaquettes', 'nb': 2}]
    par_nom = {f['nom']: f for f in res['fichiers']}
    assert par_nom['LDM.docx']['rayon'] == 'Plaquettes'
    assert par_nom['LDM.docx']['type'] == 'Word'
    assert par_nom['LDM.docx']['taille'] == 4096
    assert par_nom['Sommaire.pdf']['rayon'] == ''
    assert par_nom['Bon de commande']['lien'] == 'https://drive.google.com/open?id=f2'


def test_dossier_non_partage_message_explicite(monkeypatch):
    """Dossier non partagé avec le compte de service : 404 au ping -> message clair,
    pas « dossier vide » (Drive renvoie [] en silence dans ce cas)."""
    from app import assistant_archive

    class DriveSansAcces:
        def __init__(self, sa, dossier):
            pass

        def ping(self):
            raise RuntimeError('404 File not found')

    monkeypatch.setattr(assistant_archive, 'DriveBackend', DriveSansAcces)
    monkeypatch.setattr(assistant_archive, '_setting',
                        _settings({'GOOGLE_DRIVE_SA_JSON': '{"client_email": "x", "private_key": "y"}'}))

    res = assistant_archive.lister_modeles(force=True)

    assert res['ok'] is False
    assert 'partagé' in res['message']
    assert res['dossier_url'].endswith(assistant_archive.MODELES_FOLDER_DEFAUT)


def test_page_modeles_accessible_membre(membre_client, monkeypatch):
    from app import assistant_archive
    monkeypatch.setattr(assistant_archive, 'lister_modeles', lambda force=False: {
        'ok': True, 'source': 'drive', 'dossier_id': 'abc',
        'dossier_url': 'https://drive.google.com/drive/folders/abc',
        'rayons': [{'id': 'r1', 'nom': 'Plaquettes', 'nb': 1}],
        'fichiers': [{'id': 'f1', 'nom': 'Modele LDM.pdf', 'mime': 'application/pdf',
                      'type': 'PDF', 'icone': 'bi-file-earmark-pdf', 'taille': 2048,
                      'modifie': '2026-11-01', 'rayon': 'Plaquettes',
                      'lien': 'https://drive.google.com/file/d/f1/view'}],
        'message': '',
    })
    r = membre_client.get('/assistant/modeles')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'Modele LDM.pdf' in html
    assert 'Plaquettes' in html
    assert 'https://drive.google.com/drive/folders/abc' in html
    assert 'Ouvrir le dossier Drive' in html
    assert html.count('\ufffd') == 0


def test_page_modeles_anonyme_redirige(client):
    r = client.get('/assistant/modeles', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_dossier_modeles_par_defaut():
    from app import assistant_archive
    assert assistant_archive.MODELES_FOLDER_DEFAUT == '1bGe9XEIce2OL-cRALon5gZS9MnXszXPf'
