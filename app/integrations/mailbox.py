"""
Gmail IMAP Mailbox Client — version intelligente.
Polls a dedicated Gmail inbox for incoming client emails,
extracts PDF attachments + uses LLM (OpenRouter) avec contexte riche (dossiers existants, profil manager),
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
from email.parser import BytesParser
from email.policy import default
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app import app, db
from app.models import SuggestionTache, AppSetting, Equipe

logger = logging.getLogger(__name__)

# Import the intelligent extractor
from app.integrations.email_extractor import (
    extract_pdf_text,
    extract_email_content,
    analyze_email_intelligent,
    create_suggestion_from_analysis,
    quick_extract_from_body,
)


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


class MailboxClient:
    """Gmail IMAP client for polling incoming emails — avec extraction PDF + LLM intelligent."""

    def __init__(self):
        self.user = _get_setting("MAILBOX_USER") or os.environ.get("MAILBOX_USER", "")
        self.password = _get_setting("MAILBOX_PASSWORD") or os.environ.get("MAILBOX_PASSWORD", "")
        self.server = _get_setting("MAILBOX_SERVER") or os.environ.get("MAILBOX_SERVER", "imap.gmail.com")
        self.port = int(_get_setting("MAILBOX_PORT") or os.environ.get("MAILBOX_PORT", "993"))
        self.use_ssl = (_get_setting("MAILBOX_USE_SSL") or os.environ.get("MAILBOX_USE_SSL", "true")).lower() == "true"
        self.mailbox = _get_setting("MAILBOX_FOLDER") or os.environ.get("MAILBOX_FOLDER", "[Gmail]/Tous les messages")
        self.allowed_senders = get_allowed_senders()

    def is_configured(self) -> bool:
        return bool(self.user and self.password)

    def _connect(self) -> imaplib.IMAP4:
        if self.use_ssl:
            conn = imaplib.IMAP4_SSL(self.server, self.port)
        else:
            conn = imaplib.IMAP4(self.server, self.port)
        try:
            conn.login(self.user, self.password)
        except imaplib.IMAP4.error as e:
            msg = str(e)
            if 'LOGIN' in msg or 'AUTHENTICATE' in msg or 'AUTH' in msg:
                raise RuntimeError("IMAP login refusé : vérifie l'adresse, le mot de passe d'application et la 2FA sur le compte Microsoft.") from e
            raise RuntimeError(f"IMAP login impossible : {msg}") from e
        return conn

    def fetch_unseen(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch unseen emails from the inbox."""
        return self._fetch_emails("UNSEEN", limit)

    def fetch_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch most recent emails regardless of seen status."""
        return self._fetch_emails("ALL", limit)

    def _fetch_emails(self, search_criteria: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Generic method to fetch emails by search criteria — avec extraction PDF."""
        results = []
        try:
            conn = self._connect()
            conn.select(self.mailbox)
            typ, data = conn.search(None, search_criteria)
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
                    
                    # Parse with policy for better handling
                    try:
                        mail = email.message_from_bytes(raw, policy=default)
                    except Exception:
                        mail = email.message_from_bytes(raw)

                    subject = _decode_mime_words(mail.get("Subject", ""))
                    from_addr = _extract_email_from(_decode_mime_words(mail.get("From", "")))
                    message_id = mail.get("Message-ID", mail.get("Message-Id", ""))

                    # Use new extractor for full content + PDFs
                    body_plain, body_html = "", ""
                    pdf_texts = []
                    try:
                        subject_full, body_plain, pdf_texts = extract_email_content(mail)
                        subject = subject_full or subject
                    except Exception as e:
                        logger.warning(f"PDF extraction failed for email {num}: {e}")
                        # Fallback to old method
                        body_plain = ""
                        if mail.is_multipart():
                            for part in mail.walk():
                                if part.get_content_type() == "text/plain":
                                    try:
                                        body_plain += part.get_payload(decode=True).decode("utf-8", errors="replace")
                                    except Exception:
                                        pass
                        else:
                            try:
                                body_plain = mail.get_payload(decode=True).decode("utf-8", errors="replace")
                            except Exception:
                                pass

                    results.append({
                        "uid": _build_uid(from_addr, subject, message_id),
                        "subject": subject,
                        "from": from_addr,
                        "body": body_plain[:8000],
                        "pdf_texts": pdf_texts,
                        "pdf_count": len(pdf_texts),
                        "raw_from": _decode_mime_words(mail.get("From", "")),
                    })
                except Exception as e:
                    logger.warning(f"Failed to fetch email {num}: {e}")

            conn.logout()
        except Exception as e:
            logger.error(f"IMAP connection error: {e}")
        return results

    def process_new_messages(self, max_emails: int = 5) -> int:
        """Poll unseen emails and create suggestions — avec LLM intelligent."""
        mails = self.fetch_unseen(limit=max_emails)
        count = 0
        for m in mails:
            try:
                uid = m["uid"]
                if SuggestionTache.query.filter_by(mail_uid=uid).first():
                    logger.info(f"Mailbox skip duplicate uid={uid}")
                    continue

                subject = m.get("subject", "")
                body = m.get("body", "")
                sender = m.get("from", "")
                pdf_texts = m.get("pdf_texts", [])
                pdf_count = m.get("pdf_count", 0)

                if not _is_sender_allowed(sender):
                    logger.info(f"Mailbox skip sender={sender} subject={subject[:60]}")
                    continue

                # Log what we found
                logger.info(f"Processing email: subject='{subject[:60]}' body_len={len(body)} pdfs={pdf_count}")

                # Use the intelligent extractor with PDFs
                analysis = analyze_email_intelligent(subject, body, pdf_texts, sender)

                if not analysis:
                    # Fallback to regex if LLM fails or returns nothing
                    task_desc = quick_extract_from_body(body, subject)
                    if not task_desc:
                        AppSetting.insert_setting(f"MAILBOX_SKIPPED_{uid}", "skipped", "system")
                        logger.info(f"Mailbox skip no_task uid={uid} subject={subject[:60]}")
                        continue
                    
                    # Create simple suggestion with regex fallback
                    suggestion = SuggestionTache(
                        sujet=subject[:200],
                        corps=body or "",
                        titre_suggere=subject[:200],
                        description_suggeree=task_desc,
                        mail_uid=uid,
                        priorite_suggeree="moyenne",
                        statut="en_attente",
                    )
                else:
                    # Create suggestion from intelligent analysis
                    suggestion = create_suggestion_from_analysis(
                        subject, body, pdf_texts, uid, sender
                    )
                    if not suggestion:
                        logger.warning(f"Failed to create suggestion from analysis for uid={uid}")
                        continue

                db.session.add(suggestion)
                db.session.commit()
                count += 1
                logger.info(f"Suggestion créée: '{analysis.get('titre', subject[:40])}' dossier={analysis.get('dossier_nom')} priorite={analysis.get('priorite')}")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Email processing error: {e}")
        return count
