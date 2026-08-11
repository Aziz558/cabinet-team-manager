import requests
import logging
from app.models import AppSetting

logger = logging.getLogger(__name__)


def get_brevo_api_key() -> str:
    setting = AppSetting.query.filter_by(cle='BREVO_API_KEY').first()
    if setting and setting.valeur:
        return setting.valeur.strip()
    return ''


def send_email_via_brevo_api(
    to_email: str,
    subject: str,
    body: str,
    html_content: str = None,
    sender_name: str = 'Cabinet JMH',
) -> bool:
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
    if html_content:
        payload['htmlContent'] = html_content

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


def send_task_assigned_email_brevo(tache, assignee_id: int) -> bool:
    from app.models import User, Equipe
    from flask import render_template_string

    user = User.query.get(assignee_id)
    if not user or not user.email:
        return False

    subject = f"Nouvelle tâche assignée : {tache.titre}"

    # Render HTML email
    template = """
    <html>
    <body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,sans-serif;background:#1a1a2e;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:40px 20px;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#16213e;border-radius:12px;overflow:hidden;max-width:600px;">
                    <tr>
                        <td style="background:#FF8C00;padding:24px 32px;text-align:center;">
                            <h1 style="color:#fff;margin:0;font-size:22px;">📋 Nouvelle tâche assignée</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:32px;">
                            <p style="color:#e0e0e0;font-size:16px;margin:0 0 24px 0;">
                                Bonjour <strong style="color:#FF8C00;">{{ prenom }}</strong> {{ nom }},
                            </p>
                            <p style="color:#c0c0c0;font-size:14px;margin:0 0 24px 0;">
                                Une nouvelle tâche vous a été assignée par <strong style="color:#FF8C00;">{{ cree_par }}</strong> :
                            </p>
                            <table width="100%" cellpadding="12" cellspacing="0" style="background:#0f3460;border-radius:8px;margin-bottom:24px;">
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Tâche</td><td style="color:#fff;font-size:15px;font-weight:bold;">{{ titre }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Description</td><td style="color:#c0c0c0;font-size:14px;">{{ description|default('(aucune)') }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Priorité</td><td style="color:#FF8C00;font-size:14px;font-weight:bold;">{{ priorite|capitalize }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Échéance</td><td style="color:#fff;font-size:14px;">{{ date_echeance }}</td></tr>
                            </table>
                            <p style="color:#888;font-size:12px;margin:24px 0 0 0;">
                                Ouvrez l'application Cabinet JMH pour prendre en charge cette tâche.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="background:#0a0a1a;padding:20px 32px;text-align:center;">
                            <p style="color:#555;font-size:11px;margin:0;">Cabinet JMH — Gestion de tâches</p>
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """
    html_content = render_template_string(
        template,
        prenom=user.prenom,
        nom=user.nom,
        cree_par=tache.createur.nom if hasattr(tache, 'createur') and tache.createur else 'Votre manager',
        titre=tache.titre,
        description=tache.description or '',
        priorite=tache.priorite,
        date_echeance=tache.date_echeance.strftime('%d/%m/%Y') if tache.date_echeance else '',
    )

    return send_email_via_brevo_api(
        to_email=user.email,
        subject=subject,
        body=f"Bonjour {user.prenom} {user.nom}, nouvelle tâche : {tache.titre}",
        html_content=html_content,
    )


def send_task_taken_email_brevo(tache, collab_nom) -> bool:
    from flask import render_template_string

    creeur = User.query.get(tache.cree_par)
    if not creeur or not creeur.email:
        return False

    subject = f"Prise en charge : {tache.titre}"

    template = """
    <html>
    <body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,sans-serif;background:#1a1a2e;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:40px 20px;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#16213e;border-radius:12px;overflow:hidden;max-width:600px;">
                    <tr>
                        <td style="background:#059669;padding:24px 32px;text-align:center;">
                            <h1 style="color:#fff;margin:0;font-size:22px;">✅ Tâche en cours</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:32px;">
                            <p style="color:#e0e0e0;font-size:16px;margin:0 0 24px 0;">
                                Bonjour <strong style="color:#059669;">{{ prenom }}</strong> {{ nom }},
                            </p>
                            <p style="color:#c0c0c0;font-size:14px;margin:0 0 24px 0;">
                                <strong style="color:#FF8C00;">{{ collab }}</strong> a pris en charge la tâche :
                            </p>
                            <table width="100%" cellpadding="12" cellspacing="0" style="background:#0f3460;border-radius:8px;margin-bottom:24px;">
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Tâche</td><td style="color:#fff;font-size:15px;font-weight:bold;">{{ titre }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Collaborateur</td><td style="color:#059669;font-size:14px;font-weight:bold;">{{ collab }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Début</td><td style="color:#fff;font-size:14px;">{{ date }}</td></tr>
                            </table>
                            <p style="color:#888;font-size:12px;margin:24px 0 0 0;">
                                Suivez l'avancement dans l'application Cabinet JMH.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="background:#0a0a1a;padding:20px 32px;text-align:center;">
                            <p style="color:#555;font-size:11px;margin:0;">Cabinet JMH — Gestion de tâches</p>
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """
    date_prise = tache.date_prise_en_charge.strftime('%d/%m/%Y %H:%M') if tache.date_prise_en_charge else 'Aujourd\'hui'

    html_content = render_template_string(
        template,
        prenom=creeur.prenom,
        nom=creeur.nom,
        collab=collab_nom,
        titre=tache.titre,
        date=date_prise,
    )

    return send_email_via_brevo_api(
        to_email=creeur.email,
        subject=subject,
        body=f"Bonjour {creeur.prenom}, {collab_nom} a pris en charge la tâche : {tache.titre}",
        html_content=html_content,
    )


def send_task_completed_email_brevo(tache, collab_nom) -> bool:
    from flask import render_template_string

    creeur = User.query.get(tache.cree_par)
    if not creeur or not creeur.email:
        return False

    subject = f"Tâche terminée : {tache.titre}"

    template = """
    <html>
    <body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,sans-serif;background:#1a1a2e;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:40px 20px;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#16213e;border-radius:12px;overflow:hidden;max-width:600px;">
                    <tr>
                        <td style="background:#FF8C00;padding:24px 32px;text-align:center;">
                            <h1 style="color:#fff;margin:0;font-size:22px;">🎉 Tâche terminée</h1>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:32px;">
                            <p style="color:#e0e0e0;font-size:16px;margin:0 0 24px 0;">
                                Bonjour <strong style="color:#FF8C00;">{{ prenom }}</strong> {{ nom }},
                            </p>
                            <p style="color:#c0c0c0;font-size:14px;margin:0 0 24px 0;">
                                <strong style="color:#059669;">{{ collab }}</strong> a terminé la tâche :
                            </p>
                            <table width="100%" cellpadding="12" cellspacing="0" style="background:#0f3460;border-radius:8px;margin-bottom:24px;">
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Tâche</td><td style="color:#fff;font-size:15px;font-weight:bold;">{{ titre }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Terminée par</td><td style="color:#059669;font-size:14px;font-weight:bold;">{{ collab }}</td></tr>
                                <tr><td style="color:#888;font-size:12px;text-transform:uppercase;">Date de fin</td><td style="color:#fff;font-size:14px;">{{ date }}</td></tr>
                            </table>
                            <p style="color:#888;font-size:12px;margin:24px 0 0 0;">
                                Consultez le résultat dans l'application Cabinet JMH.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="background:#0a0a1a;padding:20px 32px;text-align:center;">
                            <p style="color:#555;font-size:11px;margin:0;">Cabinet JMH — Gestion de tâches</p>
                        </td>
                    </tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """
    date_fin = tache.date_completion.strftime('%d/%m/%Y %H:%M') if tache.date_completion else 'Aujourd\'hui'

    html_content = render_template_string(
        template,
        prenom=creeur.prenom,
        nom=creeur.nom,
        collab=collab_nom,
        titre=tache.titre,
        date=date_fin,
    )

    return send_email_via_brevo_api(
        to_email=creeur.email,
        subject=subject,
        body=f"Bonjour {creeur.prenom}, {collab_nom} a terminé la tâche : {tache.titre}",
        html_content=html_content,
    )


def send_email_notification_fallback(to_email, subject, body):
    """Fallback to SMTP if Brevo is not configured."""
    try:
        from app.routes import get_mail_config
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        config = get_mail_config()
        username = config['MAIL_USERNAME']
        password = config['MAIL_PASSWORD']
        if not username or not password:
            return False
        msg = MIMEMultipart()
        msg['From'] = config.get('MAIL_DEFAULT_SENDER', username)
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server_host = config['MAIL_SERVER']
        server_port = int(config['MAIL_PORT'])
        server = smtplib.SMTP(server_host, server_port)
        server.ehlo()
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.error('SMTP fallback failed: %s', e)
        return False
