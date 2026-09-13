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
    """Return model IDs usable by *key*, or [] when the lookup fails.

    ``None`` means "find a key yourself"; an empty string means "there is no
    key" and must NOT silently fall back to the environment.
    """
    if key is None:
        key = api_key()
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
    # An explicit pin wins — except on a forced re-resolution, which only
    # happens after the API rejected that very model as decommissioned.
    # Honouring the pin there would retry the same dead ID forever.
    if pinned and not force and pinned not in RETIRED_MODELS:
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


def model_candidates(key: Optional[str] = None) -> List[str]:
    """Modele do wypróbowania, od najlepszego, bez duplikatów i wycofanych.

    Pierwszy jest model rozstrzygnięty przez :func:`resolve_model`, potem
    reszta preferencji. Dzięki temu zachowanie „normalne" się nie zmienia, a
    dopiero po odmowie schodzimy niżej.
    """
    ordered: List[str] = []
    try:
        ordered.append(resolve_model(key))
    except Exception:
        pass
    for candidate in MODEL_PREFERENCES:
        if candidate not in ordered:
            ordered.append(candidate)
    return [m for m in ordered if m and m not in RETIRED_MODELS]


def is_rate_limited(status_code: int) -> bool:
    """True gdy Groq odmówił z powodu limitu."""
    return status_code == 429


def chat(prompt: str, max_tokens: int = 800, temperature: float = 0.0,
         key: Optional[str] = None, timeout: Optional[int] = None,
         log=print) -> Optional[str]:
    """Zapytaj Groq, przechodząc na kolejny model gdy bieżący odmawia.

    Po co: limity Groq są liczone **per model**, a nie na całe konto. Do tej
    pory jedno HTTP 429 kończyło wywołanie, mimo że pozostałe modele z
    :data:`MODEL_PREFERENCES` najczęściej mają jeszcze zapas. W praktyce
    oznaczało to ciszę AI dokładnie wtedy, gdy równolegle biegnie kilka jobów
    (np. osiem sportów w matrixie) i wszystkie trafiają w ten sam model.

    Obsługiwane odmowy:
      - 429 (limit)            -> próbuj następnego modelu
      - 400 decommissioned     -> odśwież listę modeli i próbuj dalej

    Returns:
        Treść odpowiedzi albo None, gdy żaden model nie odpowiedział.
    """
    try:
        import requests
    except Exception as e:  # pragma: no cover
        log(f"      ⚠️ Groq: brak requests ({type(e).__name__})")
        return None

    if key is None:
        key = api_key()
    if not key:
        log("      ⚠️ Groq: brak GROQ_API_KEY")
        return None

    if timeout is None:
        timeout = REQUEST_TIMEOUT

    candidates = model_candidates(key)
    if not candidates:
        return None

    tried_reset = False
    for model in candidates:
        try:
            resp = requests.post(
                CHAT_ENDPOINT,
                headers={'Authorization': f'Bearer {key}',
                         'Content-Type': 'application/json'},
                json={'model': model,
                      'messages': [{'role': 'user', 'content': prompt}],
                      'temperature': temperature,
                      'max_tokens': max_tokens},
                timeout=timeout,
            )
        except Exception as e:
            log(f"      ⚠️ Groq [{model}]: {type(e).__name__}: {e}")
            continue

        if resp.status_code == 200:
            try:
                return resp.json()['choices'][0]['message']['content'].strip()
            except Exception as e:
                log(f"      ⚠️ Groq [{model}]: zła odpowiedź ({type(e).__name__})")
                continue

        if is_rate_limited(resp.status_code):
            log(f"      ⚠️ Groq [{model}]: limit (429) — próbuję kolejnego modelu")
            continue

        if is_decommissioned_error(resp.status_code, resp.text) and not tried_reset:
            tried_reset = True
            reset_resolved_model()
            resolve_model(key, force=True)
            log(f"      ⚠️ Groq [{model}]: model wycofany — odświeżam listę")
            continue

        log(f"      ⚠️ Groq [{model}]: HTTP {resp.status_code} "
            f"{(resp.text or '')[:100]}")

    log(f"      ⛔ Groq: żaden z {len(candidates)} modeli nie odpowiedział")
    return None
