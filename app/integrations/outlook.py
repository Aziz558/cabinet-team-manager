"""
Outlook integration via Microsoft Graph – device code flow using the
public client ID of Microsoft Graph Explorer (c44b4283-bb79-491f-b596-915e3e3ef989).
No Azure AD app registration required from the user.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import msal  # pip install msal
import requests
from bs4 import BeautifulSoup  # already present via your environment

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Constants – public client ID of Microsoft Graph Explorer
# ----------------------------------------------------------------------
GRAPH_EXPLORER_CLIENT_ID = "c44b4283-bb79-491f-b596-915e3e3ef989"
GRAPH_AUTHORITY = "https://login.microsoftonline.com/common"
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
SCOPES = ["Mail.Read", "offline_access"]  # offline_access → refresh token

# ----------------------------------------------------------------------
# Helpers for storing refresh token in AppSetting
# ----------------------------------------------------------------------
def _get_setting(cle: str) -> Optional[str]:
    from app.models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    return row.valeur if row else None

def _set_setting(cle: str, valeur: str) -> None:
    from app import db
    from app.models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    if row:
        row.valeur = valeur
    else:
        row = AppSetting(cle=cle, valeur=valeur, service="outlook")
        db.session.add(row)
    db.session.commit()

def _delete_setting(cle: str) -> None:
    from app import db
    from app.models import AppSetting
    AppSetting.query.filter_by(cle=cle).delete()
    db.session.commit()

# ----------------------------------------------------------------------
# Main class
# ----------------------------------------------------------------------
class OutlookMailClient:
    def __init__(self) -> None:
        self._app = msal.PublicClientApplication(
            client_id=GRAPH_EXPLORER_CLIENT_ID,
            authority=GRAPH_AUTHORITY,
            token_cache=msal.TokenCache(),
        )
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Refresh token handling
    # ------------------------------------------------------------------
    def _load_refresh_token(self) -> Optional[str]:
        raw = _get_setting("OUTLOOK_GRAPH_REFRESH_TOKEN")
        if raw:
            try:
                data = json.loads(raw)
                return data.get("refresh_token")
            except Exception:
                logger.warning("Failed to decode stored refresh token")
        return None

    def _save_refresh_token(self, refresh_token: str, expires_in: int = None) -> None:
        payload = {
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + (expires_in or 0),
        }
        _set_setting("OUTLOOK_GRAPH_REFRESH_TOKEN", json.dumps(payload))

    def _clear_refresh_token(self) -> None:
        _delete_setting("OUTLOOK_GRAPH_REFRESH_TOKEN")
        _delete_setting("OUTLOOK_GRAPH_EXPIRES_AT")

    # ------------------------------------------------------------------
    # Silently acquire an access token using refresh token
    # ------------------------------------------------------------------
    def _acquire_token_silently(self) -> Optional[Dict[str, Any]]:
        refresh_token = self._load_refresh_token()
        if not refresh_token:
            return None
        # msal does not have a direct "acquire_by_refresh_token"; we reconstruct a token cache.
        cache = msal.TokenCache()
        cache.add(
            {
                "refresh_token": refresh_token,
                "client_id": GRAPH_EXPLORER_CLIENT_ID,
                "scope": " ".join(SCOPES),
            }
        )
        self._app.token_cache = cache
        result = self._app.acquire_token_by_refresh_token(
            refresh_token, scopes=SCOPES
        )
        if "access_token" in result:
            self._access_token = result["access_token"]
            self._expires_at = time.time() + result.get("expires_in", 0) - 30  # 30s safety margin
            if "refresh_token" in result:
                self._save_refresh_token(
                    result["refresh_token"], result.get("expires_in", 0)
                )
            return result
        else:
            logger.error(
                "Silent token acquisition failed: %s",
                result.get("error_description"),
            )
            return None

    # ------------------------------------------------------------------
    # Device code flow (first-time authentication)
    # ------------------------------------------------------------------
    def _acquire_token_via_device_code(self) -> Optional[Dict[str, Any]]:
        flow = self._app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            logger.error(
                "Failed to create device flow: %s",
                flow.get("error_description"),
            )
            return None

        print(
            "\nTo authorize access to your Outlook mailbox, follow these steps:\n"
            f"1. Open a browser and go to {flow['verification_uri']}\n"
            f"2. Enter the code: {flow['user_code']}\n"
            f"3. Sign in with your Outlook.com account and grant the permissions "
            f"Mail.Read + offline access.\n"
        )
        # Wait for user to complete the flow (timeout ~5 minutes)
        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            self._access_token = result["access_token"]
            self._expires_at = time.time() + result.get("expires_in", 0) - 30
            if "refresh_token" in result:
                self._save_refresh_token(
                    result["refresh_token"], result.get("expires_in", 0)
                )
            return result
        else:
            logger.error(
                "Device code flow failed: %s",
                result.get("error_description"),
            )
            return None

    # ------------------------------------------------------------------
    # Public API expected by the rest of the app
    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        # Always considered configured as long as the public client ID exists
        return True

    def _get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        now = time.time()
        if not self._access_token or now >= self._expires_at:
            # Try silent refresh first
            res = self._acquire_token_silently()
            if res:
                return self._access_token
            # Otherwise, trigger device code flow (requires user interaction)
            res = self._acquire_token_via_device_code()
            if not res:
                raise RuntimeError("Unable to obtain an access token for Graph")
        return self._access_token

    def fetch_recent_mails(self, limit: int = 20) -> List[Dict[str, Any]]:
        token = self._get_valid_token()
        headers = {"Authorization": f"Bearer {token}"}
        params = {"$top": str(limit), "$select": "id,subject,bodyPreview,receivedDateTime,from,importance"}
        try:
            resp = requests.get(GRAPH_ENDPOINT, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("value", [])
            out: List[Dict[str, Any]] = []
            for m in messages:
                from_addr = ""
                fr = m.get("from", {})
                if isinstance(fr, dict):
                    email_addr = fr.get("emailAddress", {})
                    if isinstance(email_addr, dict):
                        from_addr = email_addr.get("address", "")
                out.append(
                    {
                        "id": m.get("id"),
                        "subject": m.get("subject", ""),
                        "body_preview": m.get("bodyPreview", ""),
                        "body": m.get("bodyPreview", ""),  # we only have preview; keep as body for compatibility
                        "received_date_time": m.get("receivedDateTime", ""),
                        "from_email": from_addr,
                        "importance": m.get("importance", "normal").lower(),
                        "conversation_id": None,
                    }
                )
            return out
        except Exception as e:
            logger.exception("Error calling Graph API: %s", e)
            return []

    def fetch_mail_by_id(self, mail_id: str) -> Optional[Dict[str, Any]]:
        # Not currently used; keep signature for compatibility
        token = self._get_valid_token()
        url = f"https://graph.microsoft.com/v1.0/me/messages/{mail_id}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            m = resp.json()
            from_addr = ""
            fr = m.get("from", {})
            if isinstance(fr, dict):
                email_addr = fr.get("emailAddress", {})
                if isinstance(email_addr, dict):
                    from_addr = email_addr.get("address", "")
            return {
                "id": m.get("id"),
                "subject": m.get("subject", ""),
                "body_preview": m.get("bodyPreview", ""),
                "body": m.get("bodyPreview", ""),
                "received_date_time": m.get("receivedDateTime", ""),
                "from_email": from_addr,
                "importance": m.get("importance", "normal").lower(),
                "conversation_id": None,
            }
        except Exception as e:
            logger.exception("Error fetching mail by ID: %s", e)
            return None

    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        # Reuse your existing email sending via Brevo (already in routes.py)
        from app import app
        from flask_mail import Message
        from smtplib import SMTPException

        with app.app_context():
            msg = Message(subject=subject, recipients=[to_email], body=body,
                          sender=app.config.get("MAIL_DEFAULT_SENDER"))
            try:
                mail.send(msg)
                return True
            except SMTPException as e:
                logger.error("Failed to send email via Brevo: %s", e)
                return False

    # ------------------------------------------------------------------
    # Action keyword detection (identical to previous version)
    # ------------------------------------------------------------------
    _KEYWORDS = [
        "à faire", "action", "demande", "urgent", "rappel", "rappeler",
        "valider", "signer", "envoyer", "corriger", "répondre", "relancer",
        "deadline", "échéance", "à confirmer", "à revoir",
    ]

    def _match_keyword(self, text: str) -> Optional[str]:
        low = text.lower()
        for kw in self._KEYWORDS:
            if kw in low:
                return kw
        return None

    def suggest_tasks_from_mails(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        mails = self.fetch_recent_mails(limit=limit)
        suggestions: List[Dict[str, Any]] = []
        for m in mails:
            kw = self._match_keyword(f"{m['subject']} {m['body_preview']}")
            if not kw:
                continue
            priority = (
                "haute"
                if m["importance"] == "high"
                or kw in {"urgent", "deadline", "échéance"}
                else "moyenne"
            )
            suggestions.append(
                {
                    "titre": f"Mail: {m['subject'] or '(sans sujet)'}",
                    "dossier_id": m.get("dossier_id"),
                    "assigne_a": m.get("assigne_a"),
                    "priorite": priority,
                    "date_echeance": m.get("date_echeance"),
                    "source": f"outlook_graph:{m['id']}",
                    "meta": {
                        "from_email": m.get("from_email"),
                        "received_date_time": m.get("receivedDateTime", ""),
                        "matched_keyword": kw,
                    },
                }
            )
        return suggestions