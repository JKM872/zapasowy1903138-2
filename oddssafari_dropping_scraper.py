"""OddsSafari dropping-odds scraper.

Goal: for every sport listed on https://www.oddssafari.com/dropping-odds and
every row of the dropping-odds table, produce a single structured dictionary
with both the raw OddsSafari fields and a ``qualifies`` flag based on the
current odds range configured by the pipeline (default 1.35 to 2.00).

The page is rendered client-side, so we use Selenium (the same stack and
driver bootstrap as the existing Livesport scraper in
``livesport_h2h_scraper.py``). We never rely on Cloudflare bypass for
OddsSafari — the site is not behind CF at the moment; Selenium alone works.

This module exposes:

* :data:`SPORT_SLUG_TO_INTERNAL` — mapping from the sport slug present in
  match URLs (``/matches/{slug}/...``) to the internal sport name used by
  ``livesport_h2h_scraper`` / ``process_match``.
* :func:`is_livesport_supported_sport` — small helper that tells the
  pipeline whether the costly enrichment phase can be attempted.
* :func:`parse_dropping_odds_table` — pure parser that turns an HTML fragment
  containing the dropping-odds table into a list of row dicts (used in tests
  against a static fixture, without the network).
* :func:`collect_dropping_odds_rows` — Selenium-driven top-level entry point
  that iterates every sport tab and every page and returns the full list of
  raw row dicts.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

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
    "american-football": None,
    "am.-football": None,
    "darts": None,
    "snooker": None,
    "e-sports": None,
    "cricket": None,
    "mma": None,
    "boxing": None,
}


def map_slug_to_internal(slug: str) -> Optional[str]:
    """Return the internal sport name for an OddsSafari URL slug.

    Unknown slugs return ``None``. Matching is case-insensitive.
    """
    if not slug:
        return None
    return SPORT_SLUG_TO_INTERNAL.get(slug.strip().lower())


def is_livesport_supported_sport(slug_or_internal: Optional[str]) -> bool:
    """Return True when enrichment can be attempted for the given sport.

    Accepts either the OddsSafari URL slug or an already-internal name.
    """
    if not slug_or_internal:
        return False
    value = slug_or_internal.strip().lower()
    internal = SPORT_SLUG_TO_INTERNAL.get(value, value)
    return internal in {"football", "basketball", "volleyball", "handball",
                         "hockey", "tennis", "baseball", "rugby"}


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
        texts = [c.get_text(" ", strip=True) for c in cells]

        outcome = ""
        numeric_values: List[float] = []
        for raw in texts:
            stripped = raw.strip()
            if stripped in OUTCOME_LABELS and not outcome:
                outcome = stripped
                continue
            value = _parse_float(stripped)
            if value is not None:
                numeric_values.append(value)

        if not outcome:
            for raw in texts:
                token = raw.strip().upper()
                if token in OUTCOME_LABELS:
                    outcome = token
                    break

        open_odds = numeric_values[0] if len(numeric_values) >= 1 else None
        current_odds = numeric_values[1] if len(numeric_values) >= 2 else None
        drop_pct = numeric_values[2] if len(numeric_values) >= 3 else None

        href = link.get("href", "")
        match_url = urljoin(base_url, href)
        slug, match_id = _parse_match_url(href)
        home, away = _extract_teams_from_link(link.get_text(" ", strip=True))

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


def is_qualifying_row(
    row: DroppingOddsRow,
    *,
    min_odds: float = 1.35,
    max_odds: float = 2.00,
) -> Tuple[bool, Optional[str]]:
    """Return (qualifies, skip_reason).

    Closed range: ``min_odds <= current_odds <= max_odds``.
    """
    if row.current_odds is None:
        return False, "missing_current_odds"
    if row.current_odds < min_odds or row.current_odds > max_odds:
        return False, "odds_out_of_range"
    if not is_livesport_supported_sport(row.sport_slug):
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
    "1",   # Soccer
    "20",  # Basketball
    "5",   # Tennis
    "18",  # Ice Hockey
    "11",  # American Football
    "6",   # Handball
    "23",  # Volleyball
    "3",   # Baseball
    "22",  # Darts
    "19",  # Snooker
    "28",  # E-sports
    "24",  # Rugby Union
    "25",  # Rugby League
    "21",  # Cricket
    "26",  # MMA
    "10",  # Boxing
)

_DEFAULT_PAGE_WAIT_S = 4.0
_MAX_PAGES_PER_SPORT = 20


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
    "DroppingOddsRow",
    "map_slug_to_internal",
    "is_livesport_supported_sport",
    "parse_dropping_odds_table",
    "is_qualifying_row",
    "collect_dropping_odds_rows",
    "serialize_rows",
]
