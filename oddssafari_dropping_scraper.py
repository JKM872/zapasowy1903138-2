"""OddsSafari dropping-odds scraper.

Goal: for every sport listed on https://www.oddssafari.com/dropping-odds and
every row of the dropping-odds table, produce a single structured dictionary
with both the raw OddsSafari fields and a ``qualifies`` flag based on the
current odds range configured by the pipeline (default 1.35 to 2.00).

The dropping-odds table is server-side rendered (Next.js SSR), so a plain
``requests`` GET returns the full markup. That is the primary transport
(:func:`fetch_dropping_odds_html`); Selenium is kept only as a fallback for
the case where the site starts gating the HTML behind JS. OddsSafari is not
behind Cloudflare at the moment.

This module exposes:

* :data:`SPORT_SLUG_TO_INTERNAL` — mapping from the sport slug present in
  match URLs (``/matches/{slug}/...``) to the internal sport name used by
  ``livesport_h2h_scraper`` / ``process_match``.
* :func:`is_livesport_supported_sport` — small helper that tells the
  pipeline whether the costly enrichment phase can be attempted.
* :func:`parse_dropping_odds_table` — pure parser that turns an HTML fragment
  containing the dropping-odds table into a list of row dicts (used in tests
  against a static fixture, without the network). The rendered table only ever
  contains the *current* client-side page, so this is now the fallback.
* :func:`parse_dropping_odds_next_data` — pure parser over the embedded SSR
  payload (``props.pageProps.markets``), which carries **all** rows for the
  sport. OddsSafari paginates in the browser only and ignores ``?page=N``, so
  this is the primary path and removes the old first-page-only cap.
* :func:`collect_dropping_odds_rows` — Selenium-driven top-level entry point
  that iterates every sport tab and returns the full list of raw row dicts.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sport mapping
# ---------------------------------------------------------------------------

# OddsSafari URL slug (from ``/matches/{slug}/...``) → internal sport name
# that the Livesport/Forebet/SofaScore stack uses. Sports without a sensible
# Livesport counterpart map to ``None`` so the pipeline can short-circuit
# with a clear ``skipped_unsupported_sport`` reason.
SPORT_SLUG_TO_INTERNAL: Dict[str, Optional[str]] = {
    "soccer": "football",
    "basketball": "basketball",
    "tennis": "tennis",
    "ice-hockey": "hockey",
    "hockey": "hockey",
    "handball": "handball",
    "volleyball": "volleyball",
    "baseball": "baseball",
    "rugby-union": "rugby",
    "rugby-league": "rugby",
    "rugby": "rugby",
    "e-sports": "esports",
    "esports": "esports",
    # Normalised so the hyphenated form cannot leak through _internal_name as a
    # separate sport. OddsSafari itself carries NO table tennis — its sportsMenu
    # lists 14 sports and table tennis is not among them — so there is nothing to
    # map it to a page id for. Table-tennis prices come from SofaScore.
    "table-tennis": "table_tennis",
    "table_tennis": "table_tennis",
    "american-football": None,
    "am.-football": None,
    "darts": None,
    "snooker": None,
    "cricket": None,
    "mma": None,
    "boxing": None,
}

# Sports enriched through Livesport (H2H + form + Forebet + SofaScore).
_LIVESPORT_SPORTS = {
    "football", "basketball", "volleyball", "handball",
    "hockey", "tennis", "baseball", "rugby",
}

# Sports with no Livesport counterpart that we still enrich, using the
# SofaScore API directly (search event -> H2H + recent form).
_SOFASCORE_ONLY_SPORTS = {"esports"}


def map_slug_to_internal(slug: str) -> Optional[str]:
    """Return the internal sport name for an OddsSafari URL slug.

    Unknown slugs return ``None``. Matching is case-insensitive.
    """
    if not slug:
        return None
    return SPORT_SLUG_TO_INTERNAL.get(slug.strip().lower())


def _internal_name(slug_or_internal: Optional[str]) -> Optional[str]:
    """Normalize either an OddsSafari slug or an internal name to internal."""
    if not slug_or_internal:
        return None
    value = slug_or_internal.strip().lower()
    return SPORT_SLUG_TO_INTERNAL.get(value, value)


def is_livesport_supported_sport(slug_or_internal: Optional[str]) -> bool:
    """Return True when Livesport enrichment can be attempted."""
    return _internal_name(slug_or_internal) in _LIVESPORT_SPORTS


def is_enrichable_sport(slug_or_internal: Optional[str]) -> bool:
    """Return True when *any* enrichment path exists for the sport.

    e-sports has no Livesport section, but SofaScore covers it — so it must
    not be dropped by the qualification gate.
    """
    internal = _internal_name(slug_or_internal)
    return internal in _LIVESPORT_SPORTS or internal in _SOFASCORE_ONLY_SPORTS


def uses_sofascore_only_enrichment(slug_or_internal: Optional[str]) -> bool:
    """True for sports enriched exclusively via the SofaScore API."""
    return _internal_name(slug_or_internal) in _SOFASCORE_ONLY_SPORTS


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------

# Outcome labels as rendered in the OddsSafari table.
OUTCOME_LABELS: Tuple[str, ...] = ("1", "X", "2")


@dataclass
class DroppingOddsRow:
    """One parsed row from the dropping-odds table."""

    league: str
    match_url: str
    match_id: Optional[str]
    sport_slug: str
    sport: Optional[str]
    home_team: str
    away_team: str
    event_date: Optional[str]
    event_time: Optional[str]
    outcome: str
    open_odds: Optional[float]
    current_odds: Optional[float]
    drop_pct: Optional[float]
    max_odds: Optional[float] = None
    sport_page_id: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "league": self.league,
            "match_url": self.match_url,
            "match_id": self.match_id,
            "sport_slug": self.sport_slug,
            "sport": self.sport,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "event_date": self.event_date,
            "event_time": self.event_time,
            "outcome": self.outcome,
            "open_odds": self.open_odds,
            "current_odds": self.current_odds,
            "drop_pct": self.drop_pct,
            "max_odds": self.max_odds,
            "sport_page_id": self.sport_page_id,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# HTML parsing (pure, no network)
# ---------------------------------------------------------------------------

_MATCH_URL_RE = re.compile(
    r"/matches/(?P<slug>[^/]+)/.+/(?P<match_id>\d+)(?:[?#]|$)",
    re.IGNORECASE,
)


def _parse_float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    cleaned = text.strip().replace(",", ".").replace("%", "").replace("+", "")
    if not cleaned or cleaned in {"-", "–", "—"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_percent(text: Optional[str]) -> Optional[float]:
    """Parse the drop-percentage cell, e.g. ``- 21 %`` -> ``21.0``.

    The value is returned as a positive magnitude ("how much the price
    dropped"), matching the ``↓%`` legend used in the email.
    """
    if not text:
        return None
    digits = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(" ", ""))
    if not digits:
        return None
    try:
        return abs(float(digits.group(1).replace(",", ".")))
    except ValueError:
        return None


def _extract_teams_from_link(link_text: str) -> Tuple[str, str]:
    """OddsSafari link text is ``Home-Away`` (hyphen-joined).

    We split on the last hyphen that is not part of a team name prefix by
    relying on the site convention that the hyphen is a dash separator.
    Fall back to whole-string when parsing fails so downstream code can still
    use ``home_team`` (kept in sync with the link).
    """
    if not link_text:
        return "", ""
    text = link_text.strip()
    for sep in (" - ", " vs ", " v "):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    if "-" in text:
        left, right = text.rsplit("-", 1)
        return left.strip(), right.strip()
    return text, ""


def _extract_teams_from_anchor(link: Tag) -> Tuple[str, str]:
    """Prefer the anchor's ``<span>`` structure over hyphen splitting.

    OddsSafari renders ``<span>Home</span><span class="dash">-</span>
    <span>Away</span>``, so reading the spans avoids mangling team names that
    themselves contain a hyphen. Falls back to text splitting.
    """
    spans = [s for s in link.find_all("span", recursive=False)]
    named = [
        s.get_text(" ", strip=True) for s in spans
        if "dash" not in " ".join(s.get("class") or [])
    ]
    named = [n for n in named if n and n != "-"]
    if len(named) >= 2:
        return named[0], named[-1]
    return _extract_teams_from_link(link.get_text(" ", strip=True))


def _parse_match_url(href: str) -> Tuple[str, Optional[str]]:
    match = _MATCH_URL_RE.search(href)
    if not match:
        return "", None
    return match.group("slug").lower(), match.group("match_id")


def _row_cells(row: Tag) -> List[Tag]:
    return [c for c in row.find_all(["td", "th"], recursive=False)]


def parse_dropping_odds_table(
    html: str,
    *,
    base_url: str = "https://www.oddssafari.com",
    sport_page_id: Optional[str] = None,
) -> List[DroppingOddsRow]:
    """Parse the dropping-odds HTML fragment into row objects.

    The table alternates between "league header" rows (single cell, no link)
    and one or more "match" rows (link + outcome + odds). We keep the last
    seen league header as the label for subsequent match rows until the next
    header appears.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[DroppingOddsRow] = []
    current_league = ""

    for tr in soup.find_all("tr"):
        cells = _row_cells(tr)
        if not cells:
            continue

        link = tr.find("a", href=re.compile(r"/matches/"))
        if link is None:
            # League header — usually spans the full width with a single cell.
            text = tr.get_text(" ", strip=True)
            if text:
                current_league = text
            continue

        # Match row. Collect cell texts in order; the rendered layout is
        # [date+time, link (with outcome token inside the same cell or the
        # next one), open, current, drop%]. We read robustly by looking for
        # the outcome token and the three numeric cells around it.
        # Cell layout: [date+event(link), outcome, open, current, drop%, best]
        # The drop% cell renders as ``-<!-- -->21<!-- -->%`` so ``get_text``
        # yields "- 21 %" — a plain float() parse fails on it, which used to
        # push the bookmaker's best odds into ``drop_pct``. We therefore
        # classify each cell explicitly instead of taking "the Nth number".
        outcome = ""
        numeric_values: List[float] = []
        drop_pct: Optional[float] = None
        max_odds: Optional[float] = None

        for cell in cells:
            classes = " ".join(cell.get("class") or [])
            raw = cell.get_text(" ", strip=True)
            stripped = raw.strip()

            # Best current odds column (contains bookmaker link) — not an
            # odds-movement value, keep it separately.
            if "colMaxOdd" in classes:
                max_odds = _parse_float(stripped)
                continue

            if "%" in stripped:
                drop_pct = _parse_percent(stripped)
                continue

            if stripped in OUTCOME_LABELS and not outcome:
                outcome = stripped
                continue

            value = _parse_float(stripped)
            if value is not None:
                numeric_values.append(value)

        if not outcome:
            for cell in cells:
                token = cell.get_text(" ", strip=True).upper()
                if token in OUTCOME_LABELS:
                    outcome = token
                    break

        open_odds = numeric_values[0] if len(numeric_values) >= 1 else None
        current_odds = numeric_values[1] if len(numeric_values) >= 2 else None

        # Fallback: derive the drop from the two odds when the % cell is
        # missing or unparsable, so sorting never silently degrades.
        if drop_pct is None and open_odds and current_odds and open_odds > 0:
            drop_pct = round(abs(current_odds - open_odds) / open_odds * 100, 1)

        href = link.get("href", "")
        match_url = urljoin(base_url, href)
        slug, match_id = _parse_match_url(href)
        home, away = _extract_teams_from_anchor(link)

        event_date, event_time = _extract_event_datetime(tr)

        rows.append(
            DroppingOddsRow(
                league=current_league,
                match_url=match_url,
                match_id=match_id,
                sport_slug=slug,
                sport=map_slug_to_internal(slug),
                home_team=home,
                away_team=away,
                event_date=event_date,
                event_time=event_time,
                outcome=outcome or "",
                open_odds=open_odds,
                current_odds=current_odds,
                drop_pct=drop_pct,
                max_odds=max_odds,
                sport_page_id=sport_page_id,
            )
        )

    return rows


def parse_dropping_odds_next_data(
    html: str,
    *,
    base_url: str = "https://www.oddssafari.com",
    sport_page_id: Optional[str] = None,
) -> List[DroppingOddsRow]:
    """Parse **every** dropping-odds row out of the embedded SSR payload.

    The rendered table is paginated *client side* — OddsSafari ships the whole
    result set in ``__NEXT_DATA__.props.pageProps.markets`` and the ``Page:
    n / m`` control only slices it in the browser. ``?page=N`` is ignored by
    the server (it re-serves page 1), so scraping the table markup caps out at
    the first ~70 rows while the payload holds the full set (300+ for soccer).

    Reading ``markets`` therefore replaces pagination entirely: one request per
    sport returns every row, in the same order the table renders them.
    """
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return []

    try:
        import json

        data = json.loads(match.group(1))
        markets = (
            data.get("props", {}).get("pageProps", {}).get("markets") or []
        )
    except Exception as exc:
        logger.warning("failed to parse __NEXT_DATA__ markets: %s", exc)
        return []

    rows: List[DroppingOddsRow] = []
    for entry in markets:
        if not isinstance(entry, dict):
            continue

        urls = entry.get("EventUrls") or {}
        path = ""
        if isinstance(urls, dict):
            path = urls.get("en") or next(
                (v for v in urls.values() if isinstance(v, str) and v), ""
            )
        if not path:
            continue

        # The table links to /matches + the event path, carrying the market
        # type as a query arg. Rebuilding it identically keeps match_url (and
        # therefore dedup keys and downstream lookups) byte-for-byte stable.
        relative = f"/matches{path}"
        market_type_id = entry.get("MarketTypeID")
        if market_type_id is not None:
            relative = f"{relative}?MarketTypeID={market_type_id}"

        slug, match_id = _parse_match_url(relative)

        event_date: Optional[str] = None
        event_time: Optional[str] = None
        raw_date = entry.get("EventDate")
        if isinstance(raw_date, str) and raw_date.strip():
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = datetime.strptime(raw_date.strip()[:19], fmt)
                except ValueError:
                    continue
                event_date = parsed.strftime("%d/%m")
                event_time = parsed.strftime("%H:%M")
                break

        open_odds = _parse_float(entry.get("OpenQuote"))
        # AvgQuote is the post-drop price the table shows as "current"; MaxQuote
        # is the best bookmaker quote rendered in the colMaxOdd column.
        current_odds = _parse_float(entry.get("AvgQuote"))
        max_odds = _parse_float(entry.get("MaxQuote"))

        drop_pct = _parse_percent(str(entry.get("BetDiffPerc")))
        if drop_pct is None and open_odds and current_odds and open_odds > 0:
            drop_pct = round(abs(current_odds - open_odds) / open_odds * 100, 1)

        outcome = (
            entry.get("OutcomeShortName") or entry.get("OutcomeName") or ""
        )

        rows.append(
            DroppingOddsRow(
                league=(entry.get("LeagueName") or "").strip(),
                match_url=urljoin(base_url, relative),
                match_id=match_id or (
                    str(entry.get("EventID")) if entry.get("EventID") else None
                ),
                sport_slug=slug,
                sport=map_slug_to_internal(slug),
                home_team=(entry.get("EventParticipant1_Name") or "").strip(),
                away_team=(entry.get("EventParticipant2_Name") or "").strip(),
                event_date=event_date,
                event_time=event_time,
                outcome=str(outcome).strip(),
                open_odds=open_odds,
                current_odds=current_odds,
                drop_pct=drop_pct,
                max_odds=max_odds,
                sport_page_id=sport_page_id,
            )
        )

    return rows


_DATE_RE = re.compile(r"^\d{2}/\d{2}$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _extract_event_datetime(row: Tag) -> Tuple[Optional[str], Optional[str]]:
    """Find the ``DD/MM`` and ``HH:MM`` tokens in the row's text."""
    date_val: Optional[str] = None
    time_val: Optional[str] = None
    for token in row.stripped_strings:
        if date_val is None and _DATE_RE.match(token):
            date_val = token
        elif time_val is None and _TIME_RE.match(token):
            time_val = token
        if date_val and time_val:
            break
    return date_val, time_val


# ---------------------------------------------------------------------------
# Per-sport qualifying odds ranges
# ---------------------------------------------------------------------------

# Closed ranges applied to the *current* (dropped) odds. Football demands a
# higher floor because its dropping-odds feed is dominated by heavy favourites.
SPORT_ODDS_RANGE: Dict[str, Tuple[float, float]] = {
    "football": (1.80, 2.50),
    "handball": (1.60, 2.50),
    "hockey": (1.60, 2.50),
    "basketball": (1.35, 2.50),
    "volleyball": (1.35, 2.50),
    "esports": (1.35, 2.50),
    "baseball": (1.35, 2.50),
    "tennis": (1.35, 2.50),
    "rugby": (1.35, 2.50),
}

# Used for any sport without an explicit entry above.
DEFAULT_ODDS_RANGE: Tuple[float, float] = (1.35, 2.50)


def odds_range_for_sport(sport: Optional[str]) -> Tuple[float, float]:
    """Return the (min, max) qualifying odds range for *sport*."""
    internal = _internal_name(sport)
    return SPORT_ODDS_RANGE.get(internal or "", DEFAULT_ODDS_RANGE)


def is_qualifying_row(
    row: DroppingOddsRow,
    *,
    min_odds: Optional[float] = None,
    max_odds: Optional[float] = None,
) -> Tuple[bool, Optional[str]]:
    """Return (qualifies, skip_reason).

    Closed range: ``min_odds <= current_odds <= max_odds``. When the bounds are
    omitted, the per-sport range from :data:`SPORT_ODDS_RANGE` applies, so a
    single run can mix football's 1.80–2.50 with handball's 1.60–2.50.
    """
    if row.current_odds is None:
        return False, "missing_current_odds"

    sport_min, sport_max = odds_range_for_sport(row.sport or row.sport_slug)
    low = sport_min if min_odds is None else min_odds
    high = sport_max if max_odds is None else max_odds

    if row.current_odds < low or row.current_odds > high:
        return False, "odds_out_of_range"
    if not is_enrichable_sport(row.sport_slug):
        return False, "unsupported_sport"
    if not row.home_team or not row.away_team:
        return False, "missing_teams"
    return True, None


# ---------------------------------------------------------------------------
# Selenium-driven collection
# ---------------------------------------------------------------------------

ODDSSAFARI_ROOT = "https://www.oddssafari.com"
DROPPING_ODDS_ROOT = f"{ODDSSAFARI_ROOT}/dropping-odds"

# Fallback sport page IDs discovered from the public navigation. ID 0 is the
# generic "all sports" landing; 1 is Soccer (the default when no ID is given).
# Numbers reflect what the site currently serves; :func:`_discover_sport_ids`
# is used first and falls back to this list only if discovery fails.
FALLBACK_SPORT_PAGE_IDS: Tuple[str, ...] = (
    "10",   # Soccer
    "20",   # Basketball
    "30",   # Tennis
    "40",   # Ice Hockey
    "50",   # Am. Football
    "60",   # Handball
    "70",   # Volleyball
    "90",   # Baseball
    "120",  # E-sports
    "130",  # Rugby Union
    "140",  # Rugby League
    "170",  # MMA
    "180",  # Boxing
)

# Mapping of internal sport name → list of OddsSafari sport page IDs.
# Used by the per-sport pipeline split to scrape only relevant pages
# instead of all sports. When discovery yields different IDs, the scraper
# still falls back to FALLBACK_SPORT_PAGE_IDS.
SPORT_TO_PAGE_IDS: Dict[str, Tuple[str, ...]] = {
    "football": ("10",),
    "basketball": ("20",),
    "tennis": ("30",),
    "hockey": ("40",),
    "handball": ("60",),
    "volleyball": ("70",),
    "baseball": ("90",),
    "esports": ("120",),
    "rugby": ("130", "140"),
}

# Candidate IDs probed by :func:`discover_sport_page_ids`. The site numbers
# sport tabs in steps of 10; IDs without current events return a 404 page, so
# the hardcoded map above cannot be verified for quiet sports (e.g. handball
# out of season). Content-based discovery keeps us correct when IDs shift.
_ID_PROBE_CANDIDATES: Tuple[str, ...] = tuple(
    str(n) for n in range(10, 200, 10)
)

_DEFAULT_PAGE_WAIT_S = 4.0
_MAX_PAGES_PER_SPORT = 20

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_HTTP_TIMEOUT_S = 30


def fetch_dropping_odds_html(
    url: str,
    *,
    session: Optional["requests.Session"] = None,
    timeout: int = _HTTP_TIMEOUT_S,
) -> str:
    """GET *url* and return the HTML, or an empty string on failure.

    The dropping-odds table is server-rendered, so no browser is needed.
    """
    getter = session or requests
    try:
        resp = getter.get(url, headers=_REQUEST_HEADERS, timeout=timeout)
    except Exception as exc:
        logger.warning("HTTP GET failed for %s: %s", url, exc)
        return ""
    if resp.status_code != 200:
        logger.info("HTTP %s for %s", resp.status_code, url)
        return ""
    return resp.text or ""


_NEXT_DATA_RE = re.compile(
    r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)

# OddsSafari sport names (as shown in sportsMenu) → internal sport name.
_MENU_NAME_TO_INTERNAL: Dict[str, str] = {
    "soccer": "football",
    "basketball": "basketball",
    "tennis": "tennis",
    "ice hockey": "hockey",
    "handball": "handball",
    "volleyball": "volleyball",
    "baseball": "baseball",
    "rugby union": "rugby",
    "rugby league": "rugby",
    "e-sports": "esports",
    "esports": "esports",
}


def fetch_sport_menu(
    *, session: Optional["requests.Session"] = None
) -> Dict[str, List[str]]:
    """Read the authoritative sport-ID list from the page's ``__NEXT_DATA__``.

    OddsSafari embeds ``props.pageProps.global.sportsMenu`` with entries like
    ``{"SportID": 10, "SportName": "Soccer"}``. Using it means one request
    instead of probing IDs, and it stays correct when the site renumbers tabs.

    Returns ``{internal_sport: [page_id, ...]}`` (empty dict on failure).
    """
    html = fetch_dropping_odds_html(DROPPING_ODDS_ROOT, session=session)
    if not html:
        return {}
    match = _NEXT_DATA_RE.search(html)
    if not match:
        logger.info("__NEXT_DATA__ not present — cannot read sportsMenu")
        return {}
    try:
        import json

        data = json.loads(match.group(1))
        menu = (
            data.get("props", {})
            .get("pageProps", {})
            .get("global", {})
            .get("sportsMenu", [])
        )
    except Exception as exc:
        logger.warning("failed to parse __NEXT_DATA__: %s", exc)
        return {}

    mapping: Dict[str, List[str]] = {}
    for entry in menu or []:
        sid = entry.get("SportID")
        name = (entry.get("SportName") or "").strip().lower()
        internal = _MENU_NAME_TO_INTERNAL.get(name)
        if sid is None or not internal:
            continue
        mapping.setdefault(internal, []).append(str(sid))
    return mapping


def _is_missing_sport_page(html: str) -> bool:
    """True when OddsSafari served its 404 page (sport has no events now)."""
    return "404 | OddsSafari" in html[:4000]


def discover_sport_page_ids(
    sport: str,
    *,
    session: Optional["requests.Session"] = None,
    candidates: Iterable[str] = _ID_PROBE_CANDIDATES,
) -> List[str]:
    """Return the OddsSafari page IDs whose rows actually match *sport*.

    Probes the hardcoded mapping first (cheap, one request in the happy path)
    and only falls back to scanning the candidate grid when that yields
    nothing. Returns an empty list when the sport has no events today.
    """
    internal = _internal_name(sport) or (sport or "").lower()
    session = session or requests.Session()

    # Preferred: the site's own sport menu (one request, always current).
    menu = fetch_sport_menu(session=session)
    if menu.get(internal):
        logger.info("sportsMenu: '%s' → IDs %s", internal, menu[internal])
        return menu[internal]
    if menu:
        logger.info(
            "sportsMenu has no entry for '%s' — no events for it right now",
            internal,
        )
        return []

    def _matching_ids(ids: Iterable[str]) -> List[str]:
        found: List[str] = []
        for sid in ids:
            html = fetch_dropping_odds_html(
                f"{DROPPING_ODDS_ROOT}/sports/{sid}", session=session
            )
            if not html or _is_missing_sport_page(html):
                continue
            rows = parse_dropping_odds_table(html, sport_page_id=sid)
            if any((r.sport or "") == internal for r in rows):
                found.append(sid)
        return found

    preferred = list(SPORT_TO_PAGE_IDS.get(internal, ()))
    ids = _matching_ids(preferred) if preferred else []
    if ids:
        return ids

    logger.info(
        "Sport '%s': hardcoded IDs %s gave no rows — scanning candidates",
        internal, preferred or "(none)",
    )
    remaining = [c for c in candidates if c not in preferred]
    return _matching_ids(remaining)


def collect_rows_via_http(
    *,
    sport: Optional[str] = None,
    sport_page_ids: Optional[Iterable[str]] = None,
    max_pages_per_sport: int = _MAX_PAGES_PER_SPORT,
    session: Optional["requests.Session"] = None,
) -> List[DroppingOddsRow]:
    """Collect dropping-odds rows over plain HTTP (no browser).

    When *sport* is given and *sport_page_ids* is not, the correct page IDs
    are discovered by content so a stale hardcoded ID cannot silently yield
    zero rows.

    Every row for a sport arrives in a single response via the SSR payload
    (see :func:`parse_dropping_odds_next_data`), so *max_pages_per_sport* is
    accepted only for call-site compatibility and no longer limits the result.
    """
    del max_pages_per_sport  # pagination is client-side; payload holds all rows
    session = session or requests.Session()

    ids = list(sport_page_ids or [])
    if not ids and sport:
        ids = discover_sport_page_ids(sport, session=session)
        if not ids:
            logger.warning(
                "No OddsSafari page currently lists sport '%s' "
                "(likely no events today)", sport,
            )
            return []
    if not ids:
        ids = list(FALLBACK_SPORT_PAGE_IDS)

    all_rows: List[DroppingOddsRow] = []
    seen: set = set()

    for sid in ids:
        url = f"{DROPPING_ODDS_ROOT}/sports/{sid}"
        html = fetch_dropping_odds_html(url, session=session)
        if not html or _is_missing_sport_page(html):
            continue

        # Primary: the SSR payload carries every row, so the site's client-side
        # "Page: n / m" control needs no crawling. Falling back to the table
        # markup keeps the scraper working if OddsSafari drops __NEXT_DATA__,
        # but that path only ever sees the first page.
        rows = parse_dropping_odds_next_data(html, sport_page_id=sid)
        source = "next_data"
        if not rows:
            rows = parse_dropping_odds_table(html, sport_page_id=sid)
            source = "table_html"
            if rows:
                logger.warning(
                    "sport_page_id=%s — SSR payload unavailable, parsed %d "
                    "rows from the table (first page only)", sid, len(rows),
                )

        added = 0
        for row in rows:
            key = (row.match_url, row.outcome)
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)
            added += 1

        logger.info(
            "sport_page_id=%s — %d rows via %s (+%d new, total=%d)",
            sid, len(rows), source, added, len(all_rows),
        )

    return all_rows


def _wait_for_table(driver, timeout: float = _DEFAULT_PAGE_WAIT_S) -> None:
    """Block up to *timeout* seconds for the dropping-odds table to render."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        html = driver.page_source or ""
        if "/matches/" in html and "<tr" in html.lower():
            return
        time.sleep(0.25)


def _discover_sport_ids(driver) -> List[str]:
    """Read the sidebar/nav on the root page and extract ``/sports/{id}``."""
    try:
        driver.get(DROPPING_ODDS_ROOT)
    except Exception as exc:  # pragma: no cover - network error path
        logger.warning("cannot open dropping-odds root: %s", exc)
        return list(FALLBACK_SPORT_PAGE_IDS)

    _wait_for_table(driver)
    soup = BeautifulSoup(driver.page_source or "", "html.parser")
    ids: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"/dropping-odds/sports/\d+")):
        match = re.search(r"/sports/(\d+)", a.get("href", ""))
        if not match:
            continue
        sid = match.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)

    if not ids:
        logger.info("sport-id discovery yielded nothing, using fallback list")
        return list(FALLBACK_SPORT_PAGE_IDS)
    return ids


def _collect_sport_page(
    driver,
    sport_page_id: str,
    *,
    max_pages: int = _MAX_PAGES_PER_SPORT,
    page_wait_s: float = _DEFAULT_PAGE_WAIT_S,
) -> List[DroppingOddsRow]:
    """Paginate the dropping-odds table for a single sport page."""
    rows: List[DroppingOddsRow] = []
    seen_signatures: set = set()

    for page in range(1, max_pages + 1):
        url = f"{DROPPING_ODDS_ROOT}/sports/{sport_page_id}?page={page}"
        try:
            driver.get(url)
        except Exception as exc:  # pragma: no cover
            logger.warning("failed to open %s: %s", url, exc)
            break

        _wait_for_table(driver, timeout=page_wait_s)
        html = driver.page_source or ""
        # The rendered DOM shows one client-side page at a time; the SSR payload
        # embedded in the same document holds the complete set, so prefer it and
        # stop after the first fetch instead of crawling ?page=N (ignored).
        payload_rows = parse_dropping_odds_next_data(
            html, sport_page_id=sport_page_id
        )
        if payload_rows:
            rows.extend(payload_rows)
            break

        page_rows = parse_dropping_odds_table(
            html, sport_page_id=sport_page_id
        )

        if not page_rows:
            break

        page_sig = tuple(
            (r.match_url, r.outcome, r.current_odds) for r in page_rows
        )
        signature = hash(page_sig)
        if signature in seen_signatures:
            # Site returned the same page twice — pagination exhausted.
            break
        seen_signatures.add(signature)

        rows.extend(page_rows)

    return rows


def collect_dropping_odds_rows(
    driver,
    *,
    sport_page_ids: Optional[Iterable[str]] = None,
    max_pages_per_sport: int = _MAX_PAGES_PER_SPORT,
    page_wait_s: float = _DEFAULT_PAGE_WAIT_S,
) -> List[DroppingOddsRow]:
    """Top-level collection: iterate every sport tab and return all rows.

    Duplicate rows (same match URL + outcome) that appear across multiple
    sport pages are kept once.
    """
    if sport_page_ids is None:
        sport_page_ids = _discover_sport_ids(driver)

    all_rows: List[DroppingOddsRow] = []
    seen: set = set()
    for sid in sport_page_ids:
        try:
            sport_rows = _collect_sport_page(
                driver,
                sid,
                max_pages=max_pages_per_sport,
                page_wait_s=page_wait_s,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("sport %s collection error: %s", sid, exc)
            continue

        for row in sport_rows:
            key = (row.match_url, row.outcome)
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(row)

        logger.info(
            "sport_page_id=%s — %d rows collected (total=%d)",
            sid, len(sport_rows), len(all_rows),
        )

    return all_rows


def serialize_rows(rows: Iterable[DroppingOddsRow]) -> List[Dict[str, object]]:
    return [r.to_dict() for r in rows]


__all__ = [
    "SPORT_SLUG_TO_INTERNAL",
    "DROPPING_ODDS_ROOT",
    "FALLBACK_SPORT_PAGE_IDS",
    "SPORT_TO_PAGE_IDS",
    "SPORT_ODDS_RANGE",
    "DEFAULT_ODDS_RANGE",
    "odds_range_for_sport",
    "DroppingOddsRow",
    "map_slug_to_internal",
    "is_livesport_supported_sport",
    "is_enrichable_sport",
    "uses_sofascore_only_enrichment",
    "fetch_dropping_odds_html",
    "fetch_sport_menu",
    "discover_sport_page_ids",
    "collect_rows_via_http",
    "parse_dropping_odds_table",
    "parse_dropping_odds_next_data",
    "is_qualifying_row",
    "collect_dropping_odds_rows",
    "serialize_rows",
]
