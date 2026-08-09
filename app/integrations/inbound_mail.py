"""
Generic inbound-mail processor for Mailgun / SendGrid / Amazon SES webhooks.
It reuses the same extraction/persistence logic as the existing IMAP mailbox,
but the entrypoint is a POST webhook instead of IMAP fetch.

Activation:
- Set AppSetting MAILBOX_INBOUND_MODE = true
- Configure your provider to POST to /api/mailbox/inbound
- Optional secret/header check via MAILBOX_INBOUND_SECRET
"""

from __future__ import annotations

import email
import hashlib
import hmac
import json
import logging
import os
import re
from email.header import decode_header
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup
from flask import request, jsonify
from app import app, db
from app.models import SuggestionTache, AppSetting, Equipe

logger = logging.getLogger(__name__)


def _get_setting(cle: str) -> Optional[str]:
    row = AppSetting.query.filter_by(cle=cle).first()
    return row.valeur if row else None


def _decode_mime_words(s: Optional[str]) -> str:
    if not s:
        return ""
    parts = []
    for txt, enc in decode_header(s or ""):
        if isinstance(txt, bytes):
            txt = txt.decode(enc or "utf-8", errors="replace")
        parts.append(txt)
    return "".join(parts)


def _extract_email_from(header: str) -> str:
    if not header:
        return ""
    m = re.search(r"[\w.+-]+@[\w.-]+\.[\w]{2,}", header)
    return m.group(0) if m else ""


def _extract_body(msg: email.message.EmailMessage) -> str:
    if msg.is_multipart():
        has_text = False
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                has_text = True
                charset = part.get_content_charset() or "utf-8"
                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    return payload.decode(charset, errors="replace")
                except Exception:
                    continue
        if not has_text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        payload = part.get_payload(decode=True)
                        if payload is None:
                            continue
                        html = payload.decode(charset, errors="replace")
                        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
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
            return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            return ""
    return ""


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    """Normalize various inbound payload shapes to a common mail dict."""
    # Mailgun form-style payload
    if isinstance(payload, dict):
        sender = payload.get("from") or payload.get("sender") or ""
        recipient = payload.get("recipient") or payload.get("to") or ""
        subject = payload.get("subject") or ""
        date_hdr = payload.get("date") or ""
        body_plain = payload.get("body-plain") or payload.get("text") or ""
        body_html = payload.get("body-html") or payload.get("html") or ""
        if body_html and not body_plain:
            try:
                soup = BeautifulSoup(body_html, "html.parser")
                body_plain = soup.get_text(separator=" ", strip=True)
            except Exception:
                body_plain = ""
        return {
            "uid": _build_uid(payload),
            "subject": _decode_mime_words(subject),
            "from": _extract_email_from(_decode_mime_words(sender)),
            "raw_from": _decode_mime_words(sender),
            "date": _decode_mime_words(date_hdr),
            "body": body_plain,
            "raw": None,
            "recipient": _extract_email_from(_decode_mime_words(recipient)),
        }
    return {"uid": "", "subject": "", "from": "", "raw_from": "", "date": "", "body": "", "raw": None, "recipient": ""}


def _build_uid(payload: Dict[str, Any]) -> str:
    candidate = payload.get("Message-Id") or payload.get("Message-ID") or payload.get("timestamp") or ""
    if not candidate:
        sender = payload.get("from") or ""
        subject = payload.get("subject") or ""
        candidate = f"{sender}:{subject}"
    return hashlib.sha256(str(candidate).encode("utf-8", errors="replace")).hexdigest()[:64]


class InboundMailClient:
    def __init__(self) -> None:
        self.secret = _get_setting("MAILBOX_INBOUND_SECRET") or os.environ.get("MAILBOX_INBOUND_SECRET") or ""
        self.allowed_senders = self._load_allowed_senders()

    @staticmethod
    def _load_allowed_senders() -> list[str]:
        raw = _get_setting("MAILBOX_ALLOWED_SENDERS") or ""
        senders = [s.strip().lower() for s in raw.replace("\n", ",").split(",") if s.strip()]
        return list(dict.fromkeys(senders))

    def is_configured(self) -> bool:
        # Inbound mode is configured when explicit mode flag is set
        return bool(_get_setting("MAILBOX_INBOUND_MODE"))

    def _verify_signature(self, payload: bytes, signature: Optional[str]) -> bool:
        if not self.secret:
            return True
        if not signature:
            return False
        try:
            expected = hmac.new(self.secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature.strip().lower())
        except Exception:
            return False

    def _is_sender_allowed(self, sender: str) -> bool:
        if not self.allowed_senders:
            logger.info("No allowed senders configured, allowing all inbound senders")
            return True
        normalized = (sender or "").lower().strip()
        if not normalized:
            return False
        if normalized in self.allowed_senders:
            return True
        for allowed_sender in self.allowed_senders:
            if not allowed_sender:
                continue
            if allowed_sender in normalized or normalized in allowed_sender:
                return True
        return False

    def process_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        mail = _normalize_payload(payload)
        if not mail.get("from"):
            return {"ok": False, "message": "Expéditeur manquant", "stage": "validation"}

        if not self._is_sender_allowed(mail["from"]):
            return {"ok": False, "message": "Expéditeur non autorisé", "stage": "allowed_senders", "from": mail["from"], "allowed": self.allowed_senders}

        uid = mail.get("uid") or ""
        if not uid:
            uid = _build_uid(payload)

        if self._is_already_processed(uid):
            return {"ok": True, "message": "Déjà traité", "skipped": True, "uid": uid}

        subject = mail.get("subject") or ""
        body = mail.get("body") or ""
        recipient = mail.get("recipient") or ""
        equipe = self._resolve_equipe_from_recipient(recipient)
        client_id, task_desc = self._extract_task_and_client(subject, body)
        if not task_desc:
            return {"ok": True, "message": "Aucune tâche détectée", "skipped": True, "uid": uid, "subject": subject}

        try:
            self._create_suggestion(
                subject=subject,
                body=body,
                dossier_id=client_id,
                titre_suggere=subject[:200],
                description_suggeree=task_desc,
                mail_uid=uid,
                equipe=equipe,
            )
            return {"ok": True, "message": "Traitement inbound OK", "created": True, "uid": uid, "subject": subject, "equipe": equipe.nom if equipe else None}
        except Exception as exc:
            db.session.rollback()
            if "UniqueViolation" in str(exc) or "duplicate key" in str(exc):
                return {"ok": True, "message": "Doublon ignoré", "skipped": True, "uid": uid}
            logger.exception("Inbound processing failed: %s", exc)
            return {"ok": False, "message": str(exc), "stage": "processing"}

    # Extraction uses the same LLM-first + regex fallback logic as the IMAP path
    def _extract_task_and_client(self, subject: str, body: str):
        client_id = None
        task_desc = None
        try:
            from app.integrations.openrouter import OpenRouterClient
            llm = OpenRouterClient()
            if llm.is_configured():
                llm_result = self._analyze_with_llm(subject, body)
                if llm_result:
                    client_id = llm_result.get("client_id")
                    task_desc = llm_result.get("task")
        except Exception:
            pass
        if not client_id or not task_desc:
            client_id = client_id or self._resolve_client(subject, body)
            task_desc = task_desc or self._extract_task(subject, body)
        return client_id, task_desc

    def _analyze_with_llm(self, subject: str, body: str) -> Optional[Dict[str, Any]]:
        try:
            from app.integrations.openrouter import OpenRouterClient
            llm = OpenRouterClient()
            if not llm.is_configured():
                return None
            feedback = ""
            try:
                corrected = SuggestionTache.query.filter(SuggestionTache.statut.in_(['validee', 'rejetee'])).order_by(SuggestionTache.date_creation.desc()).limit(10).all()
                examples = []
                for s in corrected:
                    original = s.sujet or ""
                    final_desc = s.description_suggeree or ""
                    if original and final_desc and original != final_desc:
                        examples.append(f'  Email sujet: "{original[:60]}" → Tâche: "{final_desc[:60]}"')
                if examples:
                    feedback = "\n".join(examples[:5]) + "\n\n"
            except Exception:
                pass
            prompt = (
                "Tu es un assistant comptable pour le Cabinet JMH.\n"
                "Analyse l'email ci-dessous et extrais une tâche actionnable.\n\n"
                "RÈGLES:\n"
                "- 'task': une phrase courte décrivant l'action à faire (pas juste le sujet du mail).\n"
                "- 'client_id': null (sera assigné par le manager).\n"
                "- Si l'email est une notification (LinkedIn, Binance, etc.), réponds {\"task\": null, \"client_id\": null}.\n"
                "- Réponds STRICTEMENT en JSON: {\"client_id\": null, \"task\": \"...\"}\n\n"
            )
            if feedback:
                prompt += f"EXEMPLES DE TÂCHES CORRECTEMENT FORMULÉES (basés sur corrections du manager):\n{feedback}\n\n"
            prompt += f"Sujet: {subject}\n\nCorps de l'email:\n{body[:2000] if body else '(vide)'}\n\nRéponse JSON:"
            messages = [
                {"role": "system", "content": "Tu es un assistant comptable expert qui extrait des tâches actionnables à partir d'emails. Tu réponds uniquement en JSON."},
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
                if data.get("client_id") is not None:
                    try:
                        result["client_id"] = int(data["client_id"])
                    except (ValueError, TypeError):
                        result["client_id"] = None
                else:
                    result["client_id"] = None
                task = (data.get("task") or "").strip()
                result["task"] = task[:200] if task else None
                return result if result else None
        except Exception:
            pass
        return None

    def _resolve_equipe_from_recipient(self, recipient: str) -> Optional[Equipe]:
        if not recipient:
            return None
        try:
            return Equipe.query.filter(Equipe.equipe_email == recipient).first()
        except Exception:
            return None

    def _resolve_client(self, subject: str, body: str) -> Optional[int]:
        from app.models import Dossier
        text = f"{subject} {body}"
        m = re.search(r"(?:dossier|client|affaire)\s*[:\-]?\s*([\w\d\-]+)", text, re.I)
        if m:
            key = m.group(1).strip()
            dossier = Dossier.query.filter((Dossier.numero.ilike(f"%{key}%")) | (Dossier.nom.ilike(f"%{key}%"))).first()
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
        return None

    def _is_already_processed(self, uid: str) -> bool:
        if not uid:
            return False
        try:
            if SuggestionTache.query.filter_by(mail_uid=uid).first() is not None:
                return True
            skipped = AppSetting.query.filter_by(cle=f"MAILBOX_SKIPPED_{uid}").first()
            if skipped:
                return True
        except Exception:
            pass
        return False

    def _create_suggestion(
        self,
        subject: str,
        body: str,
        titre_suggere: str,
        description_suggeree: str,
        dossier_id: Optional[int] = None,
        mail_uid: Optional[str] = None,
        equipe: Optional[Equipe] = None,
    ) -> None:
        suggestion = SuggestionTache(
            sujet=(subject or "")[:200],
            corps=body or "",
            dossier_id=dossier_id,
            titre_suggere=(titre_suggere or "")[:200],
            description_suggeree=description_suggeree or "",
            mail_uid=mail_uid,
            cree_par=None,
            priorite_suggeree="moyenne",
            statut="en_attente",
        )
        db.session.add(suggestion)
        db.session.commit()


def _get_inbound_client() -> InboundMailClient:
    return InboundMailClient()
