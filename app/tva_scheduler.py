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
    # Clean up related records
    try:
        Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete()
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete()
    except Exception:
        pass  # Ignore errors during cleanup
    # Delete the tasks
    Tache.query.filter(
        Tache.dossier_id == dossier_id,
        or_(*conditions)
    ).delete(synchronize_session=False)
    db.session.commit()

def _planifier_tva_for_dossier(dossier):
    """Planifie les tâches TVA pour un dossier donné."""
    from app.models import Tache
    from app import db
    from flask_login import current_user

    regime = dossier.regime_tva
    if regime is None or regime == 'exonere':
        return

    # Get year from date_limite_declaration or current year
    year = (dossier.date_limite_declaration.year
            if dossier.date_limite_declaration else date.today().year)

    # Get deadlines based on regime and frequency
    import re
    freq = (dossier.frequence_tva or '').lower().strip()
    if freq.startswith('mens') or freq == '':
        # Mensuelle par défaut (si frequence vide, on prend mensuel comme base)
        deadlines = get_ca3_deadlines_mensuelle(year)
    else:  # trimestrielle (default)
        deadlines = get_ca3_deadlines_trimestrielle(year)

    # Remove existing TVA tasks for this dossier to avoid duplicates
    _cleanup_existing_tasks(dossier.id, ['TVA'])

    collaborateur_id = dossier.collaborateur_id

    for deadline in deadlines:
        # Skip past deadlines (keep last 2 months for reference)
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue

        # Task 1: Prépa TVA (3 working days before deadline)
        prepa_date = prev_working_day(deadline, offset_days=3)
        tache_prepa = Tache(
            titre=f'Prépa TVA {regime.upper()} — {dossier.numero_dossier}',
            description=f'Préparer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.',
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
            titre=f'Dépot TVA {regime.upper()} — {dossier.numero_dossier}',
            description=f'Déposer la déclaration TVA {regime.upper()} pour le dossier {dossier.numero_dossier}.',
            assigne_a=collaborateur_id,
            dossier_id=dossier.id,
            priorite='haute',
            date_echeance=deadline,
            statut='a_faire',
        )
        db.session.add(tache_depot)

    db.session.commit()
    logger.info(f'TVA tasks planned for dossier {dossier.numero_dossier}: {len(deadlines)} deadlines × 2 tasks')

def _planifier_is_for_dossier(dossier):
    """Planifie les tâches d'acompte IS pour un dossier donné (si régime IS)."""
    from app.models import Tache
    from app import db
    from flask_login import current_user

    if dossier.regime_fiscale != 'IS':
        return

    # Determine year(s) to generate: we'll generate for current year and next year
    base_year = dossier.date_limite_declaration.year if dossier.date_limite_declaration else date.today().year
    years = [base_year, base_year + 1]

    # Remove existing IS tasks for this dossier to avoid duplicates
    _cleanup_existing_tasks(dossier.id, ['IS', 'acompte'])

    collaborateur_id = dossier.collaborateur_id

    for year in years:
        # IS acomptes dates: 15/03, 15/06, 15/09, 15/12
        months = [3, 6, 9, 12]
        for month in months:
            d = date(year, month, 15)
            deadline = next_working_day(d)  # adjust if weekend
            # Skip past deadlines (keep last 2 months for reference)
            today = date.today()
            if deadline < today - timedelta(days=60):
                continue

            # Create a single task for the acompte (could split into prep/depot but not required)
            tache_is = Tache(
                titre=f'Accompte IS Q{(month-1)//3 + 1} {year} — {dossier.numero_dossier}',
                description=f"Verser l'acompte d'impôt sur les sociétés pour le trimestre {(month-1)//3 + 1} de l'année {year} pour le dossier {dossier.numero_dossier}.",
                assigne_a=collaborateur_id,
                cree_par=current_user.id if current_user.is_authenticated else None,
                dossier_id=dossier.id,
                priorite='moyenne',
                date_echeance=deadline,
                statut='a_faire',
            )
            db.session.add(tache_is)

    db.session.commit()
    logger.info(f'IS acompte tasks planned for dossier {dossier.numero_dossier} for years {years}')

def _planifier_cfe_for_dossier(dossier):
    """Planifie les tâches de CFE pour un dossier donné (si soumis à CFE)."""
    from app.models import Tache
    from app import db
    from flask_login import current_user

    if not dossier.has_cfe:
        return

    # Determine year(s) to generate: current year and next year
    base_year = dossier.date_limite_declaration.year if dossier.date_limite_declaration else date.today().year
    years = [base_year, base_year + 1]

    # Remove existing CFE tasks for this dossier to avoid duplicates
    _cleanup_existing_tasks(dossier.id, ['CFE'])

    collaborateur_id = dossier.collaborateur_id

    for year in years:
        # CFE deadline: 15/12 of each year
        d = date(year, 12, 15)
        deadline = next_working_day(d)  # adjust if weekend
        # Skip past deadlines (keep last 2 months for reference)
        today = date.today()
        if deadline < today - timedelta(days=60):
            continue

        tache_cfe = Tache(
            titre=f'CFE {year} — {dossier.numero_dossier}',
            description=f"Déclarer et payer la Cotisation Foncière des Entreprises pour l'année {year} pour le dossier {dossier.numero_dossier}.",
            assigne_a=collaborateur_id,
            cree_par=current_user.id if current_user.is_authenticated else None,
            dossier_id=dossier.id,
            priorite='moyenne',
            date_echeance=deadline,
            statut='a_faire',
        )
        db.session.add(tache_cfe)

    db.session.commit()
    logger.info(f'CFE tasks planned for dossier {dossier.numero_dossier} for years {years}')

def planifier_impots_dossier(dossier):
    """Point d'entrée unique pour planifier tous les impôts (TVA, IS, CFE) d'un dossier."""
    _planifier_tva_for_dossier(dossier)
    _planifier_is_for_dossier(dossier)
    _planifier_cfe_for_dossier(dossier)