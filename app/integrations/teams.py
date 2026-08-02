"""
Real Microsoft Teams connector via Microsoft Graph.

Reads channel messages and converts them into task suggestions.
No hard-coded secrets; credentials are read from environment variables
or constructor parameters.
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


class TeamsClient:
    """Microsoft Graph Teams integration.

    Expected env vars:
      - TEAMS_CLIENT_ID
      - TEAMS_TENANT_ID
      - TEAMS_CLIENT_SECRET
      - TEAMS_TEAM_ID
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or _env_str("TEAMS_CLIENT_ID")
        self.tenant_id = tenant_id or _env_str("TEAMS_TENANT_ID")
        self.client_secret = client_secret or _env_str("TEAMS_CLIENT_SECRET")
        self.team_id = team_id or _env_str("TEAMS_TEAM_ID")

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
            logger.warning("Teams client is not configured.")
            return None

        app = self._build_msal_app()
        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            self._access_token = result["access_token"]
            logger.info("Teams access token acquired successfully.")
            return self._access_token

        error = result.get("error")
        desc = result.get("error_description")
        logger.error("Failed to acquire Teams token: %s - %s", error, desc)
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
    # Teams / channels / messages reading
    # ----------------------------------------------------------------

    def list_channels(self) -> List[Dict[str, Any]]:
        """List channels for the configured team."""
        if not self.is_configured() or not self.team_id:
            return []

        data = self._graph_get(f"/teams/{self.team_id}/channels")
        if not data:
            return []

        channels = data.get("value", [])
        return [
            {
                "id": ch.get("id"),
                "displayName": ch.get("displayName"),
                "description": ch.get("description"),
            }
            for ch in channels
        ]

    def fetch_recent_messages(self, limit: int = 20, channel_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return recent channel messages from Microsoft Graph.

        If ``channel_id`` is omitted, the first channel is used automatically.
        """
        if not self.is_configured() or not self.team_id:
            return []

        channels = self.list_channels()
        if not channels:
            logger.warning("No channels found for team %s.", self.team_id)
            return []

        target_channel_id = channel_id or channels[0].get("id")
        if not target_channel_id:
            return []

        path = f"/teams/{self.team_id}/channels/{target_channel_id}/messages"
        params = {
            "$top": str(limit),
            "$select": "id,subject,body,createdDateTime,lastModifiedDateTime,importance,from,channelIdentity",
            "$orderby": "createdDateTime DESC",
        }

        data = self._graph_get(path, params=params)
        if not data:
            return []

        messages = data.get("value", [])
        result: List[Dict[str, Any]] = []
        for msg in messages:
            sender = msg.get("from") or {}
            email_addr = (sender.get("user") or {}).get("email") or (sender.get("application") or {}).get("displayName") or ""
            body_data = msg.get("body") or {}
            content = body_data.get("content", "")
            result.append({
                "id": msg.get("id"),
                "subject": msg.get("subject") or "",
                "body": content,
                "body_preview": content[:500],
                "created_date_time": msg.get("createdDateTime"),
                "last_modified_date_time": msg.get("lastModifiedDateTime"),
                "importance": msg.get("importance", "normal"),
                "from_email": email_addr,
                "channel_id": target_channel_id,
            })
        return result

    def fetch_message_by_id(self, message_id: str, channel_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single Teams channel message by id."""
        if not self.is_configured() or not self.team_id:
            return None

        channels = self.list_channels()
        if not channels:
            return []

        target_channel_id = channel_id or channels[0].get("id")
        if not target_channel_id:
            return None

        path = f"/teams/{self.team_id}/channels/{target_channel_id}/messages/{message_id}"
        params = {
            "$select": "id,subject,body,createdDateTime,lastModifiedDateTime,importance,from,channelIdentity",
        }

        data = self._graph_get(path, params=params)
        if not data:
            return None

        sender = data.get("from") or {}
        email_addr = (sender.get("user") or {}).get("email") or (sender.get("application") or {}).get("displayName") or ""
        body_data = data.get("body") or {}
        content = body_data.get("content", "")

        return {
            "id": data.get("id"),
            "subject": data.get("subject") or "",
            "body": content,
            "body_preview": content[:500],
            "created_date_time": data.get("createdDateTime"),
            "last_modified_date_time": data.get("lastModifiedDateTime"),
            "importance": data.get("importance", "normal"),
            "from_email": email_addr,
            "channel_id": target_channel_id,
        }

    # ----------------------------------------------------------------
    # Notifications
    # ----------------------------------------------------------------

    def send_notification(self, user_email: str, title: str, text: str) -> bool:
        """Send a chat notification to a user via Graph.

        This implementation creates a 1:1 chat and posts a message.
        """
        if not self.is_configured():
            return False

        headers = self._headers()
        if not headers:
            return False

        # Resolve user id from email
        user_id = self._resolve_user_id_by_email(user_email)
        if not user_id:
            logger.error("Cannot resolve Teams user id for %s", user_email)
            return False

        # Create/get 1:1 chat
        chat_id = self._get_or_create_chat(user_id)
        if not chat_id:
            logger.error("Cannot create or find 1:1 chat with %s", user_email)
            return False

        url = f"{GRAPH_BASE_URL}/chats/{chat_id}/messages"
        payload = {
            "body": {
                "contentType": "text",
                "content": f"**{title}**\n\n{text}",
            }
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            logger.info("Teams notification sent to %s.", user_email)
            return True
        except requests.RequestException as exc:
            logger.error("Failed to send Teams notification to %s: %s", user_email, exc)
            return False

    def _resolve_user_id_by_email(self, email: str) -> Optional[str]:
        data = self._graph_get("/users", params={"$filter": f"mail eq '{email}'", "$select": "id,mail"})
        if not data:
            return None
        users = data.get("value", [])
        if not users:
            return None
        return users[0].get("id")

    def _get_or_create_chat(self, user_id: str) -> Optional[str]:
        # Try to find existing 1:1 chat
        data = self._graph_get(
            "/chats",
            params={
                "$filter": f"chatType eq 'oneOnOne' and members/any(m:m/microsoft.graph.userId eq '{user_id}')",
                "$select": "id,chatType",
            },
        )
        if data:
            chats = data.get("value", [])
            if chats:
                return chats[0].get("id")

        # Create a new 1:1 chat
        headers = self._headers()
        if not headers:
            return None

        me_data = self._graph_get("/me", params={"$select": "id"})
        if not me_data:
            return None
        my_id = me_data.get("id")
        if not my_id:
            return None

        url = f"{GRAPH_BASE_URL}/chats"
        payload = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{my_id}')",
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{user_id}')",
                },
            ],
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code in (200, 201):
                chat = resp.json()
                return chat.get("id")
            logger.error("Create chat failed: %s %s", resp.status_code, resp.text)
            return None
        except requests.RequestException as exc:
            logger.error("Exception while creating Teams chat: %s", exc)
            return None

    # ----------------------------------------------------------------
    # Suggestion logic from messages
    # ----------------------------------------------------------------

    def _parse_suggestions_from_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Heuristic parser for Teams messages: look for action keywords."""
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
            "todo",
            "task",
            "tâche",
            "assigné",
            "assignée",
        ]
        for msg in messages:
            subj = (msg.get("subject") or "").lower()
            body = (msg.get("body") or "").lower()
            matched_keyword = next((kw for kw in keywords if kw in subj or kw in body), None)
            if matched_keyword:
                priority = (
                    "haute"
                    if msg.get("importance") == "high"
                    or matched_keyword in {"urgent", "deadline", "échéance"}
                    else "moyenne"
                )
                title = msg.get("subject") or msg.get("body", "")[:80] or "Action Teams"
                suggestions.append({
                    "titre": f"Teams: {title}",
                    "dossier_id": msg.get("dossier_id"),
                    "assigne_a": msg.get("assigne_a"),
                    "priorite": priority,
                    "date_echeance": msg.get("date_echeance"),
                    "source": f"teams:{msg.get('id')}",
                    "meta": {
                        "from_email": msg.get("from_email"),
                        "created_date_time": msg.get("created_date_time"),
                        "channel_id": msg.get("channel_id"),
                        "matched_keyword": matched_keyword,
                    },
                })
        return suggestions

    def suggest_tasks_from_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        """High-level method used by routes to propose tasks from Teams messages."""
        if not self.is_configured():
            return []

        messages = self.fetch_recent_messages(limit=limit)
        if not messages:
            return []

        return self._parse_suggestions_from_messages(messages[:limit])
