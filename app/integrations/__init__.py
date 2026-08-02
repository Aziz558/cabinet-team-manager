"""
Integrations package.

Exports:
  - OutlookMailClient from app.integrations.outlook
  - TeamsClient from app.integrations.teams
  - OpenRouterClient from app.integrations.openrouter
"""

from __future__ import annotations

from .outlook import OutlookMailClient  # noqa: F401
from .teams import TeamsClient  # noqa: F401
from .openrouter import OpenRouterClient  # noqa: F401


def get_outlook() -> OutlookMailClient:
    return OutlookMailClient()


def get_teams() -> TeamsClient:
    return TeamsClient()


def get_openrouter() -> OpenRouterClient:
    return OpenRouterClient()
