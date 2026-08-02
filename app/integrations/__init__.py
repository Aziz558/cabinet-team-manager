"""
Integrations package.

Exports:
  - OutlookMailClient from app.integrations.outlook
  - TeamsClient from app.integrations.teams
  - OpenRouterClient from app.integrations.openrouter
  - PennyLaneClient stub
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .outlook import OutlookMailClient  # noqa: F401
from .teams import TeamsClient  # noqa: F401
from .openrouter import OpenRouterClient  # noqa: F401


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class PennyLaneClient:
    """Minimal PennyLane integration stub kept for compatibility."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = "") -> None:
        self.api_key = api_key or _env_str("PENNYLANE_API_KEY")
        self.base_url = base_url or _env_str("PENNYLANE_BASE_URL", "https://app.pennylane.com")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_clients(self) -> List[Dict[str, Any]]:
        return []

    def fetch_dossiers(self) -> List[Dict[str, Any]]:
        return []

    def fetch_echeances(self) -> List[Dict[str, Any]]:
        return []

    def build_suggestions_from_deadlines(self) -> List[Dict[str, Any]]:
        return []


def get_pennylane() -> PennyLaneClient:
    return PennyLaneClient()


def get_outlook() -> OutlookMailClient:
    return OutlookMailClient()


def get_teams() -> TeamsClient:
    return TeamsClient()


def get_openrouter() -> OpenRouterClient:
    return OpenRouterClient()
