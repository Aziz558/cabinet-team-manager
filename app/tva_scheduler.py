from datetime import date, datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def next_working_day(d: date) -> date:
    """If d is weekend, return following Monday."""
    if d.weekday() >= 5:
        d += timedelta(days=(7 - d.weekday()))
    return d

def prev_working_day(d: date, offset=3) -> date:
    """Return a working day `offset` business days before d."""
    result = d - timedelta(days=offset)
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result

def make_task(title, description, deadline, dossier_id, collaborateur_id, priorite='moyenne'):
    """Create a task + a prepa task 3 working days before."""
    from app.models import Tache
    from app import db
    
    # Main task (dépôt)
    is_past = deadline < date.today()
    t = Tache(
        titre=title,
        description=description,
        statut='terminee' if is_past else 'a_faire',
        priorite=priorite,
        date_echeance=deadline,
        dossier_id=dossier_id,
        assigne_a=collaborateur_id,
        cree_par=None,
        date_completion=datetime.utcnow() if is_past else None,
    )
    db.session.add(t)
    
    # Prépa task 3 working days before
    prepa_day = prev_working_day(deadline, 3)
    prepa_title = f"Préparation {title}"
    prepa_is_past = prepa_day < date.today()
    prepa = Tache(
        titre=prepa_title,
        description=f"Préparer les documents pour : {description}",
        statut='terminee' if prepa_is_past else 'a_faire',
        priorite='moyenne',
        date_echeance=prepa_day,
        dossier_id=dossier_id,
        assigne_a=collaborateur_id,
        cree_par=None,
        date_completion=datetime.utcnow() if prepa_is_past else None,
    )
    db.session.add(prepa)

def _cleanup_existing_tasks(dossier_id, keywords):
    """Delete existing tasks matching keywords for a dossier."""
    from app.models import Tache, Notification, CommentaireTache
    from app import db
    from sqlalchemy import or_
    conditions = []
    for kw in keywords:
        conditions.append(Tache.titre.ilike(f'%{kw}%'))
        conditions.append(Tache.description.ilike(f'%{kw}%'))
    if not conditions:
        return
    existing = Tache.query.filter(Tache.dossier_id == dossier_id, or_(*conditions)).all()
    ids = [t.id for t in existing]
    if not ids:
        return
    try:
        Notification.query.filter(Notification.tache_id.in_(ids)).delete(synchronize_session=False)
    except Exception:
        pass
    try:
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(ids)).delete(synchronize_session=False)
    except Exception:
        pass
    Tache.query.filter(Tache.dossier_id == dossier_id, or_(*conditions)).delete(synchronize_session=False)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_tva(dossier):
    """TVA deadlines based on dossier's date_limite_declaration."""
    from app import db
    
    regime = (dossier.regime_tva or '').lower().strip()
    if regime == 'exonere':
        return
    if not regime:
        regime = 'mensuel'  # Par défaut si non renseigné
    # Compatibilité ascendante : mapper les anciennes valeurs
    if regime == 'ca3':
        # CA3 peut être mensuel ou trimestriel. Par défaut mensuel.
        regime = 'mensuel'
    elif regime == 'ca12':
        regime = 'annuel'
    
    ref_date = dossier.date_limite_declaration or date.today()
    year = ref_date.year
    day = ref_date.day
    
    # Determine deadlines based on frequency
    if regime == 'mensuel':
        deadlines = []
        for m in range(1, 13):
            try:
                d = date(year, m, day)
            except ValueError:
                d = date(year, m, 15)
            deadlines.append(next_working_day(d))
        regime_label = 'mensuel'
    elif regime == 'trimestriel':
        deadlines = []
        for m in [1, 4, 7, 10]:
            try:
                d = date(year, m, day)
            except ValueError:
                d = date(year, m, 15)
            deadlines.append(next_working_day(d))
        regime_label = 'trimestriel'
    else:  # annuel (CA12)
        # 2 acomptes semestriels: juillet et décembre, même jour que la date de référence
        # 1 déclaration définitive: 15/05/N+1
        deadlines = []  # We handle this separately
        regime_label = 'annuel'
    
    _cleanup_existing_tasks(dossier.id, ['TVA', 'Dépôt TVA', 'Préparation TVA'])
    
    horizon = date.today() + timedelta(days=30)
    
    # Handle TVA deadlines for mensuel and trimestriel
    for dl in deadlines:
        if dl < date.today() - timedelta(days=60):
            continue
        if dl > horizon:
            continue
        
        depot_title = f"Dépôt TVA {regime_label} — {dossier.numero_dossier}"
        depot_desc = f"Dépôt TVA {regime_label} pour {dossier.intitule} ({dossier.numero_dossier}) — échéance {dl.strftime('%d/%m/%Y')}"
        make_task(depot_title, depot_desc, dl, dossier.id, dossier.collaborateur_id, 'haute')
    
    # Handle CA12 annuel: 2 acomptes semestriels + 1 déclaration définitive
    if regime == 'annuel':
        # Acompte 1: juillet (même jour que la date de référence)
        try:
            acompte1 = next_working_day(date(year, 7, day))
        except ValueError:
            acompte1 = next_working_day(date(year, 7, 15))
        if acompte1 <= horizon and acompte1 >= date.today() - timedelta(days=60):
            make_task(f"Acompte TVA annuel (juillet) — {dossier.numero_dossier}",
                     f"Acompte TVA semestriel juillet pour {dossier.intitule} — échéance {acompte1.strftime('%d/%m/%Y')}",
                     acompte1, dossier.id, dossier.collaborateur_id, 'haute')
        
        # Acompte 2: décembre (même jour que la date de référence)
        try:
            acompte2 = next_working_day(date(year, 12, day))
        except ValueError:
            acompte2 = next_working_day(date(year, 12, 15))
        if acompte2 <= horizon and acompte2 >= date.today() - timedelta(days=60):
            make_task(f"Acompte TVA annuel (décembre) — {dossier.numero_dossier}",
                     f"Acompte TVA semestriel décembre pour {dossier.intitule} — échéance {acompte2.strftime('%d/%m/%Y')}",
                     acompte2, dossier.id, dossier.collaborateur_id, 'haute')
        
        # Déclaration définitive CA12: 15/05/N+1
        def_dl = next_working_day(date(year + 1, 5, 15))
        if def_dl <= horizon:
            make_task(f"Déclaration TVA annuelle {year} — {dossier.numero_dossier}",
                     f"Déclaration TVA CA12 pour l'exercice {year} de {dossier.intitule} — échéance {def_dl.strftime('%d/%m/%Y')}",
                     def_dl, dossier.id, dossier.collaborateur_id, 'urgente')
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_is(dossier):
    """IS: fixed dates for acomptes (15/03, 15/06, 15/09, 15/12) and déclaration (15/05)."""
    from app import db
    
    if dossier.regime_fiscale != 'IS':
        return
    
    _cleanup_existing_tasks(dossier.id, ['IS', 'Acompte IS', 'Déclaration IS', 'Préparation IS'])
    
    year = date.today().year
    horizon = date.today() + timedelta(days=30)
    
    # Acomptes provisionnels: 15/03, 15/06, 15/09, 15/12 (N and N+1)
    for y in [year, year + 1]:
        for m in [3, 6, 9, 12]:
            dl = next_working_day(date(y, m, 15))
            if dl > horizon:
                continue
            title = f"Acompte IS Q{m//3} {y} — {dossier.numero_dossier}"
            desc = f"Acompte IS trimestriel Q{m//3} {y} pour {dossier.intitule} — échéance {dl.strftime('%d/%m/%Y')}"
            make_task(title, desc, dl, dossier.id, dossier.collaborateur_id, 'haute')
    
    # Déclaration définitive IS: 15/05/N+1
    dl_def = next_working_day(date(year + 1, 5, 15))
    if dl_def <= horizon:
        title = f"Déclaration IS définitive {year} — {dossier.numero_dossier}"
        desc = f"Déclaration IS définitive pour l'exercice {year} de {dossier.intitule} — échéance {dl_def.strftime('%d/%m/%Y')}"
        make_task(title, desc, dl_def, dossier.id, dossier.collaborateur_id, 'urgente')
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def _planifier_cfe(dossier):
    """CFE: fixed date 15/12 each year."""
    from app import db
    
    if not dossier.has_cfe:
        return
    
    _cleanup_existing_tasks(dossier.id, ['CFE', 'Préparation CFE'])
    
    year = date.today().year
    horizon = date.today() + timedelta(days=30)
    
    for y in [year, year + 1]:
        dl = next_working_day(date(y, 12, 15))
        if dl > horizon:
            continue
        title = f"CFE {y} — {dossier.numero_dossier}"
        desc = f"CFE annuelle {y} pour {dossier.intitule} — échéance {dl.strftime('%d/%m/%Y')}"
        make_task(title, desc, dl, dossier.id, dossier.collaborateur_id, 'haute')
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def planifier_impots_dossier(dossier):
    """Generate all tax tasks for a dossier."""
    # Clean up first
    _cleanup_existing_tasks(dossier.id, ['TVA', 'IS', 'CFE', 'Acompte', 'Dépôt', 'Préparation', 'Déclaration'])
    # Generate tasks
    _planifier_tva(dossier)
    _planifier_is(dossier)
    _planifier_cfe(dossier)

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
