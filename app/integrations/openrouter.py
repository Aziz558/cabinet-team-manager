"""
OpenRouter / LLM integration.

Reads API key from:
- constructor parameter
- env var OPENROUTER_API_KEY
- AppSetting.cle == 'OPENROUTER_API_KEY'
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, str]], model: str = "mistralai/mistral-7b-instruct") -> Optional[str]:
        if not self.is_configured():
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 300,
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
