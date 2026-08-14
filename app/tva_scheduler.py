def planifier_taches_tva(dossier, frequence: str = 'trimestrielle'):
    """Planifie les tâches TVA pour un dossier.

    For each deadline, creates:
    - "Prépa TVA" task 3 working days before (priority: moyenne)
    - "Dépot TVA" task on deadline day (priority: haute)

    Args:
        dossier: A Dossier model instance with regime_tva and date_limite_declaration
        frequence: 'mensuelle' or 'trimestrielle'
    """
    from app.models import Tache, Notification, CommentaireTache
    from flask_login import current_user
    from app import db
    from datetime import date, timedelta
    import logging

    logger = logging.getLogger(__name__)

    regime = dossier.regime_tva
    if regime is None or regime == 'exonere':
        return

    # Get year from date_limite_declaration or current year
    year = (dossier.date_limite_declaration.year
            if dossier.date_limite_declaration else date.today().year)

    # Get deadlines based on regime and frequency
    if frequence == 'mensuelle':
        deadlines = get_ca3_deadlines_mensuelle(year)
    else:  # trimestrielle (default)
        deadlines = get_ca3_deadlines_trimestrielle(year)

    # Remove existing TVA tasks for this dossier to avoid duplicates
    # First, get the IDs of existing TVA tasks to clean up related records
    existing_tva_taches = Tache.query.filter(
        Tache.dossier_id == dossier.id,
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.description.like('%TVA%')
        )
    ).all()
    tache_ids = [t.id for t in existing_tva_taches]

    # Clean up related records to avoid foreign key constraint violations
    try:
        Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete()
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete()
    except Exception:
        pass  # Ignore errors during cleanup

    # Now delete the TVA tasks
    Tache.query.filter(
        Tache.dossier_id == dossier.id,
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.description.like('%TVA%')
        )
    ).delete(synchronize_session=False)
    db.session.commit()

    collaborateur_id = dossier.collaborateur_id

    for deadline in deadlines:
        # Skip past deadlines (keep last 2 months for reference)
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue

        # Task 1: Prépa TVA (3 working days before deadline)
        prepa_date = prev_working_day(deadline, offset_days=3)
        tache_prepa = Tache(
            titre=f"Prépa TVA {regime.upper()} — {dossier.numero_dossier}",
            description=f"Préparer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.",
            assigne_a=collaborateur_id,
            cree_par=current_user.id if current_user.is_authenticated else None,
            dossier_id=dossier.id,
            priorite='moyenne',
            date_echeance=prepa_date,
            statut='a_faire',
        )
        db.session.add(tache_prepa)

        # Task 2: Dépot TVA (on deadline day)
        tache_depot = Tache(
            titre=f"Dépot TVA {regime.upper()} — {dossier.numero_dossier}",
            description=f"Déposer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.",
            assigne_a=collaborateur_id,
            dossier_id=dossier.id,
            priorite='haute',
            date_echeance=deadline,
            statut='a_faire',
        )
        db.session.add(tache_depot)

    db.session.commit()
    logger.info(f"TVA tasks planned for dossier {dossier.numero_dossier}: {len(deadlines)} deadlines × 2 tasks")


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