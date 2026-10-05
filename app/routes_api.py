"""api — settings + API (mail, notifier, recherche globale) (extrait de app/routes.py)."""
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from . import app, db
from .models import User, Equipe, Dossier, Tache, Notification, CommentaireTache, SuggestionTache, PennylaneItem
from sqlalchemy import or_
import json
import os
import re  # sonde v11 (temporaire)
from datetime import date, datetime, timedelta

@app.route('/settings')
@login_required
def settings():
    """Page réglages (admin) : SMTP, Brevo, OpenRouter, mailbox."""
    if current_user.role != 'admin':
        return redirect(url_for('profil'))
    from app.models import AppSetting
    return render_template('settings.html', settings=AppSetting.query.all())


@app.route('/api/settings', methods=['GET', 'POST'])
@login_required
def api_settings():
    """GET : liste des réglages. POST : enregistre un réglage (admin)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
    from app.models import AppSetting
    if request.method == 'GET':
        return jsonify({'ok': True, 'settings': [
            {'cle': s.cle, 'valeur': ('••••••••' if s.masque else (s.valeur or '')), 'masque': bool(s.masque)}
            for s in AppSetting.query.all()
        ]})
    data = request.get_json(silent=True) or {}
    cle = (data.get('cle') or '').strip()
    if not cle:
        return jsonify({'ok': False, 'message': 'Clé manquante.'}), 400
    setting = AppSetting.query.filter_by(cle=cle).first()
    if setting is None:
        setting = AppSetting(cle=cle)
        db.session.add(setting)
    valeur = data.get('valeur')
    if valeur is not None:
        setting.valeur = str(valeur)
    setting.service = data.get('service') or setting.service or 'general'
    setting.type_valeur = data.get('type_valeur') or setting.type_valeur or 'string'
    setting.masque = bool(data.get('masque', setting.masque))
    db.session.commit()
    return jsonify({'ok': True, 'cle': cle})


@app.route('/api/test/mail', methods=['POST'])
@login_required
def api_test_mail():
    """Envoie un email de test à l'utilisateur connecté (Brevo, fallback SMTP)."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
    if not current_user.email:
        return jsonify({'ok': False, 'message': 'Aucun email sur votre compte.'})
    from app.integrations.brevo import send_email_via_brevo_api, get_brevo_api_key
    has_key = bool(get_brevo_api_key())
    ok = send_email_via_brevo_api(
        to_email=current_user.email,
        subject='✅ Test notification — Cabinet JMH',
        body=f"Bonjour {current_user.prenom}, ceci est un email de test de l'application de gestion.",
        html_content='<html><body style="font-family:Inter,sans-serif;background:#0a0a0a;color:#e8e8e8;padding:24px;">'
                     '<h2 style="color:#FF8C00;">✅ Email de test</h2>'
                     f'<p>Bonjour {current_user.prenom}, la configuration mail de l\'application fonctionne.</p>'
                     '</body></html>',
    )
    return jsonify({
        'ok': ok,
        'brevo_key': has_key,
        'message': ('Email de test envoyé à ' + current_user.email) if ok
                   else ('Échec envoi — ' + ('vérifiez la clé Brevo (clé absente)' if not has_key else 'vérifiez la clé Brevo et les logs Render')),
    })

@app.route('/api/taches/<int:tache_id>/notifier', methods=['POST'])
@login_required
def notifier_tache(tache_id):
    """Bouton 🔔 de la carte tâche : notifie manuellement l'assigné.

    Envoie un email Brevo à l'assigné + crée une notification in-app.
    Réservé aux managers et admins. Idempotent : le spam de clics est ignoré
    (1 email max par 60 s et par tâche) pour économiser le quota Brevo.
    """
    if current_user.role not in ('admin', 'manager'):
        return jsonify({'ok': False, 'message': 'Accès refusé.'}), 403
    tache = Tache.query.get_or_404(tache_id)
    if not tache.assigne_a:
        return jsonify({'ok': False, 'message': 'Aucun assigné sur cette tâche.'})
    if tache.statut in ('terminee', 'terminée'):
        return jsonify({'ok': False, 'message': 'Tâche déjà terminée — notification inutile.'})

    from datetime import timedelta as _td
    from app.models import Notification as NotifCls
    recent = NotifCls.query.filter(
        NotifCls.tache_id == tache.id,
        NotifCls.type_notification == 'rappel_manuel',
        NotifCls.date_envoi >= datetime.utcnow() - _td(seconds=60),
    ).first()
    if recent:
        return jsonify({'ok': False, 'message': 'Notification déjà envoyée il y a moins d\'une minute.'})

    assigne = User.query.get(tache.assigne_a)
    notifieur_nom = f'{current_user.prenom} {current_user.nom}'
    notif = NotifCls(
        user_id=tache.assigne_a, tache_id=tache.id,
        message=f'🔔 {notifieur_nom} vous rappelle la tâche : {tache.titre}',
        type_notification='rappel_manuel',
    )
    db.session.add(notif)
    db.session.commit()

    email_ok = False
    email_err = None
    try:
        from app.integrations.brevo import send_task_assigned_email_brevo
        email_ok = send_task_assigned_email_brevo(tache, tache.assigne_a)
        if not email_ok:
            email_err = 'envoi Brevo refusé (clé ou destinataire ?)'
    except Exception as e:
        email_err = str(e)

    return jsonify({
        'ok': True,
        'email_ok': email_ok,
        'message': (f'Email envoyé à {assigne.prenom} {assigne.nom}' + ('' if email_ok else f' (⚠ {email_err})')
                    + ' + notification in-app') if assigne else 'Notification in-app envoyée',
    })


@app.route('/api/dossiers-membres')
@login_required
def api_dossiers_membres():
    """API pour alimenter les menus déroulants du modal de création de tâche.
       Si ?membre_id=X est fourni, ne retourne que les dossiers de ce membre."""
    membre_id = request.args.get('membre_id', type=int)
    
    query = Dossier.query.order_by(Dossier.numero_dossier)
    if membre_id:
        query = query.filter_by(collaborateur_id=membre_id)
    dossiers = query.all()
    
    membres = User.query.filter_by(actif=True).order_by(User.prenom).all()
    
    return jsonify({
        'ok': True,
        'dossiers': [{'id': d.id, 'label': f"{d.numero_dossier} — {d.intitule}"} for d in dossiers],
        'membres': [{'id': m.id, 'label': f"{m.prenom} {m.nom}"} for m in membres]
    })


@app.route('/api/recherche-globale')
@login_required
def recherche_globale():
    """Recherche globale pour la palette Ctrl+K : dossiers, tâches, membres.
    Respecte le périmètre de l'utilisateur (membre : son périmètre ;
    manager : ses équipes ; admin : tout)."""
    q = (request.args.get('q') or '').strip()
    if len(q) < 2:
        return jsonify({'ok': True, 'resultats': []})
    like = f'%{q}%'
    role = getattr(current_user, 'role', 'membre')
    resultats = []

    dq = Dossier.query
    tq = Tache.query
    mq = User.query.filter(User.actif == True)

    if role == 'membre':
        dq = dq.filter(Dossier.collaborateur_id == current_user.id)
        tq = tq.filter(or_(Tache.assigne_a == current_user.id, Tache.cree_par == current_user.id))
        mq = mq.filter(User.id == current_user.id)
    elif role == 'manager':
        team_ids = {current_user.id}
        for eq in Equipe.query.filter_by(manager_id=current_user.id).all():
            team_ids.update(m.id for m in eq.membres.all())
        dq = dq.filter(Dossier.collaborateur_id.in_(list(team_ids)))
        tq = tq.filter(or_(Tache.assigne_a.in_(list(team_ids)), Tache.cree_par.in_(list(team_ids))))
        mq = mq.filter(User.id.in_(list(team_ids)))

    for d in dq.filter(or_(Dossier.numero_dossier.ilike(like), Dossier.intitule.ilike(like))) \
               .order_by(Dossier.numero_dossier).limit(5).all():
        resultats.append({
            'groupe': 'Dossiers', 'icone': 'bi-folder2-open',
            'label': f'{d.numero_dossier} — {d.intitule}',
            'sous': 'Dossier',
            'lien': url_for('dossiers', q=d.numero_dossier),
        })

    for t in tq.filter(Tache.titre.ilike(like)).order_by(Tache.id.desc()).limit(5).all():
        resultats.append({
            'groupe': 'Tâches', 'icone': 'bi-clipboard-check',
            'label': t.titre,
            'sous': 'Tâche · ' + (t.statut or '').replace('_', ' '),
            'lien': url_for('vue_tache', tache_id=t.id),
        })

    if role != 'membre':
        for m in mq.filter(or_(User.prenom.ilike(like), User.nom.ilike(like),
                               User.email.ilike(like))).order_by(User.prenom).limit(5).all():
            resultats.append({
                'groupe': 'Équipe', 'icone': 'bi-person',
                'label': f'{m.prenom} {m.nom}',
                'sous': m.poste or 'Membre',
                'lien': url_for('fiche_membre', user_id=m.id),
            })

    return jsonify({'ok': True, 'resultats': resultats[:15]})
