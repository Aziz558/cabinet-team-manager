"""dossiers — liste dossiers + tva-taches + planification (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta
from .route_common import (prochaine_echeance_theorique, prochaine_echeance_par_nature,
                            _tache_accessible, _nettoyer_relations_dossier)

@app.route('/dossiers')
@login_required
def dossiers():
    """Affiche la liste des dossiers selon le rôle de l'utilisateur."""
    current_equipe = None
    all_equipes_for_switch = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_user_ids)).all()
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_dossiers = Dossier.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        all_dossiers = Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
    
    # Pole social : etendre aux dossiers dont on est le referent social (equipes comptables differentes)
    if current_user.role != 'admin' and current_user.dans_pole_social:
        ids_vus = {d.id for d in all_dossiers}
        ids_sociaux = [current_user.id]
        if current_user.role == 'manager':
            ids_sociaux += [u.id for u in User.query.filter(
                User.pole.in_(['social', 'les_deux']), User.actif == True).all()]
        for d in Dossier.query.filter(Dossier.collaborateur_social_id.in_(ids_sociaux)).all():
            if d.id not in ids_vus:
                all_dossiers.append(d)

    # Pre-calculate TVA task data for each dossier to avoid Jinja template errors
    for d in all_dossiers:
        d._tva_taches = [t for t in d.taches if t.titre and ('TVA' in t.titre.upper() or 'CA3' in t.titre.upper() or 'CA12' in t.titre.upper())]
        d._tva_taches_count = len(d._tva_taches)
        d._tva_taches_restantes = sum(1 for t in d._tva_taches if t.statut not in ('terminee', 'terminée'))
        # Calcul du statut délai/retard
        d._delai_label = '-'
        d._delai_class = 'text-tertiary'
        d._delai_icon = ''
        today = date.today()
        depot_taches = [t for t in d.taches if t.titre and 'Préparation' not in t.titre and ('Dépôt' in t.titre or 'Déclaration' in t.titre or 'Acompte' in t.titre)]
        if depot_taches:
            import calendar
            debut_mois = today.replace(day=1)
            fin_mois = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
            # 1. La tâche de la période courante (mois en cours) est la référence
            mois_courant = [t for t in depot_taches if t.date_echeance and debut_mois <= t.date_echeance <= fin_mois]
            if mois_courant:
                cible = min(mois_courant, key=lambda t: t.date_echeance)
            else:
                # 2. Sinon : prochaine tâche future déjà générée
                futurs = [t for t in depot_taches if t.date_echeance and t.date_echeance > today]
                if futurs:
                    cible = min(futurs, key=lambda t: t.date_echeance)
                else:
                    # 3. Aucune tâche générée (horizon 1 mois) → échéance théorique
                    cible = None
            if cible and cible.date_echeance:
                restant = (cible.date_echeance - today).days
                done = cible.statut in ('terminee', 'terminée')
                if done:
                    d._delai_label = 'Déclaré'
                    d._delai_class = 'text-success'
                    d._delai_icon = 'bi-check-circle-fill'
                elif restant < 0:
                    d._delai_label = f'En retard (+{abs(restant)} j)'
                    d._delai_class = 'text-danger'
                    d._delai_icon = 'bi-exclamation-triangle-fill'
                elif restant == 0:
                    d._delai_label = "Aujourd'hui"
                    d._delai_class = 'text-warning'
                    d._delai_icon = 'bi-clock'
                else:
                    d._delai_label = f'{restant} j'
                    d._delai_class = 'text-success'
                    d._delai_icon = 'bi-clock'
            else:
                # Échéance théorique : délai vers la prochaine échéance, sans statut Déclaré/En retard
                theo = prochaine_echeance_theorique(d, today)
                if theo:
                    restant = (theo - today).days
                    if restant == 0:
                        d._delai_label = "Aujourd'hui"
                        d._delai_class = 'text-warning'
                        d._delai_icon = 'bi-clock'
                    else:
                        d._delai_label = f'{restant} j'
                        d._delai_class = 'text-success'
                        d._delai_icon = 'bi-clock'
        elif d.date_limite_declaration:
            restant = (d.date_limite_declaration - today).days
            if restant < 0:
                d._delai_label = f'En retard (+{abs(restant)} j)'
                d._delai_class = 'text-danger'
                d._delai_icon = 'bi-exclamation-triangle-fill'
            elif restant == 0:
                d._delai_label = "Aujourd'hui"
                d._delai_class = 'text-warning'
                d._delai_icon = 'bi-clock'
            else:
                d._delai_label = f'{restant} j'
                d._delai_class = 'text-success'
                d._delai_icon = 'bi-clock'
        d._regime_norm = (d.regime_tva or '').lower()
        d._freq_norm = (d.frequence_tva or '').lower()
        d._date_iso = d.date_limite_declaration.strftime('%Y-%m-%d') if d.date_limite_declaration else ''
        d._echeances = prochaine_echeance_par_nature(d, today)
        # data-date-iso ← première échéance (pour le filtre date)
        if d._echeances:
            d._date_iso = d._echeances[0][0].strftime('%Y-%m-%d')
        # Combo régime + fréquence pour l'affichage et le filtre unifié
        _r = d._regime_norm
        _f = d._freq_norm
        if _r in ('mensuel', 'ca3') and _f not in ('trimestrielle', 'trimestriel'):
            d._regime_combo = 'ca3_mensuelle'
        elif _r == 'trimestriel' or (_r == 'ca3' and _f in ('trimestrielle', 'trimestriel')):
            d._regime_combo = 'ca3_trimestrielle'
        elif _r in ('annuel', 'ca12'):
            d._regime_combo = 'ca12_annuel'
        elif _r == 'exonere':
            d._regime_combo = 'exonere'
        else:
            d._regime_combo = ''
    
    # Construire les données JSON pour le modal d'édition
    dossiers_data = {}
    dossiers_par_collab = {}
    for d in all_dossiers:
        dossiers_data[d.id] = {
            'numero_dossier': d.numero_dossier,
            'intitule': d.intitule,
            'collaborateur_id': d.collaborateur_id,
            'equipe_id': d.equipe_id,
            'regime_tva': d.regime_tva,
            'frequence_tva': d.frequence_tva,
            'date_limite_declaration': d.date_limite_declaration.strftime('%Y-%m-%d') if d.date_limite_declaration else None,
            'date_acompte_1': d.date_acompte_1.strftime('%Y-%m-%d') if d.date_acompte_1 else None,
            'date_acompte_2': d.date_acompte_2.strftime('%Y-%m-%d') if d.date_acompte_2 else None,
            'regime_fiscale': d.regime_fiscale,
            'has_cfe': d.has_cfe,
            'forme_juridique': d.forme_juridique,
            'secteur_activite': d.secteur_activite,
            'siren': d.siren,
            'collaborateur_social_id': d.collaborateur_social_id,
            'tva_intra': d.tva_intra,
            'naf_code': d.naf_code,
            'effectif_label': d.effectif_label,
            'categorie_entreprise': d.categorie_entreprise,
            'dirigeant': d.dirigeant,
            'adresse_siege': d.adresse_siege,
            'date_creation_entreprise': d.date_creation_entreprise.strftime('%Y-%m-%d') if d.date_creation_entreprise else None,
            'pennylane_api_token_set': bool(d.pennylane_api_token),
        }
        if d.collaborateur_id:
            dossiers_par_collab[d.collaborateur_id] = dossiers_par_collab.get(d.collaborateur_id, 0) + 1

    membres_social_list = User.query.filter(
        User.pole.in_(['social', 'les_deux']), User.actif == True).order_by(User.nom).all()
    return render_template('dossiers.html', dossiers=all_dossiers, membres=membres,
        membres_social=membres_social_list,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db,
        show_actions=True, dossiers_data=dossiers_data, dossiers_par_collab=dossiers_par_collab)

@app.route('/tva-taches')
@login_required
def tva_taches():
    """Affiche la liste des t\u00e2ches TVA avec filtrage par statut."""
    statut_filter = request.args.get('statut', 'all')
    query = Tache.query.filter(
        db.or_(
            Tache.titre.like('%TVA%'),
            Tache.titre.like('%CA3%'),
            Tache.titre.like('%ca3%'),
            Tache.titre.like('%CA12%'),
            Tache.titre.like('%ca12%')
        )
    )
    if statut_filter != 'all':
        query = query.filter_by(statut=statut_filter)
    tva_taches = query.order_by(Tache.date_echeance.asc(), Tache.titre.asc()).all()

    base_filter = db.or_(
        Tache.titre.like('%TVA%'),
        Tache.titre.like('%CA3%'),
        Tache.titre.like('%ca3%'),
        Tache.titre.like('%CA12%'),
        Tache.titre.like('%ca12%')
    )
    total_taches = Tache.query.filter(base_filter).count()
    taches_a_faire = Tache.query.filter(base_filter, Tache.statut == 'a_faire').count()
    taches_en_cours = Tache.query.filter(base_filter, Tache.statut == 'en_cours').count()
    taches_terminees = Tache.query.filter(base_filter, Tache.statut == 'terminee').count()

    return render_template('tva_taches.html', tva_taches=tva_taches,
        statut_filter=statut_filter, total_taches=total_taches,
        taches_a_faire=taches_a_faire, taches_en_cours=taches_en_cours,
        taches_terminees=taches_terminees)

@app.route('/planifier_tous_impots', methods=['POST'])
@login_required
def planifier_tous_impots():
    """Endpoint pour planifier les impôts de TOUS les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Accès refusé.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_tous_les_dossiers
        planifier_tous_les_dossiers()
        flash('Planification des impôts pour tous les dossiers terminée avec succès.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur planification tous impôts: {e}")
        flash('Erreur lors de la planification.', 'danger')
    return redirect(url_for('dossiers'))

@app.route('/tva-planifier', methods=['POST'])
@login_required
def planifier_taches_tva():
    """Endpoint pour d\u00e9clencher la planification des t\u00e2ches TVA pour tous les dossiers."""
    if current_user.role not in ('admin', 'manager'):
        flash('Acc\u00e8s refus\u00e9.', 'danger')
        return redirect(url_for('dossiers'))
    try:
        from .tva_scheduler import planifier_impots_dossier
        from app.models import Dossier
        dossiers = Dossier.query.all()
        for dossier in dossiers:
            planifier_impots_dossier(dossier)
        flash('Planification des imp\u00f4ts (TVA, IS, CFE) termin\u00e9e avec succ\u00e8s.', 'success')
    except Exception as e:
        app.logger.error(f"Erreur lors de la planification des imp\u00f4ts: {e}")
        flash('Erreur lors de la planification des imp\u00f4ts.', 'danger')
    return redirect(url_for('dossiers'))
