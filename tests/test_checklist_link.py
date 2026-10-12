"""Liaison Checklist <-> taches deadline : origine du statut « terminée ».

- manuel     : tâche terminée à la main (changement de statut dans l'application)
- auto_checklist : case cochée dans la Checklist -> tâche terminée automatiquement
- auto_pennylane : déclaration déclarée dans Pennylane (synchro) -> tâche terminée automatiquement
"""
from datetime import date


def _dossier_et_tache(flask_app, numero, titre='Dépôt TVA mensuel'):
    """Crée un dossier + une tâche deadline (échéance 24/09/2026 -> période août 2026)."""
    from app import db
    from app.models import Dossier, Tache
    with flask_app.app_context():
        d = Dossier(numero_dossier=numero, intitule='Liaison ' + numero, regime_tva='ca3')
        db.session.add(d)
        db.session.flush()
        t = Tache(titre=titre, dossier_id=d.id, date_echeance=date(2026, 9, 24))
        db.session.add(t)
        db.session.commit()
        return d.id, t.id


def test_synchro_pennylane_source_automatique(flask_app):
    from app import db
    from app.models import Tache
    from app.checklist_link import appliquer_case_a_taches
    did, tid = _dossier_et_tache(flask_app, 'D-LINK-001')
    with flask_app.app_context():
        n = appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', True,
                                    source='auto_pennylane')
        db.session.commit()
        t = Tache.query.get(tid)
        assert n == 1
        assert t.statut == 'terminee'
        assert t.statut_source == 'auto_pennylane'


def test_case_checklist_source_par_defaut_puis_remise_a_faire(flask_app):
    from app import db
    from app.models import Tache
    from app.checklist_link import appliquer_case_a_taches
    did, tid = _dossier_et_tache(flask_app, 'D-LINK-002')
    with flask_app.app_context():
        appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', True)
        db.session.commit()
        t = Tache.query.get(tid)
        assert t.statut == 'terminee'
        assert t.statut_source == 'auto_checklist'
        # case décochée -> la tâche repasse à faire et la source est effacée
        appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', False)
        db.session.commit()
        t = Tache.query.get(tid)
        assert t.statut == 'a_faire'
        assert t.statut_source is None


def test_terminer_a_la_main_source_manuelle(flask_app, admin_client):
    from app.models import Tache
    _, tid = _dossier_et_tache(flask_app, 'D-LINK-003', titre='Déclaration IS')
    r = admin_client.post(f'/changer_statut_tache/{tid}', data={'statut': 'terminee'})
    assert r.status_code == 302
    with flask_app.app_context():
        t = Tache.query.get(tid)
        assert t.statut == 'terminee'
        assert t.statut_source == 'manuel'


def test_liste_taches_affiche_le_badge_source(flask_app, admin_client):
    _, tid = _dossier_et_tache(flask_app, 'D-LINK-004')
    r = admin_client.get('/taches')
    assert r.status_code == 200


def test_notification_responsable_sur_changement_auto(flask_app, seed, monkeypatch):
    from app import db
    from app.models import Tache, Notification, User
    from app.checklist_link import appliquer_case_a_taches
    monkeypatch.setattr('app.integrations.brevo.send_email_via_brevo_api', lambda **kw: True)
    did, tid = _dossier_et_tache(flask_app, 'D-LINK-005')
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        Tache.query.get(tid).cree_par = admin.id
        db.session.commit()
        appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', True, source='auto_pennylane')
        db.session.commit()
        notifs = Notification.query.filter_by(user_id=admin.id, tache_id=tid).all()
        assert len(notifs) == 1
        assert 'synchro Pennylane' in notifs[0].message
        assert notifs[0].type_notification == 'systeme'
        # case decochee -> nouvelle notification « remise a faire »
        appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', False)
        db.session.commit()
        notifs = Notification.query.filter_by(user_id=admin.id, tache_id=tid).order_by(Notification.id).all()
        assert len(notifs) == 2
        assert 'a faire' in notifs[-1].message


def test_pas_de_notification_si_le_responsable_est_l_acteur(flask_app, seed, monkeypatch):
    from app import db
    from app.models import Tache, Notification, User
    from app.checklist_link import appliquer_case_a_taches
    monkeypatch.setattr('app.integrations.brevo.send_email_via_brevo_api', lambda **kw: True)
    did, tid = _dossier_et_tache(flask_app, 'D-LINK-006')
    with flask_app.app_context():
        admin = User.query.filter_by(email='admin@test.local').first()
        Tache.query.get(tid).cree_par = admin.id
        db.session.commit()
        appliquer_case_a_taches(did, 'tva_mensuel', 2026, 8, 'depot', True, acteur=admin)
        db.session.commit()
        assert Tache.query.get(tid).statut == 'terminee'
        assert Notification.query.filter_by(tache_id=tid).count() == 0
