import requests
import logging
from app.models import AppSetting

logger = logging.getLogger(__name__)


def get_brevo_api_key() -> str:
    setting = AppSetting.query.filter_by(cle='BREVO_API_KEY').first()
    if setting and setting.valeur:
        return setting.valeur.strip()
    return ''


def send_email_via_brevo_api(to_email: str, subject: str, body: str, sender_name: str = 'Cabinet JMH') -> bool:
    api_key = get_brevo_api_key()
    if not api_key:
        logger.error('BREVO_API_KEY is not configured')
        return False

    url = 'https://api.brevo.com/v3/smtp/email'
    headers = {
        'api-key': api_key,
        'Content-Type': 'application/json',
    }
    payload = {
        'sender': {
            'name': sender_name,
            'email': 'jlassiaziz418@gmail.com',
        },
        'to': [{'email': to_email}],
        'subject': subject,
        'textContent': body,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code in (200, 201):
            logger.info('Brevo API email sent to %s', to_email)
            return True
        logger.error('Brevo API error: %s %s', resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error('Brevo API request failed: %s', e)
        return False


def send_task_assignment_email_brevo(tache, assignee_id: int) -> None:
    from app.models import User

    user = User.query.get(assignee_id)
    if not user or not user.email:
        return

    subject = f"Nouvelle tâche assignée: {tache.titre}"
    body = f"""Bonjour {user.prenom} {user.nom},

Une nouvelle tâche vous a été assignée :

Titre: {tache.titre}
Description: {tache.description}
Priorité: {tache.priorite}
Date d'échéance: {tache.date_echeance}

Veuillez la prendre en charge dans l'application.

Cordialement,
L'équipe Cabinet JMH
"""

    send_email_via_brevo_api(to_email=user.email, subject=subject, body=body)
