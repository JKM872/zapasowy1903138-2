"""Settle mailed picks by name, not by position
===============================================

Two faults made every match in the 2026-07-28 report come back ``PENDING``
(136 of 136), which left the accuracy report a list of fixtures with no
outcomes and the backtest with no history to learn from.

**Fault 1 — one parser for several sites.** ``check_results.scrape_match_result``
drives a browser to ``match_url`` and reads Flashscore/Livesport markup
(``detailScore__status``, ``detailScore__wrapper``). That day's manifest held
102 AiScore URLs and 34 Livesport ones, so for three quarters of the card the
selectors could not exist and the scraper answered ``no_score`` — indistinguishable
from "match still running".

**Fault 2 — the orientation is not trustworthy.** The manifest stores
``home_team``/``away_team`` in an order that does not always agree with the URL::

    manifest: Phoenix Fuelmasters (home) vs Blackwater Bossing (away)
    url:      .../blackwater-bossing-bT29COrg/phoenix-fuelmasters-jm3F6d0I/

Settling a pick of "home" against a scraped ``winner='home'`` therefore risks
crediting the wrong side — silently, and in both directions. So this module
never compares positions. It resolves **which name won** and compares that with
**the name we picked**. Orientation stops mattering.

The resolver asks SofaScore's API (no browser: the report has to run in CI in
minutes, and AiScore/Livesport both fight automation), walking a player's
``events/last`` feed and requiring the event's own date to match the fixture
date — table-tennis players meet several times a week, so date-blind matching
would settle a pick against the wrong meeting.

Usage
-----
    from result_resolver import settle_match

    outcome = settle_match(manifest_row)   # 'won' | 'lost' | 'draw' | 'pending'
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Sport as written in our manifests -> SofaScore's slug.
SPORT_SLUGS: Dict[str, str] = {
    'football': 'football',
    'basketball': 'basketball',
    'tennis': 'tennis',
    'table_tennis': 'table-tennis',
    'baseball': 'baseball',
    'handball': 'handball',
    'volleyball': 'volleyball',
    'hockey': 'ice-hockey',
    'ice_hockey': 'ice-hockey',
    'esports': 'esports',
    'rugby': 'rugby',
}

# Sports where a level score is a real outcome rather than an unfinished match.
DRAW_SPORTS = {'football', 'handball', 'hockey', 'ice-hockey', 'rugby'}

# Statuses that mean the fixture will never produce a result. Without this a
# called-off match sits at PENDING forever: Michelsen vs Draper on 2026-07-28
# was cancelled, and no amount of re-checking will settle it.
VOID_STATUSES = {'canceled', 'cancelled', 'postponed', 'interrupted',
                 'suspended', 'willcontinue', 'delayed'}

_MIN_NAME_SIMILARITY = 0.55


# ---------------------------------------------------------------------------
# Name handling
# ---------------------------------------------------------------------------

def normalise_name(name: Optional[str]) -> str:
    """Strip the decoration that differs between our sources.

    Handles ``'Kurek, Pawel'`` vs ``'Pawel Kurek'`` (comma-swapped), country
    tags like ``'Tigre (ARG)'`` and initials like ``'Michelsen A.'``.
    """
    text = (name or '').strip().lower()
    text = re.sub(r'\([^)]*\)', ' ', text)          # drop "(ARG)", "(NED)"
    text = re.sub(r'[^a-z0-9\s,]', ' ', text)
    if ',' in text:                                  # "kurek, pawel" -> "pawel kurek"
        parts = [p.strip() for p in text.split(',', 1)]
        if all(parts):
            text = f'{parts[1]} {parts[0]}'
    return ' '.join(text.split())


def name_similarity(a: str, b: str) -> float:
    """How confident we are that two strings name the same competitor.

    Surnames carry the signal: our feeds abbreviate given names
    (``'Michelsen A.'`` vs ``'Alex Michelsen'``), so a shared token counts for
    more than raw character overlap.
    """
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    tokens_a = {t for t in na.split() if len(t) > 2}
    tokens_b = {t for t in nb.split() if len(t) > 2}
    if tokens_a & tokens_b:
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
        ratio = max(ratio, overlap)
    return ratio


def same_competitor(a: str, b: str,
                    min_similarity: float = _MIN_NAME_SIMILARITY) -> bool:
    return name_similarity(a, b) >= min_similarity


# ---------------------------------------------------------------------------
# What we picked
# ---------------------------------------------------------------------------

def predicted_winner_name(match: Dict[str, Any]) -> Optional[str]:
    """The name of the competitor our pipeline backed.

    Reads the pick in whichever vocabulary the sport used — ``'1'``/``'2'`` for
    team sports, ``'A'``/``'B'`` for tennis and table tennis, ``focus_team``
    otherwise — and resolves it to a name via this row's own team fields, so a
    flipped orientation cannot change who we are credited with picking.
    """
    home = match.get('home_team') or ''
    away = match.get('away_team') or ''
    if not home or not away:
        return None

    pick = str(match.get('scoring_pick') or '').strip().upper()
    if pick in ('1', 'A', '1.0', 'HOME'):
        return home
    if pick in ('2', 'B', '2.0', 'AWAY'):
        return away
    if pick == 'X':
        return None                                  # a draw pick backs nobody

    favourite = str(match.get('favorite') or '').strip().upper()
    if favourite in ('A', 'HOME', '1'):
        return home
    if favourite in ('B', 'AWAY', '2'):
        return away

    return away if str(match.get('focus_team') or '').lower() == 'away' else home


def picked_the_draw(match: Dict[str, Any]) -> bool:
    return str(match.get('scoring_pick') or '').strip().upper() == 'X'


# ---------------------------------------------------------------------------
# What actually happened
# ---------------------------------------------------------------------------

def _event_date(event: Dict[str, Any]) -> Optional[str]:
    ts = event.get('startTimestamp')
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError):
        return None


def _outcome_from_event(event: Dict[str, Any], sport: str) -> Optional[Dict[str, Any]]:
    """Turn a SofaScore event payload into a settled or void result, or None."""
    status = ((event.get('status') or {}).get('type') or '').lower()

    if status in VOID_STATUSES:
        return {
            'status': 'void',
            'event_status': status,
            'home_name': (event.get('homeTeam') or {}).get('name') or '',
            'away_name': (event.get('awayTeam') or {}).get('name') or '',
            'event_id': event.get('id'),
            'event_date': _event_date(event),
            'source': 'sofascore',
        }

    if status != 'finished':
        return None

    home = (event.get('homeTeam') or {}).get('name') or ''
    away = (event.get('awayTeam') or {}).get('name') or ''
    hs = (event.get('homeScore') or {}).get('current')
    as_ = (event.get('awayScore') or {}).get('current')
    if hs is None or as_ is None or not home or not away:
        return None

    try:
        hs, as_ = int(hs), int(as_)
    except (TypeError, ValueError):
        return None

    if hs == as_:
        # A level score is only an outcome where draws exist. Elsewhere it
        # means the payload is not the final state, so refuse to settle.
        if sport not in DRAW_SPORTS:
            return None
        winner = None
    else:
        winner = home if hs > as_ else away

    return {
        'status': 'finished',
        'home_name': home,
        'away_name': away,
        'score_home': hs,
        'score_away': as_,
        'winner_name': winner,
        # Position in the *source's* orientation, kept only so the result store
        # stays self-consistent with score_home/score_away. Settlement never
        # reads it — that is what winner_name is for.
        'winner': ('draw' if winner is None
                   else ('home' if hs > as_ else 'away')),
        'is_draw': winner is None,
        'event_id': event.get('id'),
        'event_date': _event_date(event),
        'source': 'sofascore',
    }


def resolve_result(home_team: str, away_team: str, sport: str,
                   date: Optional[str] = None,
                   allow_undated: bool = False) -> Optional[Dict[str, Any]]:
    """Find the settled result for one fixture, or None if not settled yet.

    A *date* is mandatory unless the caller explicitly opts out, because
    name-only matching demonstrably settles the wrong game. Searching
    ``'Tigre'`` (Argentina) returns ``'Tigres UANL'`` (Mexico), and walking that
    club's fixtures found ``Tigres FC vs Atlético Nacional`` — Colombian clubs,
    a different continent and a different day — which name similarity alone
    happily accepted. Requiring the fixture's own date is what makes the answer
    trustworthy; a missing settlement is far cheaper than a wrong one.
    """
    if not date and not allow_undated:
        logger.info('result_resolver: refusing to settle %s vs %s without a date',
                    home_team, away_team)
        return None

    try:
        from sofascore_scraper import _api_get_json, find_team_by_name
    except ImportError:
        logger.info('result_resolver: sofascore_scraper unavailable')
        return None

    sport_key = (sport or '').lower()
    slug = SPORT_SLUGS.get(sport_key, sport_key or None)

    for primary, opponent in ((home_team, away_team), (away_team, home_team)):
        if not primary:
            continue
        team = find_team_by_name(primary, slug)
        if not team:
            continue

        data = _api_get_json(
            f"https://api.sofascore.com/api/v1/team/{team['id']}/events/last/0",
            timeout=10)
        if not isinstance(data, dict):
            continue

        for event in reversed(data.get('events') or []):
            ev_home = (event.get('homeTeam') or {})
            ev_away = (event.get('awayTeam') or {})
            # Anchor on the resolved id so a name fluke cannot attach a
            # stranger's fixture to this row.
            if team['id'] == ev_home.get('id'):
                other = ev_away.get('name', '')
            elif team['id'] == ev_away.get('id'):
                other = ev_home.get('name', '')
            else:
                continue
            if not same_competitor(opponent, other):
                continue

            if date:
                ev_date = _event_date(event)
                if ev_date and ev_date != date:
                    continue

            outcome = _outcome_from_event(event, slug or sport_key)
            if outcome:
                return outcome

    return None


# ---------------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------------

def settle_from_result(match: Dict[str, Any],
                       result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare our pick with a resolved result. Pure — no network."""
    detail: Dict[str, Any] = {
        'outcome': 'pending',
        'score': '—',
        'actual': '—',
        'winner_name': None,
    }
    if not result:
        return detail

    if result.get('status') == 'void':
        # Called off, so it never becomes a win or a loss. Kept out of the
        # accuracy denominator instead of sitting at PENDING for good.
        detail['outcome'] = 'void'
        detail['actual'] = result.get('event_status') or 'void'
        detail['resolved_by'] = result.get('source')
        return detail

    if result.get('status') != 'finished':
        return detail

    # Present the score the way this row names the fixture. The resolver's
    # orientation is the source's, and the two disagree often enough that a raw
    # "3-1" next to a lost pick reads like a bug: Jacek Przewlocki vs Marcin
    # Kowalczyk settled correctly as a loss while showing 3-1, because in
    # SofaScore's orientation Kowalczyk was the home player.
    home_score, away_score = result.get('score_home'), result.get('score_away')
    row_home = match.get('home_team') or ''
    if (row_home and result.get('away_name')
            and same_competitor(row_home, result['away_name'])
            and not same_competitor(row_home, result.get('home_name') or '')):
        home_score, away_score = away_score, home_score
        detail['orientation_flipped'] = True

    winner_name = winning_competitor_name(result)

    detail['score'] = f"{home_score}-{away_score}"
    detail['winner_name'] = winner_name
    detail['actual'] = winner_name or 'draw'
    detail['resolved_by'] = result.get('source')

    if result.get('is_draw') or result.get('winner') == 'draw':
        detail['outcome'] = 'won' if picked_the_draw(match) else 'draw'
        return detail

    picked = predicted_winner_name(match)
    if not picked:
        # We backed the draw (or nothing legible) and the match had a winner.
        detail['outcome'] = 'lost' if picked_the_draw(match) else 'pending'
        return detail

    detail['picked_name'] = picked

    if not winner_name:
        # Judging a pick against a missing name silently marks it lost. Better to
        # leave it unsettled than to record a loss we cannot justify.
        detail['outcome'] = 'pending'
        detail['unsettled_reason'] = 'no winner name in result'
        return detail

    detail['outcome'] = 'won' if same_competitor(picked, winner_name) else 'lost'
    return detail


def winning_competitor_name(result: Dict[str, Any]) -> Optional[str]:
    """Name of the competitor who won, or None when it cannot be established.

    Fresh resolver output carries ``winner_name``, but results read back from
    ``outputs/result_store.json`` do not: the store keeps ``winner`` as
    ``'home'``/``'away'`` beside our own team names. Without this fallback the
    pick was compared against a missing name, so **every stored result settled
    as a loss** — Jirasek Martin beat Flesar Milan 3-1, we had backed Jirasek,
    and the report still printed LOST.
    """
    name = result.get('winner_name')
    if name:
        return name

    winner = result.get('winner')
    if winner == 'home':
        return result.get('home_name') or result.get('home_team')
    if winner == 'away':
        return result.get('away_name') or result.get('away_team')
    return None


def settle_match(match: Dict[str, Any],
                 fallback_date: Optional[str] = None) -> Dict[str, Any]:
    """Resolve and settle one manifest row.

    *fallback_date* covers rows whose ``match_date`` never made it into the
    manifest — every table-tennis row on 2026-07-28 had ``None`` there. The
    report's own target date is the right stand-in; without it the resolver
    refuses to settle rather than guess.
    """
    result = resolve_result(
        match.get('home_team') or '',
        match.get('away_team') or '',
        (match.get('sport') or 'football').lower(),
        (match.get('match_date') or '') or fallback_date,
    )
    return settle_from_result(match, result)


__all__ = [
    'DRAW_SPORTS',
    'SPORT_SLUGS',
    'name_similarity',
    'normalise_name',
    'picked_the_draw',
    'predicted_winner_name',
    'resolve_result',
    'same_competitor',
    'settle_from_result',
    'settle_match',
]
