"""Mémoire longue d'ASTRO : cabinet partagée + personnelle, apprentissage des discussions.

- validation/déduplication/plafond des souvenirs
- extraction des blocs <MEMOIRE> des réponses LLM
- injection dans le prompt système (cabinet pour tous, personnel pour le propriétaire)
- voie rapide « souviens-toi que… » et lecture « que sais-tu de moi ? »
- page de gestion : droits cabinet (auteur/admin/manager) vs personnel (propriétaire)
"""
import json

import pytest


@pytest.fixture()
def sans_llm(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé alors que la voie rapide devait répondre')
    monkeypatch.setattr('app.integrations.llm_provider.get_llm_manager', interdit)


@pytest.fixture()
def memoires(flask_app, seed):
    from app import db
    from app.models import AssistantMemoire, User
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        membre = User.query.filter_by(email='membre@test.local').first()
        cab = AssistantMemoire(portee='cabinet', contenu='Le cabinet utilise Pennylane pour tous les dossiers.',
                               categorie='process', source='manuel', cree_par_id=admin.id)
        perso = AssistantMemoire(portee='personnel', user_id=membre.id,
                                 contenu='Marie préfère les résumés courts le matin.',
                                 categorie='preference', source='conversation', cree_par_id=membre.id)
        db.session.add_all([cab, perso])
        db.session.commit()
        return {'cabinet': cab.id, 'perso': perso.id}


# ---------------------------------------------------------------------------
# Validation / stockage
# ---------------------------------------------------------------------------

def test_enregistrement_valide_et_deduplique(flask_app, seed):
    from app.assistant_service import enregistrer_memoire
    from app.models import User, AssistantMemoire
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        m, info = enregistrer_memoire(admin, 'cabinet', 'La réunion équipe est le lundi à 9h.', 'fait')
        assert info == 'cree' and m.portee == 'cabinet' and m.user_id is None
        # même contenu, accents/casse différents -> déjà présent, pas de doublon
        m2, info2 = enregistrer_memoire(admin, 'cabinet', 'LA RÉUNION ÉQUIPE est le lundi à 9h.')
        assert info2 == 'deja_presente'
        assert AssistantMemoire.query.filter_by(portee='cabinet').count() >= 1


def test_enregistrement_refuse_invalide(flask_app, seed):
    from app.assistant_service import enregistrer_memoire
    from app.models import User
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        assert enregistrer_memoire(admin, 'galactique', 'Contenu valide')[0] is None
        assert enregistrer_memoire(admin, 'cabinet', 'ab')[0] is None
        assert enregistrer_memoire(admin, 'cabinet', 'x' * 501)[0] is None
        m, err = enregistrer_memoire(admin, 'cabinet', 'Ma clé est nvapi_abcdefgh12345678')
        assert m is None and 'jamais' in err


def test_plafond_memoire(flask_app, seed, monkeypatch):
    from app import assistant_service as svc
    from app.models import User
    monkeypatch.setattr(svc, 'MEMOIRE_MAX_PERSONNEL', 1)
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        assert svc.enregistrer_memoire(admin, 'personnel', 'Premier souvenir unique.')[1] == 'cree'
        m, err = svc.enregistrer_memoire(admin, 'personnel', 'Deuxième souvenir unique.')
        assert m is None and 'pleine' in err


# ---------------------------------------------------------------------------
# Extraction LLM + injection prompt
# ---------------------------------------------------------------------------

def test_extraire_memoires_stocke_et_nettoie(flask_app, seed):
    from app.assistant_service import extraire_memoires
    from app.models import User, AssistantMemoire
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        raw = ("C'est noté.\n"
               '<MEMOIRE>{"portee": "cabinet", "contenu": "Les relances clients se font le mardi.", "categorie": "process"}</MEMOIRE>\n'
               '<MEMOIRE>{"portee": "personnel", "contenu": "Aziz aime les réponses directes.", "categorie": "preference"}</MEMOIRE>')
        texte, notes = extraire_memoires(raw, admin)
        assert '<MEMOIRE>' not in texte
        assert len(notes) == 2 and all(n['info'] == 'cree' for n in notes)
        assert AssistantMemoire.query.filter_by(contenu='Les relances clients se font le mardi.').count() == 1
        # JSON invalide : ignoré silencieusement
        texte2, notes2 = extraire_memoires('<MEMOIRE>{pas du json}</MEMOIRE>', admin)
        assert notes2 == []


def test_prompt_contient_les_deux_memoires(flask_app, seed, memoires):
    from app.assistant_service import construire_prompt
    from app.models import User
    with flask_app.app_context():
        membre = User.query.filter_by(email='membre@test.local').first()
        autre = User.query.filter_by(email='autre@test.local').first()
        prompt_membre = construire_prompt(membre)
        assert 'MÉMOIRE DU CABINET' in prompt_membre
        assert 'Le cabinet utilise Pennylane' in prompt_membre
        assert 'MÉMOIRE PERSONNELLE DE Marie' in prompt_membre
        assert 'Marie préfère les résumés courts' in prompt_membre
        # la mémoire personnelle de Marie ne fuite PAS chez Paul
        prompt_autre = construire_prompt(autre)
        assert 'Le cabinet utilise Pennylane' in prompt_autre
        assert 'Marie préfère les résumés courts' not in prompt_autre


# ---------------------------------------------------------------------------
# Voie rapide sans LLM
# ---------------------------------------------------------------------------

def test_souviens_toi_personnel(flask_app, seed, membre_client, sans_llm):
    from app.models import AssistantMemoire
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'Souviens-toi que je traite les dossiers SCI en priorité.'})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] is True and j['source'] == 'regles'
    assert 'personnelle' in j['reponse']
    with flask_app.app_context():
        m = AssistantMemoire.query.filter_by(contenu='je traite les dossiers SCI en priorité.').first()
        assert m is not None and m.portee == 'personnel'
        assert m.source == 'regles'


def test_souviens_toi_cabinet(flask_app, seed, membre_client, sans_llm):
    from app.models import AssistantMemoire
    r = membre_client.post('/api/assistant/message',
                           json={'message': "Note que les mandats SEPA partent le 5 du mois pour le cabinet"})
    j = r.get_json()
    assert j['ok'] is True
    assert 'cabinet' in j['reponse']
    with flask_app.app_context():
        m = AssistantMemoire.query.filter_by(portee='cabinet',
                                             contenu='les mandats SEPA partent le 5 du mois').first()
        assert m is not None


def test_lecture_memoire_sans_llm(flask_app, seed, memoires, membre_client, sans_llm):
    from app.assistant_service import detecter_intention
    assert detecter_intention('Que sais-tu de moi ?') == 'memoire'
    r = membre_client.post('/api/assistant/message', json={'message': 'Que sais-tu de moi ?'})
    j = r.get_json()
    assert j['ok'] is True and j['source'] == 'regles'
    assert 'Marie préfère les résumés courts' in j['reponse']
    assert 'Le cabinet utilise Pennylane' in j['reponse']


# ---------------------------------------------------------------------------
# Page de gestion + droits
# ---------------------------------------------------------------------------

def test_page_memoire_affiche_les_deux_portees(flask_app, seed, memoires, membre_client):
    r = membre_client.get('/assistant/memoire')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Mémoire du cabinet' in html
    assert 'Le cabinet utilise Pennylane' in html
    assert 'Marie préfère les résumés courts' in html


def test_page_memoire_isolation_personnelle(flask_app, seed, memoires, admin_client):
    r = admin_client.get('/assistant/memoire')
    html = r.get_data(as_text=True)
    assert 'Le cabinet utilise Pennylane' in html
    assert 'Marie préfère les résumés courts' not in html


def test_ajout_manuel_via_page(flask_app, seed, membre_client):
    from app.models import AssistantMemoire
    r = membre_client.post('/assistant/memoire/ajouter',
                           data={'portee': 'cabinet', 'contenu': 'Les KBIS se commandent sur le site du greffe.'},
                           follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        m = AssistantMemoire.query.filter_by(contenu='Les KBIS se commandent sur le site du greffe.').first()
        assert m is not None and m.source == 'manuel' and m.portee == 'cabinet'


def test_membre_ne_peut_modifier_memoire_cabinet_d_autrui(flask_app, seed, memoires, membre_client):
    from app.models import AssistantMemoire
    # l'entrée cabinet a été créée par l'admin : le membre ne peut pas la modifier
    r = membre_client.post(f"/assistant/memoire/{memoires['cabinet']}/modifier",
                           data={'contenu': 'Contenu détourné par un membre.'}, follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        assert 'détourné' not in AssistantMemoire.query.get(memoires['cabinet']).contenu


def test_admin_peut_modifier_et_effacer_memoire_cabinet(flask_app, seed, memoires, admin_client):
    from app.models import AssistantMemoire
    r = admin_client.post(f"/assistant/memoire/{memoires['cabinet']}/modifier",
                          data={'contenu': 'Le cabinet utilise Pennylane et Dext.'}, follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        assert AssistantMemoire.query.get(memoires['cabinet']).contenu == 'Le cabinet utilise Pennylane et Dext.'
    r2 = admin_client.post(f"/assistant/memoire/{memoires['cabinet']}/supprimer", follow_redirects=True)
    assert r2.status_code == 200
    with flask_app.app_context():
        assert AssistantMemoire.query.get(memoires['cabinet']) is None


def test_proprietaire_gere_sa_memoire_personnelle(flask_app, seed, memoires, membre_client):
    from app.models import AssistantMemoire
    r = membre_client.post(f"/assistant/memoire/{memoires['perso']}/modifier",
                           data={'contenu': 'Marie préfère les résumés le soir.'}, follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        assert AssistantMemoire.query.get(memoires['perso']).contenu == 'Marie préfère les résumés le soir.'
    r2 = membre_client.post(f"/assistant/memoire/{memoires['perso']}/supprimer", follow_redirects=True)
    assert r2.status_code == 200
    with flask_app.app_context():
        assert AssistantMemoire.query.get(memoires['perso']) is None


def test_admin_ne_peut_pas_lire_memoire_personnelle_d_autrui(flask_app, seed, memoires, admin_client):
    # même un admin ne modifie pas la mémoire personnelle d'un membre
    r = admin_client.post(f"/assistant/memoire/{memoires['perso']}/supprimer", follow_redirects=True)
    assert r.status_code == 200
    with flask_app.app_context():
        from app.models import AssistantMemoire
        assert AssistantMemoire.query.get(memoires['perso']) is not None