"""auth — index, login, logout, team-select, dashboard (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.actif:
                flash('Votre compte est d\u00e9sactiv\u00e9. Contactez le manager.', 'danger')
                return redirect(url_for('login'))
            login_user(user, remember=True)
            next_page = request.args.get('next')
            flash(f'Bienvenue, {user.prenom} !', 'success')
            return redirect(next_page or url_for('dashboard'))
        else:
            flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('D\u00e9connexion r\u00e9ussie.', 'info')
    return redirect(url_for('login'))

@app.route('/team-select')
def team_select():
    equipes = Equipe.query.order_by(Equipe.nom).all()
    return render_template('team_select.html', equipes=equipes)

@app.route('/dashboard')
@login_required
def dashboard():
    from datetime import timedelta

    # Horizon 3 mois pour les tâches
    horizon_3m = date.today() + timedelta(days=95)
    week_end = date.today() + timedelta(days=7)

    def _pl_triage_stats(ids):
        """Récap triage Pennylane par dossier (factures/transactions À TRAITER).
        Retourne None si rien à afficher (aucun item vu)."""
        if not ids:
            return None
        from app.models import PennylaneItem
        rows = db.session.query(
            PennylaneItem.dossier_id,
            PennylaneItem.item_type,
            PennylaneItem.statut,
            db.func.count(PennylaneItem.id),
            db.func.coalesce(db.func.sum(PennylaneItem.montant), 0.0),
        ).filter(
            PennylaneItem.dossier_id.in_(ids),
            PennylaneItem.statut == 'a_traiter',
        ).group_by(PennylaneItem.dossier_id, PennylaneItem.item_type, PennylaneItem.statut).all()
        by_do = {}
        for did, itype, _st, cnt, mt in rows:
            e = by_do.setdefault(did, {'vente': 0, 'achat': 0, 'banque': 0, 'total': 0})
            key = {'facture_vente': 'vente', 'facture_achat': 'achat', 'transaction': 'banque'}.get(itype)
            if key:
                e[key] += cnt
                e['total'] += cnt
        if not by_do:
            return None
        items = []
        for did, e in by_do.items():
            d = Dossier.query.get(did)
            if not d:
                continue
            items.append({
                'dossier': d,
                'total': e['total'],
                'vente_n': e['vente'], 'achat_n': e['achat'], 'banque_n': e['banque'],
            })
        items.sort(key=lambda x: -x['total'])
        return {
            'lignes': items,
            'total': sum(i['total'] for i in items),
        }
    
    if current_user.role == 'manager':
        # Compute real KPIs for manager
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))

        membres_actifs = User.query.filter(User.id.in_(team_member_ids), User.actif==True).count()
        all_dossiers_ids = [d.id for d in Dossier.query.filter(Dossier.collaborateur_id.in_(team_member_ids)).all()]
        dossiers_en_cours = len(all_dossiers_ids)
        
        taches_retard = 0
        taches_haute_priorite = 0
        total_taches = 0
        if all_dossiers_ids:
            taches_query = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance <= horizon_3m
            )
            total_taches = taches_query.count()
            taches_retard = taches_query.filter(Tache.date_echeance < date.today(), Tache.statut != 'terminee').count()
            taches_haute_priorite = taches_query.filter_by(priorite='haute', statut='a_faire').count()
        
        taux_completion = 0
        if total_taches > 0:
            terminees = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance <= horizon_3m,
                Tache.statut == 'terminee'
            ).count()
            taux_completion = int(terminees / total_taches * 100)

        kpi = {
            'membres_actifs': membres_actifs,
            'dossiers_en_cours': dossiers_en_cours,
            'taches_retard': taches_retard,
            'taches_haute_priorite': taches_haute_priorite,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }

        # Alertes : tâches en retard dans les 3 mois
        alertes = []
        if all_dossiers_ids:
            taches_en_retard = Tache.query.filter(
                Tache.dossier_id.in_(all_dossiers_ids),
                Tache.date_echeance.between(date.today() - timedelta(days=60), date.today()),
                Tache.statut != 'terminee'
            ).order_by(Tache.date_echeance.asc()).limit(5).all()
            for t in taches_en_retard:
                d = Dossier.query.get(t.dossier_id)
                alertes.append({'tache': t, 'dossier': d})

        # Suggestions
        suggestions = []
        try:
            from app.models import Suggestion
            suggestions = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))\
                .order_by(Suggestion.date_creation.desc()).limit(10).all()
        except Exception:
            suggestions = []

        membres = User.query.filter(User.id.in_(team_member_ids), User.actif==True).order_by(User.nom).all()
        
        taches_jour = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today(),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.priorite.desc()).all()
        
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.date_echeance.asc()).all()

        # Notifications non lues
        notifications_non_lues = []
        try:
            notifications_non_lues = current_user.notifications.filter_by(lu=False).order_by(Notification.date_envoi.desc()).limit(5).all() if hasattr(current_user, 'notifications') else []
        except Exception:
            notifications_non_lues = []

        return render_template('dashboard_manager.html', kpi=kpi, alertes=alertes,
            suggestions=suggestions, membres=membres, taches_jour=taches_jour,
            taches_semaine=taches_semaine, notifications_non_lues=notifications_non_lues,
            horizon_3m=horizon_3m, pl_triage=_pl_triage_stats(all_dossiers_ids))
    else:
        # Dashboard collaborateur
        team_member_ids = [current_user.id]
        mes_equipes = current_user.equipes.filter_by(actif=True).all() if hasattr(current_user, 'equipes') else []
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        team_member_ids = list(set(team_member_ids))
        
        total_taches = Tache.query.filter(Tache.assigne_a.in_(team_member_ids), Tache.date_echeance <= horizon_3m).count()
        taches_auj = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance == date.today()
        ).count()
        terminees = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance <= horizon_3m,
            Tache.statut == 'terminee'
        ).count()
        taux_completion = int(terminees / total_taches * 100) if total_taches > 0 else 0

        taches_jour = Tache.query.filter(
            Tache.assigne_a == current_user.id,
            Tache.date_echeance == date.today(),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.priorite.desc()).all()
        taches_semaine = Tache.query.filter(
            Tache.assigne_a.in_(team_member_ids),
            Tache.date_echeance.between(date.today(), week_end),
            Tache.statut.in_(['a_faire', 'en_cours'])
        ).order_by(Tache.date_echeance.asc()).all()

        kpi = {
            'taches_aujourdhui': taches_auj,
            'taux_completion': taux_completion,
            'total_taches': total_taches
        }
        # Triage Pennylane : admin voit tout, collaborateur voit ses dossiers
        if current_user.role == 'admin':
            pl_dossier_ids = [d.id for d in Dossier.query.all()]
        else:
            pl_dossier_ids = [d.id for d in Dossier.query.filter(
                Dossier.collaborateur_id.in_(team_member_ids)).all()]
        return render_template('dashboard_collaborateur.html', kpi=kpi,
            taches_jour=taches_jour, taches_semaine=taches_semaine,
            pl_triage=_pl_triage_stats(pl_dossier_ids))
