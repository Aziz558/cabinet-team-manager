"""suggestions — suggestions de taches (LLM/mail) (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/suggestions')
@login_required
def suggestions_page():
    """Page de suggestions - version corrigée."""
    from app.models import Suggestion, User, Equipe
    from app import db
    
    if current_user.role == 'admin':
        suggestions_list = Suggestion.query.order_by(Suggestion.date_creation.desc()).all()
    elif current_user.role == 'manager':
        mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
        team_member_ids = [current_user.id]
        for eq in mes_equipes:
            team_member_ids.extend([m.id for m in eq.membres.all()])
        suggestions_list = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).all()
    else:
        suggestions_list = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).all()
    
    # Pass users and dossiers for the modal form
    all_users = User.query.filter_by(actif=True).order_by(User.nom).all()
    all_dossiers = Dossier.query.order_by(Dossier.numero_dossier).all()
    
    return render_template('suggestions.html', suggestions=suggestions_list, users=all_users, dossiers=all_dossiers)

@app.route('/api/suggestions', methods=['GET'])
@login_required
def api_suggestions():
    """API pour récupérer les suggestions au format JSON."""
    try:
        from app.models import Suggestion
        status_filter = request.args.get('status', 'all')
        
        if current_user.role == 'admin':
            query = Suggestion.query
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            query = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids))
        else:
            query = Suggestion.query.filter_by(cree_par=current_user.id)
        
        if status_filter in ('en_attente', 'validee', 'rejetee'):
            query = query.filter_by(statut=status_filter)
        
        items = query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        
        return jsonify({
            'ok': True,
            'suggestions': [{
                'id': s.id,
                'titre': s.titre,
                'titre_suggere': s.titre_suggere or s.titre,
                'sujet': s.sujet,
                'description_suggeree': s.description_suggeree or s.description,
                'priorite_suggeree': s.priorite_suggeree or s.priorite or 'moyenne',
                'statut': s.statut or 'en_attente',
                'date_creation': s.date_creation.strftime('%d/%m/%Y') if s.date_creation else None,
                'date_echeance': s.date_echeance.strftime('%d/%m/%Y') if s.date_echeance else None,
                'dossier_nom': f"{s.dossier.numero_dossier} - {s.dossier.intitule}" if s.dossier_id else None,
                'dossier_id': s.dossier_id,
                'assigne_a': s.assigne_a,
                'source': s.source,
                'mail_uid': s.mail_uid
            } for s in items]
        })
    except Exception as e:
        app.logger.error(f"api_suggestions error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh', methods=['POST'])
@login_required
def api_suggestions_refresh():
    """Endpoint pour rafraîchir les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            items = Suggestion.query.order_by(Suggestion.date_creation.desc()).limit(20).all()
        elif current_user.role == 'manager':
            mes_equipes = Equipe.query.filter_by(manager_id=current_user.id).all()
            team_member_ids = [current_user.id]
            for eq in mes_equipes:
                team_member_ids.extend([m.id for m in eq.membres.all()])
            items = Suggestion.query.filter(Suggestion.cree_par.in_(team_member_ids)).order_by(Suggestion.date_creation.desc()).limit(20).all()
        else:
            items = Suggestion.query.filter_by(cree_par=current_user.id).order_by(Suggestion.date_creation.desc()).limit(20).all()
        return jsonify({'ok': True, 'suggestions': [{'id': s.id, 'titre': s.titre} for s in items]})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/validate', methods=['POST'])
@login_required
def api_suggestions_validate(suggestion_id):
    """Valider une suggestion et créer la tâche correspondante."""
    try:
        from app.models import Suggestion, Tache
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        data = request.get_json() or {}
        
        assignee = data.get('assignee') or suggestion.assigne_a
        due_date = data.get('due_date')
        if due_date:
            due_date = datetime.strptime(due_date, '%Y-%m-%d').date()
        priority = data.get('priority') or suggestion.priorite or 'moyenne'
        dossier_id = data.get('dossier_id') or suggestion.dossier_id
        
        titre = suggestion.titre_suggere or suggestion.titre or 'Tâche depuis suggestion'
        description = suggestion.description_suggeree or suggestion.description or ''
        
        nouvelle_tache = Tache(
            titre=titre,
            description=description,
            assigne_a=int(assignee) if assignee else None,
            dossier_id=int(dossier_id) if dossier_id else None,
            priorite=priority,
            date_echeance=due_date,
            statut='a_faire',
            cree_par=current_user.id
        )
        db.session.add(nouvelle_tache)
        suggestion.statut = 'validee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Tâche créée avec succès'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"validate suggestion error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reject', methods=['POST'])
@login_required
def api_suggestions_reject(suggestion_id):
    """Rejeter une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        suggestion.statut = 'rejetee'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion rejetée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/reanalyze', methods=['POST'])
@login_required
def api_suggestions_reanalyze(suggestion_id):
    """Relancer l'analyse IA sur une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        # Pour l'instant, juste marquer comme ré-analysé
        suggestion.statut = 'en_attente'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Analyse relancée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/<int:suggestion_id>/delete', methods=['DELETE'])
@login_required
def api_suggestions_delete(suggestion_id):
    """Supprimer une suggestion."""
    try:
        from app.models import Suggestion
        suggestion = Suggestion.query.get_or_404(suggestion_id)
        db.session.delete(suggestion)
        db.session.commit()
        return jsonify({'ok': True, 'message': 'Suggestion supprimée'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/reset', methods=['POST'])
@login_required
def api_suggestions_reset():
    """Réinitialiser toutes les suggestions."""
    try:
        from app.models import Suggestion
        if current_user.role == 'admin':
            Suggestion.query.delete()
            db.session.commit()
            return jsonify({'ok': True, 'message': 'Toutes les suggestions ont été supprimées'})
        else:
            return jsonify({'ok': False, 'error': 'Accès refusé'}), 403
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/suggestions/refresh_mailbox', methods=['POST'])
@login_required
def api_suggestions_refresh_mailbox():
    """Scanner la mailbox pour générer de nouvelles suggestions."""
    try:
        # Pour l'instant, retourne un message indiquant que la fonctionnalité n'est pas encore implémentée
        return jsonify({'ok': True, 'message': 'Scan de la mailbox non implémenté. Aucune nouvelle suggestion.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ==========================
# Routes s\u00e9curit\u00e9 (stubs fonctionnels)
# ==========================
