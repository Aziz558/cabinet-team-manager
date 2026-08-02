"""
Real Outlook / Microsoft Graph mail connector.

Uses MSAL confidential client to acquire an app-only access token and then
talks to Microsoft Graph. No secrets are hard-coded; everything comes from
environment variables or constructor parameters.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class OutlookMailClient:
    """Microsoft Graph mail integration for Outlook.

    Reads config from env by default:
      - OUTLOOK_CLIENT_ID
      - OUTLOOK_TENANT_ID
      - OUTLOOK_CLIENT_SECRET
      - OUTLOOK_MAILBOX_EMAIL
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        mailbox_email: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or _env_str("OUTLOOK_CLIENT_ID")
        self.tenant_id = tenant_id or _env_str("OUTLOOK_TENANT_ID")
        self.client_secret = client_secret or _env_str("OUTLOOK_CLIENT_SECRET")
        self.mailbox_email = mailbox_email or _env_str("OUTLOOK_MAILBOX_EMAIL")

        self._access_token: Optional[str] = None
        self._msal_app: Optional[msal.ConfidentialClientApplication] = None

    # ----------------------------------------------------------------
    # Config helpers
    # ----------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.client_id and self.tenant_id and self.client_secret)

    # ----------------------------------------------------------------
    # Auth / token
    # ----------------------------------------------------------------

    def _build_msal_app(self) -> msal.ConfidentialClientApplication:
        if self._msal_app is None:
            authority = f"https://login.microsoftonline.com/{self.tenant_id}"
            self._msal_app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=authority,
                client_credential=self.client_secret,
            )
        return self._msal_app

    def _get_access_token(self) -> Optional[str]:
        if self._access_token:
            return self._access_token

        if not self.is_configured():
            logger.warning("Outlook client is not configured.")
            return None

        app = self._build_msal_app()
        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            self._access_token = result["access_token"]
            logger.info("Outlook access token acquired successfully.")
            return self._access_token

        error = result.get("error")
        desc = result.get("error_description")
        logger.error("Failed to acquire Outlook token: %s - %s", error, desc)
        return None

    def _headers(self) -> Dict[str, str]:
        token = self._get_access_token()
        if not token:
            return {}
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ----------------------------------------------------------------
    # Internal HTTP helper
    # ----------------------------------------------------------------

    def _graph_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        headers = self._headers()
        if not headers:
            return None
        url = f"{GRAPH_BASE_URL}{path}"
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("Graph GET %s failed: %s", url, exc)
            return None

    # ----------------------------------------------------------------
    # Mail reading
    # ----------------------------------------------------------------

    def fetch_recent_mails(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent inbox messages from Microsoft Graph.

        Each dict contains at least:
          id, subject, bodyPreview, receivedDateTime, from/emailAddress, importance
        """
        if not self.is_configured():
            return []

        mailbox = self.mailbox_email or "me"
        path = f"/users/{mailbox}/mailFolders/inbox/messages"
        params = {
            "$top": str(limit),
            "$select": "id,subject,bodyPreview,receivedDateTime,importance,from,conversationId",
            "$orderby": "receivedDateTime DESC",
        }

        data = self._graph_get(path, params=params)
        if not data:
            return []

        messages = data.get("value", [])
        result: List[Dict[str, Any]] = []
        for msg in messages:
            sender = msg.get("from") or {}
            email_addr = (sender.get("emailAddress") or {}).get("address", "")
            result.append({
                "id": msg.get("id"),
                "subject": msg.get("subject") or "(no subject)",
                "body_preview": msg.get("bodyPreview") or "",
                "received_date_time": msg.get("receivedDateTime"),
                "from_email": email_addr,
                "importance": msg.get("importance", "normal"),
                "conversation_id": msg.get("conversationId"),
            })
        return result

    def fetch_mail_by_id(self, mail_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single message by id."""
        if not self.is_configured():
            return None

        mailbox = self.mailbox_email or "me"
        path = f"/users/{mailbox}/messages/{mail_id}"
        params = {
            "$select": "id,subject,body,receivedDateTime,importance,from,conversationId",
        }

        data = self._graph_get(path, params=params)
        if not data:
            return None

        sender = data.get("from") or {}
        email_addr = (sender.get("emailAddress") or {}).get("address", "")
        body_content = ""
        body_data = data.get("body") or {}
        body_content = body_data.get("content", "")

        return {
            "id": data.get("id"),
            "subject": data.get("subject") or "(no subject)",
            "body": body_content,
            "received_date_time": data.get("receivedDateTime"),
            "from_email": email_addr,
            "importance": data.get("importance", "normal"),
            "conversation_id": data.get("conversationId"),
        }

    # ----------------------------------------------------------------
    # Mail sending
    # ----------------------------------------------------------------

    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send an email via Microsoft Graph.

        Returns True on success, False otherwise.
        """
        if not self.is_configured():
            return False

        mailbox = self.mailbox_email or "me"
        url = f"{GRAPH_BASE_URL}/users/{mailbox}/sendMail"
        headers = self._headers()
        if not headers:
            return False

        message = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "Text",
                    "content": body,
                },
                "toRecipients": [
                    {"emailAddress": {"address": to_email}}
                ],
            },
            "saveToSentItems": "true",
        }

        try:
            resp = requests.post(url, headers=headers, json=message, timeout=30)
            resp.raise_for_status()
            logger.info("Mail sent to %s: %s", to_email, subject)
            return True
        except requests.RequestException as exc:
            logger.error("Failed to send mail to %s: %s", to_email, exc)
            return False

    # ----------------------------------------------------------------
    # Suggestion logic from mails
    # ----------------------------------------------------------------

    def _parse_suggestions_from_mails(
        self,
        mails: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Very lightweight heuristic parser: look for action keywords in subjects."""
        suggestions: List[Dict[str, Any]] = []
        keywords = [
            "à faire",
            "action",
            "demande",
            "urgent",
            "rappel",
            "rappeler",
            "valider",
            "signer",
            "envoyer",
            "corriger",
            "répondre",
            "relancer",
            "deadline",
            "échéance",
            "à confirmer",
            "à revoir",
        ]
        subj_lower = ""
        body_lower = ""
        for mail in mails:
            subj_lower = (mail.get("subject") or "").lower()
            body_lower = (mail.get("body_preview") or "").lower()
            matched_keyword = next((kw for kw in keywords if kw in subj_lower or kw in body_lower), None)
            if matched_keyword:
                priority = "haute" if mail.get("importance") == "high" or matched_keyword in {"urgent", "deadline", "échéance"} else "moyenne"
                suggestions.append({
                    "titre": f"Mail: {mail.get('subject') or '(no subject)'}",
                    "dossier_id": mail.get("dossier_id"),
                    "assigne_a": mail.get("assigne_a"),
                    "priorite": priority,
                    "date_echeance": mail.get("date_echeance"),
                    "source": f"outlook:{mail.get('id')}",
                    "meta": {
                        "from_email": mail.get("from_email"),
                        "received_date_time": mail.get("received_date_time"),
                        "matched_keyword": matched_keyword,
                    },
                })
        return suggestions

    def suggest_tasks_from_mails(self, limit: int = 20) -> List[Dict[str, Any]]:
        """High-level method used by routes to propose tasks from Outlook mails."""
        if not self.is_configured():
            return []

        mails = self.fetch_recent_mails(limit=limit)
        if not mails:
            return []

        return self._parse_suggestions_from_mails(mails[:limit])
