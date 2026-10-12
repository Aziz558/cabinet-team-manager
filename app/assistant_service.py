"""assistant_service — contexte, prompt et lecture de la réponse de l'assistant IA.

Aucune route ici (voir routes_assistant.py). Tout est limité au périmètre de l'utilisateur
(mêmes règles que route_common). Le LLM n'envoie jamais d'email : il propose un brouillon.
"""
import json
import os
import re
from datetime import date, timedelta

from sqlalchemy import or_

from .models import User, Tache, Notification
from .route_common import membres_visibles_query, dossiers_visibles_query, _ids_equipes_manager

ASSISTANT_MODEL = os.environ.get('ASSISTANT_MODEL', 'meta-llama/llama-3.3-70b-instruct')
STATUTS_TERMINES = ('terminee', 'terminée')
MAX_HISTORIQUE = 10
EMAIL_RE = re.compile(r'<EMAIL>(.*?)</EMAIL>', re.S)
TACHE_RE = re.compile(r'<TACHE>(.*?)</TACHE>', re.S)
PRIORITES = ('haute', 'moyenne', 'basse')


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
        "Pour proposer la création d'une tâche, ajoute à la fin de ta réponse un bloc exact au format :\n"
        '<TACHE>{"titre": "...", "description": "...", "assigne_a_id": <id d\'un membre listé ou null>, '
        '"priorite": "haute|moyenne|basse", "date_echeance": "AAAA-MM-JJ"}</TACHE>\n'
        "Ne propose une tâche que si l'utilisateur la demande. Si la date d'échéance manque, demande-la "
        "au lieu de l'inventer. Tu ne crées jamais la tâche toi-même : l'utilisateur doit la confirmer.\n\n"
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


def valider_tache(data, user):
    """Contrôle une tâche proposée (LLM ou formulaire). Retourne (tache, None) ou (None, erreur).

    Mêmes règles que /taches : un membre n'assigne qu'à lui-même, un manager reste dans ses équipes.
    """
    if not isinstance(data, dict):
        return None, 'données invalides'
    titre = str(data.get('titre') or '').strip()[:200]
    if not titre:
        return None, 'titre manquant'
    description = str(data.get('description') or '').strip()[:2000]
    priorite = str(data.get('priorite') or 'moyenne').strip().lower()
    if priorite not in PRIORITES:
        priorite = 'moyenne'
    try:
        echeance = date.fromisoformat(str(data.get('date_echeance') or '').strip())
    except ValueError:
        return None, "date d'échéance absente ou invalide"

    brut = data.get('assigne_a_id')
    if brut in (None, ''):
        assigne = user
    else:
        try:
            uid = int(brut)
        except (TypeError, ValueError):
            return None, 'assigné invalide'
        if user.role == 'membre' and uid != user.id:
            return None, 'vous ne pouvez assigner une tâche qu\u2019à vous-même'
        assigne = membres_visibles_query(user).filter(User.id == uid).first()
        if not assigne:
            return None, 'assigné hors de votre périmètre'

    return {'titre': titre, 'description': description, 'assigne_a_id': assigne.id,
            'assigne_nom': assigne.nom_complet(), 'priorite': priorite,
            'date_echeance': echeance.isoformat()}, None


def extraire_proposition_tache(raw, user):
    """Sépare le bloc <TACHE> de la réponse. La proposition n'est retenue que si elle est valide."""
    texte = TACHE_RE.sub('', raw).strip()
    m = TACHE_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    tache, erreur = valider_tache(data, user)
    if erreur:
        return texte + f"\n\n(Tâche non proposée : {erreur}.)", None
    return texte, tache


def creer_tache_assistant(user, data):
    """Crée la tâche après confirmation. data doit déjà être validé par valider_tache."""
    from . import db
    from datetime import date as _date
    t = Tache(
        titre=data['titre'],
        description=data['description'],
        assigne_a=data['assigne_a_id'],
        cree_par=user.id,
        priorite=data['priorite'],
        statut='a_faire',
        date_echeance=_date.fromisoformat(data['date_echeance']),
    )
    db.session.add(t)
    db.session.flush()
    if t.assigne_a and t.assigne_a != user.id:
        db.session.add(Notification(
            user_id=t.assigne_a, tache_id=t.id,
            message=f"Nouvelle tâche (via l'assistant) : {t.titre}",
            type_notification='assignation',
        ))
    db.session.commit()
    return t


def _ligne_resume(t):
    return {'id': t.id, 'titre': t.titre,
            'echeance': t.date_echeance.strftime('%d/%m/%Y') if t.date_echeance else '',
            'assigne': t.assigne.nom_complet() if t.assigne else 'personne'}


def resume_du_jour(user):
    """Résumé déterministe (sans LLM) : retards, échéances du jour et de demain dans le périmètre."""
    today = date.today()
    demain = today + timedelta(days=1)
    ouvertes = taches_visibles_query(user).filter(~Tache.statut.in_(STATUTS_TERMINES))
    en_retard = ouvertes.filter(Tache.date_echeance < today).order_by(Tache.date_echeance).limit(10).all()
    du_jour = ouvertes.filter(Tache.date_echeance == today).order_by(Tache.titre).limit(10).all()
    de_demain = ouvertes.filter(Tache.date_echeance == demain).order_by(Tache.titre).limit(10).all()
    return {
        'date': today.isoformat(),
        'nb_en_retard': ouvertes.filter(Tache.date_echeance < today).count(),
        'nb_du_jour': ouvertes.filter(Tache.date_echeance == today).count(),
        'nb_demain': ouvertes.filter(Tache.date_echeance == demain).count(),
        'en_retard': [_ligne_resume(t) for t in en_retard],
        'du_jour': [_ligne_resume(t) for t in du_jour],
        'demain': [_ligne_resume(t) for t in de_demain],
    }


def _normaliser(texte):
    """Minuscules, sans accents, espaces simplifiés : pour le routage par mots-clés."""
    import unicodedata
    sans_accents = unicodedata.normalize('NFKD', texte or '').encode('ascii', 'ignore').decode('ascii')
    return ' '.join(sans_accents.lower().replace("'", ' ').replace('\u2019', ' ').split())


def detecter_intention(message):
    """Routeur par règles (sans LLM). Retourne 'resume', 'retard', 'demain', 'jour' ou None.

    None = question libre : le modèle de réponse prend le relais.
    """
    m = _normaliser(message)
    if not m:
        return None
    if any(k in m for k in ('resume', 'bilan', 'quoi de neuf', 'ma journee')):
        return 'resume'
    if 'retard' in m:
        return 'retard'
    if 'demain' in m:
        return 'demain'
    if 'aujourd' in m or 'du jour' in m:
        return 'jour'
    return None


def _ligne_texte(t):
    return f"- {t['titre']} (échéance {t['echeance']}, assignée à {t['assigne']})"


def reponse_directe(user, intention):
    """Réponse construite depuis la base, sans LLM. Mêmes données que resume_du_jour."""
    r = resume_du_jour(user)
    if intention == 'resume':
        lignes = [f"Aujourd'hui ({r['date']}) : {r['nb_du_jour']} échéance(s), "
                  f"{r['nb_demain']} demain, {r['nb_en_retard']} en retard."]
        if r['en_retard']:
            lignes.append('En retard :')
            lignes += [_ligne_texte(t) for t in r['en_retard'][:5]]
        if r['du_jour']:
            lignes.append("Échéances d'aujourd'hui :")
            lignes += [_ligne_texte(t) for t in r['du_jour'][:5]]
        return '\n'.join(lignes)
    if intention == 'retard':
        if not r['nb_en_retard']:
            return 'Aucune tâche en retard.'
        lignes = [f"{r['nb_en_retard']} tâche(s) en retard :"]
        lignes += [_ligne_texte(t) for t in r['en_retard']]
        if r['nb_en_retard'] > len(r['en_retard']):
            lignes.append(f"… et {r['nb_en_retard'] - len(r['en_retard'])} autre(s).")
        return '\n'.join(lignes)
    if intention == 'demain':
        if not r['nb_demain']:
            return 'Aucune échéance demain.'
        lignes = [f"{r['nb_demain']} échéance(s) demain :"]
        lignes += [_ligne_texte(t) for t in r['demain']]
        return '\n'.join(lignes)
    if intention == 'jour':
        if not r['nb_du_jour']:
            return "Aucune échéance aujourd'hui."
        lignes = [f"{r['nb_du_jour']} échéance(s) aujourd'hui :"]
        lignes += [_ligne_texte(t) for t in r['du_jour']]
        return '\n'.join(lignes)
    return None
