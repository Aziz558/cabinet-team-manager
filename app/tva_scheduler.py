"""
TVA Scheduler — Planifie automatiquement les tâches de déclaration de TVA
selon le régime fiscal (CA3 mensuel, CA3 trimestriel, CA12 annuel avec acomptes).

Règles:
- CA3 mensuelle: deadline = 15th of month following the declaration period.
  - If the 15th falls on a weekend, move to the following Monday.
  - Task 1 "Prépa TVA" created 3 working days before the deadline.
  - Task 2 "Dépôt TVA" created on the deadline day.

- CA3 trimestrielle: deadlines = Jan 15, Apr 15, Jul 15, Oct 15 (quarterly).
  Same weekend adjustment.

- CA12 (déclaration annuelle): deadline = May 15 (or Jan 15 if under 50k CA).
  Also has 2 acomptes:
  - 1er acompte: June 15 (or next working day if weekend)
  - 2ème acompte: December 15 (or next working day if weekend)
  - Task 1 "Prépa TVA" created 3 working days before.
  - Task 2 "Dépôt TVA" created on the deadline day.

All deadlines are adjusted: if they fall on Saturday or Sunday,
they move to the following Monday.
"""

from datetime import date, timedelta
from app import db
import logging

logger = logging.getLogger(__name__)


def next_working_day(d: date) -> date:
    """If d is Saturday or Sunday, return the following Monday."""
    if d.weekday() == 5:  # Saturday
        return d + timedelta(days=2)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def prev_working_day(d: date, offset_days=3) -> date:
    """Return a working day approximately `offset_days` business days before d."""
    result = d - timedelta(days=offset_days)
    # If landing on weekend, move backwards to Friday
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def get_ca3_deadlines_trimestrielle(year: int):
    """CA3 trimestrielle deadlines: Jan 15, Apr 15, Jul 15, Oct 15."""
    deadlines = []
    for month in [1, 4, 7, 10]:
        d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines


def get_ca3_deadlines_mensuelle(year: int):
    """CA3 mensuelle: 15th of each month."""
    deadlines = []
    for month in range(1, 13):
        d = date(year, month, 15)
        deadlines.append(next_working_day(d))
    return deadlines


def get_ca12_deadlines(year: int):
    """CA12 deadlines: annual declaration (May 15), 1er acompte (Jun 15), 2e acompte (Dec 15)."""
    deadlines = []
    # Annual declaration
    deadlines.append(('annuelle', next_working_day(date(year, 5, 15))))
    # 1er acompte
    deadlines.append(('acompte_1', next_working_day(date(year, 6, 15))))
    # 2ème acompte
    deadlines.append(('acompte_2', next_working_day(date(year, 12, 15))))
    return deadlines


def get_tva_deadlines(regime: str, frequence: str, year: int = None):
    """Get TVA deadlines for a given regime and frequency.

    Returns a list of date objects.
    """
    if year is None:
        year = date.today().year

    if regime == 'ca3':
        if frequence == 'mensuelle':
            return get_ca3_deadlines_mensuelle(year)
        else:  # trimestrielle (default)
            return get_ca3_deadlines_trimestrielle(year)
    elif regime == 'ca12':
        return [d for _, d in get_ca12_deadlines(year)]
    else:
        return []


def planifier_taches_tva(dossier, frequence: str = 'trimestrielle'):
    """Planifie les tâches TVA pour un dossier.

    For each deadline, creates:
    - "Prépa TVA" task 3 working days before (priority: moyenne)
    - "Dépôt TVA" task on deadline day (priority: haute)

    Args:
        dossier: A Dossier model instance with regime_tva and date_limite_declaration
        frequence: 'mensuelle' or 'trimestrielle'
    """
    from app.models import Tache
    from flask_login import current_user

    regime = dossier.regime_tva
    if not regime or regime == 'exonere':
        return

    # Get year from date_limite_declaration or current year
    year = (dossier.date_limite_declaration.year
            if dossier.date_limite_declaration else date.today().year)

    # Get deadlines
    if regime == 'ca3':
        if frequence == 'mensuelle':
            deadlines = get_ca3_deadlines_mensuelle(year)
        else:
            deadlines = get_ca3_deadlines_trimestrielle(year)
    elif regime == 'ca12':
        tva_deadlines = get_ca12_deadlines(year)
        deadlines = [d for _, d in tva_deadlines]
    else:
        return

    # Remove existing TVA tasks for this dossier to avoid duplicates
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

        # Task 2: Dépôt TVA (on deadline day)
        tache_depot = Tache(
            titre=f"Dépôt TVA {regime.upper()} — {dossier.numero_dossier}",
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


def planifier_taches_tva_all():
    """Planifie les tâches TVA pour TOUS les dossiers actifs."""
    from app.models import Dossier, Tache

    with db.app.app_context() if hasattr(db, 'app') else None:
        dossiers = Dossier.query.filter(
            Dossier.regime_tva.in_(['ca3', 'ca12'])
        ).all()
        for d in dossiers:
            if d.frequence_tva:
                planifier_taches_tva(d, d.frequence_tva)
            elif d.regime_tva == 'ca12':
                planifier_taches_tva(d, 'annuelle')
