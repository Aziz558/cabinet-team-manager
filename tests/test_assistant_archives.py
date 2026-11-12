"""Archives ASTRO : capture, export local (secours), dédup, purge, /remembre,
recherche d'historique, signature JWT du compte de service Drive.

Le backend Drive complet nécessite un vrai compte de service ; on teste ici la
signature RS256 (sans réseau) et tout le flux d'export via le backend local.
"""
import base64
import json
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
_SA = {'client_email': 'astro@proj.iam.gserviceaccount.com', 'private_key': _PEM,
       'token_uri': 'https://oauth2.googleapis.com/token'}


@pytest.fixture()
def sans_llm(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé alors que la voie rapide devait répondre')
    monkeypatch.setattr('app.integrations.llm_provider.get_llm_manager', interdit)


@pytest.fixture()
def local_archive(monkeypatch, tmp_path):
    """Force le backend local (secours) dans un dossier temporaire."""
    monkeypatch.setattr('app.assistant_archive._setting',
                        lambda cle, default='': str(tmp_path) if cle == 'ARCHIVE_LOCAL_DIR' else default)
    return tmp_path


def _membre(flask_app):
    from app.models import User
    return User.query.filter_by(email='membre@test.local').first()


# ---------------------------------------------------------------------------
# Capture + /remembre
# ---------------------------------------------------------------------------

def test_capture_conversation(flask_app, seed, admin_client, sans_llm):
    from app.models import AssistantMessage
    r = admin_client.post('/api/assistant/message', json={'message': 'quel est mon résumé du jour ?'})
    assert r.get_json()['ok'] is True
    with flask_app.app_context():
        assert any('résumé du jour' in m.contenu
                   for m in AssistantMessage.query.filter_by(role='user').all())
        assert AssistantMessage.query.filter_by(role='assistant').count() >= 1


def test_remembre_garde_en_base(flask_app, seed, membre_client, sans_llm):
    from app.models import AssistantMemoire
    r = membre_client.post('/api/assistant/message',
                           json={'message': '/remembre le client Dupont préfère les appels le matin'})
    j = r.get_json()
    assert j['source'] == 'regles' and 'Gardé en Orbit' in j['reponse']
    with flask_app.app_context():
        m = AssistantMemoire.query.filter(AssistantMemoire.contenu.like('%Dupont préfère%')).first()
        assert m is not None and m.portee == 'personnel'


def test_remembre_cabinet(flask_app, seed, admin_client, sans_llm):
    from app.models import AssistantMemoire
    r = admin_client.post('/api/assistant/message',
                          json={'message': '/remembre les mandats SEPA partent le 5 pour le cabinet'})
    assert r.get_json()['source'] == 'regles'
    with flask_app.app_context():
        m = AssistantMemoire.query.filter(AssistantMemoire.contenu.like('%mandats SEPA partent le 5%')).first()
        assert m is not None and m.portee == 'cabinet'


# ---------------------------------------------------------------------------
# Export local : personnel uniquement, dédup, purge
# ---------------------------------------------------------------------------

def test_export_local_personnel_uniquement(flask_app, seed, local_archive):
    from app import db
    from app.models import User, AssistantMemoire, AssistantMessage
    from app.assistant_archive import exporter_archives
    with flask_app.app_context():
        admin_id = User.query.filter_by(email='admin@test.local').first().id
        membre = _membre(flask_app)
        db.session.add(AssistantMemoire(portee='cabinet', contenu='Le cabinet utilise Pennylane.',
                                        source='manuel', cree_par_id=admin_id))
        db.session.add(AssistantMemoire(portee='personnel', user_id=membre.id,
                                        contenu='Marie préfère les résumés courts.', source='manuel'))
        db.session.add(AssistantMessage(user_id=membre.id, role='user', contenu='Bonjour ASTRO'))
        db.session.commit()
        rapport = exporter_archives()
        assert rapport['ok'] is True and rapport['backend'] == 'local'
    dossier = local_archive / 'personnel' / 'marie-dupont'
    data = json.loads((dossier / 'memoire.json').read_text(encoding='utf-8'))
    assert any('résumés courts' in e['contenu'] for e in data['entrees'])
    assert (dossier / 'memoire.md').exists()
    assert (dossier / 'conversations').is_dir()
    # la mémoire cabinet ne doit JAMAIS partir dans le secours local
    assert not (local_archive / 'memoire').exists()
    assert all(e['portee'] == 'personnel' for e in data['entrees'])


def test_export_deduplique(flask_app, seed, local_archive):
    from app import db
    from app.models import AssistantMemoire
    from app.assistant_archive import exporter_archives
    with flask_app.app_context():
        membre = _membre(flask_app)
        db.session.add(AssistantMemoire(portee='personnel', user_id=membre.id,
                                        contenu='Info unique à dédupliquer.', source='manuel'))
        db.session.commit()
        r1 = exporter_archives()
        assert len(r1['nouvelles']) >= 1
        r2 = exporter_archives()
        assert r2['nouvelles'] == []


def test_export_purge_le_tampon_de_la_veille(flask_app, seed, local_archive):
    from app import db
    from app.models import AssistantMessage
    from app.assistant_archive import exporter_archives
    with flask_app.app_context():
        membre = _membre(flask_app)
        hier = datetime.utcnow() - timedelta(days=1)
        db.session.add(AssistantMessage(user_id=membre.id, role='user',
                                        contenu='vieux message à purger', date_creation=hier))
        db.session.add(AssistantMessage(user_id=membre.id, role='user',
                                        contenu='message du jour à garder', date_creation=datetime.utcnow()))
        db.session.commit()
        rapport = exporter_archives()
        assert rapport['purges'] >= 1
        restants = [m.contenu for m in AssistantMessage.query.filter_by(user_id=membre.id).all()]
        assert 'vieux message à purger' not in restants
        assert 'message du jour à garder' in restants


def test_secours_local_si_drive_ko(flask_app, seed, monkeypatch, tmp_path):
    from app import assistant_archive as aa

    def fake_setting(cle, default=''):
        return {'GOOGLE_DRIVE_SA_JSON': json.dumps(_SA), 'GOOGLE_DRIVE_FOLDER_ID': 'dossier',
                'ARCHIVE_LOCAL_DIR': str(tmp_path)}.get(cle, default)

    def ping_ko(self):
        raise RuntimeError('403 interdit')

    monkeypatch.setattr(aa, '_setting', fake_setting)
    monkeypatch.setattr(aa.DriveBackend, 'ping', ping_ko)
    backend, mode = aa.choisir_backend()
    assert backend.kind == 'local' and mode == 'local_secours'


def test_repli_local_si_ecriture_drive_ko(flask_app, seed, monkeypatch, tmp_path):
    """Drive joignable (ping OK) mais sans quota d'écriture (compte de service sur
    Drive personnel) : l'export doit replier sur le secours local, pas échouer."""
    from app import db
    from app import assistant_archive as aa
    from app.models import AssistantMemoire, AssistantMessage

    def fake_setting(cle, default=''):
        return {'GOOGLE_DRIVE_SA_JSON': json.dumps(_SA), 'GOOGLE_DRIVE_FOLDER_ID': 'dossier',
                'ARCHIVE_LOCAL_DIR': str(tmp_path)}.get(cle, default)

    def write_ko(self, path, content):
        raise RuntimeError('403 Service Accounts do not have storage quota')

    monkeypatch.setattr(aa, '_setting', fake_setting)
    monkeypatch.setattr(aa.DriveBackend, 'ping', lambda self: {})
    monkeypatch.setattr(aa.DriveBackend, 'read', lambda self, path: None)
    monkeypatch.setattr(aa.DriveBackend, 'write', write_ko)
    with flask_app.app_context():
        membre = _membre(flask_app)
        db.session.add(AssistantMemoire(portee='personnel', user_id=membre.id,
                                        contenu='Info de repli local.', source='manuel'))
        db.session.add(AssistantMessage(user_id=membre.id, role='user', contenu='message de repli'))
        db.session.commit()
        rapport = aa.exporter_archives()
        assert rapport['ok'] is True
        assert rapport['backend'] == 'local' and rapport['mode'] == 'local_secours'
        assert rapport.get('alerte')
    dossier = tmp_path / 'personnel' / 'marie-dupont'
    data = json.loads((dossier / 'memoire.json').read_text(encoding='utf-8'))
    assert any('repli local' in e['contenu'] for e in data['entrees'])
    assert (dossier / 'conversations').is_dir()
    assert not (tmp_path / 'memoire').exists()


# ---------------------------------------------------------------------------
# Recherche d'historique
# ---------------------------------------------------------------------------

def test_recherche_historique_base(flask_app, seed, local_archive):
    from app import db
    from app.models import AssistantMessage
    from app.assistant_archive import rechercher_historique
    with flask_app.app_context():
        membre = _membre(flask_app)
        db.session.add(AssistantMessage(user_id=membre.id, role='user',
                                        contenu='Le client Dupont veut un bilan.'))
        db.session.commit()
        res = rechercher_historique(membre, 'Dupont')
        assert any('Dupont' in e['texte'] and e['source'] == 'Orbit' for e in res)


def test_recherche_historique_archive(flask_app, seed, local_archive):
    from app import db
    from app.models import AssistantMessage
    from app.assistant_archive import exporter_archives, rechercher_historique
    with flask_app.app_context():
        membre = _membre(flask_app)
        hier = datetime.utcnow() - timedelta(days=1)
        db.session.add(AssistantMessage(user_id=membre.id, role='user',
                                        contenu='Le client Dupont archive confidentielle.', date_creation=hier))
        db.session.commit()
        exporter_archives()  # archive puis purge le message de la veille
        res = rechercher_historique(membre, 'Dupont archive')
        assert any(e['source'] == 'archive' for e in res)


def test_detecter_recherche_historique(flask_app, seed, membre_client, sans_llm, local_archive):
    r = membre_client.post('/api/assistant/message',
                           json={'message': "cherche dans l'historique : sujet introuvable xyz"})
    j = r.get_json()
    assert j['source'] == 'regles' and 'Rien trouvé' in j['reponse']


# ---------------------------------------------------------------------------
# Endpoints + signature JWT Drive
# ---------------------------------------------------------------------------

def test_export_endpoint_admin(flask_app, seed, admin_client, local_archive):
    r = admin_client.post('/api/assistant/archives/exporter')
    assert r.status_code == 200 and r.get_json()['ok'] is True


def test_export_endpoint_membre_refuse(flask_app, seed, membre_client, local_archive):
    r = membre_client.post('/api/assistant/archives/exporter')
    assert r.status_code == 403


def test_tester_connexion_sans_cle(flask_app, seed, admin_client):
    r = admin_client.post('/api/assistant/archives/tester')
    assert r.get_json()['ok'] is False


def test_drive_jwt_signe_rs256(flask_app, monkeypatch):
    from app import assistant_archive as aa
    capture = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {'access_token': 'tok123', 'expires_in': 3600}

    def fake_post(url, data=None, timeout=None, **kw):
        capture['url'] = url
        capture['data'] = data
        return Resp()

    monkeypatch.setattr(aa.requests, 'post', fake_post)
    backend = aa.DriveBackend(json.dumps(_SA), 'dossier123')
    assert backend._access_token() == 'tok123'
    assert capture['url'] == 'https://oauth2.googleapis.com/token'
    assertion = capture['data']['assertion']
    h, c, s = assertion.split('.')

    def unb64(x):
        return base64.urlsafe_b64decode(x + '=' * (-len(x) % 4))

    # la signature doit être vérifiable avec la clé publique (RS256 valide)
    _KEY.public_key().verify(unb64(s), (h + '.' + c).encode('ascii'),
                             padding.PKCS1v15(), hashes.SHA256())
    claim = json.loads(unb64(c))
    assert claim['iss'] == _SA['client_email']
    assert claim['aud'] == 'https://oauth2.googleapis.com/token'
    assert claim['scope'] == 'https://www.googleapis.com/auth/drive'