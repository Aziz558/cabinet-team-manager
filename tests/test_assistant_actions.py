"""ASTRO : actions in-app confirmées — statut, suppression dossier, étape onboarding.

Même contrat que les tâches/rappels : proposition (règles ou LLM) -> confirmation
client -> revalidation serveur (périmètre + rôle) -> application avec les mêmes
effets que les routes manuelles (checklist, notifications, mails d'étape).
"""
import json
from datetime import date

import pytest


@pytest.fixture()
def sans_email(monkeypatch):
    monkeypatch.setattr('app.integrations.brevo.send_email_via_brevo_api', lambda **kw: True)


@pytest.fixture()
def sans_llm(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé alors que la voie rapide devait répondre')
    monkeypatch.setattr('app.integrations.llm_provider.get_llm_manager', interdit)


# ---------------------------------------------------------------------------
# Changement de statut
# ---------------------------------------------------------------------------

def test_statut_refuse_sans_connexion(flask_app, seed):
    r = flask_app.test_client().post('/api/assistant/changer_statut',
                                     json={'tache_id': seed['t1'], 'statut': 'terminee'})
    assert r.status_code in (302, 401)


def test_statut_invalide_refuse(flask_app, seed, admin_client):
    r = admin_client.post('/api/assistant/changer_statut',
                          json={'tache_id': seed['t1'], 'statut': 'archive'})
    assert r.status_code == 403
    assert r.get_json()['ok'] is False


def test_statut_hors_perimetre_refuse(flask_app, seed, membre_client):
    # t2 est assignée à « autre », pas au membre connecté
    r = membre_client.post('/api/assistant/changer_statut',
                           json={'tache_id': seed['t2'], 'statut': 'terminee'})
    assert r.status_code == 403


def test_changement_statut_confirme_applique(flask_app, seed, membre_client, sans_email):
    from app.models import Tache, Notification
    r = membre_client.post('/api/assistant/changer_statut',
                           json={'tache_id': seed['t1'], 'statut': 'terminee'})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    with flask_app.app_context():
        t = Tache.query.get(seed['t1'])
        assert t.statut == 'terminee'
        assert t.statut_source == 'manuel'
        assert t.date_completion is not None
        # le créateur (admin) est notifié, avec la mention ASTRO
        n = Notification.query.filter_by(tache_id=t.id).order_by(Notification.id.desc()).first()
        assert n is not None and 'ASTRO' in n.message


def test_statut_terminee_coche_la_checklist(flask_app, admin_client, sans_email):
    from app import db
    from app.models import Dossier, Tache, ChecklistEntry
    with flask_app.app_context():
        d = Dossier(numero_dossier='D-ASTRO-TVA', intitule='Astro TVA', regime_tva='ca3')
        db.session.add(d)
        db.session.flush()
        t = Tache(titre='Dépôt TVA mensuel', dossier_id=d.id, date_echeance=date(2026, 9, 24))
        db.session.add(t)
        db.session.commit()
        tid, did = t.id, d.id
    r = admin_client.post('/api/assistant/changer_statut',
                          json={'tache_id': tid, 'statut': 'terminee'})
    assert r.status_code == 200
    with flask_app.app_context():
        e = ChecklistEntry.query.filter_by(dossier_id=did, taxe='tva_mensuel',
                                           annee=2026, mois=8, kind='depot').first()
        assert e is not None and e.declare is True
        assert e.source == 'tache'


def test_extraction_statut_llm(flask_app, seed):
    from app.assistant_service import extraire_proposition_statut
    from app.models import User
    with flask_app.app_context():
        user = User.query.filter_by(email='membre@test.local').first()
        raw = ('Je propose le changement.\n<STATUT>{"tache_id": %d, "statut": "en_cours"}</STATUT>'
               % seed['t1'])
        texte, proposition = extraire_proposition_statut(raw, user)
        assert '<STATUT>' not in texte
        assert proposition['statut'] == 'en_cours'
        assert proposition['ancien_statut'] in ('a_faire', 'en_cours', 'terminee')
        # hors périmètre -> pas de proposition, explication dans le texte
        raw2 = '<STATUT>{"tache_id": %d, "statut": "terminee"}</STATUT>' % seed['t2']
        texte2, proposition2 = extraire_proposition_statut(raw2, user)
        assert proposition2 is None
        assert 'non proposé' in texte2


# ---------------------------------------------------------------------------
# Suppression de dossier
# ---------------------------------------------------------------------------

def test_suppression_refusee_pour_membre(flask_app, seed, membre_client):
    r = membre_client.post('/api/assistant/supprimer_dossier',
                           json={'dossier_id': seed['d1']})
    assert r.status_code == 403
    with flask_app.app_context():
        from app.models import Dossier
        assert Dossier.query.get(seed['d1']) is not None


def test_suppression_admin_cascade(flask_app, admin_client, sans_email):
    from app import db
    from app.models import Dossier, Tache, Notification, ChecklistEntry
    with flask_app.app_context():
        d = Dossier(numero_dossier='D-ASTRO-DEL', intitule='A supprimer', regime_tva='ca3')
        db.session.add(d)
        db.session.flush()
        t = Tache(titre='Tâche liée', dossier_id=d.id, date_echeance=date.today())
        db.session.add(t)
        db.session.flush()
        db.session.add(Notification(user_id=1, tache_id=t.id, message='x', type_notification='systeme'))
        db.session.add(ChecklistEntry(dossier_id=d.id, taxe='tva_mensuel', annee=2026,
                                      mois=8, kind='depot', declare=True))
        db.session.commit()
        did, tid = d.id, t.id
    r = admin_client.post('/api/assistant/supprimer_dossier', json={'dossier_id': did})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    assert 'D-ASTRO-DEL' in r.get_json()['message']
    with flask_app.app_context():
        assert Dossier.query.get(did) is None
        assert Tache.query.get(tid) is None
        assert Notification.query.filter_by(tache_id=tid).count() == 0
        assert ChecklistEntry.query.filter_by(dossier_id=did).count() == 0


def test_suppression_dossier_inexistant_refusee(flask_app, admin_client):
    r = admin_client.post('/api/assistant/supprimer_dossier', json={'dossier_id': 999999})
    assert r.status_code == 403


def test_extraction_suppression_llm(flask_app, seed, admin_client):
    from app.assistant_service import extraire_proposition_suppression
    from app.models import User
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        membre = User.query.filter_by(email='membre@test.local').first()
        raw = ('Attention, action irréversible.\n<SUPPR_DOSSIER>{"dossier_id": %d}</SUPPR_DOSSIER>'
               % seed['d2'])
        texte, proposition = extraire_proposition_suppression(raw, admin)
        assert '<SUPPR_DOSSIER>' not in texte
        assert proposition['numero'] == 'D-TEST-002'
        # un membre ne reçoit jamais de proposition de suppression
        texte_m, proposition_m = extraire_proposition_suppression(raw, membre)
        assert proposition_m is None
        assert 'non proposée' in texte_m


# ---------------------------------------------------------------------------
# Étape du suivi nouveaux dossiers (onboarding)
# ---------------------------------------------------------------------------

@pytest.fixture()
def onb(flask_app, seed):
    from app import db
    from app.models import OnboardingDossier
    with flask_app.app_context():
        d = OnboardingDossier(nom_dossier='ASTRO ONB', nom_client='Client Test',
                              mail='client@test.local', type_dossier='creation')
        db.session.add(d)
        db.session.commit()
        return d.id


def test_onb_etape_refusee_pour_membre(flask_app, membre_client, onb):
    r = membre_client.post('/api/assistant/onb_etape',
                           json={'dossier_id': onb, 'code': 'rib', 'fait': True})
    assert r.status_code == 403


def test_onb_etape_code_inconnu_refuse(flask_app, admin_client, onb):
    r = admin_client.post('/api/assistant/onb_etape',
                          json={'dossier_id': onb, 'code': 'inexistant', 'fait': True})
    assert r.status_code == 403


def test_onb_etape_non_applicable_refusee(flask_app, admin_client):
    from app import db
    from app.models import OnboardingDossier
    with flask_app.app_context():
        d = OnboardingDossier(nom_dossier='ASTRO REPRISE', type_dossier='reprise')
        db.session.add(d)
        db.session.commit()
        did = d.id
    # kbis = création uniquement, pas applicable à une reprise
    r = admin_client.post('/api/assistant/onb_etape',
                          json={'dossier_id': did, 'code': 'kbis', 'fait': True})
    assert r.status_code == 403


def test_onb_etape_appliquee_puis_annulee(flask_app, admin_client, onb, sans_email):
    from app.models import OnboardingDossier, User
    r = admin_client.post('/api/assistant/onb_etape',
                          json={'dossier_id': onb, 'code': 'ldm_editee', 'fait': True})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    assert 'marquée faite' in r.get_json()['message']
    with flask_app.app_context():
        d = OnboardingDossier.query.get(onb)
        s = d.etape('ldm_editee')
        assert s.est_fait and s.date_fait == date.today()
        admin = User.query.filter_by(email='admin@test.local').first()
        assert s.fait_par_id == admin.id
    r2 = admin_client.post('/api/assistant/onb_etape',
                           json={'dossier_id': onb, 'code': 'ldm_editee', 'fait': False})
    assert r2.status_code == 200
    assert 'remise à faire' in r2.get_json()['message']
    with flask_app.app_context():
        s = OnboardingDossier.query.get(onb).etape('ldm_editee')
        assert not s.est_fait and s.date_fait is None


def test_onb_etape_declenche_le_mail_configure(flask_app, admin_client, onb, monkeypatch):
    from app import db
    from app.models import OnboardingActionMail, OnboardingMail
    envois = []
    monkeypatch.setattr('app.integrations.brevo.send_email_via_brevo_api',
                        lambda **kw: envois.append(kw) or True)
    with flask_app.app_context():
        db.session.add(OnboardingActionMail(etape_code='rib', actif=True,
                                            sujet='RIB reçu {{dossier}}',
                                            corps='Merci pour le RIB.',
                                            destinataires=json.dumps(['client'])))
        db.session.commit()
    r = admin_client.post('/api/assistant/onb_etape',
                          json={'dossier_id': onb, 'code': 'rib', 'fait': True})
    assert r.status_code == 200
    assert len(envois) == 1
    assert envois[0]['to_email'] == 'client@test.local'
    assert 'envoyé' in r.get_json()['message']
    with flask_app.app_context():
        assert OnboardingMail.query.filter_by(type_mail='rib', statut='envoye').count() == 1


def test_extraction_onb_etape_llm(flask_app, onb):
    from app.assistant_service import extraire_proposition_onb_etape
    from app.models import User
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        raw = ('Je propose de marquer l\u2019étape.\n<ONB_ETAPE>{"dossier_id": %d, '
               '"code": "ldm_signee", "fait": true}</ONB_ETAPE>' % onb)
        texte, proposition = extraire_proposition_onb_etape(raw, admin)
        assert '<ONB_ETAPE>' not in texte
        assert proposition['code'] == 'ldm_signee'
        assert proposition['label'] == 'Lettre de mission signée'
        assert proposition['fait'] is True


# ---------------------------------------------------------------------------
# Voie rapide sans LLM (detecter_action) + intention onboarding
# ---------------------------------------------------------------------------

def test_message_termine_tache_sans_llm(flask_app, seed, membre_client, sans_llm):
    r = membre_client.post('/api/assistant/message',
                           json={'message': f"termine la tâche #{seed['t1']}"})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True and j['source'] == 'regles'
    assert j['statut']['tache_id'] == seed['t1']
    assert j['statut']['statut'] == 'terminee'


def test_message_passe_en_cours_sans_llm(flask_app, seed, membre_client, sans_llm):
    r = membre_client.post('/api/assistant/message',
                           json={'message': f"passe la tâche {seed['t1']} en cours"})
    j = r.get_json()
    assert j['ok'] is True
    assert j['statut']['statut'] == 'en_cours'


def test_message_suppression_dossier_sans_llm(flask_app, seed, admin_client, sans_llm):
    r = admin_client.post('/api/assistant/message',
                          json={'message': 'supprime le dossier D-TEST-002'})
    j = r.get_json()
    assert j['ok'] is True and j['source'] == 'regles'
    assert j['suppression']['numero'] == 'D-TEST-002'
    assert j['suppression']['dossier_id'] == seed['d2']


def test_message_suppression_refusee_au_membre(flask_app, seed, membre_client, sans_llm):
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'supprime le dossier D-TEST-001'})
    j = r.get_json()
    assert j['ok'] is True
    assert j.get('suppression') is None
    assert 'réservée aux managers' in j['reponse']


def test_message_statut_ambigue_pas_de_proposition(flask_app, seed):
    from app.assistant_service import detecter_action
    from app.models import User
    with flask_app.app_context():
        user = User.query.filter_by(email='membre@test.local').first()
        assert detecter_action(f"change la tâche #{seed['t1']}", user) is None


def test_intention_onboarding_reponse_sans_llm(flask_app, onb, membre_client, sans_llm):
    from app.assistant_service import detecter_intention
    assert detecter_intention('Où en sont les nouveaux dossiers ?') == 'onboarding'
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'Où en sont les nouveaux dossiers ?'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True and j['source'] == 'regles'
    assert 'ASTRO ONB' in j['reponse']