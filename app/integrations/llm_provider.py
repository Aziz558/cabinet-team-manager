"""
llm_provider — abstraction multi-provider pour l'assistant IA.

Providers supportés :
- openrouter  (OpenRouter API) — toujours conservé en fallback de secours
- nvidia      (NVIDIA NIM API)
- gemini      (Google Gemini API)
- groq        (Groq API — rapide, quota gratuit généreux)

La clé et le modèle de chaque provider se lisent depuis les AppSetting :
  LLM_PROVIDER_PRIMAIRE  : 'openrouter' | 'nvidia' | 'gemini' | 'groq'
  OPENROUTER_API_KEY / OPENROUTER_MODEL
  NVIDIA_API_KEY / NVIDIA_MODEL
  GEMINI_API_KEY / GEMINI_MODEL
  GROQ_API_KEY / GROQ_MODEL

Le LLMManager essaie le provider primaire, puis bascule sur OpenRouter en cas
d'échec (quota, panne, clé invalide).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def _get_setting(cle: str) -> Optional[str]:
    from app.models import AppSetting
    row = AppSetting.query.filter_by(cle=cle).first()
    return row.valeur if row and row.valeur else None


def _env_or_setting(cle_env: str, cle_setting: str, default: str = '') -> str:
    return os.getenv(cle_env, '').strip() or _get_setting(cle_setting) or default


class LLMProvider(ABC):
    """Interface commune : chaque provider implémente name(), is_configured(), chat()."""

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        pass


class OpenRouterProvider(LLMProvider):
    URL = 'https://openrouter.ai/api/v1/chat/completions'

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or _env_or_setting('OPENROUTER_API_KEY', 'OPENROUTER_API_KEY')
        self.model = model or _env_or_setting('OPENROUTER_MODEL', 'OPENROUTER_MODEL',
                                                'meta-llama/llama-3.3-70b-instruct')

    def name(self) -> str:
        return 'openrouter'

    def is_configured(self) -> bool:
        # Délégation à OpenRouterClient pour rester compatible avec les tests
        # qui monkeypatchent app.integrations.openrouter.OpenRouterClient.
        from .openrouter import OpenRouterClient
        return OpenRouterClient(api_key=self.api_key).is_configured()

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        if not self.is_configured():
            return None
        from .openrouter import OpenRouterClient
        client = OpenRouterClient(api_key=self.api_key, model=model or self.model)
        return client.chat(messages)


class NVIDIAProvider(LLMProvider):
    URL = 'https://integrate.api.nvidia.com/v1/chat/completions'

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or _env_or_setting('NVIDIA_API_KEY', 'NVIDIA_API_KEY')
        self.model = model or _env_or_setting('NVIDIA_MODEL', 'NVIDIA_MODEL',
                                                'meta/llama-3.1-8b-instruct')

    def name(self) -> str:
        return 'nvidia'

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        if not self.is_configured():
            return None
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload: Dict[str, Any] = {
            'model': model or self.model,
            'messages': messages,
            'max_tokens': 1500,
            'temperature': 0.2,
        }
        try:
            resp = requests.post(self.URL, headers=headers, json=payload, timeout=25)
        except Exception as exc:
            logger.error('NVIDIA: requête échouée (%s): %s', type(exc).__name__, exc)
            return None
        if resp.status_code >= 400:
            logger.error('NVIDIA: HTTP %s model=%s corps=%s',
                         resp.status_code, payload['model'], resp.text[:300])
            return None
        try:
            data = resp.json()
            choices = data.get('choices') or []
            if choices:
                content = choices[0].get('message', {}).get('content')
                if content:
                    return content.strip()
            logger.error('NVIDIA: réponse sans contenu model=%s corps=%s',
                         payload['model'], resp.text[:300])
        except Exception as exc:
            logger.error('NVIDIA: réponse illisible (%s): %s', type(exc).__name__, exc)
        return None


class GroqProvider(LLMProvider):
    """Groq — API compatible OpenAI (api.groq.com), très rapide, quota gratuit."""
    URL = 'https://api.groq.com/openai/v1/chat/completions'

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or _env_or_setting('GROQ_API_KEY', 'GROQ_API_KEY')
        self.model = model or _env_or_setting('GROQ_MODEL', 'GROQ_MODEL',
                                                'llama-3.3-70b-versatile')

    def name(self) -> str:
        return 'groq'

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        if not self.is_configured():
            return None
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload: Dict[str, Any] = {
            'model': model or self.model,
            'messages': messages,
            'max_tokens': 1500,
            'temperature': 0.2,
        }
        try:
            resp = requests.post(self.URL, headers=headers, json=payload, timeout=25)
        except Exception as exc:
            logger.error('Groq: requête échouée (%s): %s', type(exc).__name__, exc)
            return None
        if resp.status_code >= 400:
            logger.error('Groq: HTTP %s model=%s corps=%s',
                         resp.status_code, payload['model'], resp.text[:300])
            return None
        try:
            data = resp.json()
            choices = data.get('choices') or []
            if choices:
                content = choices[0].get('message', {}).get('content')
                if content:
                    return content.strip()
            logger.error('Groq: réponse sans contenu model=%s corps=%s',
                         payload['model'], resp.text[:300])
        except Exception as exc:
            logger.error('Groq: réponse illisible (%s): %s', type(exc).__name__, exc)
        return None


class GeminiProvider(LLMProvider):
    BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or _env_or_setting('GEMINI_API_KEY', 'GEMINI_API_KEY')
        self.model = model or _env_or_setting('GEMINI_MODEL', 'GEMINI_MODEL',
                                                'gemini-1.5-flash-latest')

    def name(self) -> str:
        return 'gemini'

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None) -> Optional[str]:
        if not self.is_configured():
            return None
        url = self.BASE_URL.format(model=model or self.model)
        contents = []
        for m in messages:
            role = m.get('role', 'user')
            g_role = 'model' if role == 'assistant' else 'user'
            contents.append({'role': g_role, 'parts': [{'text': m.get('content', '')}]})
        payload: Dict[str, Any] = {'contents': contents}
        params = {'key': self.api_key}
        try:
            resp = requests.post(url, params=params, json=payload, timeout=25)
        except Exception as exc:
            logger.error('Gemini: requête échouée (%s): %s', type(exc).__name__, exc)
            return None
        if resp.status_code >= 400:
            logger.error('Gemini: HTTP %s model=%s corps=%s',
                         resp.status_code, self.model, resp.text[:300])
            return None
        try:
            data = resp.json()
            candidates = data.get('candidates') or []
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                if parts:
                    return parts[0].get('text', '').strip()
            logger.error('Gemini: réponse sans contenu model=%s corps=%s',
                         self.model, resp.text[:300])
        except Exception as exc:
            logger.error('Gemini: réponse illisible (%s): %s', type(exc).__name__, exc)
        return None



_PROVIDER_CLASSES = {
    'openrouter': OpenRouterProvider,
    'nvidia': NVIDIAProvider,
    'gemini': GeminiProvider,
    'groq': GroqProvider,
}


class LLMManager:
    """Orchestre les appels LLM : provider primaire configuré, puis OpenRouter en fallback."""

    def __init__(self) -> None:
        primaire_cle = _env_or_setting('LLM_PROVIDER_PRIMAIRE', 'LLM_PROVIDER_PRIMAIRE', 'openrouter')
        primaire_cls = _PROVIDER_CLASSES.get(primaire_cle, OpenRouterProvider)
        self.primary: LLMProvider = primaire_cls()
        self.fallback: LLMProvider = OpenRouterProvider()

    def chat(self, messages: List[Dict[str, str]],
             model: Optional[str] = None,
             prefer: Optional[str] = None) -> Optional[str]:
        """Essaye le provider demandé (ou le primaire), puis OpenRouter en fallback.
        Retourne le texte de réponse ou None si tous les providers échouent."""
        candidates: List[LLMProvider] = []
        if prefer and prefer in _PROVIDER_CLASSES:
            candidates.append(_PROVIDER_CLASSES[prefer]())
        elif self.primary and self.primary.is_configured():
            candidates.append(self.primary)
        # OpenRouter toujours en dernier recours (même si c'était le primaire, on retry avec sa propre instance)
        if not any(isinstance(p, OpenRouterProvider) for p in candidates):
            candidates.append(self.fallback)

        dernier_erreur = ''
        for prov in candidates:
            if not prov.is_configured():
                continue
            try:
                reponse = prov.chat(messages, model=model)
            except Exception as exc:
                dernier_erreur = f'{prov.name()}: exception ({type(exc).__name__})'
                logger.error('LLM %s exception: %s', prov.name(), exc)
                continue
            if reponse:
                logger.info('LLM réponse OK via %s', prov.name())
                return reponse
            dernier_erreur = f'{prov.name()}: pas de contenu'
        logger.error('Tous les providers LLM ont échoué. Dernier: %s', dernier_erreur)
        return None

    def provider_nom(self) -> str:
        return self.primary.name() if self.primary else 'openrouter'


# Pas de cache global : un manager frais est instancié à chaque appel afin de
# relire immédiatement les clés saisies dans les Réglages (AppSetting), sans
# redémarrer l'application. Le coût (quelques requêtes de config) est négligeable
# face à un appel LLM.


def get_llm_manager() -> LLMManager:
    return LLMManager()

