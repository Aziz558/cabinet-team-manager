"""assistant_service — contexte, prompt et lecture de la réponse de l'assistant IA.

Aucune route ici (voir routes_assistant.py). Tout est limité au périmètre de l'utilisateur
(mêmes règles que route_common). Le LLM n'envoie jamais d'email : il propose un brouillon.
"""
import json
import os
import re
from datetime import date, timedelta

from sqlalchemy import or_

from .models import User, Tache, Notification, Dossier
from .route_common import membres_visibles_query, dossiers_visibles_query, _ids_equipes_manager

ASSISTANT_MODEL = os.environ.get('ASSISTANT_MODEL', 'meta-llama/llama-3.3-70b-instruct')
STATUTS_TERMINES = ('terminee', 'terminée')
MAX_HISTORIQUE = 10
EMAIL_RE = re.compile(r'<EMAIL>(.*?)</EMAIL>', re.S)
TACHE_RE = re.compile(r'<TACHE>(.*?)</TACHE>', re.S)
RAPPEL_RE = re.compile(r'<RAPPEL>(.*?)</RAPPEL>', re.S)
STATUT_RE = re.compile(r'<STATUT>(.*?)</STATUT>', re.S)
STATUT_LOT_RE = re.compile(r'<STATUT_LOT>(.*?)</STATUT_LOT>', re.S)
SUPPR_DOSSIER_RE = re.compile(r'<SUPPR_DOSSIER>(.*?)</SUPPR_DOSSIER>', re.S)
ONB_ETAPE_RE = re.compile(r'<ONB_ETAPE>(.*?)</ONB_ETAPE>', re.S)
MEMOIRE_RE = re.compile(r'<MEMOIRE>(.*?)</MEMOIRE>', re.S)
PRIORITES = ('haute', 'moyenne', 'basse')
STATUTS_VALIDES = ('a_faire', 'en_cours', 'terminee')
VERBE_ACTION_RE = re.compile(
    r'\b(termine|terminee|terminer|termines|terminees|fini|finie|finir|cloture|cloturee|cloturer|'
    r'valide|validee|valider|marque|marquer|'
    r'passe|passer|mets|mettre|remets|remettre|change|changer|rends|rendre|'
    r'supprime|supprimer|efface|effacer|cree|creer|ajoute|ajouter)\b')


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
    dossiers = dossiers_visibles_query(user).order_by(Dossier.numero_dossier).limit(60).all()
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
        "",
        "Dossiers visibles (id, numéro, intitulé) — seuls ces identifiants peuvent être supprimés :",
        *([f"- id={d.id} : {d.numero_dossier} — {d.intitule}" for d in dossiers] or ['- aucun']),
    ]
    if nb_dossiers > len(dossiers):
        lignes.append(f"… et {nb_dossiers - len(dossiers)} autre(s) dossier(s) non listé(s).")
    lignes += ["", contexte_onboarding()]
    return '\n'.join(lignes)


def contexte_onboarding():
    """Suivi des nouveaux dossiers : dossiers en cours, progression, prochaine étape."""
    from .models import OnboardingDossier
    en_cours = OnboardingDossier.query.filter_by(statut='en_cours').all()
    if not en_cours:
        return 'Suivi nouveaux dossiers : aucun dossier en cours.'
    lignes = [f"Suivi nouveaux dossiers : {len(en_cours)} dossier(s) en cours "
              "(id, nom, type, progression, prochaine étape, jours d'attente) :"]
    for d in sorted(en_cours, key=lambda x: x.jours_attente(), reverse=True)[:15]:
        faites, total = d.progression()
        prochaine = d.prochaine_etape()
        libelle = prochaine[1] if prochaine else 'aucune'
        lignes.append(f"- id={d.id} « {d.nom_dossier} » ({d.type_dossier}) — {faites}/{total} étapes"
                      f" — prochaine : {libelle} — en attente depuis {d.jours_attente()} j")
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
    """Prompt système : rôle, règles d'action, instructions du cabinet et données du périmètre."""
    prompt = (
        "Tu es ASTRO, l'assistant IA du cabinet comptable JMH (application JMH Orbit). Tu réponds "
        "en français, de façon brève et claire. Tu t'appuies UNIQUEMENT sur les données ci-dessous ; "
        "si une information n'y figure pas, dis-le sans l'inventer.\n\n"
        "RÈGLE GÉNÉRALE D'ACTION : tu n'exécutes JAMAIS une action toi-même — tu proposes un bloc "
        "que l'utilisateur confirme par un bouton. S'il manque une information pour agir (identifiant, "
        "date, statut cible, dossier concerné), pose la question et attends la réponse, comme un "
        "entretien, au lieu de deviner.\n\n"
        "Pour proposer un email, ajoute à la fin de ta réponse un bloc exact au format :\n"
        '<EMAIL>{"to_user_id": <id d\'un membre listé>, "subject": "...", "body": "..."}</EMAIL>\n'
        "N'utilise que les identifiants listés.\n\n"
        "Pour proposer la création d'une tâche, ajoute à la fin de ta réponse un bloc exact au format :\n"
        '<TACHE>{"titre": "...", "description": "...", "assigne_a_id": <id d\'un membre listé ou null>, '
        '"priorite": "haute|moyenne|basse", "date_echeance": "AAAA-MM-JJ"}</TACHE>\n'
        "Ne propose une tâche que si l'utilisateur la demande. Si la date d'échéance manque, demande-la "
        "au lieu de l'inventer.\n\n"
        "Pour planifier un rappel, ajoute à la fin de ta réponse un bloc exact au format :\n"
        '<RAPPEL>{"titre": "...", "message": "...", "date_echeance": "AAAA-MM-JJ"}</RAPPEL>\n'
        "Un rappel crée une notification in-app immédiate pour l'utilisateur. S'il n'est pas marqué "
        "comme lu (NOTE) sous 24h, un email de relance est envoyé. Un email est aussi envoyé à la "
        "date d'échéance. Ne propose un rappel que si l'utilisateur le demande.\n\n"
        "Pour proposer un changement de statut d'une tâche, ajoute à la fin de ta réponse un bloc exact :\n"
        '<STATUT>{"tache_id": <id d\'une tâche listée>, "statut": "a_faire|en_cours|terminee"}</STATUT>\n'
        "N'utilise que les identifiants de tâches listés. Terminer une tâche deadline fiscale coche "
        "automatiquement la case checklist correspondante.\n\n"
        "Pour un changement EN LOT (ex. « toutes les tâches de X en retard à terminer »), un seul bloc :\n"
        '<STATUT_LOT>{"tache_ids": [<ids listés>], "statut": "a_faire|en_cours|terminee"}</STATUT_LOT>\n'
        "50 tâches maximum, uniquement des identifiants listés. Si la demande couvre des tâches non "
        "listées, dis-le et propose de filtrer (par membre, dossier ou période).\n\n"
        "MÉMOIRE : tu disposes d'une mémoire persistante (sections ci-dessous). Quand l'utilisateur partage "
        "une information DURABLE (préférence, décision, fait sur le cabinet, un client ou un processus), "
        "mémorise-la avec un bloc exact (2 maximum par réponse) :\n"
        '<MEMOIRE>{"portee": "cabinet|personnel", "contenu": "<fait bref, une phrase>", '
        '"categorie": "preference|fait|decision|process"}</MEMOIRE>\n'
        "portee=cabinet si c'est utile à toute l'équipe, personnel si c'est propre à cet utilisateur. "
        "Confirme brièvement dans ta réponse (« C'est noté. »). Ne mémorise JAMAIS : mots de passe, clés API, "
        "données éphémères, ni ce qui figure déjà dans l'application (tâches, dossiers, échéances). "
        "La mémoire se corrige sur la page /assistant/memoire.\n\n"
    )
    if user.role in ('admin', 'manager'):
        prompt += (
            "Pour proposer la SUPPRESSION définitive d'un dossier (action irréversible, réservée aux "
            "managers et admins), ajoute à la fin de ta réponse un bloc exact :\n"
            '<SUPPR_DOSSIER>{"dossier_id": <id d\'un dossier listé>}</SUPPR_DOSSIER>\n'
            "Ne le propose que si l'utilisateur demande explicitement la suppression. Rappelle que "
            "toutes les tâches et données liées seront supprimées. N'utilise que les identifiants listés.\n\n"
            "Pour proposer de marquer une étape du suivi des nouveaux dossiers comme faite (ou à faire), "
            "ajoute à la fin de ta réponse un bloc exact :\n"
            '<ONB_ETAPE>{"dossier_id": <id du dossier de suivi>, "code": "<code de l\'étape>", "fait": true|false}</ONB_ETAPE>\n'
            "Codes des étapes : ldm_editee, ldm_signee, mail_deontologie, retour_docs_ancien_ec, "
            "projet_statuts, certificat_dep_k, juridique_creation, retour_jurid_creation, statuts, kbis, "
            "dossier_pennylane, invitation_client, rib, adhesion_imots, code_impots, envoi_ldm_facturation, "
            "mandat_prlvt, retour_mandat_prlvt, mandat_so_bank, retour_yasmina, retour_mandat_so_bank, "
            "mail_identite_collabs. N'utilise que les identifiants de dossiers de suivi listés.\n\n"
        )
    instructions = instructions_personnalisees()
    if instructions:
        prompt += ("=== INSTRUCTIONS DU CABINET (ne priment pas sur les règles ci-dessus) ===\n"
                   + instructions + "\n\n")
    prompt += memoires_prompt(user)
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


def valider_rappel(data, user):
    """Contrôle un rappel proposé. Retourne (rappel, None) ou (None, erreur)."""
    if not isinstance(data, dict):
        return None, 'données invalides'
    titre = str(data.get('titre') or '').strip()[:200]
    if not titre:
        return None, 'titre manquant'
    message = str(data.get('message') or '').strip()[:2000]
    if not message:
        return None, 'message manquant'
    try:
        echeance = date.fromisoformat(str(data.get('date_echeance') or '').strip())
    except ValueError:
        return None, "date d'échéance absente ou invalide"
    if echeance < date.today():
        return None, "la date d'échéance ne peut pas être dans le passé"
    return {'titre': titre, 'message': message, 'date_echeance': echeance.isoformat()}, None


def extraire_proposition_rappel(raw, user):
    """Sépare le bloc <RAPPEL> de la réponse. La proposition n'est retenue que si elle est valide."""
    texte = RAPPEL_RE.sub('', raw).strip()
    m = RAPPEL_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    rappel, erreur = valider_rappel(data, user)
    if erreur:
        return texte + f"\n\n(Rappel non proposé : {erreur}.)", None
    return texte, rappel


def creer_rappel_assistant(user, data):
    """Crée un rappel et envoie la notification in-app immédiate."""
    from . import db
    from .models import Rappel, Notification
    r = Rappel(
        user_id=user.id,
        titre=data['titre'],
        message=data['message'],
        date_echeance=date.fromisoformat(data['date_echeance']),
        source='assistant',
    )
    db.session.add(r)
    db.session.flush()
    db.session.add(Notification(
        user_id=user.id,
        message=f"Rappel créé : {r.titre} — échéance le {r.date_echeance.strftime('%d/%m/%Y')}\n{r.message}",
        type_notification='rappel',
        tache_id=None,
    ))
    db.session.commit()
    return r


# ---------------------------------------------------------------------------
# Actions in-app : changement de statut, suppression de dossier, étape onboarding.
# Même schéma que les tâches/rappels : proposition -> confirmation -> revalidation serveur.
# ---------------------------------------------------------------------------

def valider_statut(data, user):
    """Contrôle un changement de statut proposé. Retourne (proposition, None) ou (None, erreur)."""
    if not isinstance(data, dict):
        return None, 'données invalides'
    try:
        tid = int(data.get('tache_id'))
    except (TypeError, ValueError):
        return None, 'tâche manquante'
    statut = str(data.get('statut') or '').strip().lower()
    if statut not in STATUTS_VALIDES:
        return None, 'statut invalide'
    t = taches_visibles_query(user).filter(Tache.id == tid).first()
    if not t:
        return None, 'tâche hors de votre périmètre'
    return {'tache_id': t.id, 'titre': t.titre, 'ancien_statut': t.statut, 'statut': statut}, None


def extraire_proposition_statut(raw, user):
    """Sépare le bloc <STATUT> de la réponse. Proposition retenue seulement si valide."""
    texte = STATUT_RE.sub('', raw).strip()
    m = STATUT_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    proposition, erreur = valider_statut(data, user)
    if erreur:
        return texte + f"\n\n(Changement de statut non proposé : {erreur}.)", None
    return texte, proposition


def appliquer_statut_assistant(user, data):
    """Applique un statut DÉJÀ revalidé. Même effets que la route manuelle :
    dates de suivi, liaison tâche->checklist, notification (+ email) au créateur."""
    from . import db, app
    from datetime import datetime
    from .checklist_link import appliquer_tache_a_case
    t = db.session.get(Tache, data['tache_id'])
    nouveau = data['statut']
    t.statut = nouveau
    t.statut_source = 'manuel' if nouveau == 'terminee' else None
    if nouveau == 'terminee':
        t.date_completion = datetime.utcnow()
        if not t.date_prise_en_charge:
            t.date_prise_en_charge = datetime.utcnow()
    elif nouveau == 'en_cours' and not t.date_prise_en_charge:
        t.date_prise_en_charge = datetime.utcnow()
    elif nouveau == 'a_faire':
        t.date_prise_en_charge = None
        t.date_completion = None
    db.session.commit()
    try:
        if appliquer_tache_a_case(t, acteur=user):
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.warning(f"Liaison tache->case (assistant): {exc}")

    cree_par_id = t.cree_par
    if not cree_par_id and t.dossier and t.dossier.equipe and t.dossier.equipe.manager:
        cree_par_id = t.dossier.equipe.manager.id
    if cree_par_id and cree_par_id != user.id:
        statut_txt = nouveau.replace('_', ' ')
        message = f"{user.nom_complet()} a changé le statut de \"{t.titre}\" à \"{statut_txt}\" (via ASTRO)"
        db.session.add(Notification(user_id=cree_par_id, tache_id=t.id,
                                    message=message, type_notification='systeme'))
        db.session.commit()
        dest = User.query.get(cree_par_id)
        if dest and dest.email:
            try:
                from app.integrations.brevo import send_email_via_brevo_api
                send_email_via_brevo_api(
                    to_email=dest.email, subject=f"Changement de statut : {t.titre}",
                    body=f"Bonjour {dest.prenom},\n\n{message}.\n\nCabinet JMH")
            except Exception as exc:
                app.logger.warning(f"Email statut (assistant) error: {exc}")
    return t


def valider_statut_lot(data, user):
    """Changement de statut EN LOT (1 à 50 tâches), toutes dans le périmètre.
    Retourne (proposition, None) ou (None, erreur)."""
    if not isinstance(data, dict):
        return None, 'données invalides'
    ids_bruts = data.get('tache_ids')
    if not isinstance(ids_bruts, list) or not ids_bruts:
        return None, 'liste de tâches manquante'
    try:
        ids = list(dict.fromkeys(int(i) for i in ids_bruts))
    except (TypeError, ValueError):
        return None, 'identifiants de tâches invalides'
    if len(ids) > 50:
        return None, 'lot trop grand (50 tâches maximum)'
    statut = str(data.get('statut') or '').strip().lower()
    if statut not in STATUTS_VALIDES:
        return None, 'statut invalide'
    taches = taches_visibles_query(user).filter(Tache.id.in_(ids)).all()
    if len(taches) != len(ids):
        return None, 'une ou plusieurs tâches sont hors de votre périmètre'
    return {'tache_ids': ids, 'statut': statut, 'nb': len(taches),
            'lignes': [{'id': t.id, 'titre': t.titre} for t in taches]}, None


def extraire_proposition_statut_lot(raw, user):
    """Sépare le bloc <STATUT_LOT>. Proposition retenue seulement si valide."""
    texte = STATUT_LOT_RE.sub('', raw).strip()
    m = STATUT_LOT_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    proposition, erreur = valider_statut_lot(data, user)
    if erreur:
        return texte + f"\n\n(Changement en lot non proposé : {erreur}.)", None
    return texte, proposition


def appliquer_statut_lot(user, data):
    """Applique le statut à chaque tâche du lot (mêmes effets unitaires :
    dates, liaison checklist, notification au créateur). Retourne le nombre traité."""
    n = 0
    for tid in data['tache_ids']:
        appliquer_statut_assistant(user, {'tache_id': tid, 'statut': data['statut']})
        n += 1
    return n


def valider_suppression_dossier(data, user):
    """Suppression réservée managers/admins, dossier dans le périmètre. (proposition, erreur)."""
    if user.role not in ('admin', 'manager'):
        return None, 'suppression réservée aux managers et admins'
    try:
        did = int(data.get('dossier_id'))
    except (TypeError, ValueError):
        return None, 'dossier manquant'
    d = dossiers_visibles_query(user).filter(Dossier.id == did).first()
    if not d:
        return None, 'dossier hors de votre périmètre'
    nb_taches = Tache.query.filter_by(dossier_id=d.id).count()
    return {'dossier_id': d.id, 'numero': d.numero_dossier, 'intitule': d.intitule,
            'nb_taches': nb_taches}, None


def extraire_proposition_suppression(raw, user):
    """Sépare le bloc <SUPPR_DOSSIER>. Proposition retenue seulement si valide."""
    texte = SUPPR_DOSSIER_RE.sub('', raw).strip()
    m = SUPPR_DOSSIER_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    proposition, erreur = valider_suppression_dossier(data, user)
    if erreur:
        return texte + f"\n\n(Suppression non proposée : {erreur}.)", None
    return texte, proposition


def appliquer_suppression_dossier(user, data):
    """Supprime le dossier et TOUTES ses données liées (même nettoyage que la route manuelle)."""
    from . import db, app
    from .route_common import _nettoyer_relations_dossier
    d = db.session.get(Dossier, data['dossier_id'])
    numero = d.numero_dossier
    _nettoyer_relations_dossier(d)
    db.session.delete(d)
    db.session.commit()
    app.logger.info(f"assistant suppression dossier from={user.id} dossier={numero}")
    return numero


def valider_onb_etape(data, user):
    """Étape du suivi nouveaux dossiers : managers/admins, code applicable. (proposition, erreur)."""
    if user.role not in ('admin', 'manager'):
        return None, 'modification réservée aux managers et admins'
    from .models import OnboardingDossier
    from .onboarding_steps import ONBOARDING_CODES, etape_label
    try:
        did = int(data.get('dossier_id'))
    except (TypeError, ValueError):
        return None, 'dossier manquant'
    d = OnboardingDossier.query.get(did)
    if not d:
        return None, 'dossier de suivi introuvable'
    code = str(data.get('code') or '').strip()
    if code not in ONBOARDING_CODES:
        return None, 'étape inconnue'
    if code not in [c for c, _l, _p in d.etapes_applicables()]:
        return None, 'étape non applicable à ce type de dossier'
    fait = bool(data.get('fait', True))
    s = d.etape(code)
    return {'dossier_id': d.id, 'nom_dossier': d.nom_dossier, 'code': code,
            'label': etape_label(code), 'fait': fait, 'deja_fait': bool(s and s.est_fait)}, None


def extraire_proposition_onb_etape(raw, user):
    """Sépare le bloc <ONB_ETAPE>. Proposition retenue seulement si valide."""
    texte = ONB_ETAPE_RE.sub('', raw).strip()
    m = ONB_ETAPE_RE.search(raw)
    if not m:
        return texte, None
    try:
        data = json.loads(m.group(1).strip())
    except ValueError:
        return texte, None
    proposition, erreur = valider_onb_etape(data, user)
    if erreur:
        return texte + f"\n\n(Étape non proposée : {erreur}.)", None
    return texte, proposition


def appliquer_onb_etape(user, data):
    """Marque l'étape faite (date du jour) ou à faire, puis lance l'action email configurée.
    Même logique que la route manuelle /onboarding/<id>/etape."""
    from . import db
    from .models import OnboardingDossier, OnboardingEtape
    d = OnboardingDossier.query.get(data['dossier_id'])
    s = d.etape(data['code'])
    if s is None:
        s = OnboardingEtape(dossier_onb_id=d.id, code=data['code'])
        db.session.add(s)
    s.date_fait = date.today() if data['fait'] else None
    s.sans_date = False
    s.fait_par_id = user.id if s.est_fait else None
    db.session.commit()
    mails, manquants = ([], [])
    if s.est_fait:
        from .routes_onboarding import _executer_action
        mails, manquants = _executer_action(d, data['code'])
        db.session.commit()
    return s, mails, manquants


# ---------------------------------------------------------------------------
# Mémoire longue : cabinet (partagée par l'équipe) + personnelle (par compte).
# Apprise des discussions (bloc MEMOIRE), de « souviens-toi » ou de la page dédiée.
# ---------------------------------------------------------------------------

MEMOIRE_MAX_LEN = 500
MEMOIRE_MAX_CABINET = 100
MEMOIRE_MAX_PERSONNEL = 50
_MEMOIRE_SECRET_RE = re.compile(r'\b(?:sk|nvapi|gsk|pl_o)_[A-Za-z0-9_-]{8,}|\bBearer\s+\S{12,}', re.I)


def enregistrer_memoire(user, portee, contenu, categorie=None, source='conversation'):
    """Valide, déduplique et stocke un souvenir. Retourne (memoire, info) :
    info = 'cree' | 'deja_presente', ou (None, message d'erreur)."""
    from . import db
    from .models import AssistantMemoire
    portee = str(portee or '').strip().lower()
    if portee not in ('cabinet', 'personnel'):
        return None, 'portée invalide'
    contenu = ' '.join(str(contenu or '').split())
    if len(contenu) < 3:
        return None, 'contenu trop court'
    if len(contenu) > MEMOIRE_MAX_LEN:
        return None, f'contenu trop long ({MEMOIRE_MAX_LEN} caractères max)'
    if _MEMOIRE_SECRET_RE.search(contenu):
        return None, 'ne stockez jamais de clé API ou de mot de passe dans la mémoire'
    q = AssistantMemoire.query.filter_by(portee=portee)
    if portee == 'personnel':
        q = q.filter_by(user_id=user.id)
    existantes = q.all()
    cle = _normaliser(contenu)
    for m in existantes:
        if _normaliser(m.contenu) == cle:
            return m, 'deja_presente'
    maxi = MEMOIRE_MAX_CABINET if portee == 'cabinet' else MEMOIRE_MAX_PERSONNEL
    if len(existantes) >= maxi:
        return None, f'mémoire {portee} pleine ({maxi} entrées) — faites le tri sur la page Mémoire'
    categorie = str(categorie or '').strip().lower()[:40] or None
    if categorie and categorie not in ('preference', 'fait', 'decision', 'process'):
        categorie = 'fait'
    m = AssistantMemoire(portee=portee, user_id=user.id if portee == 'personnel' else None,
                         contenu=contenu, categorie=categorie, source=source, cree_par_id=user.id)
    db.session.add(m)
    db.session.commit()
    return m, 'cree'


def extraire_memoires(raw, user):
    """Extrait les blocs <MEMOIRE> d'une réponse LLM (max 2) et les enregistre.
    Retourne (texte nettoyé, [{'contenu', 'portee', 'info'}])."""
    blocs = MEMOIRE_RE.findall(raw)
    texte = MEMOIRE_RE.sub('', raw).strip()
    notes = []
    for b in blocs[:2]:
        try:
            data = json.loads(b.strip())
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        m, info = enregistrer_memoire(user, data.get('portee'), data.get('contenu'),
                                      data.get('categorie'), source='conversation')
        if m:
            notes.append({'contenu': m.contenu, 'portee': m.portee, 'info': info})
    return texte, notes


def memoires_prompt(user):
    """Sections mémoire du prompt système : récentes d'abord, budget caractères borné."""
    from .models import AssistantMemoire

    def _section(titre, memos):
        lignes = [titre]
        budget = 1500
        for m in memos:
            ligne = f"- {m.contenu}"
            if budget - len(ligne) < 0:
                break
            lignes.append(ligne)
            budget -= len(ligne)
        if len(lignes) == 1:
            lignes.append('- (vide)')
        return '\n'.join(lignes)

    cabinet = (AssistantMemoire.query.filter_by(portee='cabinet')
               .order_by(AssistantMemoire.date_creation.desc()).limit(20).all())
    perso = (AssistantMemoire.query.filter_by(portee='personnel', user_id=user.id)
             .order_by(AssistantMemoire.date_creation.desc()).limit(20).all())
    return (_section("=== MÉMOIRE DU CABINET (partagée par toute l'équipe) ===", cabinet)
            + '\n\n' + _section(f'=== MÉMOIRE PERSONNELLE DE {user.prenom} ===', perso) + '\n\n')


def detecter_memoire(message, user):
    """Voie rapide SANS LLM : « souviens-toi que… », « note que… », « mémorise… »,
    commande « /remembre … » (garde l'info en base Orbit pour un accès rapide).
    Portée cabinet si « pour le cabinet / pour l'équipe / à partager » est précisé."""
    match = re.match(r'^\s*(souviens[-\s]toi|rappelle[-\s]toi|retiens|note(?:s)?|mémorise|memorise|/remembre|/remember)'
                     r'\s+(?:que\s+|ceci\s*:?\s*)?(.+)$', message.strip(), re.I | re.S)
    if not match:
        return None
    trigger = match.group(1).lower()
    contenu = match.group(2).strip()
    portee = 'personnel'
    scope = re.search(r'\s+(?:pour\s+(?:le\s+cabinet|toute\s+l[’\']équipe|l[’\']équipe|tous|tout\s+le\s+monde)'
                      r'|en\s+mémoire\s+partagée|à\s+partager)\s*$', contenu, re.I)
    if scope:
        portee = 'cabinet'
        contenu = contenu[:scope.start()].strip()
    m, info = enregistrer_memoire(user, portee, contenu, source='regles')
    if not m:
        return {'reponse': f"Je n'ai pas pu mémoriser : {info}."}
    libelle = 'du cabinet (partagée avec l\'équipe)' if portee == 'cabinet' else 'personnelle'
    if info == 'deja_presente':
        return {'reponse': f"C'est déjà dans ma mémoire {libelle} : « {m.contenu} »"}
    if trigger in ('/remembre', '/remember'):
        return {'reponse': f"Gardé en Orbit pour un accès rapide, dans ma mémoire {libelle} : "
                           f"« {m.contenu} ». Je l'archive aussi sur le stockage externe ce soir.",
                'memoires': [{'contenu': m.contenu, 'portee': m.portee, 'info': info}]}
    return {'reponse': f"C'est noté dans ma mémoire {libelle} : « {m.contenu} »",
            'memoires': [{'contenu': m.contenu, 'portee': m.portee, 'info': info}]}


def detecter_recherche_historique(message, user):
    """Voie rapide : « cherche dans l'historique : … ». Fouille le tampon base
    (récent) puis les archives du collaborateur (Drive/local)."""
    m = _normaliser(message)
    if not any(p in m for p in ('dans l historique', 'cherche dans l historique',
                                'recherche dans l historique', 'conversation precedente',
                                'dans nos conversations', 'historique des conversations')):
        return None
    from .assistant_archive import rechercher_historique
    requete = message.split(':', 1)[1].strip() if ':' in message else ''
    if not requete:
        mm = re.search(r'(?:historique|conversations?)\s*[:\-]?\s*(.+)$', message, re.I | re.S)
        requete = mm.group(1).strip() if mm else ''
    if not requete:
        return {'reponse': "Précisez ce que je dois chercher, par exemple : "
                           "« cherche dans l'historique : client Dupont »."}
    extraits = rechercher_historique(user, requete)
    if not extraits:
        return {'reponse': f"Rien trouvé dans l'historique pour « {requete} » "
                           "(conversations récentes + archives)."}
    lignes = [f"J'ai trouvé ceci dans l'historique pour « {requete} » :"]
    for e in extraits:
        qui = 'vous' if e['role'] == 'user' else 'ASTRO'
        lignes.append(f"- [{e['date']} · {qui} · {e['source']}] {e['texte']}")
    return {'reponse': '\n'.join(lignes)}


def journaliser_echange(user, message, reponse):
    """Tampon journalier : stocke la question + la réponse en base (exportées puis
    purgées par le job du soir). Borné à 8000 caractères par entrée pour garder
    Neon minuscule. Une erreur de journalisation ne casse jamais la réponse."""
    from . import db
    from .models import AssistantMessage
    try:
        db.session.add(AssistantMessage(user_id=user.id, role='user', contenu=(message or '')[:8000]))
        db.session.add(AssistantMessage(user_id=user.id, role='assistant', contenu=(reponse or '')[:8000]))
        db.session.commit()
    except Exception:
        db.session.rollback()


def detecter_action(message, user):
    """Voie rapide SANS LLM pour les actions explicites.

    « termine la tâche #123 », « passe la tâche 123 en cours »,
    « rendre cette tâche terminée Dépôt TVA mensuel — 1003 » (par titre),
    « toutes les tâches de Hamza en retard à terminer » (lot),
    « supprime le dossier SOPARK », « souviens-toi que… » (mémoire).
    Retourne {'reponse', 'statut'?|'statut_lot'?|'suppression'?|'memoires'?} ou None.
    """
    mem = detecter_memoire(message, user)
    if mem:
        return mem
    m = _normaliser(message)
    if not m:
        return None

    verbe_statut = re.search(r'\b(termine|terminee|terminer|termines|terminees|fini|finie|finir|'
                             r'cloture|cloturee|cloturer|valide|validee|valider|'
                             r'marque|marquer|passe|passer|mets|mettre|remets|remettre|'
                             r'change|changer|rends|rendre)\b', m)

    def _cible_statut():
        if 'en cours' in m:
            return 'en_cours'
        if 'a faire' in m:
            return 'a_faire'
        if re.search(r'\b(termine|terminee|terminer|termines|terminees|fini|finie|finir|'
                     r'cloture|cloturee|cloturer|valide|validee|valider)\b', m):
            return 'terminee'
        return None  # statut cible ambigu : le LLM demandera

    # --- Changement de statut avec n° de tâche explicite ---
    ref = re.search(r'#(\d+)', m) or re.search(r'tache\s+(\d+)', m)
    if ref and verbe_statut:
        cible = _cible_statut()
        if not cible:
            return None
        proposition, erreur = valider_statut({'tache_id': int(ref.group(1)), 'statut': cible}, user)
        if erreur:
            return {'reponse': f"Changement impossible : {erreur}."}
        return {'reponse': f"Je propose de passer « {proposition['titre']} » "
                           f"de {proposition['ancien_statut'].replace('_', ' ')} à {cible.replace('_', ' ')}.",
                'statut': proposition}

    # --- Lot : « toutes les tâches de X en retard à terminer » ---
    if re.search(r'\b(?:toutes|tous)\s+(?:(?:les|mes|ces)\s+)?taches?\b', m) and verbe_statut:
        cible = _cible_statut()
        if not cible:
            return None
        q = taches_visibles_query(user).filter(~Tache.statut.in_(STATUTS_TERMINES))
        scope = 'ouvertes'
        nm = re.search(r'\btaches?\s+(?:de\s+|a\s+|assignees?\s+a\s+)'
                       r'([a-z][a-z\s-]+?)(?:\s+en\s+retard|\s+a\s+(?:termine|terminee|faire|cours)|\s*$)', m)
        nom = nm.group(1).strip() if nm else None
        # « toutes les tâches à terminer » : la capture est un mot de statut, pas un nom
        if nom and all(p in ('termine', 'terminee', 'terminer', 'termines', 'terminees',
                             'fini', 'finir', 'faire', 'cours', 'en', 'retard', 'a')
                       for p in nom.split()):
            nom = None
        if nom:
            cible_user = None
            visibles = membres_visibles_query(user).all()
            for u in visibles:
                if nom in (_normaliser(u.nom_complet()),
                           _normaliser((u.nom or '') + ' ' + (u.prenom or ''))):
                    cible_user = u
                    break
            if not cible_user:
                for u in visibles:
                    if nom in _normaliser(u.nom_complet()):
                        cible_user = u
                        break
            if not cible_user:
                return {'reponse': f"Je ne trouve pas « {nom} » dans votre périmètre."}
            q = q.filter(Tache.assigne_a == cible_user.id)
            scope = f'assignées à {cible_user.nom_complet()}'
        elif re.search(r'\bmes\s+(?:propres\s+)?taches?\b', m):
            q = q.filter(Tache.assigne_a == user.id)
            scope = 'vous étant assignées'
        if 'en retard' in m:
            q = q.filter(Tache.date_echeance < date.today())
            scope += ', en retard'
        taches = q.order_by(Tache.date_echeance).limit(51).all()
        if not taches:
            return {'reponse': f"Aucune tâche {scope} à changer."}
        if len(taches) > 50:
            return {'reponse': "Plus de 50 tâches correspondantes : précisez un dossier ou une période."}
        proposition, erreur = valider_statut_lot({'tache_ids': [t.id for t in taches],
                                                  'statut': cible}, user)
        if erreur:
            return {'reponse': f"Changement en lot impossible : {erreur}."}
        return {'reponse': f"Je propose de passer {proposition['nb']} tâche(s) {scope} "
                           f"à {cible.replace('_', ' ')}.",
                'statut_lot': proposition}

    # --- Statut par titre : le message contient le titre d'une tâche visible ---
    if verbe_statut and not ref:
        cible = _cible_statut()
        if cible:
            candidates = [t for t in taches_visibles_query(user).limit(400).all()
                          if len(_normaliser(t.titre)) >= 8 and _normaliser(t.titre) in m]
            if len(candidates) == 1:
                proposition, erreur = valider_statut({'tache_id': candidates[0].id, 'statut': cible}, user)
                if erreur:
                    return {'reponse': f"Changement impossible : {erreur}."}
                return {'reponse': f"Je propose de passer « {proposition['titre']} » "
                                   f"de {proposition['ancien_statut'].replace('_', ' ')} "
                                   f"à {cible.replace('_', ' ')}.",
                        'statut': proposition}
            if len(candidates) > 1:
                lignes = ["Plusieurs tâches correspondent — précisez le numéro :"]
                lignes += [f"- #{t.id} « {t.titre} »" for t in candidates[:8]]
                return {'reponse': '\n'.join(lignes)}

    # --- Suppression de dossier par numéro ou intitulé ---
    suppr = re.search(r'\b(?:supprime|supprimer|efface|effacer)\s+(?:le\s+)?dossier\s+(.+)$', m)
    if suppr:
        if user.role not in ('admin', 'manager'):
            return {'reponse': 'La suppression de dossier est réservée aux managers et admins.'}
        cible = suppr.group(1).strip()
        like = f'%{cible}%'
        matchs = (dossiers_visibles_query(user)
                  .filter(or_(Dossier.numero_dossier.ilike(like), Dossier.intitule.ilike(like)))
                  .order_by(Dossier.numero_dossier).limit(8).all())
        exact = [d for d in matchs if _normaliser(d.numero_dossier) == cible]
        if len(exact) == 1:
            matchs = exact
        if not matchs:
            return {'reponse': f"Aucun dossier « {cible} » dans votre périmètre."}
        if len(matchs) > 1:
            lignes = [f"Plusieurs dossiers correspondent à « {cible} » — précisez le numéro exact :"]
            lignes += [f"- {d.numero_dossier} — {d.intitule}" for d in matchs]
            return {'reponse': '\n'.join(lignes)}
        proposition, erreur = valider_suppression_dossier({'dossier_id': matchs[0].id}, user)
        if erreur:
            return {'reponse': f"Suppression impossible : {erreur}."}
        return {'reponse': f"Je propose la suppression définitive de « {proposition['numero']} — "
                           f"{proposition['intitule']} » ({proposition['nb_taches']} tâche(s) liée(s)).",
                'suppression': proposition}
    return None


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
    """Routeur par règles (sans LLM). Retourne 'resume', 'retard', 'demain', 'jour',
    'onboarding', 'memoire' ou None.

    None = question libre : le modèle de réponse prend le relais. Les messages
    longs (> 200 caractères, ex. texte collé) ou contenant un verbe d'action ne
    sont JAMAIS routés ici — ils vont aux actions puis au LLM.
    """
    m = _normaliser(message).replace('-', ' ')
    if not m or len(m) > 200:
        return None
    if VERBE_ACTION_RE.search(m):
        return None
    if any(k in m for k in ('nouveau dossier', 'nouveaux dossiers', 'onboarding', 'suivi nouveau')):
        return 'onboarding'
    if any(k in m for k in ('memoire', 'retenu', 'sais tu de moi', 'sais tu de nous')):
        return 'memoire'
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
    if intention == 'memoire':
        from .models import AssistantMemoire
        perso = (AssistantMemoire.query.filter_by(portee='personnel', user_id=user.id)
                 .order_by(AssistantMemoire.date_creation.desc()).all())
        cabinet = (AssistantMemoire.query.filter_by(portee='cabinet')
                   .order_by(AssistantMemoire.date_creation.desc()).all())
        lignes = [f"Ma mémoire personnelle à votre sujet ({len(perso)} entrée(s)) :"]
        lignes += [f"- {m.contenu}" for m in perso[:10]] or ['- (vide)']
        lignes.append(f"\nMémoire du cabinet, partagée avec l'équipe ({len(cabinet)} entrée(s)) :")
        lignes += [f"- {m.contenu}" for m in cabinet[:10]] or ['- (vide)']
        lignes.append("\nVous pouvez corriger ou effacer ces souvenirs sur la page Mémoire "
                      "(bouton journal dans mon panneau).")
        return '\n'.join(lignes)
    if intention == 'onboarding':
        from .models import OnboardingDossier
        en_cours = OnboardingDossier.query.filter_by(statut='en_cours').all()
        if not en_cours:
            return 'Aucun nouveau dossier en cours de suivi.'
        lignes = [f"{len(en_cours)} nouveau(x) dossier(s) en cours :"]
        for d in sorted(en_cours, key=lambda x: x.jours_attente(), reverse=True)[:10]:
            faites, total = d.progression()
            prochaine = d.prochaine_etape()
            libelle = prochaine[1] if prochaine else 'aucune — pipeline terminé'
            lignes.append(f"- {d.nom_dossier} : {faites}/{total} étapes — prochaine : {libelle}"
                          f" — en attente depuis {d.jours_attente()} j")
        return '\n'.join(lignes)
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
