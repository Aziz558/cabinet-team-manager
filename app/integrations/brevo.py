import requests
import logging
from app.models import AppSetting

logger = logging.getLogger(__name__)

APP_URL = 'https://cabinet-team-manager.onrender.com'


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
            'email': 'cabinet.manager.jmh@gmail.com',
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


def _email_layout(header_title, header_emoji, intro_html, rows, cta_url=None, cta_text=None, footer_note=''):
    """Layout email unifié au thème Cabinet JMH (noir mat + orange)."""
    rows_html = ''
    for label, value in rows:
        rows_html += (
            f'<tr>'
            f'<td style="color:#777;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'padding:8px 0;vertical-align:top;white-space:nowrap;">{label}</td>'
            f'<td style="color:#e8e8e8;font-size:14px;padding:8px 0 8px 16px;vertical-align:top;">{value}</td>'
            f'</tr>'
        )

    cta_html = ''
    if cta_url and cta_text:
        cta_html = f'''
            <tr><td align="center" style="padding:24px 0 8px 0;">
                <a href="{cta_url}" style="display:inline-block;background:#FF8C00;color:#000;font-weight:bold;'
                f'text-decoration:none;padding:14px 32px;border-radius:10px;font-size:14px;">{cta_text}</a>
            </td></tr>
            <tr><td align="center" style="padding:0 0 8px 0;">
                <p style="color:#666;font-size:11px;margin:0;">Si le bouton ne fonctionne pas : <a href="{cta_url}" style="color:#FF8C00;">{cta_url}</a></p>
            </td></tr>'''

    footer_note_html = f'<p style="color:#777;font-size:12px;margin:24px 0 0 0;">{footer_note}</p>' if footer_note else ''

    return f'''
<html>
<body style="margin:0;padding:0;font-family:Inter,'Segoe UI',Tahoma,sans-serif;background:#0a0a0a;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:40px 16px;">
        <tr><td align="center">
            <table width="600" cellpadding="0" cellspacing="0" style="background:#131313;border:1px solid #262626;border-radius:16px;overflow:hidden;max-width:600px;">
                <tr>
                    <td style="background:#000;padding:10px 32px;text-align:center;border-bottom:3px solid #FF8C00;">
                        <p style="color:#FF8C00;margin:0;font-size:15px;font-weight:bold;letter-spacing:1px;">CABINET JMH</p>
                        <p style="color:#555;margin:2px 0 0 0;font-size:10px;letter-spacing:2px;text-transform:uppercase;">Gestion d'équipe & comptabilité</p>
                    </td>
                </tr>
                <tr>
                    <td style="padding:28px 32px 8px 32px;text-align:center;">
                        <h1 style="color:#fff;margin:0;font-size:20px;">{header_emoji} {header_title}</h1>
                    </td>
                </tr>
                <tr>
                    <td style="padding:16px 32px 8px 32px;">
                        {intro_html}
                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:16px 20px;margin-top:16px;">
                            {rows_html}
                        </table>
                        {cta_html}
                        {footer_note_html}
                    </td>
                </tr>
                <tr>
                    <td style="background:#000;padding:20px 32px;text-align:center;border-top:1px solid #1f1f1f;">
                        <p style="color:#555;font-size:11px;margin:0;">Cabinet JMH — Cabinet d'expertise comptable</p>
                        <p style="color:#3a3a3a;font-size:10px;margin:4px 0 0 0;">Cet email a été envoyé automatiquement par l'application de gestion.</p>
                    </td>
                </tr>
            </table>
        </td></tr>
    </table>
</body>
</html>'''


def send_task_assigned_email_brevo(tache, assignee_id: int) -> bool:
    from app.models import User
    from flask import render_template_string

    user = User.query.get(assignee_id)
    if not user or not user.email:
        return False

    subject = f"Nouvelle tâche assignée : {tache.titre}"

    template = _email_layout(
        header_title="Nouvelle tâche assignée",
        header_emoji="📋",
        intro_html=(
            f'<p style="color:#e0e0e0;font-size:15px;margin:0 0 4px 0;">Bonjour <strong style="color:#FF8C00;">{user.prenom} {user.nom}</strong>,</p>'
            f'<p style="color:#9a9a9a;font-size:13px;margin:0;">Une nouvelle tâche vous a été assignée :</p>'
        ),
        rows=[
            ('Tâche', tache.titre),
            ('Description', tache.description or '(aucune)'),
            ('Priorité', f'<span style="color:#FF8C00;font-weight:bold;">{tache.priorite.capitalize()}</span>'),
            ('Échéance', tache.date_echeance.strftime('%d/%m/%Y') if tache.date_echeance else '—'),
        ],
        cta_url=f'{APP_URL}/taches',
        cta_text='Voir mes tâches',
        footer_note="Ouvrez l'application pour prendre en charge cette tâche dès que possible.",
    )

    return send_email_via_brevo_api(
        to_email=user.email,
        subject=subject,
        body=f"Bonjour {user.prenom} {user.nom}, nouvelle tâche : {tache.titre}. Consultez vos tâches sur {APP_URL}/taches",
        html_content=template,
    )


def send_task_taken_email_brevo(tache, collab_nom) -> bool:
    from app.models import User
    from flask import render_template_string

    creeur = User.query.get(tache.cree_par)
    if not creeur or not creeur.email:
        return False

    subject = f"Prise en charge : {tache.titre}"
    date_prise = tache.date_prise_en_charge.strftime('%d/%m/%Y %H:%M') if tache.date_prise_en_charge else "Aujourd'hui"

    template = _email_layout(
        header_title="Tâche prise en charge",
        header_emoji="✅",
        intro_html=(
            f'<p style="color:#e0e0e0;font-size:15px;margin:0 0 4px 0;">Bonjour <strong style="color:#FF8C00;">{creeur.prenom} {creeur.nom}</strong>,</p>'
            f'<p style="color:#9a9a9a;font-size:13px;margin:0;"><strong style="color:#FF8C00;">{collab_nom}</strong> a pris en charge la tâche :</p>'
        ),
        rows=[
            ('Tâche', tache.titre),
            ('Collaborateur', f'<span style="color:#FF8C00;font-weight:bold;">{collab_nom}</span>'),
            ('Début', date_prise),
        ],
        cta_url=f'{APP_URL}/taches',
        cta_text='Voir les tâches',
        footer_note="Suivez l'avancement de cette tâche dans l'application.",
    )

    return send_email_via_brevo_api(
        to_email=creeur.email,
        subject=subject,
        body=f"Bonjour {creeur.prenom}, {collab_nom} a pris en charge la tâche : {tache.titre}. Consultez sur {APP_URL}/taches",
        html_content=template,
    )


def send_task_completed_email_brevo(tache, collab_nom) -> bool:
    from app.models import User
    from flask import render_template_string

    creeur = User.query.get(tache.cree_par)
    if not creeur or not creeur.email:
        return False

    subject = f"Tâche terminée : {tache.titre}"
    date_fin = tache.date_completion.strftime('%d/%m/%Y %H:%M') if tache.date_completion else "Aujourd'hui"

    template = _email_layout(
        header_title="Tâche terminée",
        header_emoji="🎉",
        intro_html=(
            f'<p style="color:#e0e0e0;font-size:15px;margin:0 0 4px 0;">Bonjour <strong style="color:#FF8C00;">{creeur.prenom} {creeur.nom}</strong>,</p>'
            f'<p style="color:#9a9a9a;font-size:13px;margin:0;"><strong style="color:#FF8C00;">{collab_nom}</strong> a terminé la tâche :</p>'
        ),
        rows=[
            ('Tâche', tache.titre),
            ('Terminée par', f'<span style="color:#FF8C00;font-weight:bold;">{collab_nom}</span>'),
            ('Date de fin', date_fin),
        ],
        cta_url=f'{APP_URL}/taches',
        cta_text='Voir les tâches',
        footer_note="Consultez le suivi de vos dossiers dans l'application.",
    )

    return send_email_via_brevo_api(
        to_email=creeur.email,
        subject=subject,
        body=f"Bonjour {creeur.prenom}, {collab_nom} a terminé la tâche : {tache.titre}. Consultez sur {APP_URL}/taches",
        html_content=template,
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
