"""Notifications dans l'application pour les échéances proches (aujourd'hui et demain).

Complète les emails existants (récapitulatif quotidien 08:00, rappel J-2 des dépôts) :
ici, une cloche dans Orbit, une seule fois par tâche, destinataire et date d'échéance.
Le marqueur est une Notification de type 'rappel_echeance' dont le message contient la date.
"""
from datetime import date, timedelta, datetime

from .models import Tache, Notification, Rappel

TYPE_RAPPEL_ECHEANCE = 'rappel_echeance'
TYPE_RAPPEL = 'rappel'
STATUTS_TERMINES = ('terminee', 'terminée')


def _destinataires(t):
    """Assigné + manager de l'équipe du dossier (même règle que le récapitulatif quotidien)."""
    ids = set()
    if t.assigne_a:
        ids.add(t.assigne_a)
    if t.dossier and t.dossier.equipe and t.dossier.equipe.manager_id:
        ids.add(t.dossier.equipe.manager_id)
    return ids


def creer_rappels_echeances(aujourd_hui=None):
    """Crée une notification pour chaque tâche ouverte due aujourd'hui ou demain.

    Retourne le nombre de notifications créées. Ne recrée jamais une notification déjà
    présente pour la même tâche, le même destinataire et la même date d'échéance.
    """
    from . import db

    ref = aujourd_hui or date.today()
    horizon = ref + timedelta(days=1)
    taches = Tache.query.filter(
        Tache.date_echeance.between(ref, horizon),
        ~Tache.statut.in_(STATUTS_TERMINES),
    ).all()

    crees = 0
    for t in taches:
        quand = "aujourd'hui" if t.date_echeance == ref else 'demain'
        marqueur = f"échéance {t.date_echeance.strftime('%d/%m/%Y')}"
        for uid in _destinataires(t):
            deja = Notification.query.filter(
                Notification.user_id == uid,
                Notification.tache_id == t.id,
                Notification.type_notification == TYPE_RAPPEL_ECHEANCE,
                Notification.message.contains(marqueur),
            ).first()
            if deja:
                continue
            db.session.add(Notification(
                user_id=uid, tache_id=t.id,
                message=f"Échéance {quand} ({marqueur}) : {t.titre}",
                type_notification=TYPE_RAPPEL_ECHEANCE,
            ))
            crees += 1
    db.session.commit()
    return crees


# ---------------------------------------------------------------------------
# Emails de rappel (relance J+1 si non lu, et email à la date d'échéance)
# ---------------------------------------------------------------------------

def _destinataire_rappel(r):
    """L'utilisateur propriétaire du rappel."""
    from .models import User
    return User.query.get(r.user_id)


def envoyer_email_rappel(r, motif):
    """Envoie un email de rappel à l'utilisateur via Brevo (avec fallback SMTP)."""
    from .integrations.brevo import send_email_via_brevo_api
    u = _destinataire_rappel(r)
    if not u or not u.email:
        return False
    sujet = f"🔔 Rappel Orbit : {r.titre}"
    corps = (
        f"Bonjour {u.prenom},\n\n"
        f"Rappel : {r.titre}\n"
        f"{r.message}\n\n"
        f"Échéance : {r.date_echeance.strftime('%d/%m/%Y')}\n"
        f"Motif : {motif}\n\n"
        f"Connectez-vous à Orbit pour marquer ce rappel comme lu (NOTE) et arrêter les relances.\n"
    )
    return send_email_via_brevo_api(
        to_email=u.email,
        subject=sujet,
        body=corps,
    )


def verifier_rappels_j1():
    """Envoie un email J+1 pour les rappels non lus créés il y a plus de 24h.

    Un seul email J+1 par rappel (marqué par email_j1_envoye).
    """
    from . import db
    depuis = datetime.utcnow() - timedelta(hours=24)
    rappels = Rappel.query.filter(
        Rappel.lu == False,  # noqa: E712
        Rappel.archive == False,  # noqa: E712
        Rappel.email_j1_envoye == False,  # noqa: E712
        Rappel.date_creation <= depuis,
    ).all()
    envoyes = 0
    for r in rappels:
        if envoyer_email_rappel(r, 'relance J+1 — rappel non lu depuis plus de 24h'):
            r.email_j1_envoye = True
            envoyes += 1
    if envoyes:
        db.session.commit()
    return envoyes


def verifier_rappels_echeance():
    """Envoie un email à la date d'échéance pour les rappels non lus.

    Un seul email à échéance par rappel (marqué par email_echeance_envoye).
    """
    from . import db
    aujourd_hui = date.today()
    rappels = Rappel.query.filter(
        Rappel.lu == False,  # noqa: E712
        Rappel.archive == False,  # noqa: E712
        Rappel.email_echeance_envoye == False,  # noqa: E712
        Rappel.date_echeance == aujourd_hui,
    ).all()
    envoyes = 0
    for r in rappels:
        if envoyer_email_rappel(r, f'échéance aujourd\'hui ({aujourd_hui.strftime("%d/%m/%Y")})'):
            r.email_echeance_envoye = True
            envoyes += 1
    if envoyes:
        db.session.commit()
    return envoyes

