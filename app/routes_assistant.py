"""routes_assistant — API de l'assistant IA (bulle flottante sur toutes les pages connectées).

- /api/assistant/message : question au LLM (OpenRouter), contexte limité au périmètre.
- /api/assistant/envoyer_email : envoi d'un email DÉJÀ confirmé par l'utilisateur.
"""
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from . import app
from .assistant_service import (construire_prompt, historique_propre,
                                extraire_brouillon, destinataire_autorise,
                                extraire_proposition_tache, valider_tache,
                                creer_tache_assistant, resume_du_jour,
                                detecter_intention, reponse_directe,
                                extraire_proposition_rappel, valider_rappel,
                                creer_rappel_assistant, detecter_action,
                                extraire_proposition_statut, valider_statut,
                                appliquer_statut_assistant,
                                extraire_proposition_statut_lot, valider_statut_lot,
                                appliquer_statut_lot,
                                extraire_proposition_suppression, valider_suppression_dossier,
                                appliquer_suppression_dossier,
                                extraire_proposition_onb_etape, valider_onb_etape,
                                appliquer_onb_etape, extraire_memoires,
                                journaliser_echange, detecter_recherche_historique)


@app.route('/api/assistant/message', methods=['POST'])
@login_required
def assistant_message():
    """Envoie un message à l'assistant. L'historique est tenu côté navigateur, rien n'est stocké."""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()[:2000]
    if not message:
        return jsonify({'ok': False, 'error': 'Message vide.'}), 400

    # Actions explicites d'abord (« termine la tâche #123 », « toutes les tâches
    # de X en retard à terminer », « supprime le dossier Y », « souviens-toi ») :
    # proposition immédiate sans LLM, confirmation requise côté client.
    # AVANT le routage par intention, sinon « retard » dans une demande d'action
    # déclencherait la simple liste des retards.
    action = detecter_action(message, current_user)
    if action:
        journaliser_echange(current_user, message, action['reponse'])
        return jsonify({'ok': True, 'reponse': action['reponse'], 'brouillon': None,
                        'tache': None, 'rappel': None, 'statut': action.get('statut'),
                        'statut_lot': action.get('statut_lot'),
                        'suppression': action.get('suppression'), 'onb_etape': None,
                        'memoires': action.get('memoires'), 'source': 'regles'})

    # Recherche dans l'historique (« cherche dans l'historique : … ») : tampon
    # base + archives du collaborateur, sans LLM.
    hist = detecter_recherche_historique(message, current_user)
    if hist:
        journaliser_echange(current_user, message, hist['reponse'])
        return jsonify({'ok': True, 'reponse': hist['reponse'], 'brouillon': None,
                        'tache': None, 'source': 'regles'})

    # Routage par règles : les questions factuelles sont répondues depuis la base, sans LLM.
    intention = detecter_intention(message)
    if intention:
        reponse = reponse_directe(current_user, intention)
        journaliser_echange(current_user, message, reponse)
        return jsonify({'ok': True, 'reponse': reponse,
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
    texte, statut = extraire_proposition_statut(texte, current_user)
    texte, statut_lot = extraire_proposition_statut_lot(texte, current_user)
    texte, suppression = extraire_proposition_suppression(texte, current_user)
    texte, onb_etape = extraire_proposition_onb_etape(texte, current_user)
    texte, memoires = extraire_memoires(texte, current_user)
    journaliser_echange(current_user, message, texte)
    return jsonify({'ok': True, 'reponse': texte, 'brouillon': brouillon, 'tache': tache,
                    'rappel': rappel, 'statut': statut, 'statut_lot': statut_lot,
                    'suppression': suppression, 'onb_etape': onb_etape, 'memoires': memoires})


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


@app.route('/api/assistant/changer_statut', methods=['POST'])
@login_required
def assistant_changer_statut():
    """Change le statut d'une tâche DÉJÀ confirmée par l'utilisateur. Revalidé côté serveur
    (périmètre + statut valide). Mêmes effets que la route manuelle (checklist, notifications)."""
    data = request.get_json(silent=True) or {}
    proposition, erreur = valider_statut(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Statut refusé : {erreur}.'}), 403
    t = appliquer_statut_assistant(current_user, proposition)
    app.logger.info(f"assistant statut from={current_user.id} tache={t.id} statut={t.statut}")
    return jsonify({'ok': True, 'message': f"Tâche « {t.titre} » → {t.statut.replace('_', ' ')}."})


@app.route('/api/assistant/statut_lot', methods=['POST'])
@login_required
def assistant_statut_lot():
    """Change le statut d'un LOT de tâches DÉJÀ confirmé. Revalidé côté serveur
    (périmètre sur CHAQUE tâche, 50 max). Mêmes effets unitaires que la route manuelle."""
    data = request.get_json(silent=True) or {}
    proposition, erreur = valider_statut_lot(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Lot refusé : {erreur}.'}), 403
    n = appliquer_statut_lot(current_user, proposition)
    app.logger.info(f"assistant statut_lot from={current_user.id} nb={n} statut={proposition['statut']}")
    return jsonify({'ok': True, 'message': f"{n} tâche(s) → {proposition['statut'].replace('_', ' ')}."})


@app.route('/api/assistant/supprimer_dossier', methods=['POST'])
@login_required
def assistant_supprimer_dossier():
    """Supprime un dossier DÉJÀ confirmé (irréversible). Managers/admins uniquement,
    revalidé côté serveur. Même nettoyage des données liées que la route manuelle."""
    data = request.get_json(silent=True) or {}
    proposition, erreur = valider_suppression_dossier(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Suppression refusée : {erreur}.'}), 403
    numero = appliquer_suppression_dossier(current_user, proposition)
    return jsonify({'ok': True, 'message': f'Dossier {numero} supprimé (tâches et données liées incluses).'})


@app.route('/api/assistant/onb_etape', methods=['POST'])
@login_required
def assistant_onb_etape():
    """Marque une étape du suivi nouveaux dossiers DÉJÀ confirmée. Managers/admins.
    Lance l'action email configurée pour l'étape, comme la route manuelle."""
    data = request.get_json(silent=True) or {}
    proposition, erreur = valider_onb_etape(data, current_user)
    if erreur:
        return jsonify({'ok': False, 'error': f'Étape refusée : {erreur}.'}), 403
    s, mails, manquants = appliquer_onb_etape(current_user, proposition)
    app.logger.info(f"assistant onb_etape from={current_user.id} dossier={proposition['dossier_id']} "
                    f"code={proposition['code']} fait={s.est_fait}")
    message = f"Étape « {proposition['label']} » — {proposition['nom_dossier']} : "
    message += 'marquée faite.' if s.est_fait else 'remise à faire.'
    for r in mails:
        message += f" Mail « {r.get('libelle', proposition['label']) } » → {r['destinataire']} : "
        message += 'envoyé.' if r['statut'] == 'envoye' else f"échec ({r['erreur']})."
    if manquants:
        message += ' Destinataire sans email : ' + ', '.join(m['libelle'] for m in manquants) + '.'
    return jsonify({'ok': True, 'message': message})


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
    corps = f"{body}\n\n— {current_user.nom_complet()} (envoyé via ASTRO, l'assistant JMH Orbit)"
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


# ---------------------------------------------------------------------------
# Mémoire d'ASTRO : page de gestion + CRUD.
# Cabinet : lisible par tous, modifiable par l'auteur ou un admin/manager.
# Personnelle : strictement réservée au propriétaire.
# ---------------------------------------------------------------------------

def _memoire_droits(m, user, ecriture=False):
    if m.portee == 'personnel':
        return m.user_id == user.id
    if not ecriture:
        return True
    return user.role in ('admin', 'manager') or m.cree_par_id == user.id


@app.route('/assistant/modeles', methods=['GET'])
@login_required
def assistant_modeles_page():
    """Rayon « Modèles » : plaquettes et modèles de documents partagés (lecture seule)."""
    from .assistant_archive import lister_modeles
    modeles = lister_modeles(force=request.args.get('rafraichir') == '1')
    return render_template('assistant_modeles.html', modeles=modeles)


@app.route('/assistant/modeles/fichier/<path:nom>', methods=['GET'])
@login_required
def assistant_modeles_fichier(nom):
    """Téléchargement d'un modèle du repli local (le Drive, lui, ouvre son lien)."""
    from flask import send_from_directory
    from .assistant_archive import _dossier_modeles_local
    dossier = _dossier_modeles_local()
    return send_from_directory(dossier, nom, as_attachment=True)


@app.route('/assistant/memoire', methods=['GET'])
@login_required
def assistant_memoire_page():
    from .models import AssistantMemoire
    cabinet = (AssistantMemoire.query.filter_by(portee='cabinet')
               .order_by(AssistantMemoire.date_creation.desc()).all())
    perso = (AssistantMemoire.query.filter_by(portee='personnel', user_id=current_user.id)
             .order_by(AssistantMemoire.date_creation.desc()).all())
    return render_template('assistant_memoire.html', cabinet=cabinet, perso=perso,
                           peut_ecrire_cabinet=lambda m: _memoire_droits(m, current_user, True))


@app.route('/assistant/memoire/ajouter', methods=['POST'])
@login_required
def assistant_memoire_ajouter():
    from .assistant_service import enregistrer_memoire
    m, info = enregistrer_memoire(current_user, request.form.get('portee', 'personnel'),
                                  request.form.get('contenu', ''), source='manuel')
    if not m:
        flash(f'Souvenir refusé : {info}.', 'warning')
    elif info == 'deja_presente':
        flash('Ce souvenir est déjà dans la mémoire.', 'info')
    else:
        flash('Souvenir ajouté.', 'success')
    return redirect(url_for('assistant_memoire_page'))


@app.route('/assistant/memoire/<int:memoire_id>/modifier', methods=['POST'])
@login_required
def assistant_memoire_modifier(memoire_id):
    from . import db
    from .models import AssistantMemoire
    from .assistant_service import MEMOIRE_MAX_LEN, _MEMOIRE_SECRET_RE
    m = AssistantMemoire.query.get_or_404(memoire_id)
    if not _memoire_droits(m, current_user, ecriture=True):
        flash('Accès refusé : ce souvenir ne vous appartient pas.', 'danger')
        return redirect(url_for('assistant_memoire_page'))
    contenu = ' '.join((request.form.get('contenu') or '').split())
    if len(contenu) < 3 or len(contenu) > MEMOIRE_MAX_LEN:
        flash(f'Contenu invalide (3 à {MEMOIRE_MAX_LEN} caractères).', 'warning')
    elif _MEMOIRE_SECRET_RE.search(contenu):
        flash('Ne stockez jamais de clé API ou de mot de passe dans la mémoire.', 'warning')
    else:
        m.contenu = contenu
        db.session.commit()
        flash('Souvenir modifié.', 'success')
    return redirect(url_for('assistant_memoire_page'))


@app.route('/assistant/memoire/<int:memoire_id>/supprimer', methods=['POST'])
@login_required
def assistant_memoire_supprimer(memoire_id):
    from . import db
    from .models import AssistantMemoire
    m = AssistantMemoire.query.get_or_404(memoire_id)
    if not _memoire_droits(m, current_user, ecriture=True):
        flash('Accès refusé : ce souvenir ne vous appartient pas.', 'danger')
        return redirect(url_for('assistant_memoire_page'))
    db.session.delete(m)
    db.session.commit()
    flash('Souvenir effacé.', 'success')
    return redirect(url_for('assistant_memoire_page'))


@app.route('/api/assistant/archives/exporter', methods=['POST'])
@login_required
def assistant_archives_exporter():
    """Export manuel des archives (mémoire + conversations) puis purge du tampon.
    Admin uniquement. Même logique que le job du soir."""
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    from .assistant_archive import exporter_archives
    rapport = exporter_archives()
    if not rapport.get('ok'):
        return jsonify({'ok': False, 'error': rapport.get('erreur', 'Export en échec.'),
                        'rapport': rapport}), 502
    return jsonify({'ok': True, 'rapport': rapport,
                    'message': f"Archives exportées ({rapport['backend']}) : "
                               f"{len(rapport['fichiers'])} fichier(s), "
                               f"{rapport['nb_messages']} message(s), "
                               f"{rapport.get('purges', 0)} entrée(s) purgée(s) de la base."})


@app.route('/api/assistant/archives/tester', methods=['POST'])
@login_required
def assistant_archives_tester():
    if current_user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Accès refusé.'}), 403
    from .assistant_archive import tester_connexion_drive
    return jsonify(tester_connexion_drive())


@app.route('/api/assistant/archives/statut', methods=['GET'])
@login_required
def assistant_archives_statut():
    from .models import AppSetting
    row = AppSetting.query.filter_by(cle='ARCHIVE_DERNIER_EXPORT').first()
    import json as _json
    rapport = None
    if row and row.valeur:
        try:
            rapport = _json.loads(row.valeur)
        except ValueError:
            rapport = None
    return jsonify({'ok': True, 'dernier_export': rapport})
