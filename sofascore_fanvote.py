"""
SofaScore Fan Vote — odporny wrapper
====================================
``sofascore_scraper.get_sofascore_prediction()`` działa, ale nie zawsze:
Cloudflare zwraca 403 z IP GitHub Actions, requesty wpadają w timeout, a część
lig po prostu nie ma Fan Vote. Wołane wprost, „raz na mecz”, gubi głosy które
druga próba by dostała, a w logach zostaje goły błąd bez informacji czy to
awaria, czy zdarzenie bez głosowania.

Ten moduł dokłada warstwę, której brakowało:

- **retry z backoffem i jitterem** — pojedyncze 403/timeout nie kończy sprawy
- **rotacja obwodu Tora** między próbami, gdy spalone IP jest przyczyną
- **circuit breaker całego runu** — po serii kompletnych porażek przestajemy
  dobijać SofaScore (i mówimy o tym wprost), zamiast tracić minuty na mecz
- **rozróżnienie „brak Fan Vote” od „nie udało się pobrać”** — pierwsze jest
  normalne i nie jest błędem, drugie trafia do diagnostyki
- **jednolity kontrakt zwrotny**, więc pipeline nie musi zgadywać kluczy

Nie modyfikuje ``sofascore_scraper`` — respektuje jego własny breaker przez
``is_sofascore_unreachable()``.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, Optional

# ── Konfiguracja (env-owalna, żeby workflow mógł przykręcić bez zmian w kodzie) ──
DEFAULT_ATTEMPTS = int(os.getenv('FANVOTE_ATTEMPTS', '3'))
BASE_DELAY = float(os.getenv('FANVOTE_BASE_DELAY', '2.0'))
MAX_DELAY = float(os.getenv('FANVOTE_MAX_DELAY', '20.0'))
# Po tylu meczach z rzędu, w których KAŻDA próba padła technicznie,
# uznajemy SofaScore za niedostępny dla tego runu.
RUN_FAILURE_LIMIT = int(os.getenv('FANVOTE_RUN_FAILURE_LIMIT', '8'))
# Czy próbować rotować Tora między próbami (wymaga ControlPort z setup_tor.sh).
ROTATE_TOR = os.getenv('FANVOTE_ROTATE_TOR', '1') not in {'0', 'false', 'False'}

_consecutive_hard_failures = 0
_disabled_for_run = False
_stats: Dict[str, int] = {
    'calls': 0,
    'found': 0,
    'no_vote': 0,
    'failed': 0,
    'skipped_breaker': 0,
    'retries': 0,
    'tor_rotations': 0,
}


def _backoff(attempt: int) -> float:
    """Exponential backoff z jitterem (attempt liczony od 1)."""
    delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)
    return delay * (0.75 + random.random() * 0.5)


def _empty(reason: str, error: Optional[str] = None,
           attempts_used: int = 0) -> Dict[str, Any]:
    return {
        'sofascore_found': False,
        'sofascore_home_win_prob': None,
        'sofascore_draw_prob': None,
        'sofascore_away_win_prob': None,
        'sofascore_total_votes': 0,
        'sofascore_url': None,
        # `unavailable=True` znaczy „nie udało się pobrać” (awaria/blokada).
        # `unavailable=False` przy found=False znaczy „pobrano, ale to
        # zdarzenie nie ma Fan Vote” — to nie jest błąd.
        'sofascore_unavailable': reason != 'no_vote',
        'sofascore_skip_reason': reason,
        'sofascore_error': error,
        'sofascore_attempts': attempts_used,
    }


def _rotate_tor() -> bool:
    if not ROTATE_TOR:
        return False
    try:
        from sofascore_scraper import _rotate_tor_circuit
    except Exception:
        return False
    try:
        if _rotate_tor_circuit():
            _stats['tor_rotations'] += 1
            # Tor rate-limituje NEWNYM (~10s do realnie nowego obwodu).
            time.sleep(10)
            return True
    except Exception:
        pass
    return False


def is_disabled_for_run() -> bool:
    """Czy Fan Vote został wyłączony na resztę runu."""
    return _disabled_for_run


def get_stats() -> Dict[str, int]:
    """Statystyki do podsumowania runu / step summary."""
    return dict(_stats)


def reset_state() -> None:
    """Zeruj breaker i statystyki (testy, wiele sportów w jednym procesie)."""
    global _consecutive_hard_failures, _disabled_for_run
    _consecutive_hard_failures = 0
    _disabled_for_run = False
    for key in _stats:
        _stats[key] = 0


def get_fan_vote(home_team: str, away_team: str, sport: str = 'football',
                 date_str: Optional[str] = None,
                 attempts: int = DEFAULT_ATTEMPTS) -> Dict[str, Any]:
    """Pobierz Fan Vote dla meczu, z retry i jawnym statusem.

    Args:
        home_team: Nazwa gospodarzy
        away_team: Nazwa gości
        sport: Sport (football, basketball, ...)
        date_str: Data meczu YYYY-MM-DD (zawęża wyszukiwanie eventu)
        attempts: Maks. liczba prób technicznych

    Returns:
        Dict z kluczami ``sofascore_*``: ``sofascore_found``,
        ``sofascore_home_win_prob``, ``sofascore_draw_prob``,
        ``sofascore_away_win_prob``, ``sofascore_total_votes``,
        ``sofascore_unavailable``, ``sofascore_skip_reason``,
        ``sofascore_error``, ``sofascore_attempts``.
    """
    global _consecutive_hard_failures, _disabled_for_run

    _stats['calls'] += 1

    if _disabled_for_run:
        _stats['skipped_breaker'] += 1
        return _empty('breaker_open', 'Fan Vote wyłączony dla tego runu')

    try:
        from sofascore_scraper import get_sofascore_prediction, is_sofascore_unreachable
    except Exception as e:
        _disabled_for_run = True
        return _empty('module_unavailable', f'{type(e).__name__}: {e}')

    # Respektuj breaker samego sofascore_scraper — jego 403-owy licznik wie
    # więcej o stanie API niż my.
    try:
        if is_sofascore_unreachable():
            _stats['skipped_breaker'] += 1
            return _empty('sofascore_unreachable',
                          'sofascore_scraper zgłasza niedostępność dla runu')
    except Exception:
        pass

    last_error: Optional[str] = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            res = get_sofascore_prediction(
                home_team=home_team,
                away_team=away_team,
                sport=sport,
                date_str=date_str,
            ) or {}
        except Exception as e:
            last_error = f'{type(e).__name__}: {e}'
            res = {}

        found = bool(res.get('found') or res.get('sofascore_found'))
        home_prob = res.get('home_win_prob', res.get('sofascore_home_win_prob'))
        votes = res.get('total_votes', res.get('sofascore_total_votes')) or 0

        if found and home_prob is not None:
            _consecutive_hard_failures = 0
            _stats['found'] += 1
            return {
                'sofascore_found': True,
                'sofascore_home_win_prob': home_prob,
                'sofascore_draw_prob': res.get('draw_prob', res.get('sofascore_draw_prob')),
                'sofascore_away_win_prob': res.get('away_win_prob', res.get('sofascore_away_win_prob')),
                'sofascore_total_votes': votes,
                'sofascore_url': res.get('url', res.get('sofascore_url')),
                'sofascore_unavailable': False,
                'sofascore_skip_reason': None,
                'sofascore_error': None,
                'sofascore_attempts': attempt,
            }

        # Odpowiedź przyszła, ale bez głosów i bez wyjątku → liga bez Fan Vote.
        # To stan normalny; ponawianie nic nie da, a kosztuje.
        if not last_error and res:
            _consecutive_hard_failures = 0
            _stats['no_vote'] += 1
            return _empty('no_vote', None, attempt)

        if attempt < attempts:
            _stats['retries'] += 1
            delay = _backoff(attempt)
            print(f"      🔁 Fan Vote retry {attempt}/{attempts - 1} za {delay:.1f}s "
                  f"({last_error or 'brak danych'})")
            # 403 to najczęściej spalone IP runnera — rotacja Tora daje nowe.
            if last_error and '403' in last_error:
                _rotate_tor()
            time.sleep(delay)

    _consecutive_hard_failures += 1
    _stats['failed'] += 1

    if _consecutive_hard_failures >= RUN_FAILURE_LIMIT:
        _disabled_for_run = True
        print(f"   ⛔ Fan Vote: {_consecutive_hard_failures} kompletnych porażek z rzędu "
              f"— wyłączam SofaScore dla reszty runu (ostatni błąd: {last_error})")

    return _empty('fetch_failed', last_error or 'brak danych po wszystkich próbach',
                  attempts)


def print_summary() -> None:
    """Wypisz podsumowanie Fan Vote — czy milczał, i dlaczego."""
    s = get_stats()
    total = s['calls']
    if not total:
        print("   🗳️ Fan Vote: brak wywołań")
        return
    print(f"   🗳️ Fan Vote: {s['found']}/{total} z głosami | "
          f"bez głosowania: {s['no_vote']} | porażki: {s['failed']} | "
          f"pominięte (breaker): {s['skipped_breaker']} | "
          f"retry: {s['retries']} | rotacje Tora: {s['tor_rotations']}")
    if _disabled_for_run:
        print("   ⚠️ Fan Vote został wyłączony w trakcie runu (seria porażek)")
