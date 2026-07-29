"""
OddsSafari daily coupon — odds source for sports the other feeds miss
=====================================================================

Why this exists: baseball had **no odds at all** — 0% across 5 978 scraped
matches — so its EV/edge could never be computed and every pick fell back to
the model's own probability. SofaScore does not expose baseball odds
(``/sport/baseball/scheduled-events`` returns nothing and
``get_odds_via_api`` answers None for MLB events), and OddsSafari's
dropping-odds page only lists *price movements*, not the full card.

The coupon page does carry the full card. It is server-rendered and embeds the
exact JSON its own frontend consumes, under
``__NEXT_DATA__.props.pageProps.fallback['/api/coupons?...']``::

    coupons.EventsGroupDate["1"].Events[] -> {
        EventID, EventName, EventDate,
        EventParticipant1_Name, EventParticipant2_Name,
        Bets: [{Outcome: "1"|"X"|"2", Quote: 1.886, NumOfBookmakers: 13}],
    }

Verified live on 2026-07-27: 42 baseball events, MLB priced by 13 bookmakers.

Usage
-----
    from oddssafari_coupons import fetch_coupon_odds, attach_odds_to_rows

    odds = fetch_coupon_odds('baseball', '2026-07-27')
    attach_odds_to_rows(rows, sport='baseball', date='2026-07-27')
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from oddssafari_dropping_scraper import (SPORT_TO_PAGE_IDS,
                                        discover_sport_page_ids,
                                        fetch_dropping_odds_html)

logger = logging.getLogger(__name__)

ROOT = 'https://www.oddssafari.com'
COUPON_PATH = '{root}/coupons/full/sports/{sport_id}'
_NEXT_DATA_RE = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

# Minimum name similarity before we accept a coupon event as the same fixture.
_MIN_SIMILARITY = 0.55


@dataclass
class CouponOdds:
    """Odds for one fixture from the daily coupon."""

    home_team: str
    away_team: str
    event_date: str = ''
    event_time: str = ''
    league: str = ''
    home_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    away_odds: Optional[float] = None
    bookmakers: int = 0
    event_id: Optional[int] = None
    match_url: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'home_team': self.home_team,
            'away_team': self.away_team,
            'event_date': self.event_date,
            'event_time': self.event_time,
            'league': self.league,
            'home_odds': self.home_odds,
            'draw_odds': self.draw_odds,
            'away_odds': self.away_odds,
            'bookmakers': self.bookmakers,
            'event_id': self.event_id,
            'match_url': self.match_url,
        }


# ---------------------------------------------------------------------------
# Parsing (pure — no network)
# ---------------------------------------------------------------------------

def _quote(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    # A quote of 1.0 or below cannot be a real decimal price.
    return num if num > 1.0 else None


def parse_coupon_payload(payload: Dict[str, Any]) -> List[CouponOdds]:
    """Turn the ``/api/coupons`` payload into odds rows."""
    out: List[CouponOdds] = []
    coupons = (payload or {}).get('coupons') or {}
    groups = coupons.get('EventsGroupDate') or {}
    if not isinstance(groups, dict):
        return out

    for group in groups.values():
        if not isinstance(group, dict):
            continue
        league = str(group.get('LeagueNameShow') or group.get('LeagueName') or '')
        league_url = ((group.get('LeagueUrls') or {}).get('en') or '')

        for event in group.get('Events') or []:
            if not isinstance(event, dict):
                continue
            home = str(event.get('EventParticipant1_Name') or '').strip()
            away = str(event.get('EventParticipant2_Name') or '').strip()
            if not home or not away:
                # Fall back to splitting "A - B".
                name = str(event.get('EventName') or '')
                if ' - ' in name:
                    home, away = (p.strip() for p in name.split(' - ', 1))
            if not home or not away:
                continue

            raw_date = str(event.get('EventDate') or '')
            date_part, _, time_part = raw_date.partition(' ')

            odds: Dict[str, Optional[float]] = {'1': None, 'X': None, '2': None}
            bookmakers = 0
            for bet in event.get('Bets') or []:
                if not isinstance(bet, dict):
                    continue
                outcome = str(bet.get('Outcome') or bet.get('OutcomeAA') or '').strip().upper()
                if outcome in odds:
                    odds[outcome] = _quote(bet.get('Quote'))
                    bookmakers = max(bookmakers, int(bet.get('NumOfBookmakers') or 0))

            url = (event.get('EventUrls') or {}).get('en') or ''
            out.append(CouponOdds(
                home_team=home,
                away_team=away,
                event_date=date_part,
                event_time=time_part[:5],
                league=league or league_url,
                home_odds=odds['1'],
                draw_odds=odds['X'],
                away_odds=odds['2'],
                bookmakers=bookmakers,
                event_id=event.get('EventID'),
                match_url=(ROOT + url) if url else '',
            ))

    return out


def extract_payload_from_html(html: str) -> Dict[str, Any]:
    """Pull the embedded ``/api/coupons`` payload out of a coupon page.

    The page ships the data its frontend would fetch, so no second request and
    no browser are needed.
    """
    match = _NEXT_DATA_RE.search(html or '')
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except (ValueError, TypeError):
        return {}

    fallback = (data.get('props', {})
                    .get('pageProps', {})
                    .get('fallback', {}))
    if not isinstance(fallback, dict):
        return {}
    for key, payload in fallback.items():
        if '/api/coupons' in str(key) and isinstance(payload, dict):
            return payload
    return {}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_coupon_odds(sport: str, date: Optional[str] = None,
                      sport_id: Optional[str] = None) -> List[CouponOdds]:
    """Fetch the daily coupon odds for *sport*.

    *date* is accepted for symmetry and logging; the coupon page serves the
    current card, so rows carry their own ``event_date`` for the caller to
    filter on.
    """
    ids: List[str] = [sport_id] if sport_id else list(
        SPORT_TO_PAGE_IDS.get((sport or '').lower(), ()))
    if not ids:
        ids = discover_sport_page_ids(sport)
    if not ids:
        logger.info("OddsSafari coupon: no page id for sport '%s'", sport)
        return []

    rows: List[CouponOdds] = []
    seen: set = set()
    for sid in ids:
        html = fetch_dropping_odds_html(
            COUPON_PATH.format(root=ROOT, sport_id=sid))
        if not html or '404 | OddsSafari' in html[:4000]:
            continue
        payload = extract_payload_from_html(html)
        for row in parse_coupon_payload(payload):
            key = (row.home_team.lower(), row.away_team.lower(), row.event_date)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    if date:
        dated = [r for r in rows if not r.event_date or r.event_date == date]
        if dated:
            rows = dated

    logger.info("OddsSafari coupon %s: %d priced fixtures", sport, len(rows))
    return rows


# ---------------------------------------------------------------------------
# Matching onto pipeline rows
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    text = (name or '').lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Drop common club/franchise noise words that differ between sources.
    stop = {'fc', 'sc', 'cf', 'ac', 'the'}
    return ' '.join(w for w in text.split() if w not in stop)


def _similarity(a: str, b: str) -> float:
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Reward token overlap: "DET Tigers" vs "Detroit Tigers" shares "tigers".
    tokens_a, tokens_b = set(na.split()), set(nb.split())
    if tokens_a & tokens_b:
        overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
        ratio = max(ratio, overlap)
    return ratio


def find_coupon_match(home: str, away: str, coupon: List[CouponOdds],
                      min_similarity: float = _MIN_SIMILARITY,
                      ) -> Optional[CouponOdds]:
    """Best coupon entry for a fixture, or None when nothing matches well."""
    best: Optional[CouponOdds] = None
    best_score = 0.0
    for row in coupon:
        score = (_similarity(home, row.home_team)
                 + _similarity(away, row.away_team)) / 2.0
        if score > best_score:
            best_score, best = score, row
    return best if best_score >= min_similarity else None


def attach_odds_to_rows(rows: List[Dict[str, Any]], sport: str,
                        date: Optional[str] = None,
                        overwrite: bool = False) -> int:
    """Fill missing ``home_odds``/``away_odds`` on *rows* from the coupon.

    Only fills gaps by default — an existing price from a dedicated scraper is
    left alone. Returns how many rows were enriched.
    """
    targets = [r for r in rows
               if overwrite or not (r.get('home_odds') and r.get('away_odds'))]
    if not targets:
        return 0

    coupon = fetch_coupon_odds(sport, date)
    if not coupon:
        return 0

    filled = 0
    for row in targets:
        found = find_coupon_match(row.get('home_team', ''),
                                  row.get('away_team', ''), coupon)
        if not found or not (found.home_odds and found.away_odds):
            continue
        row['home_odds'] = found.home_odds
        row['away_odds'] = found.away_odds
        if found.draw_odds:
            row['draw_odds'] = found.draw_odds
        row['odds_source'] = 'oddssafari_coupon'
        row['odds_bookmaker'] = f'OddsSafari ({found.bookmakers} B)'
        filled += 1

    logger.info("OddsSafari coupon: filled odds on %d/%d rows",
                filled, len(targets))
    return filled


__all__ = [
    'CouponOdds',
    'attach_odds_to_rows',
    'extract_payload_from_html',
    'fetch_coupon_odds',
    'find_coupon_match',
    'parse_coupon_payload',
]
