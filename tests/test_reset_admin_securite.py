"""/reset-admin : la porte de secours ne doit pas être une porte ouverte.

Contexte (2026-11-07) : la clé de réinitialisation était ÉCRITE EN DUR
('cabinet-jmh-reset-2024') dans app/routes_admin.py, et le dépôt GitHub du
projet est PUBLIC. N'importe qui pouvait donc réinitialiser le mot de passe du
compte administrateur de la production :

    POST /reset-admin  reset_key=cabinet-jmh-reset-2024  new_password=...

La route est désormais conditionnée à la variable d'environnement
ADMIN_RESET_KEY (absente = 404), avec comparaison à temps constant, longueur
minimale du mot de passe et limitation du nombre de tentatives.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLE = 'une-cle-de-secours-longue-et-unique-2026'
ADMIN_EMAIL = 'admin@cabinet-jmh.com'


@pytest.fixture()
def sans_cle(monkeypatch):
    monkeypatch.delenv('ADMIN_RESET_KEY', raising=False)
    return None


@pytest.fixture()
def avec_cle(monkeypatch):
    monkeypatch.setenv('ADMIN_RESET_KEY', CLE)
    from app import routes_admin
    routes_admin._RESET_TENTATIVES.clear()
    return CLE


def _creer_admin(flask_app):
    """Le compte ciblé par la route n'existe pas dans la base de test."""
    from app import db
    from app.models import User
    with flask_app.app_context():
        u = User.query.filter_by(email=ADMIN_EMAIL).first()
        if not u:
            u = User(email=ADMIN_EMAIL, nom='Jmh', prenom='Admin', role='admin', actif=True)
            u.set_password('MotDePasseInitial!')
            db.session.add(u)
            db.session.commit()
        return u.id


def _supprimer_admin(flask_app):
    """Suppression en SQL brut : la suppression ORM declenche des cascades
    vers des tables qui ne sont pas creees par la base de test."""
    from app import db
    with flask_app.app_context():
        db.session.execute(db.text('delete from users where email = :e'), {'e': ADMIN_EMAIL})
        db.session.commit()
        db.session.remove()


def test_route_inexistante_sans_variable_d_environnement(client, sans_cle):
    """Sans ADMIN_RESET_KEY la route n'existe pas : 404, même en GET."""
    assert client.get('/reset-admin').status_code == 404
    assert client.post('/reset-admin', data={'reset_key': 'peu importe',
                                             'new_password': 'MotDePasseSolide1!'}).status_code == 404


def test_ancienne_cle_en_dur_ne_fonctionne_plus(client, sans_cle):
    """La clé historique du dépôt public ne doit plus rien ouvrir."""
    r = client.post('/reset-admin', data={'reset_key': 'cabinet-jmh-reset-2024',
                                          'new_password': 'MotDePasseSolide1!'})
    assert r.status_code == 404


def test_cle_invalide_refusee(client, flask_app, avec_cle):
    _creer_admin(flask_app)
    r = client.post('/reset-admin', data={'reset_key': 'mauvaise-cle',
                                          'new_password': 'MotDePasseSolide1!'})
    assert r.status_code == 200
    from app.models import User
    with flask_app.app_context():
        u = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert u.check_password('MotDePasseInitial!'), 'le mot de passe ne doit PAS avoir changé'
    _supprimer_admin(flask_app)


def test_mot_de_passe_trop_court_refuse(client, flask_app, avec_cle):
    _creer_admin(flask_app)
    client.post('/reset-admin', data={'reset_key': CLE, 'new_password': 'court'})
    from app.models import User
    with flask_app.app_context():
        u = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert u.check_password('MotDePasseInitial!')
    _supprimer_admin(flask_app)


def test_cle_valide_change_le_mot_de_passe(client, flask_app, avec_cle):
    _creer_admin(flask_app)
    r = client.post('/reset-admin', data={'reset_key': CLE,
                                          'new_password': 'NouveauMotDePasse2026!'},
                    follow_redirects=False)
    assert r.status_code == 302, 'succès attendu : redirection vers /login'
    from app.models import User
    with flask_app.app_context():
        u = User.query.filter_by(email=ADMIN_EMAIL).first()
        assert u.check_password('NouveauMotDePasse2026!')
    _supprimer_admin(flask_app)


def test_trop_de_tentatives_est_bloque(client, avec_cle):
    """Balayage de clés : au-delà de 5 essais, la route renvoie 429."""
    codes = [client.post('/reset-admin', data={'reset_key': f'essai-{i}',
                                              'new_password': 'MotDePasseSolide1!'}).status_code
             for i in range(7)]
    assert 429 in codes, f'aucune limitation des tentatives : {codes}'
    assert codes.count(200) <= 5


def test_aucune_cle_en_dur_dans_le_code():
    """Garde-fou : plus jamais de clé de réinitialisation littérale."""
    source = (ROOT / 'app' / 'routes_admin.py').read_text(encoding='utf-8')
    assert 'ADMIN_RESET_KEY' in source, 'la clé doit venir de l’environnement'
    for interdit in ('cabinet-jmh-reset-2024',):
        assert interdit not in source
    # Aucune comparaison directe avec une chaîne littérale de type clé.
    assert not re.search(r"reset_key\s*==\s*['\"]", source)
