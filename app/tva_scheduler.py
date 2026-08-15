from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)

def prev_working_day(d: date, offset_days=3) -> date:
    """Return a working day approximately `offset_days` business days before d."""
    result = d - timedelta(days=offset_days)
    # If landing on weekend, move backwards to Friday
    while result.weekday() >= 5:  # 5=Saturday, 6=Sunday
        result -= timedelta(days=1)
    return result

def next_working_day(d: date) -> date:
    """If d is weekend, return following Monday."""
    if d.weekday() >= 5:  # Saturday or Sunday
        d += timedelta(days=(7 - d.weekday()))
    return d

def get_ca3_deadlines_mensuelle(year: int):
    """CA3 mensuelle: 15th of each month."""
    deadlines = []
    for month in range(1, 13):
        d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines

def get_ca3_deadlines_trimestrielle(year: int):
    """CA3 trimestrielle deadlines: Jan 15, Apr 15, Jul 15, Oct 15."""
    deadlines = []
    for month in [1, 4, 7, 10]:
        d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines

def _cleanup_existing_tasks(dossier_id, keywords):
    """Delete existing tasks whose titre or description contains any of the keywords."""
    from app.models import Tache, Notification, CommentaireTache
    from app import db
    # Build OR conditions for each keyword
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
    # Clean up related records
    try:
        Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete(synchronize_session=False)
    except Exception:
        pass
    try:
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete(synchronize_session=False)
    except Exception:
        pass
    # Delete the tasks
    Tache.query.filter(
        Tache.dossier_id == dossier_id,
        or_(*conditions)
    ).delete(synchronize_session=False)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_tva_for_dossier(dossier):
    """Planifie les tâches TVA pour un dossier donné - version sans current_user."""
    from app.models import Tache
    from app import db

    regime = dossier.regime_tva
    # Si aucun regime n'est défini, on crée quand même des tâches (CA3 par défaut)
    if regime is None or regime == '':
        regime = 'ca3'
    if regime == 'exonere':
        return

    # Get year from date_limite_declaration or current year
    year = (dossier.date_limite_declaration.year
            if dossier.date_limite_declaration else date.today().year)

    # Get deadlines based on regime and frequency
    import re
    freq = (dossier.frequence_tva or '').lower().strip()
    if freq.startswith('mens') or freq == '':
        deadlines = get_ca3_deadlines_mensuelle(year)
    else:
        deadlines = get_ca3_deadlines_trimestrielle(year)

    # Remove existing TVA tasks for this dossier to avoid duplicates
    _cleanup_existing_tasks(dossier.id, ['TVA'])

    collaborateur_id = dossier.collaborateur_id

    # 3 months horizon from today
    horizon_3m = date.today() + timedelta(days=95)  # ~3 mois

    for deadline in deadlines:
        # Skip past deadlines (keep last 2 months for reference)
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue
        # Skip deadlines beyond 3 months horizon
        if deadline > horizon_3m:
            continue

        # Task 1: Prépa TVA (3 working days before deadline)
        prepa_date = prev_working_day(deadline, offset_days=3)
        tache_prepa = Tache(
            titre=f'Prépa TVA {regime.upper()} — {dossier.numero_dossier}',
            description=f'Préparer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.',
            assigne_a=collaborateur_id,
            cree_par=None,  # Pas de current_user ici
            dossier_id=dossier.id,
            priorite='moyenne',
            date_echeance=prepa_date,
            statut='a_faire',
        )
        db.session.add(tache_prepa)

        # Task 2: Dépot TVA (on deadline day)
        tache_depot = Tache(
            titre=f'Dépot TVA {regime.upper()} — {dossier.numero_dossier}',
            description=f'Déposer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.',
            assigne_a=collaborateur_id,
            dossier_id=dossier.id,
            priorite='haute',
            date_echeance=deadline,
            statut='a_faire',
        )
        db.session.add(tache_depot)

    try:
        db.session.commit()
        logger.info(f'TVA tasks planned for dossier {dossier.numero_dossier}: {len(deadlines)} deadlines × 2 tasks')
    except Exception as e:
        db.session.rollback()
        logger.error(f'TVA planning error for dossier {dossier.numero_dossier}: {e}')

def _planifier_is_for_dossier(dossier):
    """Planifie les tâches d'acompte IS pour un dossier donné (si régime IS)."""
    from app.models import Tache
    from app import db

    if dossier.regime_fiscale != 'IS':
        return

    # Determine year(s) to generate: we'll generate for current year and next year
    base_year = dossier.date_limite_declaration.year if dossier.date_limite_declaration else date.today().year
    years = [base_year, base_year + 1]

    # Remove existing IS tasks for this dossier to avoid duplicates
    _cleanup_existing_tasks(dossier.id, ['IS', 'acompte'])

    collaborateur_id = dossier.collaborateur_id

    horizon_3m = date.today() + timedelta(days=95)

    for year in years:
        # IS acomptes dates: 15/03, 15/06, 15/09, 15/12
        months = [3, 6, 9, 12]
        for month in months:
            d = date(year, month, 15)
            deadline = next_working_day(d)
            # Skip past deadlines (keep last 2 months for reference)
            today = date.today()
            if deadline < today - timedelta(days=60):
                continue
            # Skip deadlines beyond 3 months horizon
            if deadline > horizon_3m:
                continue

            tache_is = Tache(
                titre=f'Accompte IS Q{(month-1)//3 + 1} {year} — {dossier.numero_dossier}',
                description=f"Verser l'acompte d'impôt sur les sociétés pour le trimestre {(month-1)//3 + 1} de l'année {year} pour le dossier {dossier.numero_dossier}.",
                assigne_a=collaborateur_id,
                cree_par=None,
                dossier_id=dossier.id,
                priorite='moyenne',
                date_echeance=deadline,
                statut='a_faire',
            )
            db.session.add(tache_is)

    try:
        db.session.commit()
        logger.info(f'IS acompte tasks planned for dossier {dossier.numero_dossier} for years {years}')
    except Exception as e:
        db.session.rollback()
        logger.error(f'IS planning error for dossier {dossier.numero_dossier}: {e}')

def _planifier_cfe_for_dossier(dossier):
    """Planifie les tâches de CFE pour un dossier donné (si soumis à CFE)."""
    from app.models import Tache
    from app import db

    if not dossier.has_cfe:
        return

    base_year = dossier.date_limite_declaration.year if dossier.date_limite_declaration else date.today().year
    years = [base_year, base_year + 1]

    _cleanup_existing_tasks(dossier.id, ['CFE'])

    collaborateur_id = dossier.collaborateur_id

    horizon_3m = date.today() + timedelta(days=95)

    for year in years:
        d = date(year, 12, 15)
        deadline = next_working_day(d)
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue
        if deadline > horizon_3m:
            continue

        tache_cfe = Tache(
            titre=f'CFE {year} — {dossier.numero_dossier}',
            description=f"Déclarer et payer la Cotisation Foncière des Entreprises pour l'année {year} pour le dossier {dossier.numero_dossier}.",
            assigne_a=collaborateur_id,
            cree_par=None,
            dossier_id=dossier.id,
            priorite='moyenne',
            date_echeance=deadline,
            statut='a_faire',
        )
        db.session.add(tache_cfe)

    try:
        db.session.commit()
        logger.info(f'CFE tasks planned for dossier {dossier.numero_dossier} for years {years}')
    except Exception as e:
        db.session.rollback()
        logger.error(f'CFE planning error for dossier {dossier.numero_dossier}: {e}')

def planifier_impots_dossier(dossier):
    """Point d'entrée unique pour planifier tous les impôts (TVA, IS, CFE) d'un dossier."""
    try:
        _planifier_tva_for_dossier(dossier)
    except Exception as e:
        logger.error(f"Error planning TVA for dossier {dossier.id}: {e}")
    try:
        _planifier_is_for_dossier(dossier)
    except Exception as e:
        logger.error(f"Error planning IS for dossier {dossier.id}: {e}")
    try:
        _planifier_cfe_for_dossier(dossier)
    except Exception as e:
        logger.error(f"Error planning CFE for dossier {dossier.id}: {e}")

def planifier_tous_les_dossiers():
    """Planifie les impôts pour TOUS les dossiers existants."""
    from app import db
    from app.models import Dossier
    dossiers = Dossier.query.all()
    logger.info(f"Planning taxes for {len(dossiers)} dossiers...")
    for d in dossiers:
        planifier_impots_dossier(d)
    logger.info("Tax planning complete for all dossiers.")
