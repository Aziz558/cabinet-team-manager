"""admin — profil, reset admin, photos admin, debug (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_login import login_required, current_user
from . import app, db
from .models import User
import os
import time
from datetime import datetime

# Limitation des tentatives sur /reset-admin : mémoire du process (suffisant
# pour une route de secours ; le but est d'arrêter le balayage de clés).
_RESET_TENTATIVES = {}
_RESET_FENETRE = 15 * 60
_RESET_MAX = 5


def _reset_dans_la_limite(ip: str) -> bool:
    """True si cette IP peut encore tenter une réinitialisation."""
    maintenant = time.time()
    essais = [t for t in _RESET_TENTATIVES.get(ip, []) if maintenant - t < _RESET_FENETRE]
    essais.append(maintenant)
    _RESET_TENTATIVES[ip] = essais
    return len(essais) <= _RESET_MAX

@app.route('/profil')
@login_required
def profil():
    return render_template('profil.html')

@app.route('/reset-admin', methods=['GET', 'POST'])
def reset_admin():
    """Récupération d'accès administrateur — DÉSACTIVÉE par défaut.

    Cette route existe pour le cas « plus personne ne peut se connecter en
    admin ». Elle ne doit JAMAIS être utilisable sans secret côté serveur :

    - la clé vient de la variable d'environnement ``ADMIN_RESET_KEY`` ;
    - sans cette variable, la route répond 404 (elle n'existe pas) ;
    - comparaison à temps constant (pas de fuite par timing) ;
    - 5 tentatives maximum par IP et par quart d'heure ;
    - tout succès ET tout échec est journalisé.

    Avant le 2026-11-07 la clé était écrite en dur dans ce fichier : le dépôt
    étant public, n'importe qui pouvait réinitialiser le mot de passe admin de
    la production. La clé littérale a été supprimée du code (et de l'historique
    visible) — elle ne doit jamais y revenir.
    """
    cle_attendue = (os.environ.get('ADMIN_RESET_KEY') or '').strip()
    if not cle_attendue:
        abort(404)

    if request.method == 'POST':
        import hmac
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '?').split(',')[0].strip()
        if not _reset_dans_la_limite(ip):
            app.logger.warning('reset-admin : trop de tentatives depuis %s', ip)
            flash('Trop de tentatives. Réessaie dans un quart d’heure.', 'danger')
            return render_template('reset_admin.html'), 429

        reset_key = (request.form.get('reset_key') or '').strip()
        new_password = request.form.get('new_password') or ''

        if not hmac.compare_digest(reset_key, cle_attendue):
            app.logger.warning('reset-admin : clé invalide depuis %s', ip)
            flash('Clé de réinitialisation invalide.', 'danger')
        elif len(new_password) < 12:
            flash('Le nouveau mot de passe doit contenir au moins 12 caractères.', 'danger')
        else:
            admin = User.query.filter_by(email='admin@cabinet-jmh.com').first()
            if admin:
                from werkzeug.security import generate_password_hash
                admin.password_hash = generate_password_hash(new_password)
                db.session.commit()
                app.logger.warning('reset-admin : mot de passe admin réinitialisé depuis %s', ip)
                flash('Mot de passe admin réinitialisé avec succès.', 'success')
                return redirect(url_for('login'))
            app.logger.warning('reset-admin : compte admin introuvable (depuis %s)', ip)
            flash('Compte admin introuvable.', 'danger')
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
