"""ASTRO : statut en lot (STATUT_LOT), statut par titre, routage action prioritaire.

Régressions des bugs constatés en prod :
- « passe toutes les tâches de X en retard à terminé » répondait la liste des
  retards (routeur intention) au lieu de proposer le lot ;
- une seule tâche était terminée au lieu de tout le lot ;
- « rendre cette tâche terminée <titre> » ne trouvait pas la tâche.
"""
from datetime import date, timedelta

import pytest


@pytest.fixture()
def sans_email(monkeypatch):
    monkeypatch.setattr('app.integrations.brevo.send_email_via_brevo_api', lambda **kw: True)


@pytest.fixture()
def sans_llm(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('LLM appelé alors que la voie rapide devait répondre')
    monkeypatch.setattr('app.integrations.llm_provider.get_llm_manager', interdit)


@pytest.fixture()
def retard(flask_app, seed):
    """3 tâches en retard pour Marie + 1 future pour Marie + 1 en retard pour Paul."""
    from app import db
    from app.models import User, Tache
    with flask_app.app_context():
        membre = User.query.filter_by(email='membre@test.local').first()
        autre = User.query.filter_by(email='autre@test.local').first()
        admin = User.query.filter_by(email='admin@test.local').first()
        hier = date.today() - timedelta(days=1)
        ids = []
        for i in range(3):
            t = Tache(titre=f'Relance client retard {i}', assigne_a=membre.id,
                      cree_par=admin.id, date_echeance=hier - timedelta(days=i),
                      statut='a_faire')
            db.session.add(t)
            db.session.flush()
            ids.append(t.id)
        future = Tache(titre='Tâche future Marie', assigne_a=membre.id, cree_par=admin.id,
                       date_echeance=date.today() + timedelta(days=5))
        paul = Tache(titre='Tâche retard Paul', assigne_a=autre.id, cree_par=admin.id,
                     date_echeance=hier)
        db.session.add_all([future, paul])
        db.session.commit()
        return {'marie': ids, 'future': future.id, 'paul': paul.id}


# ---------------------------------------------------------------------------
# Validation du lot
# ---------------------------------------------------------------------------

def test_lot_validation_unitaire(flask_app, seed):
    from app.assistant_service import valider_statut_lot
    from app.models import User
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        membre = User.query.filter_by(email='membre@test.local').first()
        assert valider_statut_lot(None, admin)[0] is None
        assert valider_statut_lot({'tache_ids': []}, admin)[0] is None
        assert valider_statut_lot({'tache_ids': ['abc']}, admin)[0] is None
        assert valider_statut_lot({'tache_ids': list(range(1, 52))}, admin)[0] is None
        assert valider_statut_lot({'tache_ids': [seed['t1']], 'statut': 'archive'}, admin)[0] is None
        # hors périmètre : t2 appartient à Paul, pas à Marie
        assert valider_statut_lot({'tache_ids': [seed['t2']], 'statut': 'terminee'}, membre)[0] is None
        # doublons dédupliqués
        p, err = valider_statut_lot({'tache_ids': [seed['t1'], seed['t1']], 'statut': 'terminee'}, admin)
        assert err is None and p['nb'] == 1 and p['tache_ids'] == [seed['t1']]


def test_lot_extraction_llm(flask_app, seed):
    from app.assistant_service import extraire_proposition_statut_lot
    from app.models import User
    with flask_app.app_context():
        membre = User.query.filter_by(email='membre@test.local').first()
        raw = ('Je propose le lot.\n<STATUT_LOT>{"tache_ids": [%d], "statut": "terminee"}</STATUT_LOT>'
               % seed['t1'])
        texte, p = extraire_proposition_statut_lot(raw, membre)
        assert '<STATUT_LOT>' not in texte and p['nb'] == 1
        texte2, p2 = extraire_proposition_statut_lot('<STATUT_LOT>{pas json}</STATUT_LOT>', membre)
        assert p2 is None
        raw3 = '<STATUT_LOT>{"tache_ids": [%d], "statut": "terminee"}</STATUT_LOT>' % seed['t2']
        texte3, p3 = extraire_proposition_statut_lot(raw3, membre)
        assert p3 is None and 'non proposé' in texte3


# ---------------------------------------------------------------------------
# Endpoint /api/assistant/statut_lot
# ---------------------------------------------------------------------------

def test_lot_refuse_sans_connexion(flask_app, seed):
    r = flask_app.test_client().post('/api/assistant/statut_lot',
                                     json={'tache_ids': [seed['t1']], 'statut': 'terminee'})
    assert r.status_code in (302, 401)


def test_lot_endpoint_refus(flask_app, seed, membre_client):
    r = membre_client.post('/api/assistant/statut_lot',
                           json={'tache_ids': [seed['t2']], 'statut': 'terminee'})
    assert r.status_code == 403
    r = membre_client.post('/api/assistant/statut_lot',
                           json={'tache_ids': [seed['t1'], seed['t2']], 'statut': 'terminee'})
    assert r.status_code == 403
    r = membre_client.post('/api/assistant/statut_lot',
                           json={'tache_ids': list(range(1, 52)), 'statut': 'terminee'})
    assert r.status_code == 403
    r = membre_client.post('/api/assistant/statut_lot',
                           json={'tache_ids': [seed['t1']], 'statut': 'archive'})
    assert r.status_code == 403


def test_lot_endpoint_applique_et_notifie(flask_app, seed, retard, membre_client, sans_email):
    from app.models import Tache, Notification
    r = membre_client.post('/api/assistant/statut_lot',
                           json={'tache_ids': retard['marie'], 'statut': 'terminee'})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    assert '3 tâche(s)' in r.get_json()['message']
    with flask_app.app_context():
        for tid in retard['marie']:
            t = Tache.query.get(tid)
            assert t.statut == 'terminee' and t.date_completion is not None
        n = (Notification.query.filter_by(tache_id=retard['marie'][0])
             .order_by(Notification.id.desc()).first())
        assert n is not None and 'ASTRO' in n.message


def test_lot_coche_la_checklist(flask_app, seed, membre_client, sans_email):
    from app import db
    from app.models import User, Dossier, Tache, ChecklistEntry
    with flask_app.app_context():
        membre = User.query.filter_by(email='membre@test.local').first()
        d = Dossier(numero_dossier='D-ASTRO-LOT', intitule='Astro Lot', regime_tva='ca3')
        db.session.add(d)
        db.session.flush()
        t1 = Tache(titre='Dépôt TVA mensuel', dossier_id=d.id, assigne_a=membre.id,
                   date_echeance=date(2026, 9, 24))
        t2 = Tache(titre='Autre tâche du lot', dossier_id=d.id, assigne_a=membre.id,
                   date_echeance=date(2026, 9, 25))
        db.session.add_all([t1, t2])
        db.session.commit()
        ids, did = [t1.id, t2.id], d.id
    r = membre_client.post('/api/assistant/statut_lot', json={'tache_ids': ids, 'statut': 'terminee'})
    assert r.status_code == 200
    with flask_app.app_context():
        e = ChecklistEntry.query.filter_by(dossier_id=did, taxe='tva_mensuel',
                                           annee=2026, mois=8, kind='depot').first()
        assert e is not None and e.declare is True and e.source == 'tache'


# ---------------------------------------------------------------------------
# Voie rapide : lot par nom, par « mes tâches », sans nom
# ---------------------------------------------------------------------------

def test_fast_path_lot_nom(flask_app, seed, retard, admin_client, sans_llm):
    # Message réel de l'utilisateur : ne doit PAS répondre la liste des retards
    r = admin_client.post('/api/assistant/message',
                          json={'message': 'je veut que tu passe tous les taches de '
                                           'Marie Dupont en retard a terminé'})
    j = r.get_json()
    assert r.status_code == 200 and j['ok'] is True
    assert j['source'] == 'regles'
    assert j['statut_lot'] is not None and j['statut_lot']['nb'] == 3
    assert set(j['statut_lot']['tache_ids']) == set(retard['marie'])
    assert j['statut_lot']['statut'] == 'terminee'


def test_fast_path_mes_taches(flask_app, seed, retard, membre_client, sans_llm):
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'passe toutes mes tâches en retard à terminer'})
    j = r.get_json()
    assert j['source'] == 'regles' and j['statut_lot'] is not None
    # les tâches du test précédent (même fixture) peuvent encore être ouvertes :
    # on vérifie l'inclusion + l'exclusion de celles de Paul, pas le compte exact
    ids = set(j['statut_lot']['tache_ids'])
    assert set(retard['marie']) <= ids
    assert retard['paul'] not in ids and retard['future'] not in ids


def test_fast_path_sans_nom(flask_app, seed, retard, membre_client, sans_llm):
    # « à terminer » ne doit pas être pris pour un nom de membre
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'passe toutes les tâches à terminer'})
    j = r.get_json()
    assert j['source'] == 'regles' and j['statut_lot'] is not None
    assert set(retard['marie']) <= set(j['statut_lot']['tache_ids'])
    assert retard['future'] in j['statut_lot']['tache_ids']


def test_fast_path_membre_inconnu(flask_app, seed, admin_client, sans_llm):
    r = admin_client.post('/api/assistant/message',
                          json={'message': 'toutes les tâches de Jean Inconnu en retard à terminer'})
    j = r.get_json()
    assert j['source'] == 'regles' and 'Je ne trouve pas' in j['reponse']
    assert j.get('statut_lot') is None


def test_fast_path_lot_trop_grand(flask_app, seed, admin_client, sans_llm):
    from app import db
    from app.models import User, Tache
    with flask_app.app_context():
        autre = User.query.filter_by(email='autre@test.local').first()
        hier = date.today() - timedelta(days=1)
        db.session.add_all([Tache(titre=f'Lot Paul {i}', assigne_a=autre.id,
                                  date_echeance=hier, statut='a_faire') for i in range(51)])
        db.session.commit()
    r = admin_client.post('/api/assistant/message',
                          json={'message': 'toutes les tâches de Paul Martin en retard à terminer'})
    j = r.get_json()
    assert 'Plus de 50' in j['reponse'] and j.get('statut_lot') is None


# ---------------------------------------------------------------------------
# Statut par titre (forme féminine « terminée » incluse)
# ---------------------------------------------------------------------------

def test_statut_par_titre_unique(flask_app, seed, membre_client, sans_llm):
    from app import db
    from app.models import User, Tache
    with flask_app.app_context():
        membre = User.query.filter_by(email='membre@test.local').first()
        t = Tache(titre='Révision bilan Zorblutec', assigne_a=membre.id,
                  date_echeance=date.today())
        db.session.add(t)
        db.session.commit()
        tid = t.id
    r = membre_client.post('/api/assistant/message',
                           json={'message': 'rends cette tâche terminée Révision bilan Zorblutec'})
    j = r.get_json()
    assert j['source'] == 'regles'
    assert j['statut'] is not None and j['statut']['tache_id'] == tid
    assert j['statut']['statut'] == 'terminee'


def test_statut_par_titre_plusieurs(flask_app, seed, admin_client, sans_llm):
    from app import db
    from app.models import Tache
    with flask_app.app_context():
        db.session.add_all([Tache(titre='Rapprochement bancaire Kraken',
                                  date_echeance=date.today()) for _ in range(2)])
        db.session.commit()
    r = admin_client.post('/api/assistant/message',
                          json={'message': 'termine la tâche Rapprochement bancaire Kraken'})
    j = r.get_json()
    assert 'Plusieurs tâches' in j['reponse'] and j.get('statut') is None


# ---------------------------------------------------------------------------
# Gardes du routeur d'intention
# ---------------------------------------------------------------------------

def test_intention_garde_verbe_action(flask_app):
    from app.assistant_service import detecter_intention
    assert detecter_intention('passe toutes les tâches de marie en retard à terminé') is None
    assert detecter_intention('quelles sont les tâches en retard') == 'retard'


def test_intention_garde_texte_long(flask_app):
    from app.assistant_service import detecter_intention
    # texte collé (instructions personnalisées) contenant « onboarding »
    assert detecter_intention('onboarding ' + 'contexte du cabinet ' * 20) is None
    assert detecter_intention('où en sont les nouveaux dossiers') == 'onboarding'