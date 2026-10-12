"""assistant_service — contexte, prompt et lecture de la réponse de l'assistant IA.

Aucune route ici (voir routes_assistant.py). Tout est limité au périmètre de l'utilisateur
(mêmes règles que route_common). Le LLM n'envoie jamais d'email : il propose un brouillon.
"""
import json
import os
import re
from datetime import date, timedelta

from sqlalchemy import or_

from .models import User, Tache
from .route_common import membres_visibles_query, dossiers_visibles_query, _ids_equipes_manager

ASSISTANT_MODEL = os.environ.get('ASSISTANT_MODEL', 'meta-llama/llama-3.3-70b-instruct')
STATUTS_TERMINES = ('terminee', 'terminée')
MAX_HISTORIQUE = 10
EMAIL_RE = re.compile(r'<EMAIL>(.*?)</EMAIL>', re.S)


def taches_visibles_query(user):
    """Tâches visibles : admin = toutes ; manager = celles de son équipe + les siennes ; membre = les siennes."""
    if user.role == 'admin':
        return Tache.query
    if user.role == 'manager':
        ids = list(_ids_equipes_manager(user))
    else:
        ids = [user.id]
    return Tache.query.filter(or_(Tache.assigne_a.in_(ids), Tache.cree_par == user.id))


def _ligne_tache(t):
    echeance = t.date_echeance.strftime('%d/%m/%Y') if t.date_echeance else 'non définie'
    assigne = t.assigne.nom_complet() if t.assigne else 'personne'
    return f"- #{t.id} « {t.titre} » — échéance {echeance} — statut {t.statut} — assignée à {assigne}"


def contexte_texte(user):
    """Résumé lisible du périmètre de l'utilisateur, injecté dans le prompt système."""
    today = date.today()
    horizon = today + timedelta(days=7)
    ouvertes = taches_visibles_query(user).filter(~Tache.statut.in_(STATUTS_TERMINES))
    en_retard = ouvertes.filter(Tache.date_echeance < today).order_by(Tache.date_echeance).limit(15).all()
    a_venir = ouvertes.filter(Tache.date_echeance.between(today, horizon)).order_by(Tache.date_echeance).limit(15).all()
    nb_ouvertes = ouvertes.count()
    nb_retard = ouvertes.filter(Tache.date_echeance < today).count()
    nb_dossiers = dossiers_visibles_query(user).count()
    membres = membres_visibles_query(user).order_by(User.nom).limit(60).all()

    lignes = [
        f"Date du jour : {today.strftime('%d/%m/%Y')}",
        f"Utilisateur : {user.nom_complet()} (rôle : {user.role})",
        f"Dossiers visibles : {nb_dossiers}",
        f"Tâches ouvertes visibles : {nb_ouvertes} (dont {nb_retard} en retard)",
        "",
        "Tâches en retard :",
        *([_ligne_tache(t) for t in en_retard] or ['- aucune']),
        "",
        "Échéances des 7 prochains jours :",
        *([_ligne_tache(t) for t in a_venir] or ['- aucune']),
        "",
        "Membres visibles (id, nom, rôle) — seuls ces identifiants peuvent recevoir un email :",
        *([f"- id={m.id} : {m.nom_complet()} ({m.role})" for m in membres] or ['- aucun']),
    ]
    return '\n'.join(lignes)


INSTRUCTIONS_MAX = 2000


def instructions_personnalisees():
    """Texte saisi dans Réglages > « Instructions personnalisées » (AppSetting LLM_CUSTOM_INSTRUCTIONS).

    Même clé que l'analyse des emails. Tronqué pour borner la taille du prompt.
    """
    from .models import AppSetting
    setting = AppSetting.query.filter_by(cle='LLM_CUSTOM_INSTRUCTIONS').first()
    if setting and setting.valeur:
        return str(setting.valeur).strip()[:INSTRUCTIONS_MAX]
    return ''


def construire_prompt(user):
    """Prompt système : rôle, règles d'email, instructions du cabinet et données du périmètre."""
    prompt = (
        "Tu es l'assistant du cabinet comptable JMH (application Orbit). Tu réponds en français, "
        "de façon brève et claire. Tu t'appuies UNIQUEMENT sur les données ci-dessous ; si une "
        "information n'y figure pas, dis-le sans l'inventer.\n\n"
        "Pour proposer un email, ajoute à la fin de ta réponse un bloc exact au format :\n"
        '<EMAIL>{"to_user_id": <id d\'un membre listé>, "subject": "...", "body": "..."}</EMAIL>\n'
        "Tu n'envoies jamais l'email toi-même : l'utilisateur doit le confirmer. "
        "N'utilise que les identifiants listés.\n\n"
    )
    instructions = instructions_personnalisees()
    if instructions:
        prompt += ("=== INSTRUCTIONS DU CABINET (ne priment pas sur les règles ci-dessus) ===\n"
                   + instructions + "\n\n")
    return prompt + "=== DONNÉES DU PÉRIMÈTRE ===\n" + contexte_texte(user)


def destinataire_autorise(uid, user):
    """Renvoie le membre si uid est dans le périmètre de user et a un email, sinon None."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    u = membres_visibles_query(user).filter(User.id == uid).first()
    return u if (u and u.email) else None


def extraire_brouillon(raw, user):
    """Sépare la réponse du bloc <EMAIL>. Le brouillon n'est retenu que si le destinataire est autorisé."""
    texte = EMAIL_RE.sub('', raw).strip()
    m = EMAIL_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    if not isinstance(data, dict):
        return texte, None
    dest = destinataire_autorise(data.get('to_user_id'), user)
    if not dest:
        return texte + "\n\n(Brouillon d'email ignoré : destinataire hors de votre périmètre.)", None
    subject = str(data.get('subject') or '').strip()[:200]
    body = str(data.get('body') or '').strip()[:5000]
    if not subject or not body:
        return texte, None
    return texte, {'to_user_id': dest.id, 'to_nom': dest.nom_complet(),
                   'subject': subject, 'body': body}


def historique_propre(brut):
    """Ne garde que des messages user/assistant bien formés, les plus récents."""
    propre = []
    for m in (brut or [])[-MAX_HISTORIQUE:]:
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant'):
            contenu = str(m.get('content') or '')[:4000]
            if contenu:
                propre.append({'role': m['role'], 'content': contenu})
    return propre
