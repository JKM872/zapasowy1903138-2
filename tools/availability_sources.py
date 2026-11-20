"""Free availability sources beside SofaScore, driven by a registry.

The registry ``config/availability_sources.json`` maps sport -> league ->
ordered source names; each source names a fetcher in ``FETCHERS``. Adding a
source is one registry entry plus one fetcher function returning

    {normalised_team_name: [{'name', 'status': 'out|doubtful|plays',
                             'reason', 'source', 'url'}]}

Every fetcher is non-blocking: one GET with a timeout (<= 10 s), robots.txt
checked first (unreachable robots = skip, like urllib.robotparser), at most
one request per second per host, one cached copy of each page per day under
``results/cache/``. Any error returns ``{}`` so the scrapers that depend on
the same machine keep running.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import time
import unicodedata
import urllib.robotparser
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(ROOT, 'config', 'availability_sources.json')
CACHE_DIR = os.path.join(ROOT, 'results', 'cache')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
STATS: Dict[str, int] = {}

_registry: Optional[Dict[str, Any]] = None
_robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
_last_hit: Dict[str, float] = {}
_parsed: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}


def _stat(k: str) -> None:
    STATS[k] = STATS.get(k, 0) + 1


# ── registry ──────────────────────────────────────────────────────────────────

def registry() -> Dict[str, Any]:
    global _registry
    if _registry is None:
        try:
            _registry = json.load(open(REGISTRY_PATH, encoding='utf-8'))
        except Exception:
            _registry = {}
    return _registry


def sources_for(sport: str, league: Any = '', country: Any = '') -> List[str]:
    """Ordered source names for a sport/league; enabled sources only.

    League keys are tried as 'country|league', then 'league' (lower case);
    otherwise the sport's default list. 'sofascore' is always first when listed."""
    reg = registry()
    sp = (reg.get('sports') or {}).get(sport) or {}
    leagues = sp.get('leagues') or {}
    lg, co = str(league or '').strip().lower(), str(country or '').strip().lower()
    names = leagues.get(f'{co}|{lg}') or leagues.get(lg) or sp.get('default') or ['sofascore']
    out = []
    for n in names:
        meta = reg.get('sofascore') if n == 'sofascore' else (reg.get('sources') or {}).get(n)
        if meta and meta.get('enabled') and (n == 'sofascore' or meta.get('fetcher') in FETCHERS):
            out.append(n)
    return out


def source_meta(name: str) -> Dict[str, Any]:
    reg = registry()
    return (reg.get('sofascore') if name == 'sofascore' else (reg.get('sources') or {}).get(name)) or {}


# ── names ─────────────────────────────────────────────────────────────────────

_STOP = {'fc', 'cf', 'afc', 'sc', 'ac', 'fk', 'sk', 'cd', 'ud', 'sv', 'the', 'club', 'de', 'cp', 'bk', 'hc'}


def norm(name: Any) -> str:
    s = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]+', ' ', s)
    return ' '.join(t for t in s.split() if t not in _STOP)


def surname(name: Any) -> str:
    toks = norm(name).split()
    return toks[-1] if toks else ''


def match_team(team: str, table: Dict[str, Any]) -> Optional[str]:
    """Key of ``table`` naming the same team: exact, else one name's tokens all
    inside the other's ('Thunder' ~ 'Oklahoma City Thunder'). Ambiguous -> None."""
    t = norm(team)
    if not t or not table:
        return None
    if t in table:
        return t
    tt = set(t.split())
    hits = [k for k in table if k and (set(k.split()) <= tt or tt <= set(k.split()))]
    return hits[0] if len(hits) == 1 else None


# ── fetching ──────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _allowed(url: str, timeout: float) -> bool:
    host = '/'.join(url.split('/')[:3])
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            import requests
            r = requests.get(host + '/robots.txt', headers={'User-Agent': UA}, timeout=timeout)
            if r.status_code >= 500:
                raise IOError(r.status_code)
            rp.parse(r.text.splitlines() if r.status_code < 400 else [])
            _robots[host] = rp
        except Exception:
            _stat('robots_unreachable')
            _robots[host] = None
    rp = _robots[host]
    return bool(rp and rp.can_fetch(UA, url))


def fetch_page(name: str, url: str, timeout: float = 10, day: Optional[str] = None) -> Optional[str]:
    """Cached GET (one copy per page per day); None on any error or robots deny."""
    day = day or _today()
    path = os.path.join(CACHE_DIR, f'avail_src_{name}_{day}.html')
    try:
        if os.path.exists(path):
            return open(path, encoding='utf-8').read()
    except Exception:
        pass
    timeout = min(float(timeout or 10), 10.0)
    try:
        if not _allowed(url, timeout):
            _stat(f'{name}_robots_skip')
            return None
        import requests
        host = url.split('/')[2]
        wait = 1.0 - (time.monotonic() - _last_hit.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.monotonic()
        r = requests.get(url, headers={'User-Agent': UA, 'Accept-Language': 'en'}, timeout=timeout)
        if r.status_code != 200 or not r.text:
            _stat(f'{name}_http_{r.status_code}')
            return None
        txt = r.text
    except Exception:
        _stat(f'{name}_error')
        return None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(txt)
    except Exception:
        pass
    return txt


def _strip(s: str) -> str:
    return ' '.join(_html.unescape(re.sub(r'<[^>]+>', ' ', s or '')).split())


# ── parsers (pure, tested on saved pages) ─────────────────────────────────────

_RW_STATUS = {'out': 'out', 'ofs': 'out', 'ir': 'out', 'ir-lt': 'out', 'ir-nr': 'out', 'susp': 'out',
              'ltir': 'out', 'ques': 'doubtful', 'gtd': 'doubtful', 'doubt': 'doubtful',
              'dtd': 'doubtful', 'prob': 'plays'}


def parse_rotowire(page: str, source: str, url: str = '') -> Dict[str, List[Dict[str, Any]]]:
    """RotoWire lineups page (NBA / NHL) -> {team: rows}.

    Starters of an expected/confirmed line-up and a highlighted goalie are
    'plays'; players with an injury tag (Out, IR, Ques, GTD ...) are out or
    doubtful."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not page:
        return out
    blocks = re.split(r'<div class="lineup is-(?:nba|nhl)[^"]*"', page)[1:]
    for b in blocks:
        names = {}
        for side in ('visit', 'home'):
            m = re.search(r'class="lineup__mteam is-%s[^"]*"[^>]*>(.*?)<span' % side, b, re.S)
            names[side] = _strip(m.group(1)) if m else ''
        for side in ('visit', 'home'):
            m = re.search(r'<ul class="lineup__list is-%s">(.*?)</ul>' % side, b, re.S)
            team = norm(names.get(side))
            if not m or not team:
                continue
            ul = m.group(1)
            st = re.search(r'lineup__status is-(\w+)', ul)
            lineup_kind = st.group(1) if st else ''
            rows: List[Dict[str, Any]] = []
            g = re.search(r'lineup__player-highlight-name">\s*<a[^>]*>(.*?)</a>.*?is-(confirmed|likely|expected|unconfirmed)',
                          ul, re.S)
            if g:
                rows.append({'name': _strip(g.group(1)), 'status': 'plays' if g.group(2) in ('confirmed', 'likely') else 'doubtful',
                             'reason': f'starting goalie ({g.group(2)})', 'source': source, 'url': url})
            middle = ul.find('lineup__title is-middle')
            for li in re.finditer(r'<li class="lineup__player[^"]*"[^>]*>(.*?)</li>', ul, re.S):
                a = re.search(r'<a title="([^"]+)"', li.group(1))
                if not a:
                    continue
                inj = re.search(r'lineup__inj">([^<]+)<', li.group(1))
                tag = (inj.group(1).strip().lower() if inj else '')
                if tag:
                    status = _RW_STATUS.get(tag, 'doubtful')
                    reason = inj.group(1).strip()
                elif middle < 0 or li.start() < middle:
                    status, reason = 'plays', f'{lineup_kind or "expected"} line-up'
                else:
                    continue
                rows.append({'name': _html.unescape(a.group(1)), 'status': status, 'reason': reason,
                             'source': source, 'url': url})
            if rows:
                seen, uniq = set(), []
                for r in rows:   # a starter tagged "Ques" also appears under MAY NOT PLAY
                    k = (r['name'], r['status'])
                    if k not in seen:
                        seen.add(k)
                        uniq.append(r)
                out.setdefault(team, []).extend(uniq)
    return out


def parse_dailyfaceoff(page: str, url: str = '') -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page or '', re.S)
    if not m:
        return out
    try:
        games = ((json.loads(m.group(1)).get('props') or {}).get('pageProps') or {}).get('data') or []
    except Exception:
        return out
    for g in games:
        for side in ('home', 'away'):
            team, goalie = g.get(f'{side}TeamName'), g.get(f'{side}GoalieName')
            strength = str(g.get(f'{side}NewsStrengthName') or '').lower()
            if not team or not goalie:
                continue
            status = 'plays' if strength in ('confirmed', 'likely') else 'doubtful'
            out.setdefault(norm(team), []).append({
                'name': goalie, 'status': status, 'reason': f'starting goalie ({strength or "unconfirmed"})',
                'source': 'dailyfaceoff', 'url': url})
    return out


def parse_transfermarkt(page: str, url: str = '') -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    t = re.search(r'<table class="items">(.*?)</table>\s*</div>', page or '', re.S)
    body = t.group(1) if t else (page or '')
    for row in re.finditer(r'<tr class="(?:odd|even)">(.*?)</tr>\s*(?=<tr class="(?:odd|even)">|</tbody>)', body, re.S):
        r = row.group(1)
        p = re.search(r'<td class="hauptlink">\s*<a title="([^"]+)"', r)
        c = re.search(r'<a title="([^"]+)" href="/[^"]+/startseite/verein/', r)
        inj = re.findall(r'<td class="links">(.*?)</td>', r, re.S)
        if not p or not c:
            continue
        out.setdefault(norm(_html.unescape(c.group(1))), []).append({
            'name': _html.unescape(p.group(1)), 'status': 'out',
            'reason': _strip(inj[-1]) if inj else 'injury', 'source': 'transfermarkt', 'url': url})
    return out


# ── fetchers ──────────────────────────────────────────────────────────────────

def _cached_parse(key: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    if key not in _parsed:
        try:
            _parsed[key] = fn() or {}
        except Exception:
            _stat(f'{key}_parse_error')
            _parsed[key] = {}
    return _parsed[key]


def _src(name: str) -> Dict[str, Any]:
    return (registry().get('sources') or {}).get(name) or {}


def rotowire_nba(day: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    s = _src('rotowire_nba')
    url = s.get('url') or 'https://www.rotowire.com/basketball/nba-lineups.php'
    return _cached_parse('rotowire_nba', lambda: parse_rotowire(
        fetch_page('rotowire_nba', url, s.get('timeout', 10), day) or '', 'rotowire', url))


def rotowire_nhl(day: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    s = _src('rotowire_nhl')
    url = s.get('url') or 'https://www.rotowire.com/hockey/nhl-lineups.php'
    return _cached_parse('rotowire_nhl', lambda: parse_rotowire(
        fetch_page('rotowire_nhl', url, s.get('timeout', 10), day) or '', 'rotowire', url))


def dailyfaceoff_goalies(day: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    s = _src('dailyfaceoff_goalies')
    url = s.get('url') or 'https://www.dailyfaceoff.com/starting-goalies'
    return _cached_parse('dailyfaceoff', lambda: parse_dailyfaceoff(
        fetch_page('dailyfaceoff', url, s.get('timeout', 10), day) or '', url))


def transfermarkt_injuries(league_code: str, day: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    code = str(league_code or '').upper()
    meta = next((v for v in (registry().get('sources') or {}).values()
                 if v.get('fetcher') == 'transfermarkt_injuries' and v.get('league_code') == code), {})
    url = meta.get('url') or f'https://www.transfermarkt.com/x/verletztespieler/wettbewerb/{code}'
    return _cached_parse(f'tm_{code}', lambda: parse_transfermarkt(
        fetch_page(f'transfermarkt_{code}', url, meta.get('timeout', 10), day) or '', url))


_ESPN_STATUS = {'out': 'out', 'injured reserve': 'out', 'suspension': 'out', 'suspended': 'out',
                'doubtful': 'doubtful', 'questionable': 'doubtful', 'day-to-day': 'doubtful',
                'game time decision': 'doubtful', 'probable': 'plays', 'active': 'plays'}


def parse_espn_injuries(data: Any, url: str = '') -> Dict[str, List[Dict[str, Any]]]:
    """ESPN public ``/sports/<sport>/<league>/injuries`` JSON -> {team: rows}.
    Unknown statuses (e.g. '7-day IL', 'Out For Season') with 'out'/'il' count as out."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for t in (data or {}).get('injuries') or []:
        team = norm(t.get('displayName'))
        if not team:
            continue
        rows = []
        for i in t.get('injuries') or []:
            a = i.get('athlete') or {}
            name = a.get('displayName') or a.get('shortName')
            raw = str(i.get('status') or (i.get('type') or {}).get('description') or '').strip()
            st = _ESPN_STATUS.get(raw.lower())
            if st is None:
                low = raw.lower()
                st = 'out' if ('out' in low or ' il' in f' {low}' or 'reserve' in low) else 'doubtful'
            if not name or st == 'plays':
                continue
            pos = ((a.get('position') or {}).get('abbreviation')) or None
            rows.append({'name': name, 'status': st, 'reason': raw + (f" ({i.get('shortComment')[:120]})"
                         if i.get('shortComment') else ''), 'position': pos, 'date': i.get('date'),
                         'source': 'espn', 'url': url})
        if rows:
            out[team] = rows
    return out


def espn_injuries(path: str, timeout: float = 12, day: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    url = f'https://site.api.espn.com/apis/site/v2/sports/{path}/injuries'

    def _get():
        import requests
        r = requests.get(url, timeout=timeout, headers={'User-Agent': UA})
        _stat(f'espn_http_{r.status_code}')
        return parse_espn_injuries(r.json() if r.status_code == 200 else {}, url)
    return _cached_parse(f'espn_{path}', _get)


FETCHERS: Dict[str, Callable[..., Dict[str, List[Dict[str, Any]]]]] = {
    'espn_injuries': lambda meta, day=None: espn_injuries(meta.get('path'), meta.get('timeout', 12), day),
    'rotowire_nba': lambda meta, day=None: rotowire_nba(day),
    'rotowire_nhl': lambda meta, day=None: rotowire_nhl(day),
    'dailyfaceoff_goalies': lambda meta, day=None: dailyfaceoff_goalies(day),
    'transfermarkt_injuries': lambda meta, day=None: transfermarkt_injuries(meta.get('league_code'), day),
}


def rows_for_match(sport: str, league: Any, country: Any, home: str, away: str,
                   day: Optional[str] = None) -> Dict[str, Any]:
    """{'home': rows, 'away': rows, 'sources': [names that matched a team]} from
    every enabled non-SofaScore source for this sport/league. Never raises."""
    res: Dict[str, Any] = {'home': [], 'away': [], 'sources': []}
    for name in sources_for(sport, league, country):
        if name == 'sofascore':
            continue
        meta = source_meta(name)
        try:
            table = FETCHERS[meta['fetcher']](meta, day) or {}
        except Exception:
            _stat(f'{name}_error')
            continue
        hit = False
        for side, team in (('home', home), ('away', away)):
            k = match_team(team, table)
            if k:
                hit = True
                have = {surname(r['name']) for r in res[side]}
                res[side].extend(r for r in table[k] if surname(r['name']) not in have)
        if hit:
            res['sources'].append(name)
            _stat(f'{name}_match')
    return res
