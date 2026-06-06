# -*- coding: utf-8 -*-
"""
🏓 AISCORE SCRAPER — table-tennis match list + H2H + form
=========================================================

Why AiScore?
------------
For table tennis (especially amateur / lower-tier events such as TT Cup,
TT Elite, Setka Cup) AiScore (https://www.aiscore.com/table-tennis) lists
practically every match together with a rich head-to-head section and recent
form (general + home/away splits). LiveSport lists too few of these events and
SofaScore is reserved here ONLY for the (mandatory) Fan Vote signal.

This module is intentionally split into two layers:

  1. PURE PARSERS (no Selenium, fully unit-testable against saved HTML):
       • parse_aiscore_matches(html_or_soup)  -> list[dict]   (one per <li>)
       • filter_h2h(matches, a, b)            -> direct head-to-head subset
       • h2h_record(matches, a, b)            -> win counts + win-rate
       • recent_form(matches, player, venue)  -> ['W','L',...]
       • favourite_meets_h2h_threshold(...)   -> qualification helper

  2. SELENIUM WRAPPERS (live fetch; cannot be unit-tested offline):
       • list_match_urls(driver, date_str)
       • scrape_match_page(driver, url)

The AiScore DOM (confirmed from a real H2H section) is:

    div.matchContent
      ul.matchBox
        li[itemtype=…/SportsEvent]
          meta[itemprop=name]       (optional) "Home vs Away"
          meta[itemprop=url]        (optional) absolute match url
          meta[itemprop=startDate]  ISO timestamp
          p.collect span.round.win|loser   (badge, page-subject POV — UNRELIABLE
                                            for counting, so we ignore it)
          a[href]                   relative match url
            p.time                  human date
            p.teamBox
              span.teamBoxItem span.teamName   (HOME, then AWAY — document order)
            p.scoreBox
              span.winText|loserText           (HOME score, then AWAY score)

Winner is derived from the SCORE (winText/loserText + numeric comparison),
NOT from the ``p.collect`` badge — the badge proved inconsistent with the
actual scoreline in real data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from bs4 import BeautifulSoup  # type: ignore
    _BS4_OK = True
except Exception:  # pragma: no cover - import guard
    _BS4_OK = False


AISCORE_BASE = "https://www.aiscore.com"
AISCORE_TT_URL = "https://www.aiscore.com/table-tennis"

# A match-detail link looks like /table-tennis/match-<slug>/<id>
_MATCH_HREF_RE = re.compile(r"/table-tennis/match-[^\"'\s]+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _soup(html_or_soup: Union[str, "BeautifulSoup"]) -> "BeautifulSoup":
    """Accept either raw HTML or an existing BeautifulSoup, return a soup."""
    if not _BS4_OK:
        raise RuntimeError("BeautifulSoup (bs4) is required for AiScore parsing")
    if isinstance(html_or_soup, str):
        return BeautifulSoup(html_or_soup, "html.parser")
    return html_or_soup


def normalize_name(name: Optional[str]) -> str:
    """Normalize a player name for robust matching across sections.

    AiScore writes names inconsistently ("Komorowicz, Jakub" vs
    "Jakub Komorowicz"). We lowercase, drop punctuation, sort the tokens and
    rejoin, so "Komorowicz, Jakub" and "Jakub Komorowicz" compare equal.
    """
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", name, flags=re.UNICODE).lower()
    tokens = [t for t in cleaned.split() if t]
    return " ".join(sorted(tokens))


def _to_int(txt: Optional[str]) -> Optional[int]:
    if txt is None:
        return None
    m = re.search(r"-?\d+", txt)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def iso_to_match_time(iso: Optional[str]) -> str:
    """Convert an AiScore ISO startDate ('2026-06-03T16:40:00-04:00') to the
    'DD.MM.YYYY HH:MM' UTC string the downstream gate / email expect.

    Returns '' when the input cannot be parsed (e.g. it is a human date string).
    """
    if not iso:
        return ""
    from datetime import datetime, timezone

    s = iso.strip()
    # Python's fromisoformat handles the '-04:00' offset on 3.11.
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Some rows carry a trailing 'Z'.
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------
# PURE PARSERS
# ---------------------------------------------------------------------------

def _parse_li(li: Any) -> Optional[Dict[str, Any]]:
    """Parse a single ``li[itemtype=SportsEvent]`` into a match dict.

    Returns None when the element does not carry enough data (no teams).
    """
    # --- team names (HOME first, AWAY second, in document order) ---
    team_names = [t.get_text(strip=True) for t in li.select("span.teamName")]
    team_names = [t for t in team_names if t]
    if len(team_names) < 2:
        # Fallback: derive from meta[name] "Home vs Away"
        meta_name = li.find("meta", attrs={"itemprop": "name"})
        if meta_name and " vs " in (meta_name.get("content") or ""):
            parts = meta_name["content"].split(" vs ", 1)
            team_names = [parts[0].strip(), parts[1].strip()]
    if len(team_names) < 2:
        return None
    home, away = team_names[0], team_names[1]

    # --- scores (HOME first, AWAY second) + winner via win/loser class ---
    home_score = away_score = None
    winner_side: Optional[str] = None
    score_spans = li.select("p.scoreBox span")
    if len(score_spans) >= 2:
        home_span, away_span = score_spans[0], score_spans[1]
        home_score = _to_int(home_span.get_text(strip=True))
        away_score = _to_int(away_span.get_text(strip=True))
        home_cls = " ".join(home_span.get("class") or [])
        away_cls = " ".join(away_span.get("class") or [])
        if "winText" in home_cls and "winText" not in away_cls:
            winner_side = "home"
        elif "winText" in away_cls and "winText" not in home_cls:
            winner_side = "away"

    # Fall back to numeric comparison if the class hint was inconclusive.
    if winner_side is None and home_score is not None and away_score is not None:
        if home_score > away_score:
            winner_side = "home"
        elif away_score > home_score:
            winner_side = "away"

    winner = home if winner_side == "home" else (away if winner_side == "away" else None)

    # --- url ---
    url = None
    meta_url = li.find("meta", attrs={"itemprop": "url"})
    if meta_url and meta_url.get("content"):
        url = meta_url["content"].strip()
    if not url:
        a = li.find("a", href=True)
        if a:
            href = a["href"].strip()
            url = href if href.startswith("http") else f"{AISCORE_BASE}{href}"

    # --- date ---
    date = None
    meta_date = li.find("meta", attrs={"itemprop": "startDate"})
    if meta_date and meta_date.get("content"):
        date = meta_date["content"].strip()
    if not date:
        t = li.select_one("p.time")
        if t:
            date = t.get_text(strip=True)

    return {
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "winner_side": winner_side,
        "date": date,
        "url": url,
        "finished": home_score is not None and away_score is not None,
    }


def parse_aiscore_matches(html_or_soup: Union[str, "BeautifulSoup"]) -> List[Dict[str, Any]]:
    """Parse every ``li[itemtype=SportsEvent]`` in the document.

    Works for both the listing page and a match-detail page (whose H2H / form
    sections reuse the same ``ul.matchBox > li`` markup). Returns one dict per
    match in document order.
    """
    soup = _soup(html_or_soup)
    out: List[Dict[str, Any]] = []
    # Be liberal: any <li> with an itemtype mentioning SportsEvent.
    lis = soup.find_all("li", attrs={"itemtype": re.compile("SportsEvent", re.I)})
    if not lis:
        # Fallback: <li> living inside a ul.matchBox.
        lis = [li for box in soup.select("ul.matchBox") for li in box.find_all("li")]
    for li in lis:
        row = _parse_li(li)
        if row:
            out.append(row)
    return out


def _involves(match: Dict[str, Any], player: str) -> bool:
    p = normalize_name(player)
    return normalize_name(match.get("home")) == p or normalize_name(match.get("away")) == p


def _dedupe_by_url(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicate matches (same URL) keeping first occurrence/order.

    On a /h2h page the same meeting can appear in the direct-H2H section AND in
    a player's recent-form section. Counting it twice would inflate both the
    head-to-head record and form, so we de-duplicate by match URL (falling back
    to a date+participants key when a URL is missing).
    """
    seen = set()
    out: List[Dict[str, Any]] = []
    for m in matches:
        key = m.get("url")
        if not key:
            key = (m.get("date"),
                   normalize_name(m.get("home")),
                   normalize_name(m.get("away")),
                   m.get("home_score"), m.get("away_score"))
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def filter_h2h(matches: List[Dict[str, Any]], player_a: str,
               player_b: str) -> List[Dict[str, Any]]:
    """Return only the direct head-to-head matches between A and B (deduped)."""
    a, b = normalize_name(player_a), normalize_name(player_b)
    pair = {a, b}
    res = []
    for m in _dedupe_by_url(matches):
        if {normalize_name(m.get("home")), normalize_name(m.get("away"))} == pair:
            res.append(m)
    return res


def h2h_record(matches: List[Dict[str, Any]], player_a: str,
               player_b: str) -> Dict[str, Any]:
    """Head-to-head record of A vs B (only decided matches are counted).

    Returns dict with a_wins, b_wins, total, a_win_rate, b_win_rate.
    """
    a, b = normalize_name(player_a), normalize_name(player_b)
    direct = filter_h2h(matches, player_a, player_b)
    a_wins = b_wins = 0
    for m in direct:
        w = normalize_name(m.get("winner"))
        if not w:
            continue
        if w == a:
            a_wins += 1
        elif w == b:
            b_wins += 1
    total = a_wins + b_wins
    return {
        "a_wins": a_wins,
        "b_wins": b_wins,
        "total": total,
        "a_win_rate": round(a_wins / total, 4) if total else 0.0,
        "b_win_rate": round(b_wins / total, 4) if total else 0.0,
        "matches": direct,
    }


def recent_form(matches: List[Dict[str, Any]], player: str,
                venue: Optional[str] = None, limit: int = 5) -> List[str]:
    """Recent W/L form for ``player`` as a list (most-recent first).

    venue:
        None    — all matches involving the player
        'home'  — only matches where the player was the HOME side
        'away'  — only matches where the player was the AWAY side
    """
    p = normalize_name(player)
    form: List[str] = []
    for m in _dedupe_by_url(matches):
        if not m.get("winner"):
            continue
        is_home = normalize_name(m.get("home")) == p
        is_away = normalize_name(m.get("away")) == p
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        form.append("W" if normalize_name(m.get("winner")) == p else "L")
        if len(form) >= limit:
            break
    return form


def favourite_meets_h2h_threshold(matches: List[Dict[str, Any]], favourite: str,
                                  rival: str, threshold: float = 0.60,
                                  min_matches: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """Qualification gate: did ``favourite`` win >= ``threshold`` of H2H vs rival?

    Mirrors the tennis rule (favourite wins >= 60% of head-to-head meetings).
    Returns (passes, record) where record is the h2h_record() dict augmented
    with ``fav_wins`` / ``fav_win_rate``.
    """
    rec = h2h_record(matches, favourite, rival)
    fav_wins = rec["a_wins"]
    fav_rate = rec["a_win_rate"]
    rec["fav_wins"] = fav_wins
    rec["fav_win_rate"] = fav_rate
    passes = rec["total"] >= min_matches and fav_rate >= threshold
    return passes, rec


# ---------------------------------------------------------------------------
# SELENIUM WRAPPERS (live fetch — not unit-tested)
# ---------------------------------------------------------------------------

def _safe_page_source(driver: Any) -> Optional[str]:
    try:
        return driver.page_source
    except Exception:
        return None


def list_match_urls(driver: Any, date_str: Optional[str] = None,
                    settle_seconds: float = 3.0) -> List[str]:
    """Open the AiScore table-tennis listing and return match-detail URLs.

    The listing is JS-rendered, so we load the page, let it settle, then
    harvest every ``/table-tennis/match-…`` href (de-duplicated, absolute).
    ``date_str`` is accepted for API symmetry; AiScore shows the current day
    by default and a date selector that we do not depend on here.
    """
    import time

    url = AISCORE_TT_URL
    try:
        driver.get(url)
    except Exception:
        return []
    time.sleep(settle_seconds)
    # Encourage lazy content to render.
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

    html = _safe_page_source(driver) or ""
    hrefs = set()
    for m in _MATCH_HREF_RE.finditer(html):
        href = m.group(0)
        hrefs.add(href if href.startswith("http") else f"{AISCORE_BASE}{href}")
    return sorted(hrefs)


def parse_h2h_header(html_or_soup: Union[str, "BeautifulSoup"]) -> Optional[Tuple[str, str]]:
    """Return (home, away) participant names from an AiScore /h2h page header.

    The match's two participants are the first two distinct player-profile links
    at the top of the page (``a[href*='/player-']``). The first is the HOME
    (left) side, the second the AWAY (right) side. Returns None if fewer than
    two distinct player links are found.
    """
    soup = _soup(html_or_soup)
    seen_href = []
    names: List[str] = []
    for a in soup.find_all("a", href=True):
        if "/player-" not in a["href"]:
            continue
        href = a["href"].split("?")[0].rstrip("/")
        if href in seen_href:
            continue
        name = a.get_text(strip=True)
        if not name:
            continue
        seen_href.append(href)
        names.append(name)
        if len(names) >= 2:
            break
    if len(names) >= 2:
        return names[0], names[1]
    return None


def h2h_url_for(match_url: str) -> str:
    """Return the /h2h sub-page URL for an AiScore match URL.

    AiScore match pages (``/table-tennis/match-<slug>/<id>``) show only the
    single-match overview; the head-to-head + recent-form lists live on the
    ``/h2h`` sub-page. Idempotent (won't append twice) and strips query/hash.
    """
    if not match_url:
        return match_url
    base = match_url.split("#")[0].split("?")[0].rstrip("/")
    if base.endswith("/h2h"):
        return base
    return base + "/h2h"


def scrape_match_page(driver: Any, url: str,
                      settle_seconds: float = 3.0) -> Dict[str, Any]:
    """Open a match's /h2h sub-page and parse its H2H + form sections.

    Returns a dict:
        {
          "url": <h2h url loaded>,
          "all_matches": [...],          # every <li> across all three sections
          "home": <home player or None>, # upcoming match participants (from header)
          "away": <away player or None>,
          "match_date": <iso/text or None>,
        }

    Participants come from the page HEADER (first two player links), which is
    the reliable source for the upcoming match. ``all_matches`` contains the
    direct H2H section plus each player's recent-form section, so the caller can
    derive both the head-to-head record and general/venue form.
    """
    import time

    target = h2h_url_for(url)
    try:
        driver.get(target)
    except Exception:
        return {"url": target, "all_matches": [], "home": None, "away": None,
                "match_date": None}
    time.sleep(settle_seconds)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

    html = _safe_page_source(driver) or ""
    matches = parse_aiscore_matches(html)

    # Participants: prefer the page header (player links).
    home = away = None
    header = parse_h2h_header(html)
    if header:
        home, away = header

    match_date = None
    # Fallback: derive participants from the most common pair in the lists.
    if home is None and matches:
        from collections import Counter
        pairs = Counter()
        for m in matches:
            key = tuple(sorted([normalize_name(m.get("home")), normalize_name(m.get("away"))]))
            pairs[key] += 1
        if pairs:
            top_norm = pairs.most_common(1)[0][0]
            for m in matches:
                k = tuple(sorted([normalize_name(m.get("home")), normalize_name(m.get("away"))]))
                if k == top_norm:
                    home, away = m.get("home"), m.get("away")
                    match_date = m.get("date")
                    break

    return {"url": target, "all_matches": matches, "home": home, "away": away,
            "match_date": match_date}


__all__ = [
    "AISCORE_BASE",
    "AISCORE_TT_URL",
    "normalize_name",
    "iso_to_match_time",
    "parse_aiscore_matches",
    "parse_h2h_header",
    "h2h_url_for",
    "filter_h2h",
    "h2h_record",
    "recent_form",
    "favourite_meets_h2h_threshold",
    "list_match_urls",
    "scrape_match_page",
]
