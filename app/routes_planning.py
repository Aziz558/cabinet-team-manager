"""planning — calendrier + analytics (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/calendrier')
@login_required
def calendrier():
    """Fenêtre calendrier supprimée : redirige vers la page Avancement qui
    intègre désormais l'échéancier annuel par module (fiscal/comptable/social)."""
    annee = request.args.get('annee', type=int)
    return redirect(url_for('suivi_avancement', annee=annee) if annee else url_for('suivi_avancement'))


@app.route('/calendrier/data')
@login_required
def calendrier_data():
    """API JSON : échéancier annuel par catégorie (tva, IS, CFE, paie...)
    avec compteurs reste à faire / fait / prochaine échéance, onglets par module.
    Utilisé par la page Avancement (onglet Échéancier)."""
    from collections import defaultdict

    annee = request.args.get('annee', type=int) or date.today().year

    team_member_ids = None
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        ids = [current_user.id]
        for eq in mes_equipes:
            ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(ids))
    elif current_user.role != 'admin':
        team_member_ids = [current_user.id]

    taches_q = Tache.query.filter(
        Tache.date_echeance.between(date(annee, 1, 1), date(annee, 12, 31))
    )
    if team_member_ids:
        dossiers_ids = [d.id for d in Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()]
        taches_q = taches_q.filter(Tache.dossier_id.in_(dossiers_ids))
    taches_list = taches_q.filter(~Tache.titre.ilike('%Préparation%')).all()

    def _categorie(t):
        titre = (t.titre or '').lower()
        if 'tva' in titre:
            return 'tva', 'Récurrents - TVA'
        if 'acompte' in titre and 'is' in titre:
            return 'is_acompte', 'IS - Acomptes'
        if 'is' in titre and ('dépôt' in titre or 'depot' in titre or 'déclaration' in titre or 'declaration' in titre):
            return 'is_depot', 'IS - Déclaration'
        if 'cfe' in titre:
            return 'cfe', 'CFE'
        if 'liasse' in titre:
            return 'liasse', 'Liasse fiscale'
        if 'paie' in titre or 'bulletin' in titre or 'salaire' in titre:
            return 'paie', 'Paie'
        if 'tenue' in titre:
            return 'tenue', 'Tenue comptable'
        if 'impot' in titre or 'fiscal' in titre or 'déclaration' in titre or 'declaration' in titre:
            return 'fiscal_autres', 'Fiscal - Autres'
        return 'autres', 'Autres'

    def _module(t):
        titre = (t.titre or '').lower()
        if any(k in titre for k in ('tva', 'is ', 'is-', 'acompte', 'cfe', 'liasse', 'impot', 'fiscal', 'déclaration', 'declaration')):
            return 'fiscal'
        if any(k in titre for k in ('paie', 'bulletin', 'salaire', 'social', 'urssaf')):
            return 'social'
        return 'comptable'

    groupes = defaultdict(lambda: {'reste': 0, 'fait': 0, 'prochaine': None, 'module': '', 'label': ''})
    compteurs_modules = {'fiscal': 0, 'comptable': 0, 'social': 0}
    for t in taches_list:
        cat, label = _categorie(t)
        mod = _module(t)
        g = groupes[cat]
        g['label'] = label
        g['module'] = mod
        if t.statut == 'terminee':
            g['fait'] += 1
        else:
            g['reste'] += 1
            if g['prochaine'] is None or t.date_echeance < g['prochaine']:
                g['prochaine'] = t.date_echeance
        compteurs_modules[mod] += 1

    lignes = []
    for cat in sorted(groupes.keys(), key=lambda c: (groupes[c]['module'], -groupes[c]['reste'])):
        g = groupes[cat]
        lignes.append({
            'cat': cat, 'label': g['label'], 'module': g['module'],
            'reste': g['reste'], 'fait': g['fait'],
            'prochaine': g['prochaine'].strftime('%d/%m/%Y') if g['prochaine'] else '—',
            'total': g['reste'] + g['fait'],
        })

    data = {
        'annee': annee,
        'lignes': lignes,
        'compteurs': {
            'tous': len(taches_list),
            'fiscal': compteurs_modules['fiscal'],
            'comptable': compteurs_modules['comptable'],
            'social': compteurs_modules['social'],
        },
    }
    return jsonify(data)


@app.route('/analytics')
@login_required
def analytics():
    """Dashboard analytics inspiré FollowApp : KPI annulaires, échéancier mensuel,
    répartition statuts, dossiers par utilisateur / forme juridique / secteur."""
    annee = request.args.get('annee', type=int) or date.today().year

    # ---- Scoping identique au dashboard : manager = ses équipes, sinon ses dossiers
    team_member_ids = None
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        ids = [current_user.id]
        for eq in mes_equipes:
            ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(ids))
    elif current_user.role != 'admin':
        team_member_ids = [current_user.id]

    dossiers_q = Dossier.query
    if team_member_ids:
        dossiers_q = dossiers_q.filter(Dossier.collaborateur_id.in_(team_member_ids))
    dossiers_list = dossiers_q.all()

    # ---- Tâches de l'année (deadline fiscale ou échéance de tâche), hors « Préparation »
    taches_q = Tache.query.filter(
        Tache.date_echeance.between(date(annee, 1, 1), date(annee, 12, 31))
    )
    if team_member_ids:
        dossiers_ids = [d.id for d in dossiers_list]
        taches_q = taches_q.filter(Tache.dossier_id.in_(dossiers_ids))
    taches_list = taches_q.filter(~Tache.titre.ilike('%Préparation%')).all()

    def _module(t):
        titre = (t.titre or '').lower()
        if any(k in titre for k in ('tva', 'is ', 'is-', 'acompte', 'cfe', 'liasse', 'impot', 'fiscal', 'déclaration', 'declaration')):
            return 'fiscal'
        if any(k in titre for k in ('paie', 'bulletin', 'salaire', 'social', 'urssaf')):
            return 'social'
        return 'comptable'

    # ---- Par module : fait / reste
    modules = {'fiscal': {'fait': 0, 'reste': 0}, 'comptable': {'fait': 0, 'reste': 0}, 'social': {'fait': 0, 'reste': 0}}
    par_mois = {m: {'fait': 0, 'reste': 0} for m in range(1, 13)}
    statuts = {'fait': 0, 'a_faire': 0, 'en_retard': 0}
    for t in taches_list:
        mod = _module(t)
        est_fait = (t.statut == 'terminee')
        est_retard = t.est_en_retard()
        if est_fait:
            modules[mod]['fait'] += 1
            statuts['fait'] += 1
            par_mois[t.date_echeance.month]['fait'] += 1
        else:
            modules[mod]['reste'] += 1
            statuts['en_retard' if est_retard else 'a_faire'] += 1
            par_mois[t.date_echeance.month]['reste'] += 1
    total_taches = len(taches_list)

    # ---- Par utilisateur (dossiers suivis + tâches)
    par_user = {}
    for d in dossiers_list:
        u = d.collaborateur
        if u:
            e = par_user.setdefault(u.id, {'nom': f"{u.prenom} {u.nom}", 'dossiers': 0, 'taches': 0})
            e['dossiers'] += 1
    from collections import Counter
    tache_user = Counter(t.assigne_a for t in taches_list if t.assigne_a)
    for uid, c in tache_user.items():
        if uid in par_user:
            par_user[uid]['taches'] = c
        else:
            u = User.query.get(uid)
            if u:
                par_user[uid] = {'nom': f"{u.prenom} {u.nom}", 'dossiers': 0, 'taches': c}
    par_user_list = sorted(par_user.values(), key=lambda x: -x['taches'])[:10]

    # ---- Formes juridiques / secteurs
    formes = Counter((d.forme_juridique or 'Non renseigné') for d in dossiers_list)
    secteurs = Counter((d.secteur_activite or 'Non renseigné') for d in dossiers_list)

    data = {
        'annee': annee,
        'total_dossiers': len(dossiers_list),
        'total_taches': total_taches,
        'modules': modules,
        'par_mois': par_mois,
        'statuts': statuts,
        'par_user': par_user_list,
        'formes': formes.most_common(),
        'secteurs': secteurs.most_common(),
    }

    if request.args.get('format') == 'json':
        from flask import jsonify
        return jsonify(data)

    return render_template('analytics.html', data=data, annee=annee,
                           annees=sorted({date.today().year, date.today().year - 1, date.today().year - 2}, reverse=True))
