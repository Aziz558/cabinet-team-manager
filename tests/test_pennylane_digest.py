"""Recapitulatif mail Pennylane : frequence configurable, un mail groupe par creneau."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def test_normaliser_heures_digest():
    from app.integrations.pennylane import normaliser_heures_digest
    assert normaliser_heures_digest('17, 9,13') == '9,13,17'
    assert normaliser_heures_digest('9,9') == '9'
    assert normaliser_heures_digest('') == ''
    assert normaliser_heures_digest(None) == ''
    for invalide in ('25', '-1', 'abc', '9;13'):
        with pytest.raises(ValueError):
            normaliser_heures_digest(invalide)


def test_api_settings_refuse_heure_invalide(admin_client):
    r = admin_client.post('/api/settings', json={'cle': 'PENNYLANE_DIGEST_HEURES', 'valeur': '9,25'})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_envoi_digest_groupe_puis_plus_rien(flask_app, seed, monkeypatch):
    """Un mail par destinataire pour tous les items en attente, puis rien au creneau suivant."""
    from app import db
    from app.models import AppSetting, PennylaneItem
    from app.integrations import brevo
    from app.integrations.pennylane import envoyer_digest_pennylane

    appels = []
    monkeypatch.setattr(brevo, 'send_pennylane_digest_email_brevo',
                        lambda user, par_dossier, creneau: appels.append((user.email, creneau)) or True)

    with flask_app.app_context():
        heure = datetime.now(ZoneInfo('Europe/Paris')).hour
        db.session.add(AppSetting(cle='PENNYLANE_DIGEST_HEURES', valeur=str((heure + 1) % 24), service='mail'))
        items = [PennylaneItem(dossier_id=seed['d1'], item_type='facture_vente', item_id=f'dig-{i}',
                               reference=f'F-{i}', montant=10.0, statut='a_traiter', digest_envoye=False)
                 for i in range(3)]
        db.session.add_all(items)
        db.session.commit()
        ids = [it.id for it in items]
        try:
            # creneau different de l'heure courante : aucun envoi
            assert envoyer_digest_pennylane()['skipped'] is True
            assert appels == []

            # creneau force : un seul mail a membre (collaborateur du dossier d1)
            res = envoyer_digest_pennylane(force=True)
            assert res['sent'] == 1
            assert appels == [('membre@test.local', f"{datetime.now(ZoneInfo('Europe/Paris')).hour:02d}h")]
            assert all(PennylaneItem.query.get(i).digest_envoye for i in ids)

            # rien de nouveau : pas de second mail
            assert envoyer_digest_pennylane(force=True)['items'] == 0
            assert len(appels) == 1
        finally:
            PennylaneItem.query.filter(PennylaneItem.id.in_(ids)).delete(synchronize_session=False)
            AppSetting.query.filter_by(cle='PENNYLANE_DIGEST_HEURES').delete()
            db.session.commit()
