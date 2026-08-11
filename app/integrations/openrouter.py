"""
OpenRouter / LLM integration.

Reads API key from:
- constructor parameter
- env var OPENROUTER_API_KEY
- AppSetting.cle == 'OPENROUTER_API_KEY'

Reads default model from:
- constructor parameter
- env var OPENROUTER_MODEL
- AppSetting.cle == 'OPENROUTER_MODEL'
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _get_setting(cle: str) -> Optional[str]:
    from app.models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    return row.valeur if row else None


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip() or _get_setting("OPENROUTER_API_KEY") or ""
        self.model = model or os.getenv("OPENROUTER_MODEL", "").strip() or _get_setting("OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct:free"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        if not self.is_configured():
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": 1500,
        }
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content")
                if content:
                    return content.strip()
        except Exception:
            return None
        return None

    def list_models(self, provider: Optional[str] = None) -> List[str]:
        if not self.is_configured():
            return []
        url = "https://openrouter.ai/api/v1/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            if provider:
                prefix = provider.strip().lower() + "/"
                models = [m for m in models if m.lower().startswith(prefix)]
            return sorted(models)
        except Exception:
            return []
