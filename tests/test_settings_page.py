"""Page Réglages : secrets jamais renvoyés au navigateur, champs vides conservés."""
from app.models import AppSetting

SECRET_TEST = 'sk-or-v1-TESTSECRET-0123456789'


def _valeur_base(flask_app, cle):
    with flask_app.app_context():
        s = AppSetting.query.filter_by(cle=cle).first()
        return s.valeur if s else None


def test_settings_admin_page_200_sans_secret(admin_client, flask_app):
    admin_client.post('/api/settings', json={
        'cle': 'OPENROUTER_API_KEY', 'valeur': SECRET_TEST,
        'service': 'llm', 'type_valeur': 'password', 'masque': True,
    })
    r = admin_client.get('/settings')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert SECRET_TEST not in html
    assert 'clé enregistrée' in html
    assert 'Enregistrée : laisser vide pour conserver' in html


def test_settings_page_sans_elements_supprimes(admin_client):
    html = admin_client.get('/settings').get_data(as_text=True)
    for retire in ('mailboxForm', 'inboundForm', 'testPennyLaneBtn', 'settingsTable',
                   'OPENROUTER_PROVIDER', 'MAILBOX_PASSWORD', 'BREVO_API_KEY" value='):
        assert retire not in html, retire


def test_champ_secret_vide_conserve_la_valeur(admin_client, flask_app):
    admin_client.post('/api/settings', json={
        'cle': 'OPENROUTER_API_KEY', 'valeur': SECRET_TEST,
        'service': 'llm', 'type_valeur': 'password', 'masque': True,
    })
    r = admin_client.post('/api/settings', json={
        'cle': 'OPENROUTER_API_KEY', 'valeur': '',
        'service': 'llm', 'type_valeur': 'password', 'masque': True,
    })
    assert r.get_json()['ok'] is True
    assert _valeur_base(flask_app, 'OPENROUTER_API_KEY') == SECRET_TEST


def test_secret_masque_meme_si_masque_faux(admin_client, flask_app):
    admin_client.post('/api/settings', json={
        'cle': 'BREVO_API_KEY', 'valeur': 'xkeysib-test', 'service': 'mail',
        'type_valeur': 'password', 'masque': False,
    })
    with flask_app.app_context():
        s = AppSetting.query.filter_by(cle='BREVO_API_KEY').first()
        assert s.masque is True


def test_membre_redirige_hors_reglages(membre_client):
    r = membre_client.get('/settings', follow_redirects=False)
    assert r.status_code == 302
