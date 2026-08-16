from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

def next_working_day(d: date) -> date:
    """If d is weekend, return following Monday."""
    if d.weekday() >= 5:
        d += timedelta(days=(7 - d.weekday()))
    return d

def get_ca3_deadlines_mensuelle(year: int, day: int = 15):
    deadlines = []
    for month in range(1, 13):
        try:
            d = date(year, month, day)
        except ValueError:
            d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines

def get_ca3_deadlines_trimestrielle(year: int, day: int = 15):
    deadlines = []
    for month in [1, 4, 7, 10]:
        try:
            d = date(year, month, day)
        except ValueError:
            d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines

def _cleanup_existing_tasks(dossier_id, keywords):
    from app.models import Tache, Notification, CommentaireTache
    from app import db
    from sqlalchemy import or_
    conditions = []
    for kw in keywords:
        conditions.append(Tache.titre.ilike(f'%{kw}%'))
        conditions.append(Tache.description.ilike(f'%{kw}%'))
    if not conditions:
        return
    existing_taches = Tache.query.filter(
        Tache.dossier_id == dossier_id,
        or_(*conditions)
    ).all()
    tache_ids = [t.id for t in existing_taches]
    if not tache_ids:
        return
    try:
        Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete(synchronize_session=False)
    except Exception:
        pass
    try:
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete(synchronize_session=False)
    except Exception:
        pass
    Tache.query.filter(
        Tache.dossier_id == dossier_id,
        or_(*conditions)
    ).delete(synchronize_session=False)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_tva_for_dossier(dossier):
    from app.models import Tache
    from app import db

    regime = dossier.regime_tva
    if regime is None or regime == '':
        regime = 'ca3'
    if regime == 'exonere':
        return

    ref_date = dossier.date_limite_declaration or date.today()
    year = ref_date.year
    day = ref_date.day

    freq = (dossier.frequence_tva or '').lower().strip()
    if freq.startswith('mens') or freq == '':
        deadlines = get_ca3_deadlines_mensuelle(year, day)
    else:
        deadlines = get_ca3_deadlines_trimestrielle(year, day)

    _cleanup_existing_tasks(dossier.id, ['TVA'])

    collaborateur_id = dossier.collaborateur_id
    horizon_3m = date.today() + timedelta(days=95)

    for deadline in deadlines:
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue
        if deadline > horizon_3m:
            continue

        prepa_title = f"Prépa TVA {regime.upper()} — {dossier.numero_dossier}"
        depot_title = f"Dépôt TVA {regime.upper()} — {dossier.numero_dossier}"
        
        for title, desc_suffix in [(prepa_title, "Préparation"), (depot_title, "Dépôt")]:
            t = Tache(
                titre=title,
                description=f"{desc_suffix} TVA pour {dossier.intitule} ({dossier.numero_dossier}) — échéance {deadline.strftime('%d/%m/%Y')}",
                statut='a_faire',
                priorite='haute' if 'Dépôt' in title else 'moyenne',
                date_echeance=deadline,
                dossier_id=dossier.id,
                assigne_a=collaborateur_id,
                cree_par=None,
            )
            db.session.add(t)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_is_for_dossier(dossier):
    from app.models import Tache
    from app import db

    if dossier.regime_fiscale != 'IS':
        return

    collaborateur_id = dossier.collaborateur_id
    ref_date = dossier.date_limite_declaration or date.today()
    year = ref_date.year
    day = ref_date.day

    horizon_3m = date.today() + timedelta(days=95)
    years = [year, year + 1]

    for y in years:
        for month in [3, 6, 9, 12]:
            try:
                d = date(y, month, day)
            except ValueError:
                d = date(y, month, 15)
            deadline = next_working_day(d)
            if deadline > horizon_3m:
                continue
            title = f"Acompte IS Q{month//3} {y} — {dossier.numero_dossier}"
            t = Tache(
                titre=title,
                description=f"Acompte IS trimestriel Q{month//3} {y} pour {dossier.intitule}",
                statut='a_faire',
                priorite='haute',
                date_echeance=deadline,
                dossier_id=dossier.id,
                assigne_a=collaborateur_id,
                cree_par=None,
            )
            db.session.add(t)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_cfe_for_dossier(dossier):
    from app.models import Tache
    from app import db

    if not dossier.has_cfe:
        return

    collaborateur_id = dossier.collaborateur_id
    ref_date = dossier.date_limite_declaration or date.today()
    year = ref_date.year
    day = ref_date.day

    horizon_3m = date.today() + timedelta(days=95)
    years = [year, year + 1]

    for y in years:
        try:
            d = date(y, 12, day)
        except ValueError:
            d = date(y, 12, 15)
        deadline = next_working_day(d)
        if deadline > horizon_3m:
            continue
        title = f"CFE {y} — {dossier.numero_dossier}"
        t = Tache(
            titre=title,
            description=f"CFE annuelle {y} pour {dossier.intitule}",
            statut='a_faire',
            priorite='haute',
            date_echeance=deadline,
            dossier_id=dossier.id,
            assigne_a=collaborateur_id,
            cree_par=None,
        )
        db.session.add(t)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def planifier_impots_dossier(dossier):
    _cleanup_existing_tasks(dossier.id, ['TVA', 'IS', 'CFE', 'Acompte', 'Prépa', 'Dépôt'])
    _planifier_tva_for_dossier(dossier)
    _planifier_is_for_dossier(dossier)
    _planifier_cfe_for_dossier(dossier)

def planifier_tous_les_dossiers():
    from app.models import Dossier
    from app import db
    
    dossiers = Dossier.query.all()
    count = 0
    for d in dossiers:
        try:
            planifier_impots_dossier(d)
            count += 1
        except Exception as e:
            logger.error(f"Erreur planification dossier {d.id}: {e}")
    return count
