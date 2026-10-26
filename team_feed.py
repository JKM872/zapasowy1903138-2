"""Team history for GET /api/teams/<name> (design K6).

Reads the per-sport index written by tools/build_team_index.py
(outputs/team_index/<sport>.json.gz) and the alias table
(outputs/team_aliases.json). Each sport is loaded on first use and reloaded
when its file changes; answers are cached per (sport, team, limit) for
CACHE_TTL_S. ``ourPicks`` comes from top_feed.load_top in the visitor view, so
it never shows a pick the paywall hides, and its record uses top_feed's single
summary (withdrawn picks excluded).

get_team(name, sport, limit) -> (http_status, body):
- 400 {error} for bad input (name 1-80 chars, sport in SPORTS, limit 1-50);
- 404 {error: "team not found", suggestions: [<=5 names]};
- 200 {team, sport, aliases, games, last, form, home, away, ourPicks, sources}.
"""
from __future__ import annotations

import difflib
import gzip
import json
import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools.team_names import fold, player_alternative, split_match  # noqa: E402

INDEX_DIR = os.path.join(ROOT, 'outputs', 'team_index')
ALIASES_PATH = os.path.join(ROOT, 'outputs', 'team_aliases.json')
SPORTS = ('football', 'basketball', 'tennis', 'hockey', 'handball', 'volleyball',
          'baseball', 'table_tennis', 'rugby')
SOURCES = ('result_store', 'supabase')
NAME_MAX = 80
LIMIT_DEFAULT, LIMIT_MAX = 20, 50
FORM_N = 5
CACHE_TTL_S = 600
CACHE_MAX = 512
SUGGEST_N = 5

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_indexes: Dict[str, Dict[str, Any]] = {}
_aliases: Dict[str, Any] = {'mtime': None, 'map': {}}
_cache: 'OrderedDict[Tuple[str, str, int], Tuple[float, Tuple[int, Dict[str, Any]]]]' = OrderedDict()


def clear_cache() -> None:
    with _lock:
        _indexes.clear()
        _cache.clear()
        _aliases.update(mtime=None, map={})


def _load_index(sport: str, index_dir: str) -> Optional[Dict[str, Any]]:
    """Index of one sport plus team -> game positions; None when missing."""
    path = os.path.join(index_dir, f'{sport}.json.gz')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _indexes.get(sport)
    if cached and cached['mtime'] == mtime and cached['path'] == path:
        return cached
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning('team index %s unreadable: %s', sport, type(e).__name__)
        return None
    games = raw.get('games') or []
    by_team: Dict[str, List[int]] = {}
    for i, g in enumerate(games):
        by_team.setdefault(g[1], []).append(i)
        by_team.setdefault(g[2], []).append(i)
    idx = {'mtime': mtime, 'path': path, 'teams': raw.get('teams') or {},
           'games': games, 'byTeam': by_team}
    _indexes[sport] = idx
    return idx


def _alias_map(path: str) -> Dict[str, str]:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _aliases['mtime'] != mtime or _aliases.get('path') != path:
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                m = json.load(fh).get('aliases') or {}
        except (OSError, ValueError, AttributeError):
            m = {}
        _aliases.update(mtime=mtime, path=path, map=m if isinstance(m, dict) else {})
    return _aliases['map']


def resolve(name: Any, sport: str, aliases: Dict[str, str]) -> str:
    """Folded index key for a raw name (alias-mapped)."""
    k = fold(name, sport)
    return aliases.get(f'{sport}|{k}', k)


def _display(idx: Dict[str, Any], key: str) -> str:
    names = idx['teams'].get(key) or []
    return names[0] if names else key


def _suggest(idx: Optional[Dict[str, Any]], key: str) -> List[str]:
    if not idx or not key:
        return []
    teams = idx['teams']
    count = lambda k: len(idx['byTeam'].get(k, ()))  # noqa: E731
    pref = sorted((k for k in teams if k.startswith(key) or key in k.split()), key=lambda k: (-count(k), k))
    close = difflib.get_close_matches(key, list(teams), n=SUGGEST_N, cutoff=0.75)
    out: List[str] = []
    for k in pref[:SUGGEST_N] + close:
        name = _display(idx, k)
        if name not in out:
            out.append(name)
    return out[:SUGGEST_N]


def _wdl(own: int, opp: int) -> str:
    return 'W' if own > opp else 'L' if own < opp else 'D'


def _our_picks(sport: str, key: str, aliases: Dict[str, str],
               top_loader: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    empty = {'n': 0, 'won': 0, 'roi': None, 'picks': []}
    try:
        import top_feed
        data = top_loader()
    except Exception as e:  # the record is a bonus; history still answers
        logger.warning('ourPicks unavailable: %s', type(e).__name__)
        return empty
    rows = []
    for day in data.get('days') or []:
        for p in day.get('picks') or []:
            if p.get('sport') != sport:
                continue
            home, away = split_match(p.get('match'))
            if key not in (resolve(home, sport, aliases), resolve(away, sport, aliases)):
                continue
            rows.append(p)
    s = top_feed._summary(rows)
    return {
        'n': s['settled'], 'won': s['won'], 'roi': s['roi'],
        'picks': [{'date': p.get('date'), 'match': p.get('match'),
                   'pick': None if p.get('selectionLocked') else p.get('pick') or None,
                   'odds': None if p.get('selectionLocked') else p.get('odds'),
                   'status': top_feed._status(p)}
                  for p in sorted(rows, key=lambda p: p.get('date') or '', reverse=True)],
    }


def _validate(name: Any, sport: Any, limit: Any) -> Tuple[Optional[str], str, str, int]:
    name = str(name or '').strip()
    sport = str(sport or '').strip().lower()
    if not name:
        return 'name is required', name, sport, 0
    if len(name) > NAME_MAX:
        return f'name must be at most {NAME_MAX} characters', name, sport, 0
    if not sport:
        return 'sport is required', name, sport, 0
    if sport not in SPORTS:
        return f'sport must be one of: {", ".join(SPORTS)}', name, sport, 0
    if limit in (None, ''):
        n = LIMIT_DEFAULT
    else:
        try:
            n = int(str(limit).strip())
        except ValueError:
            return f'limit must be an integer 1-{LIMIT_MAX}', name, sport, 0
        if not 1 <= n <= LIMIT_MAX:
            return f'limit must be an integer 1-{LIMIT_MAX}', name, sport, 0
    if not fold(name, sport):
        return 'name has no letters or digits', name, sport, 0
    return None, name, sport, n


def get_team(name: Any, sport: Any, limit: Any = None, index_dir: str = INDEX_DIR,
             aliases_path: str = ALIASES_PATH,
             top_loader: Optional[Callable[[], Dict[str, Any]]] = None,
             now: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
    err, name, sport, limit = _validate(name, sport, limit)
    if err:
        return 400, {'error': err}
    now = time.time() if now is None else now
    with _lock:
        aliases = _alias_map(aliases_path)
        key = resolve(name, sport, aliases)
        ck = (sport, key, limit)
        hit = _cache.get(ck)
        if hit and now - hit[0] < CACHE_TTL_S:
            _cache.move_to_end(ck)
            return hit[1]
        idx = _load_index(sport, index_dir)
    if idx and key not in idx['byTeam']:
        alt = player_alternative(name, sport)
        alt = aliases.get(f'{sport}|{alt}', alt)
        if alt and alt in idx['byTeam']:
            key = alt
    if not idx or key not in idx['byTeam']:
        logger.info('team not found: %s|%s', sport, key)
        return 404, {'error': 'team not found', 'suggestions': _suggest(idx, key)}

    if top_loader is None:
        def top_loader():
            from top_feed import load_top
            return load_top(is_subscriber=False)

    games = [idx['games'][i] for i in idx['byTeam'][key]]
    games.sort(key=lambda g: g[0], reverse=True)
    rec = {'home': {'w': 0, 'd': 0, 'l': 0}, 'away': {'w': 0, 'd': 0, 'l': 0}}
    last = []
    form = ''
    srcs = set()
    for g in games:
        d, h, a, sh, sa, src = g[:6]
        venue = 'home' if h == key else 'away'
        own, opp = (sh, sa) if venue == 'home' else (sa, sh)
        res = _wdl(own, opp)
        rec[venue][res.lower()] += 1
        srcs.add(src)
        if len(form) < FORM_N:
            form += res
        if len(last) < limit:
            last.append({'date': d, 'opponent': _display(idx, a if venue == 'home' else h),
                         'venue': venue, 'score': f'{own}-{opp}', 'result': res})
    display = _display(idx, key)
    body = {
        'team': display, 'sport': sport,
        'aliases': [n for n in (idx['teams'].get(key) or []) if n != display],
        'games': len(games),
        'last': last,
        'form': form,
        'home': rec['home'], 'away': rec['away'],
        'ourPicks': _our_picks(sport, key, aliases, top_loader),
        'sources': [SOURCES[s] for s in sorted(srcs) if 0 <= s < len(SOURCES)],
    }
    out = (200, body)
    with _lock:
        _cache[ck] = (now, out)
        _cache.move_to_end(ck)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return out
