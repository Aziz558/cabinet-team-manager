"""
Gmail IMAP Mailbox Client.
Polls a dedicated Gmail inbox for incoming client emails,
extracts tasks via LLM (OpenRouter) or regex fallback,
and creates SuggestionTache records.

Setup:
1. Create a dedicated Gmail (e.g., cabinet.jmh.taches@gmail.com)
2. Enable IMAP in Gmail Settings → See all settings → Forwarding and POP/IMAP
3. Create an App Password: Google Account → Security → 2-Step Verification → App passwords
4. Configure the settings in the app (Paramètres → section mailbox)
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import os
import re
import time
from email.header import decode_header
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app import app, db
from app.models import SuggestionTache, AppSetting, Equipe

logger = logging.getLogger(__name__)


def _get_setting(cle: str) -> Optional[str]:
    row = AppSetting.query.filter_by(cle=cle).first()
    if row and row.valeur:
        return row.valeur
    return os.environ.get(cle)


def get_allowed_senders() -> list:
    """Load allowed senders from settings or env."""
    raw = _get_setting("MAILBOX_ALLOWED_SENDERS") or ""
    senders = [s.strip().lower() for s in raw.replace("\n", ",").split(",") if s.strip()]
    return list(dict.fromkeys(senders))


def _decode_mime_words(value: str) -> str:
    """Decode MIME encoded words like =?UTF-8?Q?....?="""
    if not value:
        return ""
    try:
        decoded_parts = decode_header(value)
        return " ".join(
            part.decode(charset or "utf-8", errors="replace") if isinstance(part, bytes) else part
            for part, charset in decoded_parts
        )
    except Exception:
        return value


def _extract_email_from(header: str) -> str:
    """Extract email address from a From/Sender header."""
    if not header:
        return ""
    m = re.search(r'[\w.+-]+@[\w.-]+\.[\w]{2,}', header)
    return m.group(0) if m else ""


def _build_uid(sender: str, subject: str, message_id: str) -> str:
    """Build a unique ID for deduplication."""
    candidate = message_id or f"{sender}:{subject}"
    return hashlib.sha256(str(candidate).encode("utf-8", errors="replace")).hexdigest()[:64]


def _is_sender_allowed(sender: str) -> bool:
    """Check if sender is allowed."""
    allowed_senders = get_allowed_senders()
    if not allowed_senders:
        return True
    normalized = (sender or "").lower().strip()
    if not normalized:
        return False
    if normalized in allowed_senders:
        return True
    for allowed in allowed_senders:
        if not allowed:
            continue
        if allowed in normalized or normalized in allowed:
            return True
    return False


def _resolve_client(subject: str, body: str) -> Optional[int]:
    """Try to find a Dossier from subject/body regex."""
    from app.models import Dossier
    text = f"{subject} {body}"
    m = re.search(r'(?:dossier|client|affaire)\s*[\-:\s]*([\w\d\-]+)', text, re.I)
    if m:
        key = m.group(1).strip()
        try:
            dossier = Dossier.query.filter(
                (Dossier.numero_dossier.ilike(f"%{key}%")) | (Dossier.intitule.ilike(f"%{key}%"))
            ).first()
            if dossier:
                return dossier.id
        except Exception:
            pass
    return None


def _extract_task_regex(subject: str, body: str) -> Optional[str]:
    """Regex fallback for task extraction."""
    text = f"{subject} {body}"
    triggers = [
        r"(?:à faire|action|tâche|faire|préparer|valider|envoyer|merci de)\s*[\-:\s]*(.+)",
    ]
    for pat in triggers:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1).strip().split("\n")[0][:200]
    return None


def _analyze_with_llm(llm, subject: str, body: str) -> Optional[str]:
    """Use LLM to extract a task from email content."""
    import json
    try:
        prompt = (
            "Tu es un assistant comptable pour le Cabinet JMH.\n"
            "Analyse l'email ci-dessous et extrais une tâche actionnable.\n\n"
            "RÈGLES:\n"
            "- 'task': une phrase courte décrivant l'action à faire.\n"
            "- Si l'email est une notification automatique, réponds {\"task\": null}.\n"
            "- Réponds STRICTEMENT en JSON: {\"task\": \"...\"}\n\n"
            f"Sujet: {subject}\n\n"
            f"Corps:\n{body[:2000] if body else '(vide)'}\n\nRéponse JSON:"
        )
        messages = [
            {"role": "system", "content": "Tu es un assistant comptable expert. Réponds uniquement en JSON."},
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
            task = (data.get("task") or "").strip()[:200]
            return task if task else None
    except Exception:
        pass
    return None


def _extract_task_and_client(subject: str, body: str, sender: str):
    """Extract task and client_id via LLM first, regex fallback."""
    client_id = None
    task_desc = None

    try:
        from app.integrations.openrouter import OpenRouterClient
        llm = OpenRouterClient()
        if llm.is_configured():
            task_desc = _analyze_with_llm(llm, subject, body)
            if not task_desc:
                task_desc = _extract_task_regex(subject, body)
        else:
            task_desc = _extract_task_regex(subject, body)
    except Exception as e:
        logger.warning(f"LLM analysis failed, falling back to regex: {e}")
        task_desc = _extract_task_regex(subject, body)

    client_id = _resolve_client(subject, body)
    return client_id, task_desc


class MailboxClient:
    """Gmail IMAP client for polling incoming emails."""

    def __init__(self):
        self.user = _get_setting("MAILBOX_USER") or os.environ.get("MAILBOX_USER", "")
        self.password = _get_setting("MAILBOX_PASSWORD") or os.environ.get("MAILBOX_PASSWORD", "")
        self.server = _get_setting("MAILBOX_SERVER") or os.environ.get("MAILBOX_SERVER", "outlook.office365.com")
        self.port = int(_get_setting("MAILBOX_PORT") or os.environ.get("MAILBOX_PORT", "993"))
        self.use_ssl = (_get_setting("MAILBOX_USE_SSL") or os.environ.get("MAILBOX_USE_SSL", "true")).lower() == "true"
        self.mailbox = _get_setting("MAILBOX_FOLDER") or os.environ.get("MAILBOX_FOLDER", "INBOX")
        self.allowed_senders = get_allowed_senders()

    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def _connect(self) -> imaplib.IMAP4:
        if self.use_ssl:
            conn = imaplib.IMAP4_SSL(self.server, self.port)
        else:
            conn = imaplib.IMAP4(self.server, self.port)
        conn.login(self.user, self.password)
        return conn

    def fetch_unseen(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch unseen emails from the inbox."""
        results = []
        try:
            conn = self._connect()
            conn.select(self.mailbox)
            typ, data = conn.search(None, "UNSEEN")
            if typ != "OK":
                conn.logout()
                return results

            ids = data[0].split() if data[0] else []
            for num in ids[-limit:]:
                try:
                    typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
                    if typ != "OK":
                        continue
                    raw = msg_data[0][1]
                    mail = email.message_from_bytes(raw)

                    subject = _decode_mime_words(mail.get("Subject", ""))
                    from_addr = _extract_email_from(_decode_mime_words(mail.get("From", "")))
                    message_id = mail.get("Message-ID", mail.get("Message-Id", ""))

                    body = ""
                    if mail.is_multipart():
                        for part in mail.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body += part.get_payload(decode=True).decode("utf-8", errors="replace")
                                except Exception:
                                    pass
                    else:
                        try:
                            body = mail.get_payload(decode=True).decode("utf-8", errors="replace")
                        except Exception:
                            pass

                    results.append({
                        "uid": _build_uid(from_addr, subject, message_id),
                        "subject": subject,
                        "from": from_addr,
                        "body": body[:5000],
                        "raw_from": _decode_mime_words(mail.get("From", "")),
                    })
                except Exception as e:
                    logger.warning(f"Failed to fetch email {num}: {e}")

            conn.logout()
        except Exception as e:
            logger.error(f"IMAP connection error: {e}")
        return results

    def process_new_messages(self, max_emails: int = 5) -> int:
        """Poll unseen emails and create suggestions."""
        mails = self.fetch_unseen(limit=max_emails)
        count = 0
        for m in mails:
            try:
                uid = m["uid"]
                if SuggestionTache.query.filter_by(mail_uid=uid).first():
                    continue

                subject = m.get("subject", "")
                body = m.get("body", "")
                sender = m.get("from", "")

                if not _is_sender_allowed(sender):
                    continue

                client_id, task_desc = _extract_task_and_client(subject, body, sender)

                if not task_desc:
                    AppSetting.insert_setting(f"MAILBOX_SKIPPED_{uid}", "skipped", "system")
                    continue

                suggestion = SuggestionTache(
                    sujet=subject[:200],
                    corps=body or "",
                    dossier_id=client_id,
                    titre_suggere=subject[:200],
                    description_suggeree=task_desc,
                    mail_uid=uid,
                    priorite_suggeree="moyenne",
                    statut="en_attente",
                )
                db.session.add(suggestion)
                db.session.commit()
                count += 1
                logger.info(f"Suggestion créée depuis email: {subject[:60]}")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Email processing error: {e}")
        return count
