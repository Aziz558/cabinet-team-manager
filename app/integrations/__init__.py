"""
Integrations package.

Exports:
  - TeamsClient from app.integrations.teams
  - OpenRouterClient from app.integrations.openrouter
"""

from __future__ import annotations

from .teams import TeamsClient  # noqa: F401
from .openrouter import OpenRouterClient  # noqa: F401


def get_teams() -> TeamsClient:
    return TeamsClient()


def get_openrouter() -> OpenRouterClient:
    return OpenRouterClient()
