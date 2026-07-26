"""
Groq model resolution
---------------------
Hosted model IDs are moving targets: Groq retired ``mixtral-8x7b-32768`` in
March 2025 and has rotated its lineup several times since. Pinning a name in
code guarantees an eventual silent outage, because a retired ID answers HTTP
400 and callers typically log the error and return None.

This module resolves the model at runtime against what the account can
actually see (``GET /openai/v1/models``), caching the result per process.

It lives here — not in ``groq_config.py`` — because that file is gitignored
(it used to hold a hardcoded key), so anything defined there is missing in CI.
Local ``groq_config.py`` remains supported as an optional override.

Precedence for the model:
  1. ``GROQ_MODEL`` environment variable (explicit pin)
  2. first entry of :data:`MODEL_PREFERENCES` offered by the API
  3. any model the account can see
  4. first preference (offline / no key)
"""

from __future__ import annotations

import os
from typing import List, Optional

MODELS_ENDPOINT = 'https://api.groq.com/openai/v1/models'
CHAT_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'

# Ordered preference. Small/fast models rank high because the in-repo use case
# is short team-name matching prompts, not long-form reasoning.
MODEL_PREFERENCES: List[str] = [
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
    'openai/gpt-oss-120b',
    'openai/gpt-oss-20b',
    'gemma2-9b-it',
    'mistral-saba-24b',
]

# Models known to be retired — never select these even if a stale config or
# cached list mentions them.
RETIRED_MODELS = frozenset({
    'mixtral-8x7b-32768',
    'llama2-70b-4096',
    'gemma-7b-it',
    'llama-3.1-70b-versatile',
})

REQUEST_TIMEOUT = 30
RATE_LIMIT_DELAY = 0.5

_resolved_model: Optional[str] = None


def api_key() -> Optional[str]:
    """Return the Groq key from the environment, or a local config override."""
    key = os.environ.get('GROQ_API_KEY')
    if key:
        return key
    try:
        import groq_config  # type: ignore[import-not-found]

        if getattr(groq_config, 'GROQ_ENABLED', True):
            return getattr(groq_config, 'GROQ_API_KEY', None)
    except ImportError:
        pass
    return None


def list_available_models(key: Optional[str] = None, timeout: int = 10) -> List[str]:
    """Return model IDs usable by *key*, or [] when the lookup fails."""
    key = key or api_key()
    if not key:
        return []
    try:
        import requests

        resp = requests.get(
            MODELS_ENDPOINT,
            headers={'Authorization': f'Bearer {key}'},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json()
    except Exception:
        return []

    models = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [m.get('id') for m in models
            if isinstance(m, dict) and m.get('id')
            and m.get('id') not in RETIRED_MODELS]


def resolve_model(key: Optional[str] = None, force: bool = False) -> str:
    """Pick the best usable model. See module docstring for precedence."""
    global _resolved_model

    pinned = os.environ.get('GROQ_MODEL')
    if pinned:
        return pinned

    if _resolved_model and not force:
        return _resolved_model

    available = set(list_available_models(key))
    if available:
        for candidate in MODEL_PREFERENCES:
            if candidate in available:
                _resolved_model = candidate
                return candidate
        # None of our preferences survive — use whatever the account offers
        # rather than failing outright.
        _resolved_model = sorted(available)[0]
        return _resolved_model

    # No key or no network: behave like the previous hardcoded default.
    return MODEL_PREFERENCES[0]


def reset_resolved_model() -> None:
    """Clear the cached choice (tests, and after a mid-run decommission)."""
    global _resolved_model
    _resolved_model = None


def is_decommissioned_error(status_code: int, body: str) -> bool:
    """True when a response indicates the requested model no longer exists."""
    if status_code != 400:
        return False
    text = (body or '').lower()
    return any(marker in text for marker in
               ('decommission', 'does not exist', 'not found', 'unknown model'))
