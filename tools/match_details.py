"""Match details for Fan Favourites picks from the SofaScore API.

``details(event_id, sport)`` returns the tournament, round and surface of the
event plus the last finished matches of both sides (date, opponent, venue,
result, score and, for tennis, the match duration from the period times).
Three API calls per event: /event/{id} and /team/{id}/events/last/0 per side.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

API = 'https://api.sofascore.com/api/v1'
LAST_N = 5


def _get(url: str) -> Any:
    import sofascore_scraper
    return sofascore_scraper._api_get_json(url, timeout=15)


def event_id(pick_or_row: Dict[str, Any]) -> Optional[int]:
    eid = pick_or_row.get('sofascoreEventId') or pick_or_row.get('eventId')
    if not eid:
        url = pick_or_row.get('sofascoreUrl') or (pick_or_row.get('sofascore') or {}).get('url') or ''
        if 'sofascore.com' in url:
            tail = url.rstrip('/').split('/')[-1].split(':')[-1]
            eid = tail if tail.isdigit() else None
    try:
        return int(eid) if eid else None
    except (TypeError, ValueError):
        return None


def _date(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError, OverflowError):
        return ''


def duration_min(ev: Dict[str, Any]) -> Optional[int]:
    """Playing time in minutes: sum of ``time.periodN`` seconds (tennis)."""
    t = ev.get('time') or {}
    secs = sum(v for k, v in t.items() if k.startswith('period') and k[6:].isdigit()
               and isinstance(v, (int, float)))
    return round(secs / 60) if secs else None


def score_text(ev: Dict[str, Any], sport: str, team_home: bool) -> str:
    hs, as_ = ev.get('homeScore') or {}, ev.get('awayScore') or {}
    if hs.get('current') is None or as_.get('current') is None:
        return ''
    mine, theirs = (hs, as_) if team_home else (as_, hs)
    txt = f"{mine['current']}-{theirs['current']}"
    if sport in ('tennis', 'table_tennis', 'volleyball'):
        sets = [f"{mine[k]}-{theirs.get(k)}" for k in sorted(
            (k for k in mine if k.startswith('period') and k[6:].isdigit()), key=lambda k: int(k[6:]))
            if theirs.get(k) is not None]
        if sets:
            txt += f" ({' '.join(sets)})"
    return txt


def last_matches(team_id: int, sport: str, get: Callable = _get, n: int = LAST_N) -> List[Dict[str, Any]]:
    data = get(f'{API}/team/{team_id}/events/last/0') or {}
    out: List[Dict[str, Any]] = []
    for ev in reversed(data.get('events') or []):
        if ((ev.get('status') or {}).get('type') or '') != 'finished':
            continue
        home, away = ev.get('homeTeam') or {}, ev.get('awayTeam') or {}
        if team_id not in (home.get('id'), away.get('id')):
            continue
        is_home = home.get('id') == team_id
        wc = ev.get('winnerCode')
        res = 'D' if wc == 3 else ('W' if wc == (1 if is_home else 2) else 'L') if wc in (1, 2) else ''
        item = {'date': _date(ev.get('startTimestamp')),
                'opponent': (away if is_home else home).get('name') or '',
                'venue': 'H' if is_home else 'A', 'result': res,
                'score': score_text(ev, sport, is_home),
                'tournament': (ev.get('tournament') or {}).get('name') or '',
                'round': ((ev.get('roundInfo') or {}).get('name') or '')}
        if sport in ('tennis', 'table_tennis'):
            item['durationMin'] = duration_min(ev)
        out.append(item)
        if len(out) >= n:
            break
    return out


def details(eid: int, sport: str, side: str, get: Callable = _get) -> Optional[Dict[str, Any]]:
    """{'tournament', 'round', 'surface', 'team': [...], 'opponent': [...]} or None."""
    ev = (get(f'{API}/event/{eid}') or {}).get('event') or {}
    if not ev:
        return None
    ri = ev.get('roundInfo') or {}
    rnd = ri.get('name') or (f"Round {ri['round']}" if ri.get('round') else '')
    ids = {'home': (ev.get('homeTeam') or {}).get('id'), 'away': (ev.get('awayTeam') or {}).get('id')}
    op = 'away' if side == 'home' else 'home'
    t = ev.get('tournament') or {}
    return {'tournament': t.get('name') or '',
            'category': (t.get('category') or {}).get('name') or '',
            'round': rnd, 'surface': ev.get('groundType') or '',
            'team': last_matches(ids[side], sport, get) if ids[side] else [],
            'opponent': last_matches(ids[op], sport, get) if ids[op] else []}
