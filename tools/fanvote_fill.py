"""Fan Vote for every upcoming row of a sport-day (Fan Favourites board job).

``fill_votes(rows, sport, day, now, store, log, budget_s, max_calls)``:
for every row whose kick-off has not passed, reuse the Forebet pipeline's
verified vote (orientation direct/reversed) or the stored one; fetch when
there is none, or when it is older than STALE_H and (votes < min votes or
|fan % - threshold| < NEAR_PP). Stops at the time budget or max calls.
Store: results/fanvote_votes_<day>.json ``{sport: {"home|away": {...}}}``.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import fan_limits  # noqa: E402
from tools import pricing  # noqa: E402

STALE_H = 3
NEAR_PP = 10
WORKERS = int(os.getenv('FAN_FILL_WORKERS', '6'))
BUDGET_S = float(os.getenv('FAN_FILL_BUDGET_S', '1500'))
MAX_CALLS = int(os.getenv('FAN_FILL_MAX_CALLS', '3000'))
VERIFIED = ('direct', 'reversed')


def store_path(day: str, results: str) -> str:
    return os.path.join(results, f'fanvote_votes_{day}.json')


def load_store(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding='utf-8-sig') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_store(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _key(r: Dict[str, Any]) -> str:
    return f"{(r.get('homeTeam') or '').lower()}|{(r.get('awayTeam') or '').lower()}"


def _default_fetch(home: str, away: str, sport: str, day: str) -> Optional[Dict[str, Any]]:
    import sofascore_fanvote as fanvote
    from forebet_pipeline import _orient_fan_vote
    v = fanvote.get_fan_vote(home, away, sport, day)
    _orient_fan_vote(v, home, away, day)
    if not v.get('sofascore_found') or v.get('sofascore_orientation') == 'unknown':
        return None
    return {'found': True, 'homeProb': v.get('sofascore_home_win_prob'),
            'drawProb': v.get('sofascore_draw_prob'),
            'awayProb': v.get('sofascore_away_win_prob'),
            'votes': v.get('sofascore_total_votes'), 'url': v.get('sofascore_url'),
            'orientation': v.get('sofascore_orientation'),
            'eventId': v.get('sofascore_event_id'), 'startTimestamp': v.get('sofascore_start_timestamp')}


# Refresh set pinned to the pre-trial vote minimum (30; basketball/hockey 100)
# so the 100-vote Fan Favourites trial does not add SofaScore requests.
FILL_MIN_VOTES = 30
FILL_MIN_VOTES_BY_SPORT = {'basketball': 100, 'hockey': 100}


def needs_fetch(r: Dict[str, Any], sport: str, now: datetime) -> bool:
    ss = r.get('sofascore') or {}
    fs = fan_limits.fan_side(r)
    if fs is None:
        return True
    ts = pricing._parse_ts(ss.get('refreshedAt'))
    if ts is None and ss.get('orientation') in VERIFIED:
        return False
    if ts is not None and (now - ts).total_seconds() < STALE_H * 3600:
        return False
    return (fs['votes'] < FILL_MIN_VOTES_BY_SPORT.get(sport, FILL_MIN_VOTES)
            or abs(fs['fanPct'] - fan_limits.fan_threshold(sport)) < NEAR_PP)


def fill_votes(rows: List[Dict[str, Any]], sport: str, day: str, now: datetime,
               store: Optional[Dict[str, Any]] = None, log=print,
               budget_s: float = BUDGET_S, max_calls: int = MAX_CALLS,
               fetch: Optional[Callable] = None, workers: int = WORKERS) -> Dict[str, int]:
    fetch = fetch or _default_fetch
    store = store if store is not None else {}
    sv = store.setdefault(sport, {})
    st = {'voteRequested': 0, 'voteFound': 0, 'calls': 0, 'budgetHit': 0}
    todo = []
    for r in rows:
        ko = pricing._parse_ts(pricing.parse_kickoff(day, r.get('time'), [r.get('kickoffUtc')], sport=sport))
        if ko and ko <= now:
            continue
        prev = sv.get(_key(r))
        if prev and not fan_limits.fan_side(r):
            r['sofascore'] = {**(r.get('sofascore') or {}), **prev}
        if needs_fetch(r, sport, now):
            todo.append(r)
    t0 = time.monotonic()

    def one(r):
        if time.monotonic() - t0 > budget_s:
            return r, 'budget'
        try:
            return r, fetch(r.get('homeTeam') or '', r.get('awayTeam') or '', sport, day)
        except Exception as e:                   # noqa: BLE001
            log(f'   fan vote {r.get("homeTeam")} - {r.get("awayTeam")}: {type(e).__name__}')
            return r, None

    batch = todo[:max_calls]
    if len(todo) > max_calls:
        st['budgetHit'] = 1
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for r, v in ex.map(one, batch):
            if v == 'budget':
                st['budgetHit'] = 1
                continue
            st['voteRequested'] += 1
            st['calls'] += 1
            if not v:
                continue
            st['voteFound'] += 1
            eid = v.pop('eventId', None)
            sts = v.pop('startTimestamp', None)
            v['refreshedAt'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
            r['sofascore'] = {**(r.get('sofascore') or {}), **v}
            if eid:
                r['sofascoreEventId'] = eid
            if sts and not r.get('kickoffUtc'):
                r['kickoffUtc'] = datetime.fromtimestamp(int(sts), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            sv[_key(r)] = r['sofascore']
    log(f'   fan vote fill {sport} {day}: requested {st["voteRequested"]}, found {st["voteFound"]}, '
        f'relay calls {st["calls"]}{" (budget hit)" if st["budgetHit"] else ""}')
    return st
