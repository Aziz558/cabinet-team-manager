"""admin — profil, reset admin, photos admin, debug (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/reset-admin', methods=['GET', 'POST'])
def reset_admin():
    if request.method == 'POST':
        reset_key = request.form.get('reset_key')
        new_password = request.form.get('new_password')
        if reset_key == 'cabinet-jmh-reset-2024':
            admin = User.query.filter_by(email='admin@cabinet-jmh.com').first()
            if admin:
                from werkzeug.security import generate_password_hash
                admin.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Mot de passe admin r\u00e9initialis\u00e9 avec succ\u00e8s.', 'success')
                return redirect(url_for('login'))
            else:
                flash('Compte admin introuvable.', 'danger')
        else:
            flash('Cl\u00e9 de r\u00e9initialisation invalide.', 'danger')
    return render_template('reset_admin.html')

@app.route('/admin/assign_photo/<email>')
@login_required
def admin_assign_photo(email):
    """Assigner une photo à un utilisateur par email (depuis static/uploads/)."""
    if current_user.role != 'admin':
        flash('Accès refusé.', 'danger')
        return redirect(url_for('membres'))
    photo = request.args.get('photo', '')
    if not photo:
        flash('Paramètre photo manquant. Utilisez ?photo=nom_fichier.png', 'warning')
        return redirect(url_for('membres'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash(f'Utilisateur {email} introuvable.', 'danger')
        return redirect(url_for('membres'))
    user.photo_profil = photo
    db.session.commit()
    flash(f'Photo {photo} assignée à {user.prenom} {user.nom}', 'success')
    return redirect(url_for('fiche_membre', user_id=user.id))

@app.route('/api/set_photo', methods=['POST'])
@login_required
def api_set_photo():
    """API admin pour assigner une photo à un utilisateur par email."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé'}), 403
    email = request.form.get('email') or (request.get_json() or {}).get('email')
    photo = request.form.get('photo') or (request.get_json() or {}).get('photo')
    if not email or not photo:
        return jsonify({'ok': False, 'message': 'email et photo requis'}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'message': 'Utilisateur introuvable'}), 404
    user.photo_profil = photo
    db.session.commit()
    return jsonify({'ok': True, 'message': f'Photo {photo} assignée à {email}'})

@app.route('/admin_debug')
@login_required
def admin_debug():
    if current_user.role != 'admin':
        flash('Accès réservé aux administrateurs.', 'danger')
        return redirect(url_for('dossiers'))
    return render_template('admin_debug.html')

# ==========================
# Tableau de bord fiscal
# ==========================
