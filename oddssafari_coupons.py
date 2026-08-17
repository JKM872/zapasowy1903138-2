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
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Iterator, List, Optional
from zoneinfo import ZoneInfo

import requests

from oddssafari_dropping_scraper import (SPORT_TO_PAGE_IDS,
                                        discover_sport_page_ids,
                                        fetch_dropping_odds_html)

logger = logging.getLogger(__name__)

ROOT = 'https://www.oddssafari.com'
COUPON_PATH = '{root}/coupons/full/sports/{sport_id}'
_NEXT_DATA_RE = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

# The JSON endpoint the coupon page itself calls. Hitting it directly is both
# cheaper and *more complete* than scraping the server-rendered page: verified
# 2026-08-17 for football, the SSR page embedded 23 fixtures while the API
# returned 147 for the same card. ``DateFromDatepicker`` walks the calendar, so
# tomorrow's card is reachable — the SSR page only ever serves "now".
#
# Careful with ``SportID``: it selects the *market list*, but the events that
# come back are chosen by ``MarketTypeID``/``ScopeID`` alone. Asking for
# SportID=20 (basketball) while leaving football's 101/103 market in the query
# returns the **football** card — a silent, plausible-looking mix-up.
# :func:`discover_coupon_market` resolves the right pair per sport, and
# :func:`fetch_coupon_board` additionally verifies the sport of every row.
COUPON_API = (
    '{root}/api/coupons?CouponType=Full&SportID={sport_id}'
    '&MarketTypeID={market_type}&ScopeID={scope}&ParamID=0&OutcomeID=0'
    '&DateFromDatepicker={date}&SortColumn=Time&Lang=en'
)

# Moneyline market (1-X-2 or Winner) per sport, used when discovery fails —
# e.g. a sport that is completely out of season serves no market list at all.
# Observed live 2026-08-17; the first entry of the API's own ``marketTypes`` is
# always the moneyline, which is what discovery reads.
MONEYLINE_MARKET: Dict[str, tuple] = {
    'football': (101, 103),
    'basketball': (201, 204),
    'tennis': (301, 301),
    'hockey': (401, 404),
    'handball': (601, 603),
    'volleyball': (701, 703),
    'baseball': (901, 902),
    'esports': (1201, 1201),
    'rugby': (1301, 1303),
    # Coupon-only sports (no form source, odds still useful).
    'american-football': (501, 504),
    'darts': (1001, 1001),
    'cricket': (1601, 1601),
    'mma': (1701, 1701),
    'boxing': (1801, 1801),
}

# Probe pair used only to ask the API which markets a sport offers.
_MARKET_PROBE = (101, 103)

# Every sport the coupon menu carries, read from ``sportsMenu`` on 2026-08-17
# (14 sports; note there is no volleyball and no table tennis). This is wider
# than SPORT_TO_PAGE_IDS in the dropping scraper, which only lists the sports
# with a form source — the coupon prices darts and boxing too, and those prices
# are still worth reading.
COUPON_SPORT_IDS: Dict[str, tuple] = {
    'football': ('10',),
    'basketball': ('20',),
    'tennis': ('30',),
    'hockey': ('40',),
    'american-football': ('50',),
    'handball': ('60',),
    'volleyball': ('70',),
    'baseball': ('90',),
    'darts': ('100',),
    'esports': ('120',),
    'rugby': ('130', '140'),
    'cricket': ('160',),
    'mma': ('170',),
    'boxing': ('180',),
}

# OddsSafari stamps ``EventDate`` in UTC, not local time. Established
# 2026-08-17: at 20:17 UTC (22:17 Europe/Warsaw) the earliest fixture on the
# card was "2026-08-17 21:00:00". The coupon only lists fixtures that have not
# started, so 21:00 has to be in the future — true in UTC, false in Warsaw.
SITE_TZ = ZoneInfo('UTC')

_API_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/125.0 Safari/537.36'
    ),
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': ROOT + '/coupons/full/sports/10',
}

_HTTP_TIMEOUT_S = 30

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
    # Kickoff as served by the site (UTC, "YYYY-MM-DD HH:MM:SS"). Kept raw so
    # the caller decides the display timezone.
    kickoff: str = ''
    # How many bookmakers price each individual outcome. The per-outcome count
    # can differ from :attr:`bookmakers` (which is the max across outcomes),
    # and a thinly-priced outcome is a weaker signal than a fully-priced one.
    bookmakers_by_outcome: Dict[str, int] = field(default_factory=dict)
    sport: str = ''

    def kickoff_dt(self) -> Optional[datetime]:
        """Kickoff as a timezone-aware datetime, or None when unparseable."""
        return _parse_site_datetime(self.kickoff or
                                    f'{self.event_date} {self.event_time}')

    def odds_for(self, outcome: str) -> Optional[float]:
        """Price for outcome ``'1'``, ``'X'`` or ``'2'``."""
        return {'1': self.home_odds,
                'X': self.draw_odds,
                '2': self.away_odds}.get((outcome or '').upper())

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
            'kickoff': self.kickoff,
            'bookmakers_by_outcome': dict(self.bookmakers_by_outcome),
            'sport': self.sport,
        }


def _parse_site_datetime(raw: str) -> Optional[datetime]:
    """Parse an OddsSafari timestamp into an aware UTC datetime."""
    text = (raw or '').strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=SITE_TZ)
        except ValueError:
            continue
    return None


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


def _iter_event_groups(payload: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield league groups from a coupon payload, whatever shape it arrived in.

    ``EventsGroupDate`` is a dict keyed by group number when there are fixtures
    and a plain (usually empty) list when the requested day is exhausted —
    observed live on 2026-08-17. Handling both keeps a quiet card from raising.
    """
    coupons = (payload or {}).get('coupons') or {}
    if not isinstance(coupons, dict):
        return
    groups = coupons.get('EventsGroupDate') or {}
    if isinstance(groups, dict):
        candidates: Iterable[Any] = groups.values()
    elif isinstance(groups, list):
        candidates = groups
    else:
        return
    for group in candidates:
        if isinstance(group, dict):
            yield group


def parse_coupon_payload(payload: Dict[str, Any]) -> List[CouponOdds]:
    """Turn the ``/api/coupons`` payload into odds rows."""
    out: List[CouponOdds] = []

    for group in _iter_event_groups(payload):
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
            per_outcome: Dict[str, int] = {}
            bookmakers = 0
            for bet in event.get('Bets') or []:
                if not isinstance(bet, dict):
                    continue
                outcome = str(bet.get('Outcome') or bet.get('OutcomeAA') or '').strip().upper()
                if outcome in odds:
                    odds[outcome] = _quote(bet.get('Quote'))
                    count = int(bet.get('NumOfBookmakers') or 0)
                    per_outcome[outcome] = count
                    bookmakers = max(bookmakers, count)

            # The event carries its own count too; trust the larger of the two so
            # a missing per-bet field cannot zero out the consensus signal.
            bookmakers = max(bookmakers, int(event.get('NumOfBookmakers') or 0))

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
                kickoff=raw_date,
                bookmakers_by_outcome=per_outcome,
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


def sport_page_ids(sport: str, sport_id: Optional[str] = None) -> List[str]:
    """OddsSafari sport IDs for *sport*, discovered by content when unknown."""
    if sport_id:
        return [str(sport_id)]
    key = (sport or '').lower()
    ids = [str(s) for s in SPORT_TO_PAGE_IDS.get(key, ())]
    if not ids:
        ids = [str(s) for s in COUPON_SPORT_IDS.get(key, ())]
    # Content discovery is a 20-request scan, so it stays the last resort.
    return ids or list(discover_sport_page_ids(sport))


def fetch_coupon_payload_api(sport_id: str, date: str,
                             market: Optional[tuple] = None,
                             session: Optional[requests.Session] = None,
                             ) -> Dict[str, Any]:
    """Fetch one coupon payload straight from the JSON endpoint.

    *market* is the ``(MarketTypeID, ScopeID)`` pair identifying the moneyline
    market for the sport. Returns ``{}`` on any failure so the caller can fall
    back to the server-rendered page instead of aborting the run.
    """
    market_type, scope = market or _MARKET_PROBE
    url = COUPON_API.format(root=ROOT, sport_id=sport_id, date=date,
                            market_type=market_type, scope=scope)
    try:
        getter = session.get if session is not None else requests.get
        response = getter(url, headers=_API_HEADERS, timeout=_HTTP_TIMEOUT_S)
    except Exception as exc:
        logger.warning("Coupon API request failed (sport %s, %s): %s",
                       sport_id, date, exc)
        return {}
    if response.status_code != 200:
        logger.info("Coupon API returned HTTP %s (sport %s, %s)",
                    response.status_code, sport_id, date)
        return {}
    try:
        payload = response.json()
    except ValueError:
        logger.warning("Coupon API returned non-JSON (sport %s, %s)",
                       sport_id, date)
        return {}
    return payload if isinstance(payload, dict) else {}


def discover_coupon_market(sport_id: str, date: str,
                           session: Optional[requests.Session] = None,
                           ) -> Optional[tuple]:
    """Resolve the ``(MarketTypeID, ScopeID)`` moneyline pair for a sport.

    The API answers every request with the market list belonging to the
    requested ``SportID``, and its first entry is the moneyline (``1-X-2`` for
    football/hockey/handball, ``Winner`` for basketball/tennis/baseball). Read
    it rather than hardcoding, so a renumbering on the site cannot silently
    hand us another sport's card.
    """
    payload = fetch_coupon_payload_api(sport_id, date, market=_MARKET_PROBE,
                                       session=session)
    markets = payload.get('marketTypes') if isinstance(payload, dict) else None
    if not isinstance(markets, list):
        return None
    for entry in markets:
        if not isinstance(entry, dict):
            continue
        market_type, scope = entry.get('MarketTypeID'), entry.get('ScopeID')
        if market_type is None or scope is None:
            continue
        logger.debug("Coupon market for sport %s: %s/%s (%s)", sport_id,
                     market_type, scope, entry.get('MarketTypeFullName'))
        return (market_type, scope)
    return None


def _event_sport_slug(match_url: str) -> str:
    """The sport slug from a coupon event URL (``/soccer/argentina/...``)."""
    path = (match_url or '').replace(ROOT, '', 1).lstrip('/')
    return path.split('/', 1)[0].lower() if path else ''


def _belongs_to_sport(row: CouponOdds, sport: str) -> bool:
    """Guard against the API serving another sport's card.

    Rows without a usable URL are kept — the slug is a cross-check, not the
    primary source of truth.
    """
    from oddssafari_dropping_scraper import map_slug_to_internal

    slug = _event_sport_slug(row.match_url)
    if not slug:
        return True
    mapped = map_slug_to_internal(slug)
    return mapped is None or mapped == (sport or '').lower()


def coupon_dates(days: int = 2, now: Optional[datetime] = None) -> List[str]:
    """The ``DateFromDatepicker`` values covering *days* of the calendar."""
    start = (now or datetime.now(SITE_TZ)).astimezone(SITE_TZ)
    return [(start + timedelta(days=offset)).strftime('%Y-%m-%d')
            for offset in range(max(1, days))]


def fetch_coupon_board(sport: str, dates: Optional[List[str]] = None,
                       sport_id: Optional[str] = None,
                       days: int = 2,
                       session: Optional[requests.Session] = None,
                       ) -> List[CouponOdds]:
    """Full 1-X-2 card for *sport* across *dates*, deduplicated by event.

    Prefers the JSON endpoint (complete, date-addressable) and falls back to the
    server-rendered coupon page when the API is unreachable, so a change on
    OddsSafari's side degrades the card rather than emptying it.
    """
    ids = sport_page_ids(sport, sport_id)
    if not ids:
        logger.info("OddsSafari coupon: no page id for sport '%s'", sport)
        return []

    wanted = dates or coupon_dates(days)
    owned = session is None
    session = session or requests.Session()

    rows: List[CouponOdds] = []
    seen: set = set()
    api_worked = False
    wrong_sport = 0

    def _keep(row: CouponOdds) -> None:
        nonlocal wrong_sport
        if not _belongs_to_sport(row, sport):
            wrong_sport += 1
            return
        key = row.event_id or (row.home_team.lower(),
                               row.away_team.lower(), row.kickoff)
        if key in seen:
            return
        seen.add(key)
        row.sport = sport
        rows.append(row)

    try:
        for sid in ids:
            market = (discover_coupon_market(sid, wanted[0], session=session)
                      or MONEYLINE_MARKET.get((sport or '').lower()))
            if market is None:
                logger.info("No coupon market resolved for sport '%s' (id %s)",
                            sport, sid)
                continue
            for date in wanted:
                payload = fetch_coupon_payload_api(sid, date, market=market,
                                                   session=session)
                if not payload:
                    continue
                parsed = parse_coupon_payload(payload)
                api_worked = api_worked or bool(parsed)
                for row in parsed:
                    _keep(row)
    finally:
        if owned:
            session.close()

    if not api_worked:
        logger.warning("Coupon API yielded nothing for %s — falling back to "
                       "the server-rendered page", sport)
        # Pass the already-resolved ids through: fetch_coupon_odds does its own
        # lookup against SPORT_TO_PAGE_IDS, which does not know the coupon-only
        # sports (am. football, darts, cricket, mma, boxing).
        for sid in ids:
            for row in fetch_coupon_odds(sport, sport_id=sid):
                _keep(row)

    if wrong_sport:
        logger.warning("Dropped %d coupon rows that did not belong to '%s'",
                       wrong_sport, sport)

    rows.sort(key=lambda r: r.kickoff or '')
    logger.info("OddsSafari coupon board %s: %d fixtures across %s",
                sport, len(rows), ', '.join(wanted))
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
    'MONEYLINE_MARKET',
    'SITE_TZ',
    'attach_odds_to_rows',
    'coupon_dates',
    'discover_coupon_market',
    'extract_payload_from_html',
    'fetch_coupon_board',
    'fetch_coupon_odds',
    'fetch_coupon_payload_api',
    'find_coupon_match',
    'parse_coupon_payload',
    'sport_page_ids',
]
