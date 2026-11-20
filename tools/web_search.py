"""Team-news web search: Tavily first, Brave second, both on free monthly credit.

Keys: TAVILY_API_KEYS / BRAVE_API_KEYS (comma-separated). A key answering
401/429/432/433 is skipped for the rest of the run. Usage is persisted in
outputs/search_usage_<YYYY-MM>.json (no key values, only short hashes) so
the monthly free credit is never exceeded; results are cached per match per day.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import calendar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAVILY_URL = 'https://api.tavily.com/search'
BRAVE_URL = 'https://api.search.brave.com/res/v1/web/search'
MONTHLY = {'tavily': int(os.getenv('TAVILY_MONTHLY_CREDITS', '1000')),
           'brave': int(os.getenv('BRAVE_MONTHLY_QUERIES', '1000'))}
SAFETY = 0.95                      # keep 5% headroom of every key's monthly credit
COST = {'tavily': 1, 'brave': 1}   # basic search = 1 credit; one Brave query ~= $0.005
DEAD_CODES = (401, 429, 432, 433)
# Share of today's allowance each tier may use (TOP > Fan Favourites > Forebet A/B).
TIER_SHARE = {'top': 1.0, 'fan': 0.85, 'ab': 0.6}

STATS: Dict[str, int] = {}
_DEAD: set = set()


def _stat(k: str) -> None:
    STATS[k] = STATS.get(k, 0) + 1


def keys(provider: str) -> List[str]:
    raw = os.getenv(f'{provider.upper()}_API_KEYS', '') or os.getenv(f'{provider.upper()}_API_KEY', '')
    out: List[str] = []
    for k in raw.replace('\n', ',').split(','):
        k = k.strip()
        if k and k not in out:
            out.append(k)
    return out


def kid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


# ── query wording ─────────────────────────────────────────────────────────────

_WORDS = {
    'football': 'injuries suspensions team news predicted lineup',
    'basketball': 'injury report out questionable starting lineup',
    'hockey': 'injuries lineup goalie starter team news',
    'handball': 'injuries squad team news',
    'volleyball': 'injuries squad lineup',
    'baseball': 'injured list probable pitchers lineup',
    'rugby': 'team news injuries starting XV',
    'tennis': 'injury withdrawal fitness news',
}


def query(sport: str, home: str, away: str, day: str) -> str:
    return f"{home} vs {away} {_WORDS.get(sport, 'injuries team news lineup')} {day}"


# ── parsers (unit-tested) ─────────────────────────────────────────────────────

def parse_tavily(data: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for r in (data or {}).get('results') or []:
        u = (r or {}).get('url')
        if isinstance(u, str) and u.startswith('http'):
            out.append({'url': u, 'title': str(r.get('title') or '')[:200],
                        'snippet': str(r.get('content') or '')[:700]})
    return out


def parse_brave(data: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for r in ((data or {}).get('web') or {}).get('results') or []:
        u = (r or {}).get('url')
        if not (isinstance(u, str) and u.startswith('http')):
            continue
        snip = ' '.join([str(r.get('description') or '')] + [str(x) for x in (r.get('extra_snippets') or [])])
        out.append({'url': u, 'title': str(r.get('title') or '')[:200], 'snippet': snip[:700]})
    return out


# ── budget (unit-tested) ──────────────────────────────────────────────────────

def usage_path(month: str) -> str:
    return os.path.join(ROOT, 'outputs', f'search_usage_{month}.json')


def load_usage(month: str) -> Dict[str, Any]:
    try:
        return json.load(open(usage_path(month), encoding='utf-8'))
    except Exception:
        return {'month': month, 'used': {}, 'days': {}, 'cache': {}}


def save_usage(u: Dict[str, Any]) -> None:
    p = usage_path(u['month'])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump(u, fh, ensure_ascii=False, indent=1)
    os.replace(p + '.tmp', p)


def key_cap(provider: str) -> int:
    return int(MONTHLY[provider] * SAFETY)


def key_left(u: Dict[str, Any], provider: str, key: str) -> int:
    return key_cap(provider) - int(((u.get('used') or {}).get(provider) or {}).get(kid(key), 0))


def daily_allowance(u: Dict[str, Any], provider: str, ks: List[str], day: str) -> int:
    """Remaining monthly credit of all keys spread evenly over the days left
    (today included), plus what today already used."""
    d = date.fromisoformat(day)
    days_left = calendar.monthrange(d.year, d.month)[1] - d.day + 1
    left = sum(max(0, key_left(u, provider, k)) for k in ks)
    today = int(((u.get('days') or {}).get(day) or {}).get(provider, 0))
    return (left + today) // max(1, days_left)


def allowed(u: Dict[str, Any], provider: str, ks: List[str], day: str, tier: str) -> bool:
    today = int(((u.get('days') or {}).get(day) or {}).get(provider, 0))
    return today + COST[provider] <= daily_allowance(u, provider, ks, day) * TIER_SHARE.get(tier, 0.6)


def charge(u: Dict[str, Any], provider: str, key: str, day: str) -> None:
    c = COST[provider]
    used = u.setdefault('used', {}).setdefault(provider, {})
    used[kid(key)] = used.get(kid(key), 0) + c
    dd = u.setdefault('days', {}).setdefault(day, {})
    dd[provider] = dd.get(provider, 0) + c


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _call(provider: str, key: str, q: str):
    import requests
    if provider == 'tavily':
        r = requests.post(TAVILY_URL, headers={'Authorization': f'Bearer {key}'},
                          json={'query': q, 'search_depth': 'basic', 'max_results': 5,
                                'include_answer': False}, timeout=20)
        return r.status_code, (parse_tavily(r.json()) if r.status_code == 200 else [])
    r = requests.get(BRAVE_URL, headers={'X-Subscription-Token': key, 'Accept': 'application/json'},
                     params={'q': q, 'count': 5, 'extra_snippets': 'true'}, timeout=20)
    return r.status_code, (parse_brave(r.json()) if r.status_code == 200 else [])


def search(match_key: str, sport: str, home: str, away: str, day: str, tier: str = 'ab',
           call=_call) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """-> (results, provider) or ([], None). Never raises."""
    month = day[:7]
    u = load_usage(month)
    cache = u.setdefault('cache', {})
    for k in [k for k in cache if not k.startswith(day + '|')]:
        cache.pop(k)       # cache only the current day
    ck = f'{day}|{match_key}'
    if ck in cache:
        _stat('cache_hit')
        return cache[ck]['results'], cache[ck]['provider']
    q = query(sport, home, away, day)
    for provider in ('tavily', 'brave'):
        ks = keys(provider)
        if not ks:
            _stat(f'{provider}_no_keys')
            continue
        if not allowed(u, provider, ks, day, tier):
            _stat(f'{provider}_budget_{tier}')
            continue
        for key in ks:
            if (provider, key) in _DEAD or key_left(u, provider, key) < COST[provider]:
                continue
            try:
                code, res = call(provider, key, q)
            except Exception:
                _stat(f'{provider}_net_error')
                continue
            _stat(f'{provider}_http_{code}')
            if code in DEAD_CODES:
                _DEAD.add((provider, key))
                continue
            if code != 200:
                continue
            charge(u, provider, key, day)
            cache[ck] = {'provider': provider, 'results': res,
                         'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            save_usage(u)
            return res, provider
    save_usage(u)
    return [], None


def month_summary(day: str) -> Dict[str, Any]:
    u = load_usage(day[:7])
    return {p: {'used': sum((u.get('used') or {}).get(p, {}).values()),
                'today': ((u.get('days') or {}).get(day) or {}).get(p, 0),
                'keys': len(keys(p)), 'capPerKey': key_cap(p)} for p in ('tavily', 'brave')}
