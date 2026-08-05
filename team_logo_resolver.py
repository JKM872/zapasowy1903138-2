"""
Team Logo Resolver – TheSportsDB lookup with persistent JSON cache.

Usage:
    from team_logo_resolver import get_logo_url, enrich_matches_with_logos

Single lookup:
    url = get_logo_url("Arsenal")           # -> "https://…/Arsenal.png" or None

Batch (in-place, adds home_logo_url / away_logo_url):
    enrich_matches_with_logos(matches)
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json"
_API_KEY = os.environ.get("THESPORTSDB_API_KEY", "3")  # free tier key
_CACHE_FILE = Path(__file__).with_name("team_logos_cache.json")
_CACHE_TTL = 7 * 24 * 3600  # 7 days
_REQUEST_TIMEOUT = 6  # seconds
_NEGATIVE_TTL = 24 * 3600  # cache misses for 1 day


# ---------------------------------------------------------------------------
# In-memory + file cache
# ---------------------------------------------------------------------------
_mem_cache: Dict[str, Dict[str, Any]] = {}


def _load_file_cache() -> Dict[str, Dict[str, Any]]:
    """Load cache from disk once, merging into memory."""
    global _mem_cache
    if _mem_cache:
        return _mem_cache
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
                _mem_cache = json.load(fh)
        except (json.JSONDecodeError, OSError):
            _mem_cache = {}
    return _mem_cache


def _save_file_cache() -> None:
    """Persist cache to disk (best-effort)."""
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(_mem_cache, fh, ensure_ascii=False)
    except OSError:
        pass


def _normalize_name(name: str) -> str:
    return name.strip().lower()


# ---------------------------------------------------------------------------
# Name variants
#
# Measured on 2 280 looked-up names, only 78 (3.4%) resolved to a badge. The
# misses were not random — TheSportsDB is an English club/team database and our
# rows are Polish, so three fixable things accounted for nearly all of them:
#
#   * country names arrive translated ("Meksyk", "Portoryko", "Czechy"),
#   * women's and youth sides carry a suffix ("Meksyk K", "Polska U18 K"),
#     while the badge is filed under the base side,
#   * punctuation is glued ("St.Louis Cardinals").
#
# Individual sports are hopeless by design: "Putincewa J." is a person, and
# searchteams.php only knows teams. Those keep the initials avatar.
# ---------------------------------------------------------------------------

_INDIVIDUAL_SPORTS = {"tennis", "table_tennis", "table-tennis", "darts", "snooker"}

# Suffixes that mark a variant of a side, not a different side. Ordered longest
# first so "U18 K" is stripped before "K".
_SIDE_SUFFIXES = (
    " u21 k", " u19 k", " u18 k", " u17 k",
    " u21", " u23", " u19", " u18", " u17",
    " (k)", " k",
    " ii", " 2", " b",
)

_PL_TO_EN = {
    # Countries seen in the data, plus their common neighbours.
    "algieria": "Algeria", "belgia": "Belgium", "belize": "Belize",
    "brazylia": "Brazil", "chile": "Chile", "chorwacja": "Croatia",
    "czarnogóra": "Montenegro", "czarnogora": "Montenegro",
    "czechy": "Czech Republic", "dominikana": "Dominican Republic",
    "finlandia": "Finland", "francja": "France", "grecja": "Greece",
    "gwatemala": "Guatemala", "guatemala": "Guatemala",
    "hiszpania": "Spain", "holandia": "Netherlands", "indonezja": "Indonesia",
    "irlandia": "Ireland", "islandia": "Iceland", "jamajka": "Jamaica",
    "japonia": "Japan", "kambodża": "Cambodia", "kambodza": "Cambodia",
    "kanada": "Canada", "kenia": "Kenya", "kolumbia": "Colombia",
    "kostaryka": "Costa Rica", "kuba": "Cuba", "łotwa": "Latvia",
    "lotwa": "Latvia", "maroko": "Morocco", "meksyk": "Mexico",
    "niemcy": "Germany", "nikaragua": "Nicaragua", "norwegia": "Norway",
    "panama": "Panama", "paragwaj": "Paraguay", "polska": "Poland",
    "portoryko": "Puerto Rico", "portugalia": "Portugal",
    "rumunia": "Romania", "senegal": "Senegal", "serbia": "Serbia",
    "słowacja": "Slovakia", "slowacja": "Slovakia",
    "słowenia": "Slovenia", "slowenia": "Slovenia",
    "szkocja": "Scotland", "szwajcaria": "Switzerland", "szwecja": "Sweden",
    "timor wschodni": "East Timor", "turcja": "Turkey", "ukraina": "Ukraine",
    "urugwaj": "Uruguay", "wenezuela": "Venezuela", "węgry": "Hungary",
    "wegry": "Hungary", "wietnam": "Vietnam", "włochy": "Italy",
    "wlochy": "Italy", "austria": "Austria", "dania": "Denmark",
    "estonia": "Estonia", "litwa": "Lithuania", "bułgaria": "Bulgaria",
    "bulgaria": "Bulgaria", "armenia": "Armenia", "gruzja": "Georgia",
    "izrael": "Israel", "egipt": "Egypt", "nigeria": "Nigeria",
    "ghana": "Ghana", "australia": "Australia", "chiny": "China",
    "korea": "South Korea", "tajlandia": "Thailand", "filipiny": "Philippines",
    "peru": "Peru", "ekwador": "Ecuador", "boliwia": "Bolivia",
    "argentyna": "Argentina", "honduras": "Honduras", "salwador": "El Salvador",
    "haiti": "Haiti", "trynidad i tobago": "Trinidad and Tobago",
    "curacao": "Curacao", "surinam": "Suriname",
}


def _strip_side_suffix(name: str) -> Optional[str]:
    """Base side for a women's/youth/reserve variant, or None.

    Matching ignores case but the result keeps the original spelling, so the term
    stays readable in logs and usable by a case-sensitive source.
    """
    lowered = name.lower()
    for suffix in _SIDE_SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix) + 2:
            return name[: -len(suffix)].strip()
    return None


def _name_variants(team_name: str) -> List[str]:
    """Search terms to try, best first, without duplicates."""
    raw = team_name.strip()
    lowered = raw.lower()
    variants: List[str] = [raw]

    # "St.Louis Cardinals" -> "St. Louis Cardinals"
    spaced = re.sub(r"\.(?=\S)", ". ", raw)
    if spaced != raw:
        variants.append(spaced)

    translated = _PL_TO_EN.get(lowered)
    if translated:
        variants.append(translated)

    base = _strip_side_suffix(raw)
    if base:
        variants.append(base)
        base_translated = _PL_TO_EN.get(base.lower())
        if base_translated:
            variants.append(base_translated)

    seen: set = set()
    out: List[str] = []
    for v in variants:
        key = v.strip().lower()
        if v.strip() and key not in seen:
            seen.add(key)
            out.append(v.strip())
    return out


def _query_badge(term: str) -> Optional[str]:
    """One TheSportsDB lookup. Returns a badge URL or None."""
    encoded = urllib.parse.quote(term, safe="")
    api_url = f"{_SPORTSDB_BASE}/{_API_KEY}/searchteams.php?t={encoded}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "PicklySportsApp/1.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        data: Dict[str, Any] = json.loads(resp.read().decode())
    teams: List[Any] = data.get("teams") or []
    if not teams:
        return None
    first: Dict[str, Any] = teams[0]
    return first.get("strBadge") or first.get("strLogo") or None


# ---------------------------------------------------------------------------
# Core lookup
# ---------------------------------------------------------------------------

def get_logo_url(team_name: str, sport: Optional[str] = None) -> Optional[str]:
    """
    Return a badge/logo URL for *team_name* or ``None``.

    Several spellings are tried before giving up — see ``_name_variants``. When
    *sport* is an individual one the lookup is skipped entirely: the competitors
    are people and ``searchteams.php`` only indexes teams, so every such call was
    a guaranteed miss that still cost a request.

    Results (including misses) are cached on disk for fast subsequent calls.
    """
    if not team_name or not team_name.strip():
        return None

    if sport and sport.strip().lower() in _INDIVIDUAL_SPORTS:
        return None

    key = _normalize_name(team_name)
    cache = _load_file_cache()
    now = time.time()

    cached = cache.get(key)
    if cached:
        ttl = _CACHE_TTL if cached.get("url") else _NEGATIVE_TTL
        if now - cached.get("ts", 0) < ttl:
            return cached.get("url")

    url: Optional[str] = None
    try:
        for term in _name_variants(team_name):
            url = _query_badge(term)
            if url:
                break
    except Exception:
        # On network error keep a stale hit rather than overwriting it with a miss.
        if cached and cached.get("url"):
            return cached["url"]

    cache[key] = {"url": url, "ts": now}
    _mem_cache[key] = cache[key]
    _save_file_cache()
    return url


def get_logo_url_cached_only(team_name: str) -> Optional[str]:
    """Return logo URL only from cache – no network call."""
    if not team_name:
        return None
    cache = _load_file_cache()
    entry = cache.get(_normalize_name(team_name))
    if entry:
        return entry.get("url")
    return None


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------

def enrich_matches_with_logos(matches: List[Dict[str, Any]]) -> None:
    """
    Add ``home_logo_url`` and ``away_logo_url`` to each match dict (in-place).

    Uses batched lookups so each unique team name hits the network at most once.
    """
    # Collect unique team names first to avoid duplicate network calls
    team_names: set[str] = set()
    for m in matches:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        if home:
            team_names.add(home)
        if away:
            team_names.add(away)

    # Resolve all unique names
    resolved: Dict[str, Optional[str]] = {}
    for name in team_names:
        resolved[name] = get_logo_url(name)

    # Inject into match dicts
    for m in matches:
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        m["home_logo_url"] = resolved.get(home)
        m["away_logo_url"] = resolved.get(away)
