"""avancement — suivi avancement + taches du jour (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/taches/aujourdhui')
@login_required
def taches_aujourdhui():
    """Tâches dont l'échéance est aujourd'hui (scoping : mes equipes / social)."""
    from .social_service import est_tache_sociale
    today_taches = Tache.query.filter(Tache.date_echeance == date.today()).all()
    if current_user.role == 'membre':
        mine = {current_user.id}
        today_taches = [t for t in today_taches if t.assigne_a in mine]
    elif current_user.role == 'manager':
        mes_eq = Equipe.query.filter_by(manager_id=current_user.id).all()
        ids = {current_user.id}
        for eq in mes_eq:
            ids.update(m.id for m in eq.membres.all())
        today_taches = [t for t in today_taches if t.assigne_a in ids]
    # pole social pur : uniquement les taches sociales
    social_only = (current_user.role not in ('admin', 'manager')
                   and (current_user.pole or '') == 'social')
    if social_only:
        today_taches = [t for t in today_taches if est_tache_sociale(t)]
    return render_template('taches.html', taches=today_taches, date=date, timedelta=timedelta,
                           social_only=social_only)

# ===========================
# Suivi d'avancement par membre
# ===========================
# API JSON : détails des tâches d'un membre (fenêtre "Tableau d'avancement")
@app.route('/suivi_avancement/api/membre/<int:membre_id>')
@login_required
def api_avancement_membre(membre_id):
    """Détails d'un membre pour la fenêtre d'avancement : tâches + compteurs.

    Isolation : admin = tout ; manager = membres de ses équipes (+ lui-même) ;
    membre = lui-même uniquement.
    """
    # Vérification du périmètre
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_ids = {current_user.id}
        for eq in mes_equipes:
            team_ids.update(m.id for m in eq.membres.all())
        if membre_id not in team_ids:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    elif current_user.role != 'admin':
        if membre_id != current_user.id:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    membre = User.query.get_or_404(membre_id)
    taches = Tache.query.filter_by(assigne_a=membre_id).order_by(Tache.date_echeance).all()

    def _t_json(t):
        return {
            'id': t.id,
            'titre': t.titre,
            'description': t.description or '',
            'dossier': t.dossier.numero_dossier if t.dossier else '',
            'dossier_id': t.dossier_id,
            'priorite': t.priorite,
            'statut': t.statut,
            'date_echeance': t.date_echeance.strftime('%Y-%m-%d') if t.date_echeance else None,
            'date_echeance_fr': t.date_echeance.strftime('%d/%m/%Y') if t.date_echeance else '-',
            'en_retard': bool(t.est_en_retard()),
            'recurrente': bool(t.frequence_repetition),
        }

    a_faire = [t for t in taches if t.statut == 'a_faire']
    en_cours = [t for t in taches if t.statut == 'en_cours']
    terminees = [t for t in taches if t.statut in ('terminee', 'terminée')]

    return jsonify({
        'ok': True,
        'membre': {
            'id': membre.id,
            'nom': f'{membre.prenom} {membre.nom}',
            'poste': membre.poste or membre.role,
            'photo': membre.photo_display_src(),
            'initiales': ((membre.prenom[:1] + (membre.nom[:1] or '')).upper()),
        },
        'compteurs': {
            'total': len(taches),
            'a_faire': len(a_faire),
            'en_cours': len(en_cours),
            'terminees': len(terminees),
            'en_retard': sum(1 for t in taches if t.est_en_retard()),
            'avancement': round(len(terminees) * 100 / len(taches)) if taches else 0,
        },
        'taches': [_t_json(t) for t in taches],
    })

# Ajout d'une tâche pour un membre depuis la fenêtre d'avancement (manager/admin)
@app.route('/suivi_avancement/ajouter_tache/<int:membre_id>', methods=['POST'])
@login_required
def avancement_ajouter_tache(membre_id):
    if current_user.role == 'membre' and membre_id != current_user.id:
        return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_ids = {current_user.id}
        for eq in mes_equipes:
            team_ids.update(m.id for m in eq.membres.all())
        if membre_id not in team_ids:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    titre = (request.form.get('titre') or '').strip()
    if not titre:
        return jsonify({'ok': False, 'error': 'Le titre est obligatoire'}), 400
    echeance_val = (request.form.get('date_echeance') or '').strip()
    if not echeance_val:
        return jsonify({'ok': False, 'error': "La date d'échéance est obligatoire"}), 400
    try:
        echeance = datetime.strptime(echeance_val, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'ok': False, 'error': "Date d'échéance invalide"}), 400

    t = Tache(
        titre=titre,
        description=(request.form.get('description') or '').strip() or None,
        assigne_a=membre_id,
        cree_par=current_user.id,
        priorite=(request.form.get('priorite') or 'moyenne').strip(),
        statut='a_faire',
        date_echeance=echeance,
    )
    if t.priorite not in ('haute', 'moyenne', 'basse'):
        t.priorite = 'moyenne'
    db.session.add(t)
    db.session.flush()
    # Notification in-app à l'assigné (pas d'email : ajout ponctuel depuis le pilotage)
    notif = Notification(user_id=membre_id, tache_id=t.id,
        message=f"Nouvelle tâche assignée : {t.titre}", type_notification='assignation')
    db.session.add(notif)
    db.session.commit()
    return jsonify({'ok': True, 'id': t.id, 'message': 'Tâche ajoutée'})

# Suppression d'une tâche depuis la fenêtre d'avancement (manager/admin)
@app.route('/suivi_avancement/supprimer_tache/<int:tache_id>', methods=['POST'])
@login_required
def avancement_supprimer_tache(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if current_user.role == 'membre':
        return jsonify({'ok': False, 'error': 'Seuls les managers et administrateurs peuvent supprimer'}), 403
    if current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_ids = {current_user.id}
        for eq in mes_equipes:
            team_ids.update(m.id for m in eq.membres.all())
        if tache.assigne_a not in team_ids:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403

    Notification.query.filter_by(tache_id=tache.id).delete()
    CommentaireTache.query.filter_by(tache_id=tache.id).delete()
    db.session.delete(tache)
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Tâche supprimée'})

# Gérer le changement de statut depuis le suivi
@app.route('/suivi_avancement')
@login_required
def suivi_avancement():
    """Page de suivi d'avancement des tâches par membre (+ échéancier annuel)."""
    from app.models import User, Equipe, Tache
    from datetime import date

    annee = request.args.get('annee', type=int) or date.today().year
    annees = sorted({date.today().year, date.today().year - 1, date.today().year - 2, date.today().year + 1}, reverse=True)

    # Récupérer les membres selon le rôle
    if current_user.role == 'admin':
        membres = User.query.filter_by(actif=True).order_by(User.prenom).all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_ids = [current_user.id]
        for eq in mes_equipes:
            team_ids.extend([m.id for m in eq.membres.all()])
        # Isolation par equipe : le manager ne voit que les membres de ses equipes
        membres = User.query.filter(User.id.in_(team_ids), User.actif==True).order_by(User.prenom).all()
    else:
        membres = [current_user]
    
    # Collecter les stats par membre
    suivi_data = []
    dossiers_par_membre = {}
    for m in membres:
        taches = Tache.query.filter_by(assigne_a=m.id).order_by(Tache.date_echeance).all()
        a_faire = [t for t in taches if t.statut == 'a_faire']
        en_cours = [t for t in taches if t.statut == 'en_cours']
        terminees = [t for t in taches if t.statut in ('terminee', 'terminée')]
        en_retard = [t for t in taches if t.est_en_retard()]
        # Dossiers uniques pour ce membre
        dossiers_ids = set()
        for t in taches:
            if t.dossier_id:
                dossiers_ids.add(t.dossier_id)
        dossiers_par_membre[m.id] = Dossier.query.filter(Dossier.id.in_(dossiers_ids)).order_by(Dossier.numero_dossier).all() if dossiers_ids else []
        # Nom de l'équipe du membre (affichage sur la carte)
        equipe_nom = m.equipe.nom if m.equipe else None
        # Pastilles fiscales TVA/IS/CFE (total, faits, en retard) — style matrice FollowApp
        def _cat_taxe(titre):
            tl = (titre or '').lower()
            if 'tva' in tl or 'ca3' in tl or 'ca12' in tl: return 'TVA'
            if 'cfe' in tl: return 'CFE'
            if 'liasse' in tl or 'impôt sur' in tl or tl.startswith('is ') or ' is ' in tl or tl.startswith('is-') or tl == 'is': return 'IS'
            return None
        taxes = {'TVA': [0, 0, 0], 'IS': [0, 0, 0], 'CFE': [0, 0, 0]}  # [total, fait, retard]
        for t in taches:
            k = _cat_taxe(t.titre)
            if k:
                taxes[k][0] += 1
                if t.statut in ('terminee', 'terminée'):
                    taxes[k][1] += 1
                elif t.est_en_retard():
                    taxes[k][2] += 1
        suivi_data.append({
            'membre': m,
            'equipe_nom': equipe_nom,
            'taxes': taxes,
            'total': len(taches),
            'a_faire': len(a_faire),
            'en_cours': len(en_cours),
            'terminees': len(terminees),
            'en_retard': len(en_retard),
            'toutes_taches': taches,  # toutes les tâches pour le tableau
            'taches_a_faire': a_faire[:10],
            'taches_en_cours': en_cours[:10],
            'taches_terminees': terminees[:5],
        })
    
    return render_template('suivi_avancement.html', suivi_data=suivi_data, membres=membres, dossiers_par_membre=dossiers_par_membre, annee=annee, annees=annees)

# Gérer le changement de statut depuis le suivi
@app.route('/suivi_avancement/changer_statut/<int:tache_id>', methods=['POST'])
@login_required
def suivi_changer_statut(tache_id):
    tache = Tache.query.get_or_404(tache_id)
    if current_user.role == 'membre' and tache.assigne_a != current_user.id:
        flash('Accès refusé.', 'danger')
        return redirect(url_for('suivi_avancement'))
    nouveau = request.form.get('statut', '').strip()
    if nouveau not in ('a_faire', 'en_cours', 'terminee'):
        flash('Statut invalide.', 'warning')
        return redirect(url_for('suivi_avancement'))
    tache.statut = nouveau
    if nouveau == 'terminee':
        tache.date_completion = datetime.utcnow()
    elif nouveau == 'a_faire':
        tache.date_completion = None
        tache.date_prise_en_charge = None
    elif nouveau == 'en_cours' and not tache.date_prise_en_charge:
        tache.date_prise_en_charge = datetime.utcnow()
    db.session.commit()
    # LIAISON tache -> checklist (meme logique que changer_statut_tache)
    try:
        from .checklist_link import appliquer_tache_a_case
        if appliquer_tache_a_case(tache):
            db.session.commit()
    except Exception as _lk_e:
        db.session.rollback()
        app.logger.warning(f"Liaison tache->case (suivi): {_lk_e}")

    # Notifier le créateur (manager) : notif in-app toujours, email si tâche urgente
    # (même logique que le reste de l'app : économie quota Brevo).
    cree_par_id = tache.cree_par
    if not cree_par_id and tache.dossier and tache.dossier.equipe and tache.dossier.equipe.manager:
        cree_par_id = tache.dossier.equipe.manager.id
    if cree_par_id and cree_par_id != current_user.id:
        collab_nom = f"{current_user.prenom} {current_user.nom}".strip()
        notif = Notification(
            user_id=cree_par_id,
            tache_id=tache.id,
            message=f"{collab_nom} a changé le statut de \"{tache.titre}\" à \"{nouveau.replace('_', ' ')}\"",
            type_notification='systeme'
        )
        db.session.add(notif)
        db.session.commit()
        # Email au créateur (manager) : TOUJOURS (quelle que soit la priorité).
        dest_user = User.query.get(cree_par_id)
        if dest_user and dest_user.email:
            try:
                from app.integrations.brevo import send_email_via_brevo_api
                sujet = f"Changement de statut : {tache.titre}"
                corps = f"Bonjour {dest_user.prenom},\n\n{collab_nom} a changé le statut de la tâche \"{tache.titre}\" à \"{nouveau.replace('_', ' ')}\".\n\nCabinet JMH"
                envoye = send_email_via_brevo_api(to_email=dest_user.email, subject=sujet, body=corps)
                app.logger.info(f"Email statut change (suivi) to {dest_user.email}: {'OK' if envoye else 'ECHEC'}")
            except Exception as e:
                app.logger.warning(f"Email statut change (suivi) error: {e}")

    flash(f'Statut changé.', 'success')
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify({'ok': True})
    return redirect(url_for('suivi_avancement'))

@app.route('/api/suivi_membre/<int:membre_id>')
@login_required
def api_suivi_membre(membre_id):
    """API pour le suivi avec filtres JSON."""
    from app.models import Tache
    
    if current_user.role == 'membre' and current_user.id != membre_id:
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    
    statut = request.args.get('statut', 'all')
    debut = request.args.get('debut', '')
    fin = request.args.get('fin', '')
    
    query = Tache.query.filter_by(assigne_a=membre_id)
    
    if statut != 'all':
        query = query.filter(Tache.statut == statut)
    
    if debut:
        try:
            d_debut = datetime.strptime(debut, '%Y-%m-%d').date()
            query = query.filter(Tache.date_echeance >= d_debut)
        except ValueError:
            pass
    if fin:
        try:
            d_fin = datetime.strptime(fin, '%Y-%m-%d').date()
            query = query.filter(Tache.date_echeance <= d_fin)
        except ValueError:
            pass
    
    taches = query.order_by(Tache.date_echeance).all()
    
    return jsonify({
        'ok': True,
        'taches': [{
            'id': t.id,
            'titre': t.titre,
            'statut': t.statut,
            'priorite': t.priorite,
            'date_echeance': t.date_echeance.strftime('%d/%m/%Y') if t.date_echeance else '',
            'en_retard': t.est_en_retard(),
            'dossier': t.dossier.numero_dossier if t.dossier else '',
        } for t in taches]
    })

@app.route('/api/envoyer_notifications_echeances')
@login_required
def envoyer_notifications_echeances():
    """Envoyer les notifications par email pour les tâches fiscales échéant aujourd'hui."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    
    from app.integrations.brevo import send_task_assigned_email_brevo
    fiscal_keywords = ['tva', 'is ', 'cfe ', 'acompte', 'dépôt', 'préparation', 'déclaration', 'prépa']
    
    tasks = Tache.query.filter(Tache.date_echeance == date.today()).all()
    sent = 0
    for t in tasks:
        titre = (t.titre or '').lower()
        is_fiscal = any(kw in titre for kw in fiscal_keywords)
        if is_fiscal and t.assigne_a and t.statut != 'terminee':
            try:
                send_task_assigned_email_brevo(t, t.assigne_a)
                sent += 1
            except Exception as e:
                app.logger.warning(f"Send due notification failed: {e}")
    
    return jsonify({'ok': True, 'message': f'{sent} notification(s) envoyée(s).'})
