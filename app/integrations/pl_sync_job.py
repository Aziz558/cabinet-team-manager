# -*- coding: utf-8 -*-
"""Synchro TVA Pennylane en tâche de fond.

`sync_checklist_tva()` interroge les 53 dossiers reliés les uns après les
autres (cadence ~0,7 s + ré-essais sur 418). Sur Render, le proxy coupe la
requête bien avant la fin : le navigateur reçoit un corps VIDE et `r.json()`
lève « Unexpected end of JSON input », sans qu'aucun bilan ne soit affiché.

On ne peut pas raccourcir ce travail, donc on le sort de la requête :
le POST démarre le job et répond en 202 immédiatement, l'UI interroge
`/checklist/pl_sync_status` jusqu'à obtenir le résultat.

L'état est persisté dans AppSetting (comme PENNYLANE_NEWDOCS_CHECK) pour
survivre à un redéploiement. Un « running » orphelin — process tué avant son
`finally` — est écarté après STALE_MINUTES ; un heartbeat rafraîchit la trace
pendant le passage pour qu'une synchro légitimement longue ne soit jamais
considérée comme périmée.
"""

import json as _json
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KEY = 'PENNYLANE_TVA_SYNC_JOB'
STALE_MINUTES = 30

_lock = threading.Lock()
_running = False


def _horodatage() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _save(payload: dict):
    """Upsert de l'état du job (AppSetting partagé entre workers)."""
    from app import db
    from app.models import AppSetting
    try:
        data = dict(payload)
        data['quand'] = _horodatage()
        s = AppSetting.query.filter_by(cle=KEY).first()
        v = _json.dumps(data, ensure_ascii=False, default=str)
        if not s:
            s = AppSetting(cle=KEY, valeur=v, type_valeur='json', service='pennylane')
            db.session.add(s)
        else:
            s.valeur = v
        db.session.commit()
    except Exception as e:
        logger.warning('pl_sync_job save: %s', e)
        try:
            db.session.rollback()
        except Exception:
            pass


def _recent(etat: dict, max_age_minutes: int = STALE_MINUTES) -> bool:
    """True si la trace est assez fraîche pour correspondre à un job vivant."""
    q = etat.get('quand')
    if not q:
        return False
    try:
        dt = datetime.fromisoformat(str(q).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except (ValueError, TypeError, OverflowError):
        return False
    return 0 <= age <= max_age_minutes


def _lire() -> dict:
    from app.models import AppSetting
    try:
        s = AppSetting.query.filter_by(cle=KEY).first()
        return _json.loads(s.valeur) if s and s.valeur else {}
    except Exception:
        return {}


def status() -> dict:
    """État du job, avec un verrou orphelin normalisé en « terminé »."""
    etat = _lire()
    if etat.get('running') and not _recent(etat):
        etat = dict(etat)
        etat['running'] = False
        etat['perime'] = True
        etat.setdefault('message', 'Synchro interrompue (instance redémarrée).')
    return etat


def start() -> dict:
    """Démarre la synchro (au plus une à la fois) et répond immédiatement."""
    global _running
    with _lock:
        if _running:
            return {'ok': True, 'en_cours': True,
                    'message': 'Une synchronisation est déjà en cours.'}
        if status().get('running'):
            return {'ok': True, 'en_cours': True,
                    'message': 'Une synchronisation est déjà en cours.'}
        _running = True
    _save({'running': True, 'message': 'Synchronisation en cours…'})

    from app import app as flask_app
    arret = threading.Event()

    def _battement():
        # Maintient `quand` frais : un passage long ne doit pas être pris pour
        # un verrou orphelin par un autre worker.
        while not arret.wait(20):
            try:
                with flask_app.app_context():
                    _save({'running': True, 'message': 'Synchronisation en cours…'})
            except Exception:
                pass

    def _work():
        global _running
        try:
            with flask_app.app_context():
                from app.integrations.pennylane_web import sync_checklist_tva
                resultat = sync_checklist_tva()
        except Exception as e:
            logger.exception('pl_sync_job: échec inattendu')
            resultat = {'ok': False,
                        'message': f'Erreur interne pendant la synchro : {e}',
                        'erreurs': [str(e)], 'dossiers_ok': 0,
                        'dossiers_total': 0}
        finally:
            arret.set()
            try:
                with flask_app.app_context():
                    _save({'running': False, 'resultat': resultat})
            except Exception:
                pass
            with _lock:
                _running = False

    threading.Thread(target=_battement, daemon=True).start()
    threading.Thread(target=_work, daemon=True).start()
    return {'ok': True, 'en_cours': True,
            'message': 'Synchronisation lancée en arrière-plan — le bilan '
                       's’affichera automatiquement.'}
