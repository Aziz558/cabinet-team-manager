"""taches — liste/creation de taches (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/taches', methods=['GET', 'POST'])
@login_required
def taches():
    """Affiche la liste des tâches et gère la création."""
    if request.method == 'POST':
        titre = request.form.get('titre', '').strip()
        if not titre:
            flash('Le titre est obligatoire.', 'warning')
            return redirect(url_for('taches'))
        # Isolation par equipe : valider assigne_a et dossier_id selon le role
        assigne_a = request.form.get('assigne_a', type=int) or None
        dossier_id = request.form.get('dossier_id', type=int) or None
        if current_user.role == 'membre':
            # Un membre assigne uniquement a lui-meme et a un dossier de son perimetre
            if assigne_a and assigne_a != current_user.id:
                flash('Vous ne pouvez assigner une tâche qu\u2019à vous-même.', 'danger')
                return redirect(url_for('taches'))
            if dossier_id:
                d = Dossier.query.get(dossier_id)
                if not d or d.collaborateur_id != current_user.id:
                    flash('Dossier hors de votre périmètre.', 'danger')
                    return redirect(url_for('taches'))
        elif current_user.role == 'manager':
            team_ids = {current_user.id}
            for eq in Equipe.query.filter_by(manager_id=current_user.id).all():
                team_ids.update(m.id for m in eq.membres.all())
            if assigne_a and assigne_a not in team_ids:
                flash('Assignation refusée : ce membre ne fait pas partie de vos équipes.', 'danger')
                return redirect(url_for('taches'))
            if dossier_id:
                d = Dossier.query.get(dossier_id)
                if d and d.collaborateur_id and d.collaborateur_id not in team_ids:
                    flash('Dossier hors de votre périmètre.', 'danger')
                    return redirect(url_for('taches'))
        t = Tache(
            titre=titre,
            description=request.form.get('description', '').strip(),
            dossier_id=dossier_id,
            assigne_a=assigne_a,
            priorite=request.form.get('priorite', 'moyenne'),
            statut=request.form.get('statut', 'a_faire'),
            date_echeance=datetime.strptime(request.form['date_echeance'], '%Y-%m-%d').date() if request.form.get('date_echeance') else None,
            cree_par=current_user.id,
            frequence_repetition=request.form.get('frequence_repetition') or None,
        )
        # Date de fin de répétition
        fin_repetition_val = request.form.get('fin_repetition')
        if fin_repetition_val:
            try:
                t.fin_repetition = datetime.strptime(fin_repetition_val, '%Y-%m-%d').date()
            except ValueError:
                pass
        db.session.add(t)
        db.session.flush()  # pour obtenir t.id avant de pré-générer les occurrences
        
        # Pré-générer les occurrences récurrentes (horizon 1 mois comme les deadlines)
        if t.frequence_repetition and t.date_echeance:
            max_date = date.today() + timedelta(days=30)
            if t.fin_repetition and t.fin_repetition < max_date:
                max_date = t.fin_repetition
            next_date = t.date_echeance
            for _ in range(36):  # sécurité : max 36 occurrences
                if t.frequence_repetition == 'daily':
                    next_date += timedelta(days=1)
                elif t.frequence_repetition == 'weekly':
                    next_date += timedelta(weeks=1)
                elif t.frequence_repetition == 'monthly':
                    m = next_date.month + 1
                    y = next_date.year
                    if m > 12: m = 1; y += 1
                    try:
                        next_date = date(y, m, t.date_echeance.day)
                    except ValueError:
                        next_date = date(y, m, min(t.date_echeance.day, 28))
                elif t.frequence_repetition == 'yearly':
                    try:
                        next_date = date(next_date.year + 1, next_date.month, next_date.day)
                    except ValueError:
                        next_date = date(next_date.year + 1, next_date.month, 28)
                else:
                    break
                if next_date > max_date:
                    break
                new_t = Tache(
                    titre=t.titre, description=t.description,
                    dossier_id=t.dossier_id, assigne_a=t.assigne_a,
                    priorite=t.priorite, statut='a_faire',
                    date_echeance=next_date, cree_par=t.cree_par,
                    frequence_repetition=t.frequence_repetition,
                    fin_repetition=t.fin_repetition,
                    template_id=t.id,
                )
                db.session.add(new_t)
                # Notifier l'assigné
                if new_t.assigne_a:
                    from app.models import Notification as NotifCls
                    notif = NotifCls(user_id=new_t.assigne_a, tache_id=new_t.id,
                        message=f"Nouvelle occurrence : {new_t.titre}", type_notification='assignation')
                    db.session.add(notif)
            db.session.commit()
        db.session.commit()
        
        # Notification email + in-app
        fiscal_keywords = ['tva', 'is ', 'cfe ', 'acompte', 'dépôt', 'préparation', 'déclaration', 'prépa']
        is_fiscal = any(kw in titre.lower() for kw in fiscal_keywords)
        
        if t.assigne_a:
            # Vérifier si c'est une tâche de deadline antérieure → auto-terminée
            if is_fiscal and t.date_echeance and t.date_echeance < date.today():
                t.statut = 'terminee'
                t.date_completion = datetime.utcnow()
                db.session.commit()
            # Créer notification in-app
            notif_msg = f"Nouvelle tâche assignée : {t.titre}"
            notif = Notification(user_id=t.assigne_a, tache_id=t.id, message=notif_msg, type_notification='assignation')
            db.session.add(notif)
            db.session.commit()
            
            # Email d'assignation : UNIQUEMENT pour les tâches urgentes (priorité haute).
            # Les autres priorités → notification in-app seulement (économie quota Brevo).
            # Pour rappeler une tâche non urgente : bouton 🔔 sur la carte (email + notif).
            if t.priorite == 'haute':
                try:
                    from app.integrations.brevo import send_task_assigned_email_brevo
                    send_task_assigned_email_brevo(t, t.assigne_a)
                except Exception as e:
                    app.logger.warning(f"Send email failed: {e}")
        
        flash('Tâche créée avec succès.', 'success')
        return redirect(url_for('taches'))
    
    current_equipe = None
    all_equipes_for_switch = []
    membres = []

    if current_user.role == 'admin':
        equipe_id = session.get('current_equipe_id')
        if equipe_id:
            equipe = Equipe.query.get(equipe_id)
            current_equipe = equipe
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            team_user_ids = [m.id for m in equipe.membres.all()] if equipe else []
            membres = User.query.filter(User.id.in_(team_user_ids), User.actif==True).all()
            all_taches = Tache.query.filter(Tache.assigne_a.in_(team_user_ids)).all() if team_user_ids else []
        else:
            current_equipe = None
            all_equipes_for_switch = Equipe.query.order_by(Equipe.nom).all()
            membres = User.query.filter_by(actif=True).all()
            all_taches = Tache.query.all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()
    else:
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        all_equipes_for_switch = mes_equipes
        current_equipe = None
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).all()
        all_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids)).all()

    # Pole social pur : ne voir que les taches sociales (DSN, paie, RH) — filtre dur
    social_only = (current_user.role not in ('admin', 'manager')
                   and (current_user.pole or '') == 'social')
    if social_only:
        from .social_service import est_tache_sociale
        all_taches = [t for t in all_taches if est_tache_sociale(t)]

    return render_template('taches.html', taches=all_taches, membres=membres,
        equipes=Equipe.query.order_by(Equipe.nom).all(), Tache=Tache,
        current_equipe=current_equipe, all_equipes_for_switch=all_equipes_for_switch, db=db,
        dossiers=Dossier.query.order_by(Dossier.numero_dossier).all(),
        dossier_filtre=request.args.get('dossier', type=int),
        social_only=social_only,
        date=date, timedelta=timedelta)
