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
import re
from typing import List, Optional

MODELS_ENDPOINT = 'https://api.groq.com/openai/v1/models'
CHAT_ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'

# Ordered preference.
#
# Kolejność wynika z LIMITU TOKENÓW NA MINUTĘ, nie z rozmiaru modelu. Prompty
# w tym repo bywają duże (lista ~150 meczów-kandydatów do dopasowania to
# 4-5K tokenów), a przy 8K TPM drugie takie wywołanie w tej samej minucie
# dostaje 429 — i to właśnie było przyczyną ciszy AI, nie limit dzienny.
#
# Zmierzone limity konta (2026-09):
#   groq/compound        30 RPM,  250 RPD, 70K TPM, brak limitu dziennego
#   groq/compound-mini   30 RPM,  250 RPD, 70K TPM, brak limitu dziennego
#   openai/gpt-oss-120b  30 RPM,   1K RPD,  8K TPM, 200K TPD
#   openai/gpt-oss-20b   30 RPM,   1K RPD,  8K TPM, 200K TPD
#   qwen/qwen3.8-27b     30 RPM,   1K RPD,  8K TPM, 200K TPD
#   allam-2-7b           30 RPM,   7K RPD,  6K TPM, 500K TPD
#
# Dlatego compound (70K TPM) jest pierwszy: mieści duże prompty wielokrotnie
# w minucie. Modele 8K TPM są dalej jako zapas dla krótkich zapytań.
#
# Poprzednia lista (llama-3.3-70b-versatile, llama-3.1-8b-instant, gemma2-9b-it,
# mistral-saba-24b) była nieaktualna — te modele nie są już oferowane, więc
# rotacja marnowała próby na nieistniejące ID.
MODEL_PREFERENCES: List[str] = [
    'groq/compound',
    'groq/compound-mini',
    'openai/gpt-oss-120b',
    'openai/gpt-oss-20b',
    'qwen/qwen3.8-27b',
    'qwen/qwen3.6-27b',
    'allam-2-7b',
]

# Modele, które nie są modelami czatu — nigdy ich nie wybieramy, nawet gdy
# konto je widzi. prompt-guard to klasyfikatory bezpieczeństwa, a nie modele
# generujące odpowiedzi, więc trafiłyby do rotacji tylko po to, by zawieść.
NON_CHAT_MODEL_MARKERS = ('prompt-guard', 'whisper', 'tts', 'guard')

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


MAX_NUMBERED_KEYS = 10

# Kursor po kluczach. Gdy klucz wyczerpie limity, kolejne wywołania w tym samym
# procesie startują od następnego — inaczej każde zapytanie znów przepalałoby
# pierwszy klucz na 429 i tracilibyśmy czas na pewną odmowę.
_key_cursor = 0


def api_keys() -> List[str]:
    """Wszystkie dostępne klucze Groq, w kolejności użycia.

    Źródła (łączone, bez duplikatów):
      * ``GROQ_API_KEYS`` — kilka kluczy oddzielonych przecinkiem, średnikiem
        lub białym znakiem,
      * ``GROQ_API_KEY``, ``GROQ_API_KEY_2`` … ``GROQ_API_KEY_10``,
      * ``groq_config.GROQ_API_KEY`` jako zapas lokalny.

    Po co wiele kluczy: limity Groq są liczone na konto ORAZ na model. Gdy
    wszystkie modele jednego konta oddadzą 429, drugi klucz daje świeżą pulę.
    Uwaga: dwa klucze z TEGO SAMEGO konta dzielą ten sam limit i nic nie dają.
    """
    found: List[str] = []

    def _add(value: Optional[str]) -> None:
        if not value:
            return
        for part in re.split(r'[,;\s]+', str(value)):
            part = part.strip()
            if part and part not in found:
                found.append(part)

    _add(os.environ.get('GROQ_API_KEYS'))
    _add(os.environ.get('GROQ_API_KEY'))
    for i in range(2, MAX_NUMBERED_KEYS + 1):
        _add(os.environ.get(f'GROQ_API_KEY_{i}'))

    if not found:
        try:
            import groq_config  # type: ignore[import-not-found]

            if getattr(groq_config, 'GROQ_ENABLED', True):
                _add(getattr(groq_config, 'GROQ_API_KEY', None))
                _add(getattr(groq_config, 'GROQ_API_KEYS', None))
        except ImportError:
            pass
    return found


def api_key() -> Optional[str]:
    """Pierwszy dostępny klucz Groq.

    Zachowane dla zgodności — wywołania, które chcą jednego klucza, dostają
    ten sam co dotąd. Rotację po wszystkich kluczach robi :func:`chat`.
    """
    keys = api_keys()
    return keys[0] if keys else None


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
            and m.get('id') not in RETIRED_MODELS
            and not is_non_chat_model(m.get('id'))]


def is_non_chat_model(model_id: Optional[str]) -> bool:
    """True dla modeli, które nie odpowiadają na czat (klasyfikatory, audio)."""
    if not model_id:
        return True
    lowered = model_id.lower()
    return any(marker in lowered for marker in NON_CHAT_MODEL_MARKERS)


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
    return [m for m in ordered
            if m and m not in RETIRED_MODELS and not is_non_chat_model(m)]


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

    global _key_cursor

    # Jawnie podany klucz = używamy tylko jego (wywołujący wie, co robi).
    # Bez niego bierzemy wszystkie skonfigurowane i rotujemy po nich.
    if key is not None:
        keys = [key] if key else []
    else:
        keys = api_keys()
    if not keys:
        log("      ⚠️ Groq: brak GROQ_API_KEY")
        return None

    if timeout is None:
        timeout = REQUEST_TIMEOUT

    # Listę modeli ustalamy RAZ, pierwszym działającym kluczem, i używamy dla
    # wszystkich. Odpytywanie /models osobno dla każdego klucza to dodatkowe
    # żądania, a konta darmowe widzą ten sam zestaw modeli.
    candidates = model_candidates(keys[0])
    if not candidates:
        return None

    tried_reset = False
    # Start od kursora: jeśli klucz #1 już się wyczerpał w tym procesie, nie ma
    # sensu znów o niego pytać. Pełne kółko, żeby żadnego nie pominąć.
    order = [keys[(_key_cursor + i) % len(keys)] for i in range(len(keys))]

    for key_no, current in enumerate(order, 1):
        rate_limited_all = True
        for model in candidates:
            try:
                resp = requests.post(
                    CHAT_ENDPOINT,
                    headers={'Authorization': f'Bearer {current}',
                             'Content-Type': 'application/json'},
                    json={'model': model,
                          'messages': [{'role': 'user', 'content': prompt}],
                          'temperature': temperature,
                          'max_tokens': max_tokens},
                    timeout=timeout,
                )
            except Exception as e:
                log(f"      ⚠️ Groq [{model}]: {type(e).__name__}: {e}")
                rate_limited_all = False
                continue

            if resp.status_code == 200:
                try:
                    out = resp.json()['choices'][0]['message']['content']
                    # Zapamiętaj klucz, który zadziałał, żeby następne
                    # wywołanie zaczęło od niego, a nie od wyczerpanego.
                    _key_cursor = keys.index(current)
                    return out.strip()
                except Exception as e:
                    log(f"      ⚠️ Groq [{model}]: zła odpowiedź "
                        f"({type(e).__name__})")
                    rate_limited_all = False
                    continue

            if is_rate_limited(resp.status_code):
                suffix = (f" [klucz {key_no}/{len(order)}]"
                          if len(order) > 1 else "")
                log(f"      ⚠️ Groq [{model}]{suffix}: limit (429) — "
                    f"próbuję kolejnego modelu")
                continue

            rate_limited_all = False

            if (is_decommissioned_error(resp.status_code, resp.text)
                    and not tried_reset):
                tried_reset = True
                reset_resolved_model()
                resolve_model(current, force=True)
                log(f"      ⚠️ Groq [{model}]: model wycofany — odświeżam listę")
                continue

            log(f"      ⚠️ Groq [{model}]: HTTP {resp.status_code} "
                f"{(resp.text or '')[:100]}")

        # Wszystkie modele tego klucza na limicie — przesuń kursor, żeby
        # kolejne wywołania nie zaczynały od niego, i spróbuj następnego.
        if rate_limited_all and len(order) > 1:
            _key_cursor = (keys.index(current) + 1) % len(keys)
            if key_no < len(order):
                log(f"      ↻ Groq: klucz {key_no} wyczerpany na wszystkich "
                    f"{len(candidates)} modelach — przechodzę na klucz "
                    f"{key_no + 1}/{len(order)}")

    if len(order) > 1:
        log(f"      ⛔ Groq: {len(order)} kluczy × {len(candidates)} modeli — "
            f"nic nie odpowiedziało")
    else:
        log(f"      ⛔ Groq: żaden z {len(candidates)} modeli nie odpowiedział")
    return None
