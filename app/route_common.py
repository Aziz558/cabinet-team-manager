"""Helpers partages entre les modules routes_* (appels Python directs)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

def prochaine_echeance_theorique(dossier, today):
    """Calcule la prochaine échéance TVA théorique pour les tâches pas encore générées."""
    from .tva_scheduler import next_working_day
    import calendar
    r = (dossier.regime_tva or '').lower().strip()
    ref = dossier.date_limite_declaration
    if not ref or r in ('', 'exonere'):
        return None
    jour = ref.day
    annee = ref.year
    echeances = []
    if r in ('mensuel', 'ca3'):
        for m in range(1, 13):
            try:
                echeances.append(next_working_day(date(annee, m, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, m, 15)))
    elif r == 'trimestriel':
        for m in (1, 4, 7, 10):
            try:
                echeances.append(next_working_day(date(annee, m, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, m, 15)))
    elif r in ('annuel', 'ca12'):
        # Acomptes : dates personnalisées si définies, sinon défauts
        if dossier.date_acompte_1:
            echeances.append(next_working_day(dossier.date_acompte_1))
        else:
            echeances.append(next_working_day(date(annee, 7, 15)))
        if dossier.date_acompte_2:
            echeances.append(next_working_day(dossier.date_acompte_2))
        else:
            try:
                echeances.append(next_working_day(date(annee, 12, jour)))
            except ValueError:
                echeances.append(next_working_day(date(annee, 12, 15)))
        echeances.append(next_working_day(date(annee + 1, 5, 15)))
    # Prochaines échéances >= aujourd'hui
    futurs = [e for e in echeances if e >= today]
    if not futurs:
        # Si tout passé, générer l'année suivante pour mensuel/trimestriel
        if r in ('mensuel', 'ca3'):
            for m in range(1, 13):
                try:
                    futurs.append(next_working_day(date(annee + 1, m, jour)))
                except ValueError:
                    futurs.append(next_working_day(date(annee + 1, m, 15)))
        elif r == 'trimestriel':
            for m in (1, 4, 7, 10):
                try:
                    futurs.append(next_working_day(date(annee + 1, m, jour)))
                except ValueError:
                    futurs.append(next_working_day(date(annee + 1, m, 15)))
    return min(futurs) if futurs else None

def prochaine_echeance_par_nature(d, today):
    """Prochaines échéances (date, nature) par nature d'impôt : TVA, IS, CFE."""
    from .tva_scheduler import next_working_day
    import calendar
    resultats = []
    taches_d = [t for t in d.taches if t.titre and 'Préparation' not in t.titre]

    # --- TVA ---
    taches_tva = [t for t in taches_d if 'TVA' in t.titre or 'Dépôt' in t.titre]
    futurs_tva = [t.date_echeance for t in taches_tva if t.date_echeance and t.date_echeance >= today]
    if futurs_tva:
        resultats.append((min(futurs_tva), 'TVA'))
    else:
        theo = prochaine_echeance_theorique(d, today)
        if theo:
            resultats.append((theo, 'TVA'))

    # --- IS ---
    if (d.regime_fiscale or '').upper() == 'IS':
        taches_is = [t for t in taches_d if 'IS' in t.titre]
        futurs_is = [t.date_echeance for t in taches_is if t.date_echeance and t.date_echeance >= today]
        if futurs_is:
            resultats.append((min(futurs_is), 'IS'))
        else:
            echeances = []
            for y in [today.year, today.year + 1]:
                for m in [3, 6, 9, 12]:
                    echeances.append(next_working_day(date(y, m, 15)))
                echeances.append(next_working_day(date(y + 1, 5, 15)))
            futurs = [e for e in echeances if e >= today]
            if futurs:
                resultats.append((min(futurs), 'IS'))

    # --- CFE ---
    if d.has_cfe:
        taches_cfe = [t for t in taches_d if 'CFE' in t.titre]
        futurs_cfe = [t.date_echeance for t in taches_cfe if t.date_echeance and t.date_echeance >= today]
        if futurs_cfe:
            resultats.append((min(futurs_cfe), 'CFE'))
        else:
            echeances = [next_working_day(date(y, 12, 15)) for y in [today.year, today.year + 1]]
            futurs = [e for e in echeances if e >= today]
            if futurs:
                resultats.append((min(futurs), 'CFE'))

    resultats.sort(key=lambda x: x[0])
    return resultats[:4]


def _tache_accessible(tache, user):
    """Isolation par equipe : True si la tache est dans le perimetre de l'utilisateur.
    - admin : tout (sauf quand une equipe est switchee en session)
    - manager : taches des membres de ses equipes + les siennes + celles qu'il a creees
    - membre : ses taches assignees + celles qu'il a creees
    """
    if user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if not equipe_id:
            return True
        equipe = Equipe.query.get(equipe_id)
        team_ids = [m.id for m in equipe.membres.all()] if equipe else []
        return (tache.assigne_a in team_ids) if team_ids else False
    if user.role == 'manager':
        if tache.assigne_a == user.id or tache.cree_par == user.id:
            return True
        mes_equipes = Equipe.query.filter_by(manager_id=user.id).all()
        team_ids = {user.id}
        for eq in mes_equipes:
            team_ids.update(m.id for m in eq.membres.all())
        return tache.assigne_a in team_ids
    # membre
    if tache.assigne_a == user.id or tache.cree_par == user.id:
        return True
    return False


def _nettoyer_relations_dossier(dossier):
    """Supprime TOUTES les lignes rattachees a un dossier avant de le deletes
    (taches + notifications/commentaires + suggestions + items Pennylane +
    checklists + statuts TVA Pennylane). Doit etre appelle dans le meme
    session que db.session.delete(dossier)."""
    from .models import ChecklistEntry, TvaStatutPennylane, DsnSuivi
    tache_ids = [t.id for t in Tache.query.filter_by(dossier_id=dossier.id).all()]
    if tache_ids:
        Notification.query.filter(Notification.tache_id.in_(tache_ids)).delete(synchronize_session=False)
        CommentaireTache.query.filter(CommentaireTache.tache_id.in_(tache_ids)).delete(synchronize_session=False)
    SuggestionTache.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    Tache.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    # Tables Pennylane (causes de la FK violation pennylane_items_dossier_id_fkey)
    PennylaneItem.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    TvaStatutPennylane.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    ChecklistEntry.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    DsnSuivi.query.filter_by(dossier_id=dossier.id).delete(synchronize_session=False)
    db.session.flush()


