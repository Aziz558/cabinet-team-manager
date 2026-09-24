# -*- coding: utf-8 -*-
"""Pôle social : suivi DSN + écritures de paie (Couche 1).

- Périmètre : dossiers suivis par le social (collaborateur_social_id) ou tous pour admin.
- Echés DSN : le 5 du mois M+1 (>= 50 salaries) ou le 15, reporte au jour ouvre suivant.
- Taches « Depôt DSN » generees comme les taches fiscales (scheduler).
"""
from datetime import date, datetime, timedelta

from . import db
from .models import Dossier, DsnSuivi, Tache, Notification, User


def est_pole_social(user):
    """Acces aux vues sociales : admin + pole social/les_deux."""
    return bool(user and user.is_authenticated and (
        user.role == 'admin' or user.dans_pole_social))


MOIS_FR = ['', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
           'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']


def dossiers_suivis_par(user):
    """Dossiers visibles cote social : les siens (referent social) ; admin = tous."""
    q = Dossier.query
    if user.role == 'admin':
        return q.all()
    ids = [user.id]
    if user.role == 'manager':
        # managers du pole social : + les referents sociaux des équipes dont il a la main ?
        # (Un social peut couvrir des dossiers d'equipes comptables differentes : on se
        # base sur collaborateur_social_id, pas sur l'equipe.)
        ids = [u.id for u in User.query.filter(
            User.pole.in_(['social', 'les_deux']), User.actif == True).all()] \
            if user.pole in ('social', 'les_deux') else [user.id]
    return q.filter(Dossier.collaborateur_social_id.in_(ids)).all()


def effectif_nbre(dossier):
    """Best effort : nbre approximatif de salaries depuis la tranche INSEE."""
    lab = (dossier.effectif_label or '')
    approx = {
        '0 salarié': 0, '1 ou 2 salariés': 2, '3 à 5 salariés': 5, '6 à 9 salariés': 8,
        '10 à 19 salariés': 15, '20 à 49 salariés': 35, '50 à 99 salariés': 70,
        '100 à 199 salariés': 140, '200 à 249 salariés': 220, '250 à 499 salariés': 350,
        '500 à 999 salariés': 700, '1 000 à 1 999 salariés': 1500,
        '5 000 à 9 999 salariés': 7000, '2 000 à 4 999 salariés': 3000,
        '10 000 et plus': 15000,
    }
    return approx.get(lab, 0)


def date_exigibilite(annee, mois, nb_eff):
    """M+1 le 5 (>=50 salaries) sinon le 15, jour ouvre si week-end."""
    from .tva_scheduler import next_working_day
    y, m = (annee + 1, 1) if mois == 12 else (annee, mois + 1)
    jour = 5 if nb_eff >= 50 else 15
    try:
        d = date(y, m, jour)
    except ValueError:
        d = date(y, m, 28)
    return next_working_day(d)


def grille(dossier, annee):
    """12 cellules DsnSuivi (crees si absentes) pour une annee donnee.
    Retourne liste de dicts {mois, ligne, exigible, retard} triee par mois."""
    existantes = {l.mois: l for l in DsnSuivi.query.filter_by(
        dossier_id=dossier.id, annee=annee).all()}
    nb = effectif_nbre(dossier)
    out = []
    today = date.today()
    for mois in range(1, 13):
        ligne = existantes.get(mois)
        if ligne is None:
            ligne = DsnSuivi(dossier_id=dossier.id, annee=annee, mois=mois)
            db.session.add(ligne)
        dl = date_exigibilite(annee, mois, nb)
        retard = (ligne.dsn_statut in ('a_deposer', 'deposee', 'rejetee')
                  and dl < today)
        out.append({'mois': mois, 'ligne': ligne, 'exigible': dl, 'retard': retard})
    db.session.flush()
    return out


def statut_global(row, exigible, today):
    """Etiquette + couleur d'une cellule pour l'UI."""
    if row.dsn_statut == 'validee':
        return ('validee', 'success')
    if row.dsn_statut == 'rejetee':
        return ('rejetee', 'danger')
    if row.dsn_statut == 'deposee':
        return ('deposee', 'info')
    # a_deposer
    if (row.annee, row.mois) >= (today.year, today.month) and row.mois != today.month:
        return ('avenir', 'muted')
    if exigible < today:
        return ('retard', 'danger')
    return ('a_deposer', 'warning')


def generer_taches_dsn(dossier=None, horizon_jours=25):
    """Cree les taches « Depôt DSN {MM/AAAA} — {dossier} » pour les echeances a venir
    (horizon par defaut 25 jours — couvre l'echeance du 5/15 du mois suivant).
    Idempotent (titre unique par dossier+periode).
    Retourne le nb de taches creees."""
    today = date.today()
    dossiers = [dossier] if dossier else Dossier.query.filter(
        Dossier.collaborateur_social_id.isnot(None)).all()
    nb = 0
    for d in dossiers:
        nb_eff = effectif_nbre(d)
        for y in {today.year, today.year + 1}:
            for m in range(1, 13):
                dl = date_exigibilite(y, m, nb_eff)
                if dl < today or dl > today + timedelta(days=horizon_jours):
                    continue
                titre = f"Dépôt DSN {m:02d}/{y} — {d.numero_dossier}"
                if Tache.query.filter_by(dossier_id=d.id, titre=titre).first():
                    continue
                t = Tache(
                    titre=titre,
                    description=(f"DSN période {m:02d}/{y} (exigible le {dl:%d/%m/%Y}).\n"
                                 f"Dossier : {d.intitule}\nGénérée automatiquement (suivi social)."),
                    dossier_id=d.id,
                    assigne_a=d.collaborateur_social_id,
                    cree_par=None,
                    priorite='haute' if dl <= today + timedelta(days=3) else 'moyenne',
                    statut='a_faire',
                    date_echeance=dl,
                )
                db.session.add(t)
                nb += 1
    db.session.commit()
    return nb


def taches_dsn_retard():
    """Taches DSN en retard (pour la carte dashboard)."""
    return Tache.query.filter(
        Tache.titre.like('Dépôt DSN %'),
        Tache.statut != 'terminee',
        Tache.date_echeance < date.today(),
    ).count()
