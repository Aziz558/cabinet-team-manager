# -*- coding: utf-8 -*-
"""Liaison bidirectionnelle : cases Checklist (déclarations TVA/IS/CFE) <->
taches deadline correspondantes (Dépôt TVA, Acompte IS, CFE...).

Sens A/B  — case -> tache : `appliquer_case_a_taches()` appelle quand une case
             devient declare (manuel via /checklist/toggle OU via synchro Pennylane)
             => la tache deadline de la meme periode est marquee terminee.
             Si la case est remise a « a faire / venir » => la tache repasse a_faire.
Sens C    — tache -> case : `appliquer_tache_a_case()` appelee quand un utilisateur
             change le statut d'une tache deadline => la case checklist correspondante
             est declaree (ou effacee si la tache revient a a_faire).

Mapping periode (aligne sur la logique « seed » de la checklist, routes.py) :
  Dépôt TVA mensuel/trimestriel : periode declaree = mois precedant l'echeance
  Acompte TVA annuel (juillet|decembre) : (annee echeance, mois echeance, acompte)
  Declaration TVA annuelle : (annee echeance, 5, declaration)
  Acompte IS : (annee echeance, mois echeance, acompte)
  Declaration IS definitive : (annee echeance, 5, declaration)
  CFE : (annee echeance, 12, depot)
"""
from datetime import date, datetime

from . import db
from .models import Tache, ChecklistEntry

_KINDE = ('tva_mensuel', 'tva_trimestriel', 'tva_ca12', 'is', 'cfe')


def _periode_depuis_deadline(dt, freq):
    """Alignee sur routes.checklist : mensuel 24/08 -> juillet (07)."""
    y, m = dt.year, dt.month - 1
    if m == 0:
        y, m = y - 1, 12
    if freq == 'trimestriel':
        m = ((m - 1) // 3) * 3 + 1
    return y, m


def case_pour_tache(tache):
    """Retourne (taxe, annee, mois, kind, paye) si la tache est une echeance
    fiscale liee a la checklist, sinon None. Ignore les Preparations."""
    titre = (tache.titre or '').lower()
    if 'préparation' in titre or 'preparation' in titre:
        return None
    if not tache.date_echeance:
        return None
    e = tache.date_echeance
    if 'dépôt tva mensuel' in titre or 'depot tva mensuel' in titre:
        y, mo = _periode_depuis_deadline(e, 'mensuel')
        return ('tva_mensuel', y, mo, 'depot', False)
    if 'dépôt tva trimestriel' in titre or 'depot tva trimestriel' in titre:
        y, mo = _periode_depuis_deadline(e, 'trimestriel')
        return ('tva_trimestriel', y, mo, 'depot', False)
    if 'acompte tva annuel' in titre:
        return ('tva_ca12', e.year, e.month, 'acompte', True)
    if 'déclaration tva annuelle' in titre or 'declaration tva annuelle' in titre:
        return ('tva_ca12', e.year, e.month, 'declaration', False)
    if 'acompte is' in titre:
        return ('is', e.year, e.month, 'acompte', True)
    if 'déclaration is' in titre or 'declaration is' in titre:
        return ('is', e.year, e.month, 'declaration', False)
    if 'cfe' in titre:
        return ('cfe', e.year, e.month, 'depot', False)
    return None


def _taches_pour_case(dossier_id, taxe, annee, mois, kind):
    """Les taches deadline du dossier qui correspondent a la case donnee."""
    cands = Tache.query.filter(Tache.dossier_id == dossier_id).all()
    out = []
    for t in cands:
        m = case_pour_tache(t)
        if m and m[:4] == (taxe, annee, mois, kind):
            out.append(t)
    return out


def appliquer_case_a_taches(dossier_id, taxe, annee, mois, kind, declare, paye=False):
    """Case cochee -> taches terminee ; case videe -> taches a_faire.
    Retourne le nb de taches mises a jour."""
    n = 0
    for t in _taches_pour_case(dossier_id, taxe, annee, mois, kind):
        if declare and t.statut != 'terminee':
            t.statut = 'terminee'
            if not t.date_completion:
                t.date_completion = datetime.utcnow()
            n += 1
        elif not declare and t.statut == 'terminee':
            t.statut = 'a_faire'
            t.date_completion = None
            n += 1
    return n


def appliquer_tache_a_case(tache):
    """Changement de statut d'une tache deadline -> reflte dans la checklist.
    terminee -> case declaree (+paye si acompte) ; a_faire -> case supprimee.
    en_cours -> on ne touche pas. Retourne nb de cases mises a jour (0/1)."""
    m = case_pour_tache(tache)
    if not m or not tache.dossier_id:
        return 0
    taxe, annee, mois, kind, paye = m
    e = ChecklistEntry.query.filter_by(dossier_id=tache.dossier_id, taxe=taxe,
                                       annee=annee, mois=mois, kind=kind).first()
    if tache.statut == 'terminee':
        if not e:
            e = ChecklistEntry(dossier_id=tache.dossier_id, taxe=taxe,
                               annee=annee, mois=mois, kind=kind)
            db.session.add(e)
        e.declare = True
        e.paye = bool(paye)
        e.pl_mode = False
    elif tache.statut == 'a_faire':
        if e:
            db.session.delete(e)
            # si la synchro PL a impose declare sur la periode, la re-supprimer ici
            # serait un aller-retour : pl_mode=True ne doit etre annule que par la synchro
            # (e.pl_mode est False quand cree par l'homme ; les lignes pl_mode=True
            # n'arrivent ici que si un humain remet la tache a faire -> on laisse partir)
    else:
        return 0
    return 1
