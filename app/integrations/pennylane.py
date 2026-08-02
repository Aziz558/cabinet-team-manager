"""
Real PennyLane integration.

Uses requests to call the PennyLane API.
Never hardcode credentials here; read them from environment variables.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from app.models import AppSetting


class PennyLaneClient:
    """Minimal PennyLane integration using basic auth API key."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = "") -> None:
        self.api_key = api_key or os.getenv("PENNYLANE_API_KEY", "")
        self.base_url = (base_url or os.getenv("PENNYLANE_BASE_URL", "https://app.pennylane.com")).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _auth(self) -> tuple[str, str]:
        return ("__api__", self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"Accept": "application/json"}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        resp = requests.get(url, auth=self._auth(), headers=self._headers(), params=params, timeout=15)
        if resp.status_code == 401:
            return []
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("data") or data.get("items") or []
        if isinstance(data, list):
            return data
        return []

    def fetch_companies(self) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        return self._get("/api/external/v2/companies")

    def _company_id(self) -> Optional[str]:
        return getattr(self, "company_id", None)

    def fetch_clients(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        company_id = company_id or self._company_id()
        if company_id:
            return self._get(f"/api/external/v2/companies/{company_id}/clients")
        return self._get("/api/external/v2/clients")

    def fetch_dossiers(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        company_id = company_id or self._company_id()
        if company_id:
            return self._get(f"/api/external/v2/companies/{company_id}/dossiers")
        return self._get("/api/external/v2/dossiers")

    def fetch_echeances(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.is_configured():
            return []
        company_id = company_id or self._company_id()
        if company_id:
            return self._get(f"/api/external/v2/companies/{company_id}/echeances")
        return self._get("/api/external/v2/echeances")

    def build_suggestions_from_deadlines(self, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        company_id = company_id or self._company_id()
        for item in self.fetch_echeances(company_id=company_id):
            suggestions.append(
                {
                    "titre": item.get("titre") or item.get("label") or "Échéance PennyLane",
                    "dossier_id": item.get("dossier_id") or item.get("dossierId"),
                    "assigne_a": item.get("assigne_a") or item.get("assignedTo"),
                    "priorite": item.get("priorite") or item.get("priority") or "moyenne",
                    "date_echeance": item.get("date_echeance") or item.get("dueAt") or item.get("date"),
                }
            )
        return suggestions


def get_pennylane() -> PennyLaneClient:
    from app import app as _app
    with _app.app_context():
        key_row = AppSetting.query.filter_by(cle="PENNYLANE_API_KEY").first()
        base_row = AppSetting.query.filter_by(cle="PENNYLANE_BASE_URL").first()
        company_row = AppSetting.query.filter_by(cle="PENNYLANE_COMPANY_ID").first()
    api_key = key_row.valeur if key_row and key_row.valeur else os.getenv("PENNYLANE_API_KEY", "")
    base_url = base_row.valeur if base_row and base_row.valeur else os.getenv("PENNYLANE_BASE_URL", "https://app.pennylane.com")
    company_id = company_row.valeur if company_row and company_row.valeur else os.getenv("PENNYLANE_COMPANY_ID", "")
    client = PennyLaneClient(api_key=api_key, base_url=base_url)
    client.company_id = company_id or None
    return client
