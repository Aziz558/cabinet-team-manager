"""Notifications dans l'application pour les échéances proches (aujourd'hui et demain).

Complète les emails existants (récapitulatif quotidien 08:00, rappel J-2 des dépôts) :
ici, une cloche dans Orbit, une seule fois par tâche, destinataire et date d'échéance.
Le marqueur est une Notification de type 'rappel_echeance' dont le message contient la date.
"""
from datetime import date, timedelta

from .models import Tache, Notification

TYPE_RAPPEL_ECHEANCE = 'rappel_echeance'
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
