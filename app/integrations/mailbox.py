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
        mailbox: str = "INBOX",
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
            return True
        return sender.lower() in self.allowed_senders

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
                typ, msg_data = imap.fetch(num, "(RFC822)")
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
        processed = 0
        for m in mails:
            try:
                client_id = self._resolve_client(m["subject"], m["body"])
                task_desc = self._extract_task(m["subject"], m["body"])
                if not client_id or not task_desc:
                    llm_result = self._analyze_with_llm(m["subject"], m["body"])
                    if llm_result:
                        client_id = client_id or llm_result.get("client_id")
                        task_desc = task_desc or llm_result.get("task")
                if client_id and task_desc:
                    self._create_task(client_id, task_desc, m["subject"])
                self._mark_as_processed(m["uid"])
                processed += 1
            except Exception as exc:
                logger.error("Error processing mail %s: %s", m.get("uid"), exc)
                self._move_to_error(m["uid"])
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
                return {
                    "client_id": data.get("client_id"),
                    "task": data.get("task"),
                }
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
