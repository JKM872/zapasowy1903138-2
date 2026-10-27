"""
Team logo / player photo resolver (design K7) with a committed media cache.

Usage:
    from team_logo_resolver import resolve_media, get_logo_url, media_for_page

    resolve_media("Arsenal", "football")      # -> {url, source, license, author, attributionUrl} or None
    get_logo_url("Arsenal", "football")       # -> "https://r2.thesportsdb.com/..." or None (wrapper)
    media_for_page(matches)                   # API: cache only + at most 3 live lookups

Cache filler (GitHub Actions `media_cache.yml`, 06:30 / 14:30 UTC):
    python team_logo_resolver.py --fill [--days 2026-10-27,2026-10-28] [--budget-sec 300]

Sources, in order (free only):
  teams   -> cache -> TheSportsDB v1 key 123 -> ESPN (only MEDIA_ALLOW_ESPN=1, big leagues)
             -> Wikidata P154 (Commons-hosted free file) -> none
  players -> cache -> Wikidata P18 (tennis / table tennis player, Commons file with
             license + author) -> TheSportsDB player (tennis) -> none
  doubles -> none
SofaScore images are never used. Every URL passes the https host allowlist.

Cache ``outputs/media_cache.json``: ``sport|kind|folded`` -> ``{url, source, license,
author, attributionUrl, ts}``; hits are refreshed after 30 days, misses after 7 days
and rate-limited (429) misses after 1 hour. The file is written only by the filler,
never at request time (live lookups during a request stay in memory).
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.team_names import fold, player_alternative  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json"
# Key "3" was retired (HTTP 403); "123" is TheSportsDB's current free key.
_API_KEY = os.environ.get("THESPORTSDB_API_KEY") or "123"
_CACHE_FILE = _ROOT / "outputs" / "media_cache.json"
_LEGACY_CACHE_FILE = _ROOT / "team_logos_cache.json"   # read once by the filler (migration)
_CACHE_TTL = 30 * 24 * 3600      # hits: 30 days
_NEGATIVE_TTL = 7 * 24 * 3600    # misses / errors: 7 days
_RATE_LIMIT_TTL = 3600           # 429: 1 hour
_REQUEST_TIMEOUT = 6             # seconds
_USER_AGENT = "PicklyMedia/1.0 (https://github.com/JKM872/zapasowy1903138-2)"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
LIVE_LOOKUPS_PER_REQUEST = 3

# Hosts a served image may come from. Anything else (SofaScore CDN included) is dropped.
_ALLOWED_HOSTS = frozenset({
    "r2.thesportsdb.com", "www.thesportsdb.com",
    "upload.wikimedia.org", "thumb.wikimedia.org",
})
_ESPN_HOSTS = frozenset({"a.espncdn.com"})

# Seconds between requests per source; enforced only while filling (filler sets it).
_MIN_INTERVAL = {"thesportsdb": 2.4, "wikidata": 1.0, "espn": 1.0}
_throttle = False
_last_call: Dict[str, float] = {}

PLAYER_SPORTS = frozenset({"tennis", "table_tennis"})
_INDIVIDUAL_SPORTS = {"tennis", "table_tennis", "table-tennis", "darts", "snooker"}

_TSDB_SPORT = {
    "football": "Soccer", "basketball": "Basketball", "hockey": "Ice Hockey",
    "volleyball": "Volleyball", "handball": "Handball", "baseball": "Baseball",
    "rugby": "Rugby", "tennis": "Tennis",
}
# Wikidata items: sport (P641) for clubs, occupation (P106) for players.
_WD_SPORT = {
    "football": "Q2736", "basketball": "Q5372", "hockey": "Q41466",
    "volleyball": "Q1734", "handball": "Q8418", "baseball": "Q5369", "rugby": "Q5849",
}
_WD_OCCUPATION = {"tennis": "Q10833314", "table_tennis": "Q13382519"}

# ESPN (opt-in only): our (sport, league) -> ESPN site API league path.
_ESPN_LEAGUES = {
    ("hockey", "nhl"): "hockey/nhl",
    ("basketball", "nba"): "basketball/nba",
    ("basketball", "wnba"): "basketball/wnba",
    ("baseball", "mlb"): "baseball/mlb",
    ("football", "premier league"): "soccer/eng.1",
    ("football", "laliga"): "soccer/esp.1",
    ("football", "bundesliga"): "soccer/ger.1",
    ("football", "serie a"): "soccer/ita.1",
    ("football", "ligue 1"): "soccer/fra.1",
}


class _RateLimited(Exception):
    """HTTP 429 from a source."""


def _sport_key(sport: Optional[str]) -> str:
    s = (sport or "").strip().lower().replace("-", "_").replace(" ", "_")
    return s or "any"


def _kind_for(sport: Optional[str]) -> str:
    return "photo" if _sport_key(sport) in PLAYER_SPORTS else "logo"


def espn_allowed() -> bool:
    return os.environ.get("MEDIA_ALLOW_ESPN", "").strip() == "1"


def allowed_media_url(url: Any) -> bool:
    """https + allowlisted host. SofaScore never; ESPN only when MEDIA_ALLOW_ESPN=1."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or "sofascore" in host:
        return False
    if host in _ALLOWED_HOSTS:
        return True
    return host in _ESPN_HOSTS and espn_allowed()


def cache_key(name: str, sport: Optional[str], kind: Optional[str] = None) -> str:
    sp = _sport_key(sport)
    return f"{sp}|{kind or _kind_for(sport)}|{fold(name, sp)}"


# ---------------------------------------------------------------------------
# Cache (outputs/media_cache.json). Loaded once; written only by save_media_cache().
# ---------------------------------------------------------------------------
_mem_cache: Dict[str, Dict[str, Any]] = {}
_loaded = False


def _load_file_cache() -> Dict[str, Dict[str, Any]]:
    """Media cache entries (loaded from disk once per process)."""
    global _loaded
    if _loaded or _mem_cache:
        return _mem_cache
    _loaded = True
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                _mem_cache.update({k: v for k, v in data.items() if isinstance(v, dict)})
        except (json.JSONDecodeError, OSError):
            pass
    return _mem_cache


def _save_file_cache() -> None:
    """No-op at request time: only the filler persists the cache (save_media_cache)."""
    return None


def save_media_cache(path: Optional[Path] = None) -> None:
    """Write the cache, one entry per line in key order (stable, reviewable diffs)."""
    target = Path(path or _CACHE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}"
             for k, v in sorted(_mem_cache.items())]
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("{\n" + ",\n".join(lines) + ("\n" if lines else "") + "}\n")
    os.replace(tmp, target)


def _ttl(entry: Dict[str, Any]) -> int:
    if entry.get("url"):
        return _CACHE_TTL
    return _RATE_LIMIT_TTL if entry.get("miss") == "429" else _NEGATIVE_TTL


def _fresh(entry: Optional[Dict[str, Any]], now: float) -> bool:
    return bool(entry) and now - float(entry.get("ts") or 0) < _ttl(entry)


def _public(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """API shape of a cached hit, or None (miss, or host no longer allowed)."""
    if not entry or not allowed_media_url(entry.get("url")):
        return None
    return {
        "url": entry["url"],
        "source": entry.get("source"),
        "license": entry.get("license"),
        "author": entry.get("author"),
        "attributionUrl": entry.get("attributionUrl"),
    }


def media_from_url(url: Any) -> Optional[Dict[str, Any]]:
    """Media object for a pre-resolved URL from a match file (allowlist applied)."""
    if not allowed_media_url(url):
        return None
    host = urllib.parse.urlparse(url).hostname or ""
    source = ("thesportsdb" if "thesportsdb" in host else
              "wikimedia" if "wikimedia" in host else "espn")
    return {"url": url, "source": source, "license": None, "author": None, "attributionUrl": None}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get_json(url: str, source: str) -> Any:
    if _throttle:
        wait = _MIN_INTERVAL.get(source, 1.0) - (time.time() - _last_call.get(source, 0.0))
        if wait > 0:
            time.sleep(wait)
    _last_call[source] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimited(source) from e
        raise


def _strip_html(value: Any, limit: int = 120) -> Optional[str]:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


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
# Individual sports never use searchteams.php: "Putincewa J." is a person, so
# players go to Wikidata instead.
# ---------------------------------------------------------------------------

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


def _normalize_name(name: str) -> str:
    return name.strip().lower()


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


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _tsdb_record(team: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = team.get("strBadge") or team.get("strLogo") or None
    if not allowed_media_url(url):
        return None
    tid = team.get("idTeam")
    return {"url": url, "source": "thesportsdb", "license": None, "author": None,
            "attributionUrl": f"https://www.thesportsdb.com/team/{tid}" if tid else "https://www.thesportsdb.com"}


def _query_badge(term: str, sport: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One TheSportsDB team search. Returns a media record or None.

    With a known sport only a team of that sport counts ("Arsenal" the club, not
    a namesake in another sport)."""
    encoded = urllib.parse.quote(term, safe="")
    data = _get_json(f"{_SPORTSDB_BASE}/{_API_KEY}/searchteams.php?t={encoded}", "thesportsdb")
    teams: List[Any] = (data or {}).get("teams") or []
    want = _TSDB_SPORT.get(_sport_key(sport))
    for team in teams:
        if not isinstance(team, dict):
            continue
        if want and team.get("strSport") and team.get("strSport") != want:
            continue
        rec = _tsdb_record(team)
        if rec:
            return rec
    return None


def _tsdb_team(name: str, sport: Optional[str], max_terms: Optional[int] = None) -> Optional[Dict[str, Any]]:
    for term in _name_variants(name)[:max_terms]:
        rec = _query_badge(term, sport)
        if isinstance(rec, str):          # a bare URL (stubbed source)
            rec = media_from_url(rec)
        if rec:
            return rec
    return None


def _tsdb_player(name: str, sport: Optional[str]) -> Optional[Dict[str, Any]]:
    """TheSportsDB player search (full names only; the free key matches whole names)."""
    target = {fold(name, sport), player_alternative(name, sport)} - {""}
    words = [w for w in re.split(r"\s+", name.strip()) if len(w.strip(".")) > 1]
    if len(words) < 2:
        return None
    encoded = urllib.parse.quote(" ".join(words), safe="")
    data = _get_json(f"{_SPORTSDB_BASE}/{_API_KEY}/searchplayers.php?p={encoded}", "thesportsdb")
    want = _TSDB_SPORT.get(_sport_key(sport))
    for p in (data or {}).get("player") or []:
        if not isinstance(p, dict) or (want and p.get("strSport") != want):
            continue
        if fold(p.get("strPlayer"), sport) not in target:
            continue
        url = p.get("strCutout") or p.get("strThumb") or p.get("strRender")
        if allowed_media_url(url):
            pid = p.get("idPlayer")
            return {"url": url, "source": "thesportsdb", "license": None, "author": None,
                    "attributionUrl": f"https://www.thesportsdb.com/player/{pid}" if pid else "https://www.thesportsdb.com"}
    return None


_espn_teams: Dict[str, List[Tuple[set, str]]] = {}


def _espn_team(name: str, sport: Optional[str], league: Optional[str]) -> Optional[Dict[str, Any]]:
    """Big-league logo from ESPN's site API. Only with MEDIA_ALLOW_ESPN=1 (no license)."""
    if not espn_allowed():
        return None
    path = _ESPN_LEAGUES.get((_sport_key(sport), (league or "").strip().lower()))
    if not path:
        return None
    if path not in _espn_teams:
        data = _get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams", "espn")
        rows: List[Tuple[set, str]] = []
        for lg in ((data or {}).get("sports") or [{}])[0].get("leagues") or []:
            for t in lg.get("teams") or []:
                team = t.get("team") or {}
                logos = team.get("logos") or []
                href = logos[0].get("href") if logos else None
                names = {fold(team.get(k), sport) for k in ("displayName", "shortDisplayName", "name", "location")}
                if href:
                    rows.append((names - {""}, href))
        _espn_teams[path] = rows
    f = fold(name, sport)
    for names, href in _espn_teams[path]:
        if f in names and allowed_media_url(href):
            return {"url": href, "source": "espn", "license": None, "author": None,
                    "attributionUrl": "https://www.espn.com"}
    return None


def _commons_file(filename: str) -> Optional[Dict[str, Any]]:
    """Commons file -> {url, license, author, attributionUrl}; None when not a free file."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "256",
        "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|NonFree",
        "titles": f"File:{filename}",
    })
    data = _get_json(f"{_COMMONS_API}?{params}", "wikidata")
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        meta = info.get("extmetadata") or {}
        lic = _strip_html((meta.get("LicenseShortName") or {}).get("value"), 60)
        nonfree = str((meta.get("NonFree") or {}).get("value") or "").lower() in ("true", "1", "yes")
        if not lic or nonfree or re.search(r"fair use|non-free", lic, re.I):
            return None
        url = info.get("thumburl") or info.get("url")
        url = url.split("?", 1)[0] if url else url   # drop utm_* tracking params
        if not allowed_media_url(url):
            return None
        return {
            "url": url,
            "source": "wikimedia",
            "license": lic,
            "author": _strip_html((meta.get("Artist") or {}).get("value")) or "Unknown author",
            "attributionUrl": info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(filename)}",
        }
    return None


def _wd_search(text: str, statements: Iterable[str]) -> List[str]:
    query = " ".join([text] + [f"haswbstatement:{s}" for s in statements])
    params = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json",
                                     "srsearch": query, "srlimit": "5"})
    data = _get_json(f"{_WIKIDATA_API}?{params}", "wikidata")
    hits = ((data or {}).get("query") or {}).get("search") or []
    return [h.get("title") for h in hits if isinstance(h, dict) and str(h.get("title", "")).startswith("Q")]


def _wd_entities(ids: List[str]) -> Dict[str, Any]:
    params = urllib.parse.urlencode({"action": "wbgetentities", "format": "json",
                                     "ids": "|".join(ids), "props": "labels|aliases|claims",
                                     "languages": "en|pl"})
    data = _get_json(f"{_WIKIDATA_API}?{params}", "wikidata")
    return (data or {}).get("entities") or {}


def _wd_names(entity: Dict[str, Any]) -> List[str]:
    names = [v.get("value") for v in (entity.get("labels") or {}).values() if isinstance(v, dict)]
    for vals in (entity.get("aliases") or {}).values():
        names += [v.get("value") for v in vals if isinstance(v, dict)]
    return [n for n in names if n]


def _wd_file(entity: Dict[str, Any], prop: str) -> Optional[str]:
    for claim in (entity.get("claims") or {}).get(prop) or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value:
            return value
    return None


_MIN_BIRTH_YEAR = 1975   # players born earlier are not on today's tours


def _wd_birth_year(entity: Dict[str, Any]) -> Optional[int]:
    for claim in (entity.get("claims") or {}).get("P569") or []:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        m = re.match(r"^\+?(\d{4})-", str(value.get("time") or "")) if isinstance(value, dict) else None
        if m:
            return int(m.group(1))
    return None


def _wikidata(name: str, sport: Optional[str], kind: str) -> Optional[Dict[str, Any]]:
    """Wikidata P18 (players) / P154 (clubs) with Commons license + author.

    Only an unambiguous name match counts: two candidates that both fold to the
    name (e.g. two "Y. Jeong") give no photo rather than possibly the wrong face."""
    sp = _sport_key(sport)
    prop = "P18" if kind == "photo" else "P154"
    if kind == "photo":
        occ = _WD_OCCUPATION.get(sp)
        if not occ:
            return None
        statements = [f"P106={occ}", prop]
        targets = {fold(name, sp), player_alternative(name, sp)} - {""}
        text = " ".join(w for w in re.split(r"\s+", name.strip()) if len(w.strip(".")) > 1)
    else:
        wd_sport = _WD_SPORT.get(sp)
        statements = ([f"P641={wd_sport}"] if wd_sport else []) + [prop]
        targets = {fold(v, sp) for v in _name_variants(name)} - {""}
        text = name.strip()
    if not text:
        return None
    ids = _wd_search(text, statements)
    if not ids:
        return None
    matches = []
    for qid, entity in _wd_entities(ids).items():
        if kind == "photo" and (_wd_birth_year(entity) or 9999) < _MIN_BIRTH_YEAR:
            continue                                  # a retired namesake, not today's player
        if any(fold(n, sp) in targets for n in _wd_names(entity)):
            filename = _wd_file(entity, prop)
            if filename:
                matches.append(filename)
    if len(set(matches)) != 1:
        return None
    return _commons_file(matches[0])


# ---------------------------------------------------------------------------
# Core lookup
# ---------------------------------------------------------------------------

def _lookup(name: str, sport: Optional[str], kind: str, league: Optional[str],
            network: str) -> Optional[Dict[str, Any]]:
    """Run the source chain. network: 'full' (filler) or 'tsdb' (request time, teams only)."""
    if kind == "photo":
        if network != "full":
            return None
        rec = _wikidata(name, sport, "photo")
        if not rec and _sport_key(sport) == "tennis":
            rec = _tsdb_player(name, sport)
        return rec
    rec = _tsdb_team(name, sport, max_terms=None if network == "full" else 2)
    if rec or network != "full":
        return rec
    rec = _espn_team(name, sport, league)
    if rec:
        return rec
    return _wikidata(name, sport, "logo")


def resolve_media(name: str, sport: Optional[str] = None, kind: Optional[str] = None,
                  league: Optional[str] = None, network: str = "full",
                  force: bool = False) -> Optional[Dict[str, Any]]:
    """Logo (teams) or photo (players) for *name* as ``{url, source, license, author,
    attributionUrl}``, or None.

    network: 'full' runs every source, 'tsdb' only TheSportsDB (teams), 'none' is
    cache only. Results (misses too) go into the in-memory cache; the file is only
    written by save_media_cache() (the filler).
    """
    if not name or not str(name).strip():
        return None
    kind = kind or _kind_for(sport)
    if kind == "photo" and "/" in name:
        return None                                   # doubles: no single photo
    cache = _load_file_cache()
    key = cache_key(name, sport, kind)
    now = time.time()
    cached = cache.get(key)
    # Migrated team_logos_cache.json hit (sport unknown): fallback for teams only.
    legacy = cache.get(f"any|logo|{fold(name, 'any')}") if kind == "logo" else None
    if cached and _fresh(cached, now) and not force:
        return _public(cached) or _public(legacy)
    if network == "none":
        return (_public(cached) if cached and cached.get("url") else None) or _public(legacy)

    try:
        rec = _lookup(name, sport, kind, league, network)
        entry: Dict[str, Any] = dict(rec, ts=int(now)) if rec else {"url": None, "miss": "none", "ts": int(now)}
    except _RateLimited as e:
        entry = {"url": None, "miss": "429", "rateLimitedBy": str(e) or None, "ts": int(now)}
    except Exception:
        entry = {"url": None, "miss": "error", "ts": int(now)}
    if entry.get("miss") in ("error", "429") and cached and cached.get("url"):
        # A failed refresh keeps the stale hit (retried on the next run).
        entry = cached
    cache[key] = entry
    return _public(entry) or _public(legacy)


def get_logo_url(team_name: str, sport: Optional[str] = None) -> Optional[str]:
    """Badge URL for a team or None (wrapper over resolve_media).

    Individual sports return None without any request: competitors are people,
    and their photos come from resolve_media(kind='photo')."""
    if not team_name or not team_name.strip():
        return None
    if sport and sport.strip().lower() in _INDIVIDUAL_SPORTS:
        return None
    rec = resolve_media(team_name, sport, "logo")
    return rec["url"] if rec else None


def get_logo_url_cached_only(team_name: str, sport: Optional[str] = None) -> Optional[str]:
    """Logo URL only from the cache – no network call."""
    if not team_name:
        return None
    rec = resolve_media(team_name, sport, "logo", network="none")
    return rec["url"] if rec else None


def media_for_page(matches: List[Dict[str, Any]], live_budget: int = LIVE_LOOKUPS_PER_REQUEST) -> List[Dict[str, Any]]:
    """Fill homeLogo/awayLogo + homeMedia/awayMedia for one API page.

    Cache only, plus at most *live_budget* TheSportsDB lookups for team names the
    cache has never seen (players are never looked up live). Nothing is written
    to disk."""
    cache = _load_file_cache()
    for m in matches:
        sport = m.get("sport")
        kind = _kind_for(sport)
        for side in ("home", "away"):
            try:
                name = m.get(f"{side}Team")
                pre = media_from_url(m.get(f"{side}Logo"))
                if pre:
                    m[f"{side}Logo"] = pre["url"]
                    m[f"{side}Media"] = pre
                    continue
                m[f"{side}Logo"] = ""
                m[f"{side}Media"] = None
                if not name:
                    continue
                rec = resolve_media(name, sport, kind, league=m.get("league"), network="none")
                if (not rec and kind == "logo" and live_budget > 0
                        and cache_key(name, sport, kind) not in cache):
                    live_budget -= 1
                    rec = resolve_media(name, sport, kind, network="tsdb")
                if rec:
                    m[f"{side}Logo"] = rec["url"]
                    m[f"{side}Media"] = rec
            except Exception:
                continue
    return matches


# ---------------------------------------------------------------------------
# Batch enrichment (legacy helper)
# ---------------------------------------------------------------------------

def enrich_matches_with_logos(matches: List[Dict[str, Any]]) -> None:
    """
    Add ``home_logo_url`` and ``away_logo_url`` to each match dict (in-place).

    Each unique team name hits the network at most once.
    """
    team_names: set = set()
    for m in matches:
        for k in ("home_team", "away_team"):
            if m.get(k):
                team_names.add(m[k])
    resolved: Dict[str, Optional[str]] = {name: get_logo_url(name) for name in team_names}
    for m in matches:
        m["home_logo_url"] = resolved.get(m.get("home_team", ""))
        m["away_logo_url"] = resolved.get(m.get("away_team", ""))


# ---------------------------------------------------------------------------
# Filler (media_cache.yml)
# ---------------------------------------------------------------------------

def migrate_legacy_cache() -> int:
    """Copy team_logos_cache.json hits (no sport recorded) to ``any|logo|<fold>``."""
    if not _LEGACY_CACHE_FILE.exists():
        return 0
    try:
        legacy = json.loads(_LEGACY_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    cache = _load_file_cache()
    added = 0
    for name, v in legacy.items():
        url = (v or {}).get("url") if isinstance(v, dict) else None
        rec = media_from_url(url)
        key = f"any|logo|{fold(name, 'any')}"
        if rec and key not in cache:
            cache[key] = dict(rec, attributionUrl="https://www.thesportsdb.com",
                              ts=int((v or {}).get("ts") or time.time()))
            added += 1
    return added


def competitors(days: List[str], results_dir: Path) -> List[Tuple[str, str, Optional[str], bool]]:
    """(name, sport, league, qualifies) from results/matches_<day>_*.json, qualifying first."""
    seen: Dict[Tuple[str, str], Tuple[str, str, Optional[str], bool]] = {}
    for day in days:
        for f in sorted(results_dir.glob(f"matches_{day}_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rows = data.get("matches") if isinstance(data, dict) else data
            file_sport = data.get("sport") if isinstance(data, dict) else None
            for m in rows or []:
                if not isinstance(m, dict):
                    continue
                sport = _sport_key(m.get("sport") or file_sport)
                if sport == "any":
                    continue
                for k in ("homeTeam", "awayTeam", "home_team", "away_team"):
                    name = (m.get(k) or "").strip()
                    if not name:
                        continue
                    key = (sport, fold(name, sport))
                    q = bool(m.get("qualifies"))
                    if key not in seen or (q and not seen[key][3]):
                        seen[key] = (name, sport, m.get("league"), q)
    return sorted(seen.values(), key=lambda c: (not c[3], c[1], c[0].lower()))


def fill(days: List[str], budget_sec: float, results_dir: Path) -> Dict[str, int]:
    """Look up every competitor without a fresh cache entry until the time budget runs out."""
    global _throttle
    _throttle = True
    started = time.time()
    stats = {"competitors": 0, "fresh": 0, "looked_up": 0, "hits": 0, "rate_limited": 0,
             "migrated": migrate_legacy_cache(), "skipped_budget": 0}
    cache = _load_file_cache()
    for name, sport, league, _q in competitors(days, results_dir):
        stats["competitors"] += 1
        kind = _kind_for(sport)
        if kind == "photo" and "/" in name:
            continue
        if _fresh(cache.get(cache_key(name, sport, kind)), time.time()):
            stats["fresh"] += 1
            continue
        if time.time() - started > budget_sec:
            stats["skipped_budget"] += 1
            continue
        rec = resolve_media(name, sport, kind, league=league, network="full", force=True)
        stats["looked_up"] += 1
        entry = cache.get(cache_key(name, sport, kind)) or {}
        if not rec and entry.get("miss") == "429":
            # Wait out the per-minute window, slow that source down, retry once.
            stats["rate_limited"] += 1
            src = entry.get("rateLimitedBy") or "thesportsdb"
            _MIN_INTERVAL[src] = min(6.0, _MIN_INTERVAL.get(src, 1.0) * 1.5)
            time.sleep(60)
            rec = resolve_media(name, sport, kind, league=league, network="full", force=True)
        if rec:
            stats["hits"] += 1
    save_media_cache()
    _throttle = False
    return stats


def _main(argv: List[str]) -> int:
    import argparse
    from datetime import datetime, timedelta, timezone
    ap = argparse.ArgumentParser(description="Fill outputs/media_cache.json (logos/photos).")
    ap.add_argument("--fill", action="store_true", required=True)
    ap.add_argument("--days", default="", help="comma-separated YYYY-MM-DD (default: today+tomorrow UTC)")
    ap.add_argument("--budget-sec", type=float, default=300.0)
    ap.add_argument("--results-dir", default=str(_ROOT / "results"))
    a = ap.parse_args(argv)
    today = datetime.now(timezone.utc).date()
    days = [d.strip() for d in a.days.split(",") if d.strip()] or \
        [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    for d in days:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            print(f"bad day {d!r}")
            return 1
    stats = fill(days, a.budget_sec, Path(a.results_dir))
    print(f"media cache {days}: " + ", ".join(f"{k}={v}" for k, v in stats.items())
          + f", entries={len(_mem_cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
