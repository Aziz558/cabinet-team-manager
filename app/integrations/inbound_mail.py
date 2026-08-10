"""
Cloudflare Email Routing inbound webhook processor.
Reçoit les emails depuis un Worker Cloudflare vers /api/mailbox/inbound,
extrait une tâche via LLM (OpenRouter) ou regex fallback,
et crée une SuggestionTache.

Activation:
- Active le mode inbound dans Paramètres > Réception par webhook inbound
- Configure Cloudflare Email Routing → Worker → POST /api/mailbox/inbound
- Optionnel : secret via MAILBOX_INBOUND_SECRET
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any, Dict, Optional

from app import app, db
from app.models import SuggestionTache, AppSetting, Equipe

logger = logging.getLogger(__name__)


def _get_setting(cle: str) -> Optional[str]:
    row = AppSetting.query.filter_by(cle=cle).first()
    if row and row.valeur:
        return row.valeur
    return os.environ.get(cle)


def get_webhook_secret() -> str:
    """Get webhook verification secret."""
    return _get_setting("MAILBOX_INBOUND_SECRET") or os.environ.get("MAILBOX_INBOUND_SECRET", "")


def is_inbound_enabled() -> bool:
    """Check if inbound webhook mode is enabled."""
    val = _get_setting("MAILBOX_INBOUND_MODE")
    if val:
        return val.strip().lower() == "true"
    return False


def get_allowed_senders() -> list:
    """Load allowed senders from settings or env."""
    raw = _get_setting("MAILBOX_ALLOWED_SENDERS") or ""
    senders = [s.strip().lower() for s in raw.replace("\n", ",").split(",") if s.strip()]
    return list(dict.fromkeys(senders))


def _verify_signature(payload: bytes, signature: Optional[str]) -> bool:
    """Verify HMAC-SHA256 signature."""
    secret = get_webhook_secret()
    if not secret:
        return True  # No secret configured = no verification
    if not signature:
        return False
    try:
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())
    except Exception:
        return False


def _is_sender_allowed(sender: str) -> bool:
    """Check if sender is allowed."""
    allowed_senders = get_allowed_senders()
    if not allowed_senders:
        logger.info("No allowed senders configured, accepting all")
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


def _resolve_equipe_from_recipient(recipient: str) -> Optional[Equipe]:
    """Resolve team from the recipient email address."""
    if not recipient:
        return None
    try:
        return Equipe.query.filter(Equipe.equipe_email == recipient).first()
    except Exception:
        return None


def _resolve_equipe_from_sender(sender: str) -> Optional[Equipe]:
    """Resolve team from the sender email address."""
    if not sender:
        return None
    try:
        return Equipe.query.filter(Equipe.manager.has(User.email == sender)).first()
    except Exception:
        return None


def _resolve_team_for_email(sender: str, recipient: str) -> Optional[Equipe]:
    """Resolve team using recipient first, then sender."""
    equipe = _resolve_equipe_from_recipient(recipient)
    if equipe:
        return equipe
    return _resolve_equipe_from_sender(sender)


def _resolve_client(subject: str, body: str) -> Optional[int]:
    """Try to find a Dossier from subject/body regex."""
    from app.models import Dossier
    text = f"{subject} {body}"
    m = re.search(r'(?:dossier|client|affaire)\s*[:\\-]?\s*([\w\d\-]+)', text, re.I)
    if m:
        key = m.group(1).strip()
        try:
            dossier = Dossier.query.filter(
                (Dossier.numero.ilike(f"%{key}%")) | (Dossier.intitule.ilike(f"%{key}%"))
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
        r"(?:à faire|action|tâche|faire|préparer|valider|envoyer|merci de)\s*[:\\-]?\s*(.+)",
    ]
    for pat in triggers:
        m = re.search(pat, text, re.I | re.S)
        if m:
            return m.group(1).strip().split("\n")[0][:200]
    return None


def _extract_task_and_client(subject: str, body: str, sender: str, team_name: str = ""):
    """Extract task and client_id via LLM first, regex fallback."""
    client_id = None
    task_desc = None

    # Try LLM via OpenRouter
    try:
        from app.integrations.openrouter import OpenRouterClient
        llm = OpenRouterClient()
        if llm.is_configured():
            task_desc = _analyze_with_llm(llm, subject, body, team_name=team_name)
            if not task_desc:
                # Fallback to regex
                task_desc = _extract_task_regex(subject, body)
        else:
            task_desc = _extract_task_regex(subject, body)
    except Exception as e:
        logger.warning(f"LLM analysis failed, falling back to regex: {e}")
        task_desc = _extract_task_regex(subject, body)

    # Resolve client
    client_id = _resolve_client(subject, body)

    return client_id, task_desc


def _analyze_with_llm(llm, subject: str, body: str, team_name: str = "") -> Optional[str]:
    """Use LLM to extract a task from email."""
    try:
        feedback = ""
        try:
            corrected = SuggestionTache.query.filter(
                SuggestionTache.statut.in_(['validee', 'rejetee'])
            ).order_by(SuggestionTache.date_creation.desc()).limit(10).all()
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

        team_context = f"Équipe concernée: {team_name}\n" if team_name else ""
        prompt = (
            "Tu es un assistant comptable pour le Cabinet JMH.\n"
            "Analyse l'email ci-dessous et extrais une tâche actionnable.\n\n"
            "CONTEXTE:\n"
            "- C'est un cabinet comptable.\n"
            "- Les emails clients concernent souvent: déclarations fiscales, bilan, TVA, paie, dossiers clients.\n"
            "- Si c'est une demande client, extrais l'action concrète à faire.\n\n"
            f"{team_context}"
            "RÈGLES:\n"
            "- 'task': une phrase courte décrivant l'action à faire (pas juste le sujet du mail).\n"
            "- Si l'email est une notification automatique (LinkedIn, Binance, etc.), réponds {\"task\": null}.\n"
            "- Réponds STRICTEMENT en JSON: {\"task\": \"...\"}\n\n"
        )
        if feedback:
            prompt += f"EXEMPLES DE TÂCHES CORRECTEMENT FORMULÉES:\n{feedback}\n"

        prompt += f"Sujet: {subject}\n\nCorps de l'email:\n{body[:2000] if body else '(vide)'}\n\nRéponse JSON:"
        messages = [
            {"role": "system", "content": "Tu es un assistant comptable expert qui extrait des tâches actionnables à partir d'emails. Tu réponds uniquement en JSON."},
            {"role": "user", "content": prompt},
        ]
        default_model = os.environ.get("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct-free")
        raw = llm.chat(messages, model=llm.model or default_model)
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        data = json.loads(raw)
        if isinstance(data, dict):
            task = (data.get("task") or "").strip()[:200]
            return task if task else None
    except json.JSONDecodeError:
        logger.warning("LLM response was not valid JSON")
    except Exception as e:
        logger.warning(f"LLM analysis error: {e}")
    return None


def process_webhook(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process an inbound webhook payload and create a SuggestionTache.
    Returns a dict with ok/message/status.
    """
    try:
        # Extract fields from payload
        sender = data.get("from", data.get("sender", ""))
        sender_email = _extract_email_from(sender)
        subject = data.get("subject", "")
        body = data.get("body", data.get("body_plain", data.get("text", "")))
        recipient = data.get("to", data.get("recipient", ""))
        message_id = data.get("message_id", data.get("Message-Id", ""))

        # Validate sender
        if not sender_email:
            return {"ok": False, "message": "Expéditeur manquant", "stage": "validation"}

        # Check allowed senders
        if not _is_sender_allowed(sender_email):
            return {
                "ok": False,
                "message": "Expéditeur non autorisé",
                "stage": "allowed_senders",
                "from": sender_email,
                "allowed": get_allowed_senders(),
            }

        # Build UID for dedup
        uid = _build_uid(sender_email, subject, message_id)

        # Check if already processed
        existing = SuggestionTache.query.filter_by(mail_uid=uid).first()
        if existing:
            return {"ok": True, "message": "Déjà traité", "skipped": True, "uid": uid}

        # Resolve team from recipient, fallback to sender
        equipe = _resolve_team_for_email(sender_email, recipient)
        team_name = equipe.nom if equipe else ""
        app.logger.info(f"Mailbox email from={sender_email} recipient={recipient} equipe={team_name or 'none'}")

        # Extract task and client
        client_id, task_desc = _extract_task_and_client(subject, body, sender_email, team_name=team_name)

        if not task_desc:
            # Record as skipped
            AppSetting.insert_setting("MAILBOX_SKIPPED_" + uid, "skipped", "system")
            return {
                "ok": True,
                "message": "Aucune tâche détectée",
                "skipped": True,
                "uid": uid,
                "subject": subject,
            }

        if not equipe:
            return {
                "ok": False,
                "message": "Équipe non identifiée. Vérifie l'adresse email d'équipe ou l'expéditeur autorisé.",
                "stage": "team_resolution",
                "from": sender_email,
                "recipient": recipient,
            }

        # Determine assigned team user id
        team_member_id = None
        if equipe.manager_id:
            team_member_id = equipe.manager_id

        # Create suggestion
        suggestion = SuggestionTache(
            sujet=(subject or "")[:200],
            corps=body or "",
            dossier_id=client_id,
            titre_suggere=(subject or "")[:200],
            description_suggeree=task_desc,
            mail_uid=uid,
            cree_par=team_member_id,
            priorite_suggeree="moyenne",
            statut="en_attente",
        )
        db.session.add(suggestion)
        db.session.commit()

        return {
            "ok": True,
            "message": "Suggestion créée",
            "created": True,
            "uid": uid,
            "subject": subject,
            "equipe": equipe.nom if equipe else None,
            "task": task_desc[:100],
        }

    except Exception as exc:
        db.session.rollback()
        if "UniqueViolation" in str(exc) or "duplicate key" in str(exc):
            return {"ok": True, "message": "Doublon ignoré", "skipped": True}
        logger.exception("Inbound processing failed: %s", exc)
        return {"ok": False, "message": str(exc), "stage": "processing"}


class InboundMailClient:
    """Client for inbound webhook — wraps process_webhook for compatibility."""

    def __init__(self):
        self.secret = get_webhook_secret()

    def is_configured(self) -> bool:
        return is_inbound_enabled()

    def _verify_signature(self, payload: bytes, signature: Optional[str]) -> bool:
        return _verify_signature(payload, signature)

    def process_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return process_webhook(payload)

    def process_new_messages(self, max_emails: int = 10) -> int:
        """Compatibility stub — inbound mode doesn't poll."""
        return 0
