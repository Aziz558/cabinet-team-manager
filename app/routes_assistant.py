"""routes_assistant — API de l'assistant IA (bulle flottante sur toutes les pages connectées).

- /api/assistant/message : question au LLM (OpenRouter), contexte limité au périmètre.
- /api/assistant/envoyer_email : envoi d'un email DÉJÀ confirmé par l'utilisateur.
"""
from flask import request, jsonify
from flask_login import login_required, current_user

from . import app
from .assistant_service import (construire_prompt, historique_propre,
                                extraire_brouillon, destinataire_autorise,
                                extraire_proposition_tache, valider_tache,
                                creer_tache_assistant, resume_du_jour,
                                 detecter_intention, reponse_directe)


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

    from .integrations.openrouter import OpenRouterClient
    llm = OpenRouterClient()
    if not llm.is_configured():
        return jsonify({'ok': False,
                        'error': "Assistant non configuré : ajoutez la clé OPENROUTER_API_KEY dans les réglages."}), 503

    messages = ([{'role': 'system', 'content': construire_prompt(current_user)}]
                + historique_propre(data.get('historique'))
                + [{'role': 'user', 'content': message}])
    # Modèle : OPENROUTER_MODEL (env) > réglage enregistré > défaut du client.
    raw = llm.chat(messages)
    if not raw:
        return jsonify({'ok': False, 'error': "L'assistant n'a pas répondu. Réessayez dans un instant."}), 502

    texte, brouillon = extraire_brouillon(raw, current_user)
    texte, tache = extraire_proposition_tache(texte, current_user)
    return jsonify({'ok': True, 'reponse': texte, 'brouillon': brouillon, 'tache': tache})


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
