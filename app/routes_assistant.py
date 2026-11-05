"""routes_assistant — API de l'assistant IA (bulle flottante sur toutes les pages connectées).

- /api/assistant/message : question au LLM (OpenRouter), contexte limité au périmètre.
- /api/assistant/envoyer_email : envoi d'un email DÉJÀ confirmé par l'utilisateur.
"""
from flask import render_template, request, jsonify
from flask_login import login_required, current_user

from . import app
from .assistant_service import (construire_prompt, historique_propre,
                                extraire_brouillon, destinataire_autorise,
                                extraire_proposition_tache, valider_tache,
                                creer_tache_assistant, resume_du_jour,
                                detecter_intention, reponse_directe,
                                extraire_proposition_rappel, valider_rappel,
                                creer_rappel_assistant)


@app.route('/api/assistant/message', methods=['POST'])
@login_required
def assistant_message():
    """Envoie un message à l'assistant. L'historique est tenu côté navigateur, rien n'est stocké."""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()[:2000]
    if not message:
        return jsonify({'ok': False, 'error': 'Message vide.'}), 400

    # Routage par règles : les questions factuelles sont répondues depuis la base, sans LLM.
    intention = detecter_intention(message)
    if intention:
        return jsonify({'ok': True, 'reponse': reponse_directe(current_user, intention),
                        'brouillon': None, 'tache': None, 'source': 'regles'})

    from .integrations.llm_provider import get_llm_manager
    manager = get_llm_manager()
    if not manager.any_configured():
        return jsonify({'ok': False,
                        'error': "Assistant non configuré : ajoutez une clé API (OpenRouter, Groq, NVIDIA ou Gemini) dans les réglages."}), 503
    messages = ([{'role': 'system', 'content': construire_prompt(current_user)}]
                + historique_propre(data.get('historique'))
                + [{'role': 'user', 'content': message}])
    raw = manager.chat(messages)
    if not raw:
        return jsonify({'ok': False,
                        'error': "L'assistant n'a pas répondu (tous les providers IA ont échoué). Réessayez dans un instant."}), 502

    texte, brouillon = extraire_brouillon(raw, current_user)
    texte, tache = extraire_proposition_tache(texte, current_user)
    texte, rappel = extraire_proposition_rappel(texte, current_user)
    return jsonify({'ok': True, 'reponse': texte, 'brouillon': brouillon, 'tache': tache, 'rappel': rappel})


@app.route('/api/assistant/creer_tache', methods=['POST'])
@login_required
def assistant_creer_tache():
    """Crée une tâche DÉJÀ confirmée par l'utilisateur. Revalidée côté serveur."""
    data = request.get_json(silent=True) or {}
    tache, erreur = valider_tache(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Tâche refusée : {erreur}.'}), 403
    t = creer_tache_assistant(current_user, tache)
    app.logger.info(f"assistant tache from={current_user.id} tache={t.id}")
    return jsonify({'ok': True, 'message': f"Tâche créée : {t.titre} (échéance {t.date_echeance.strftime('%d/%m/%Y')})."})


@app.route('/api/assistant/creer_rappel', methods=['POST'])
@login_required
def assistant_creer_rappel():
    """Crée un rappel (validé côté serveur) et envoie la notification in-app immédiate."""
    data = request.get_json(silent=True) or {}
    rappel, erreur = valider_rappel(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Rappel refusé : {erreur}.'}), 403
    r = creer_rappel_assistant(current_user, rappel)
    app.logger.info(f"assistant rappel from={current_user.id} rappel={r.id}")
    return jsonify({'ok': True,
                    'message': f"Rappel créé : {r.titre} — échéance le {r.date_echeance.strftime('%d/%m/%Y')}."})


@app.route('/api/assistant/rappels', methods=['GET'])
@login_required
def assistant_liste_rappels():
    """Liste les rappels actifs (non archivés) de l'utilisateur courant."""
    from .models import Rappel
    rappels = (Rappel.query.filter_by(user_id=current_user.id, archive=False)
               .order_by(Rappel.date_echeance.asc()).all())
    return jsonify({'ok': True, 'rappels': [
        {'id': r.id, 'titre': r.titre, 'message': r.message,
         'date_echeance': r.date_echeance.isoformat(),
         'lu': r.lu, 'archive': r.archive, 'source': r.source,
         'date_creation': r.date_creation.isoformat() if r.date_creation else None}
        for r in rappels]})


@app.route('/api/assistant/rappels/<int:rappel_id>/lu', methods=['POST'])
@login_required
def assistant_marquer_rappel_lu(rappel_id):
    """Marque un rappel comme lu (NOTE) — stoppe les emails de relance J+1."""
    from .models import Rappel
    from . import db
    r = Rappel.query.filter_by(id=rappel_id, user_id=current_user.id).first()
    if not r:
        return jsonify({'ok': False, 'error': 'Rappel introuvable.'}), 404
    r.lu = True
    from datetime import datetime as _dt
    r.date_lu = _dt.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Rappel marqué comme lu.'})


@app.route('/api/assistant/rappels/<int:rappel_id>/archive', methods=['POST'])
@login_required
def assistant_archiver_rappel(rappel_id):
    """Archive un rappel (le retire de la liste active)."""
    from .models import Rappel
    from . import db
    r = Rappel.query.filter_by(id=rappel_id, user_id=current_user.id).first()
    if not r:
        return jsonify({'ok': False, 'error': 'Rappel introuvable.'}), 404
    r.archive = True
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Rappel archivé.'})


@app.route('/api/assistant/sante', methods=['GET'])
@login_required
def assistant_sante():
    """État réel des fournisseurs IA — pour diagnostiquer « l'assistant ne répond pas ».

    Sans paramètre : dit seulement qui est configuré (aucun appel réseau).
    ?probe=1 : envoie un mini-message à chaque fournisseur configuré et renvoie
    la vraie erreur (HTTP + extrait), jamais la clé.
    """
    from .integrations.llm_provider import get_llm_manager
    manager = get_llm_manager()
    probe = request.args.get('probe') == '1'
    providers = []
    for i, prov in enumerate(manager.chain or [manager.primary]):
        role = 'principal' if i == 0 else ('secours %d' % i)
        info = {
            'role': role,
            'fournisseur': getattr(prov, 'NOM', prov.__class__.__name__),
            'configure': bool(prov.is_configured()),
            'modele': getattr(prov, 'model', None),
        }
        if probe and info['configure']:
            try:
                rep = prov.chat([{'role': 'user', 'content': 'Réponds seulement: OK'}])
                info['ok'] = bool(rep)
                info['extrait'] = (rep or '')[:80]
            except Exception as exc:
                info['ok'] = False
                info['erreur'] = str(exc)[:200]
        providers.append(info)

    if not any(p['configure'] for p in providers):
        etat = "Aucune clé IA configurée : l'assistant ne peut pas répondre aux questions ouvertes (le résumé du jour et les questions sur vos tâches fonctionnent sans IA)."
    elif probe and not any(p.get('ok') for p in providers):
        etat = "Clé(s) présente(s) mais aucun fournisseur ne répond : vérifiez le modèle et le crédit du compte."
    else:
        etat = "Assistant opérationnel." if probe else "Clé(s) IA configurée(s). Lancez le diagnostic pour tester réellement."
    return jsonify({'ok': True, 'etat': etat, 'providers': providers})


@app.route('/api/assistant/resume', methods=['GET'])
@login_required
def assistant_resume():
    """Résumé du jour, sans LLM : fonctionne même si OpenRouter est indisponible."""
    return jsonify({'ok': True, 'resume': resume_du_jour(current_user)})


@app.route('/api/assistant/envoyer_email', methods=['POST'])
@login_required
def assistant_envoyer_email():
    """Envoie un email confirmé par l'utilisateur. Le destinataire est recontrôlé côté serveur."""
    data = request.get_json(silent=True) or {}
    dest = destinataire_autorise(data.get('to_user_id'), current_user)
    if not dest:
        return jsonify({'ok': False, 'error': 'Destinataire hors de votre périmètre.'}), 403
    subject = str(data.get('subject') or '').strip()[:200]
    body = str(data.get('body') or '').strip()[:5000]
    if not subject or not body:
        return jsonify({'ok': False, 'error': 'Objet et message obligatoires.'}), 400

    from .integrations.brevo import send_email_via_brevo_api
    corps = f"{body}\n\n— {current_user.nom_complet()} (envoyé via l'assistant Orbit)"
    ok = send_email_via_brevo_api(to_email=dest.email, subject=subject, body=corps)
    app.logger.info(f"assistant email from={current_user.id} to={dest.id} ok={ok}")
    if not ok:
        return jsonify({'ok': False, 'error': "Échec de l'envoi. Vérifiez la configuration Brevo."}), 502
    return jsonify({'ok': True, 'message': f'Email envoyé à {dest.nom_complet()}.'})


@app.route('/rappels', methods=['GET'])
@login_required
def rappels_suivi():
    """Fenêtre de suivi des rappels : liste, marquer lu, archiver. Tous les rôles."""
    from .models import Rappel
    rappels = (Rappel.query.filter_by(user_id=current_user.id, archive=False)
               .order_by(Rappel.date_echeance.asc()).all())
    rappels_archives = (Rappel.query.filter_by(user_id=current_user.id, archive=True)
                        .order_by(Rappel.date_echeance.desc()).limit(20).all())
    return render_template('rappels.html', rappels=rappels, rappels_archives=rappels_archives)
