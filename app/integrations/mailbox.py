"""
IMAP-based dedicated mailbox client for the application.
Connects to a Gmail/IMAP mailbox, extracts client/task info from emails,
and creates tasks automatically.
"""

from __future__ import annotations

import email
import imaplib
import json
import logging
import os
import re
from email.header import decode_header
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _get_setting(cle: str) -> Optional[str]:
    from app.models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    return row.valeur if row else None


class MailboxClient:
    def __init__(
        self,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        mailbox: str = "[Gmail]/All Mail",
    ) -> None:
        self.user = user or _get_setting("MAILBOX_USER") or ""
        self.password = password or _get_setting("MAILBOX_PASSWORD") or ""
        self.host = host or _get_setting("MAILBOX_SERVER") or "imap.gmail.com"
        self.port = int(_get_setting("MAILBOX_PORT") or 993)
        self.mailbox = mailbox.upper()
        self.allowed_senders = self._load_allowed_senders()
        self._imap: Optional[imaplib.IMAP4_SSL] = None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _connect(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            try:
                self._imap = imaplib.IMAP4_SSL(self.host, self.port)
                self._imap.login(self.user, self.password)
                self._imap.select(self.mailbox)
                logger.info("IMAP connected to %s as %s", self.host, self.user)
            except imaplib.IMAP4.error as exc:
                logger.error("IMAP connection failed: %s", exc)
                raise
        return self._imap

    def logout(self) -> None:
        if self._imap is not None:
            try:
                self._imap.close()
                self._imap.logout()
            except Exception:
                pass
            finally:
                self._imap = None

    # ------------------------------------------------------------------
    # Sender restriction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load_allowed_senders() -> List[str]:
        raw = _get_setting("MAILBOX_ALLOWED_SENDERS") or ""
        senders = [s.strip().lower() for s in raw.replace("\n", ",").split(",") if s.strip()]
        return list(dict.fromkeys(senders))

    def _is_sender_allowed(self, sender: str) -> bool:
        if not self.allowed_senders:
            logger.info("No allowed senders configured, allowing all")
            return True
        normalized = sender.lower().strip()
        allowed = normalized in self.allowed_senders
        if not allowed:
            # Try partial match: allow if sender contains any allowed sender
            for allowed_sender in self.allowed_senders:
                if allowed_sender in normalized or normalized in allowed_sender:
                    allowed = True
                    break
        logger.info("Sender check: raw='%s' normalized='%s' allowed=%s allowed_list=%s", sender, normalized, allowed, self.allowed_senders)
        return allowed

    # ------------------------------------------------------------------
    # Email parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_mime_words(s: Optional[str]) -> str:
        if not s:
            return ""
        parts = []
        for txt, enc in decode_header(s or ""):
            if isinstance(txt, bytes):
                txt = txt.decode(enc or "utf-8", errors="replace")
            parts.append(txt)
        return "".join(parts)

    @staticmethod
    def _has_text_part(msg: email.message.EmailMessage) -> bool:
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return True
        return False

    @staticmethod
    def _extract_body(msg: email.message.EmailMessage) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return part.get_payload(decode=True).decode(charset, errors="replace")
                    except Exception:
                        continue
                elif ctype == "text/html" and not MailboxClient._has_text_part(msg):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html = part.get_payload(decode=True).decode(charset, errors="replace")
                        soup = BeautifulSoup(html, "html.parser")
                        return soup.get_text(separator=" ", strip=True)
                    except Exception:
                        continue
            return ""
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if not payload:
            return ""
        if ctype == "text/plain":
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except Exception:
                return ""
        elif ctype == "text/html":
            charset = msg.get_content_charset() or "utf-8"
            try:
                html = payload.decode(charset, errors="replace")
                soup = BeautifulSoup(html, "html.parser")
                return soup.get_text(separator=" ", strip=True)
            except Exception:
                return ""
        return ""

    @staticmethod
    def _extract_email_from(header: str) -> str:
        if not header:
            return ""
        m = re.search(r"[\w.+-]+@[\w.-]+\.[\w]{2,}", header)
        return m.group(0) if m else ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def fetch_unseen(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        try:
            imap = self._connect()
            typ, data = imap.search(None, "UNSEEN")
            if typ != "OK":
                return []
            ids = data[0].split()
            ids = list(reversed(ids))[-limit:]
            messages: List[Dict[str, Any]] = []
            for num in ids:
                typ, msg_data = imap.fetch(num, "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                raw = msg_data[0][1]
                mail = email.message_from_bytes(raw)
                subject = self._decode_mime_words(mail.get("Subject"))
                from_addr = self._extract_email_from(self._decode_mime_words(mail.get("From")))
                date_hdr = self._decode_mime_words(mail.get("Date"))
                body = self._extract_body(mail)
                if not self._is_sender_allowed(from_addr):
                    continue
                messages.append({
                    "uid": num.decode() if isinstance(num, bytes) else str(num),
                    "subject": subject,
                    "from": from_addr,
                    "date": date_hdr,
                    "body": body,
                    "raw": mail,
                })
            return messages
        except Exception as e:
            logger.exception("IMAP fetch failed: %s", e)
            return []

    def process_new_messages(self) -> int:
        mails = self.fetch_unseen(limit=50)
        logger.info("process_new_messages: fetched %d mails", len(mails))
        processed = 0
        for m in mails:
            try:
                logger.info("Processing mail uid=%s subject=%s", m.get("uid"), m.get("subject"))
                # Skip if already processed
                if self._is_already_processed(m.get("uid")):
                    logger.info("Mail uid=%s already processed, skipping", m.get("uid"))
                    continue

                # Use LLM as primary extraction method
                llm_result = self._analyze_with_llm(m["subject"], m["body"])
                client_id = None
                task_desc = None
                if llm_result:
                    client_id = llm_result.get("client_id")
                    task_desc = llm_result.get("task")

                # Fallback to regex if LLM fails
                if not client_id or not task_desc:
                    client_id = client_id or self._resolve_client(m["subject"], m["body"])
                    task_desc = task_desc or self._extract_task(m["subject"], m["body"])

                logger.info("Mail uid=%s extraction result: client_id=%s task_desc=%s", m.get("uid"), client_id, task_desc)

                # Create suggestion instead of task directly
                if task_desc:
                    self._create_suggestion(
                        subject=m["subject"],
                        body=m["body"],
                        dossier_id=client_id,
                        titre_suggere=m["subject"][:200],
                        description_suggeree=task_desc,
                        mail_uid=m.get("uid"),
                    )
                    logger.info("Created suggestion for mail uid=%s", m.get("uid"))
                else:
                    logger.info("No task extracted for mail uid=%s, marking as processed anyway", m.get("uid"))

                self._mark_as_processed(m["uid"])
                processed += 1
            except Exception as exc:
                logger.error("Error processing mail %s: %s", m.get("uid"), exc)
                self._move_to_error(m["uid"])
        logger.info("process_new_messages: processed %d mails", processed)
        return processed

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------
    def _analyze_with_llm(self, subject: str, body: str) -> Optional[Dict[str, Any]]:
        try:
            from app.integrations.openrouter import OpenRouterClient
            llm = OpenRouterClient()
            if not llm.is_configured():
                return None
            prompt = (
                "Analyse ce message et extrais uniquement les informations utiles pour créer une tâche.\n"
                "- Si le mail mentionne un dossier/client identifiable, renvoie 'client_id' comme un entier si possible, sinon null.\n"
                "- Si le mail contient une action à faire, renvoie 'task' comme une phrase courte.\n"
                "- Réponds strictement en JSON : { \"client_id\": number|null, \"task\": string|null }\n\n"
                f"Sujet: {subject}\n\nCorps:\n{body}"
            )
            messages = [
                {"role": "system", "content": "Tu es un assistant qui extrait des actions à partir d'emails."},
                {"role": "user", "content": prompt},
            ]
            raw = llm.chat(messages, model=llm.model)
            if not raw:
                return None
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
            data = json.loads(raw)
            if isinstance(data, dict):
                result = {}
                if "client_id" in data and data["client_id"] is not None:
                    try:
                        result["client_id"] = int(data["client_id"])
                    except (ValueError, TypeError):
                        result["client_id"] = None
                else:
                    result["client_id"] = None
                if "task" in data and isinstance(data["task"], str) and data["task"].strip():
                    result["task"] = data["task"].strip()[:200]
                else:
                    result["task"] = None
                return result if result else None
        except Exception as exc:
            logger.error("LLM mailbox analysis failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Client/task extraction
    # ------------------------------------------------------------------
    def _resolve_client(self, subject: str, body: str) -> Optional[int]:
        from app.models import Dossier
        text = f"{subject} {body}"
        m = re.search(r"(?:dossier|client|affaire)\s*[:\-]?\s*([\w\d\-]+)", text, re.I)
        if m:
            key = m.group(1).strip()
            dossier = Dossier.query.filter(
                (Dossier.numero.ilike(f"%{key}%")) |
                (Dossier.nom.ilike(f"%{key}%"))
            ).first()
            if dossier:
                return dossier.id
        return None

    def _extract_task(self, subject: str, body: str) -> Optional[str]:
        text = f"{subject} {body}"
        triggers = [
            r"à faire\s*[:\-]?\s*(.+)",
            r"action\s*[:\-]?\s*(.+)",
            r"tâche\s*[:\-]?\s*(.+)",
            r"faire\s*[:\-]?\s*(.+)",
            r"préparer\s*[:\-]?\s*(.+)",
            r"valider\s*[:\-]?\s*(.+)",
            r"envoyer\s*[:\-]?\s*(.+)",
            r"merci de\s*[:\-]?\s*(.+)",
        ]
        for pat in triggers:
            m = re.search(pat, text, re.I | re.S)
            if m:
                return m.group(1).strip().split("\n")[0][:200]
        return subject.strip()[:200] if subject else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _is_already_processed(self, uid: str) -> bool:
        from app.models import SuggestionTache
        return SuggestionTache.query.filter_by(mail_uid=uid).first() is not None

    def _create_suggestion(
        self,
        subject: str,
        body: str,
        titre_suggere: str,
        description_suggeree: str,
        dossier_id: Optional[int] = None,
        mail_uid: Optional[str] = None,
    ) -> None:
        from app import db
        from app.models import SuggestionTache

        suggestion = SuggestionTache(
            sujet=subject[:200] if subject else '',
            corps=body,
            dossier_id=dossier_id,
            titre_suggere=titre_suggere[:200],
            description_suggeree=description_suggeree,
            mail_uid=mail_uid,
            priorite_suggeree='moyenne',
        )
        db.session.add(suggestion)
        db.session.commit()
        logger.info("Suggestion created: %s", suggestion.titre_suggere)

    def _create_task(self, client_id: int, description: str, title: str) -> None:
        from app import db
        from app.models import Tache, Dossier
        dossier = Dossier.query.filter_by(id=client_id).first()
        if not dossier:
            dossier = Dossier(
                nom=f"Boîte de reception – client {client_id}",
                client_id=client_id,
                actif=True,
            )
            db.session.add(dossier)
            db.session.flush()
        tache = Tache(
            titre=title[:200],
            description=description,
            dossier_id=dossier.id,
            statut="à faire",
            priorite="moyenne",
        )
        db.session.add(tache)
        db.session.commit()
        logger.info("Task created: %s (dossier %s)", tache.titre, dossier.nom)

    # ------------------------------------------------------------------
    # IMAP state updates
    # ------------------------------------------------------------------
    def _mark_as_processed(self, uid: str) -> None:
        try:
            imap = self._connect()
            imap.store(uid, '+FLAGS', '\\Seen')
            if self._folder_exists("Traité"):
                imap.copy(uid, "Traité")
            imap.store(uid, '+FLAGS', '\\Deleted')
            imap.expunge()
        except Exception as e:
            logger.error("Failed to mark mail %s as processed: %s", uid, e)

    def _move_to_error(self, uid: str) -> None:
        try:
            imap = self._connect()
            if self._folder_exists("Erreur"):
                imap.copy(uid, "Erreur")
            imap.store(uid, '+FLAGS', '\\Deleted')
            imap.expunge()
        except Exception as e:
            logger.error("Failed to move mail %s to error: %s", uid, e)

    def _folder_exists(self, folder_name: str) -> bool:
        try:
            imap = self._connect()
            status, _ = imap.list('""', f'"{folder_name}"')
            return status == "OK" and bool(_)
        except Exception:
            return False


def send_task_assignment_email(tache, assignee_id: int) -> None:
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

    # Try SMTP first, fallback to Brevo API
    try:
        send_task_assignment_email_smtp(tache, assignee_id)
    except Exception as e:
        logger.error(f"SMTP failed, trying Brevo API: {e}")
        try:
            from app.integrations.brevo import send_task_assignment_email_brevo
            send_task_assignment_email_brevo(tache, assignee_id)
        except Exception as e2:
            logger.error(f"Brevo API also failed: {e2}")


def send_task_assignment_email_smtp(tache, assignee_id: int) -> None:
    from app.models import User, AppSetting

    user = User.query.get(assignee_id)
    if not user or not user.email:
        return

    def get_setting(key, default=''):
        setting = AppSetting.query.filter_by(cle=key).first()
        return (setting.valeur if setting and setting.valeur else default) or os.environ.get(key, default)

    smtp_server = get_setting('MAIL_SERVER', 'smtp.office365.com')
    smtp_port = int(get_setting('MAIL_PORT', 587))
    smtp_user = get_setting('MAIL_USERNAME', '')
    smtp_password = get_setting('MAIL_PASSWORD', '')

    if not smtp_user or not smtp_password:
        logger.warning("SMTP not fully configured, skipping assignment email")
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

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = user.email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, user.email, msg.as_string())
        server.quit()
        logger.info(f"Assignment email sent to {user.email}")
    except Exception as e:
        logger.error(f"Failed to send assignment email via SMTP: {e}")
        raise
