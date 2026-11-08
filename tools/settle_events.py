"""Settle published picks (TOP, Fan Favourites, Weekend legs) from the SofaScore event.

Event id: item ``sofascoreEventId``/``eventId`` -> the day's Forebet row ->
``results/fanvote_votes_<d>.json`` -> SofaScore search for d-1/d/d+1.
Football/handball/rugby use the normal-time score (draw allowed); canceled,
postponed and abandoned events are ``void``. Writes ``results/event_settled.json``
keyed ``<day>|<sport>|<home>|<away>``.

    python -u tools/settle_events.py --days 3
    python -B tools/settle_events.py --from 2026-10-17 --to 2026-10-31
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

RESULTS = os.path.join(ROOT, 'results')
OUT_NAME = 'event_settled.json'
THREE_WAY = ('football', 'handball', 'rugby')
NORMAL_TIME = ('football', 'handball', 'rugby')
VOID = ('canceled', 'cancelled', 'postponed', 'abandoned')
STARTED_H = 3
SLUG = {'hockey': 'ice-hockey', 'table_tennis': 'table-tennis', 'ice_hockey': 'ice-hockey'}


def _read(path: str) -> Any:
    try:
        with open(path, encoding='utf-8-sig') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _norm(s: Any) -> str:
    import top_feed
    return top_feed._norm(s)


def _ts(s: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _eid(*vals: Any) -> Optional[int]:
    for v in vals:
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        m = re.search(r'(?:/match/|id:)(\d+)', str(v)) if isinstance(v, str) and not v.isdigit() else None
        try:
            n = int(m.group(1)) if m else int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return None


# ---------------------------------------------------------------------------
# Published items
# ---------------------------------------------------------------------------
def _item(day, sport, home, away, kickoff, eid) -> Dict[str, Any]:
    return {'day': day, 'sport': sport, 'home': home, 'away': away,
            'kickoff': kickoff, 'eventId': eid}


def collect(days: Iterable[str], results: str = RESULTS) -> List[Dict[str, Any]]:
    import top_feed
    from tools import pricing
    out: Dict[str, Dict[str, Any]] = {}
    days = list(days)
    for day in days:
        live = _read(os.path.join(results, f'top_live_{day}.json')) or {}
        for p in _read(os.path.join(results, f'top_{day}.json')) or []:
            if not isinstance(p, dict) or p.get('withdrawn') \
                    or (live.get(f"{p.get('sport')}|{p.get('match')}") or {}).get('withdrawn'):
                continue
            h, a = top_feed._split_match(p.get('match'))
            ko = p.get('kickoffUtc') or pricing.parse_kickoff(day, p.get('time'), sport=p.get('sport'))
            it = _item(day, p.get('sport'), h, a, ko, _eid(p.get('sofascoreEventId'), p.get('eventId')))
            it['pick'] = p.get('pick')
            out.setdefault(f"{day}|{it['sport']}|{h}|{a}", it)
        fan = _read(os.path.join(results, f'fanvote_{day}.json')) or {}
        for blk in (fan.get('sports') or {}).values() if isinstance(fan, dict) else ():
            for p in (blk or {}).get('picks') or []:
                if isinstance(p, dict) and p.get('home') and p.get('away'):
                    it = _item(day, p.get('sport'), p['home'], p['away'], p.get('kickoff'),
                               _eid(p.get('sofascoreEventId'), p.get('eventId'), p.get('sofascoreUrl')))
                    it['pick'] = p.get('team')
                    out.setdefault(f"{day}|{it['sport']}|{p['home']}|{p['away']}", it)
    fridays = {d for d in days if date.fromisoformat(d).weekday() == 4}
    fridays |= {(date.fromisoformat(d) - timedelta(days=(date.fromisoformat(d).weekday() - 4) % 7)).isoformat()
                for d in days}
    for fr in sorted(fridays):
        wk = _read(os.path.join(results, f'weekend_{fr}.json')) or {}
        for s in wk.get('slips') or [] if isinstance(wk, dict) else ():
            for l in s.get('legs') or []:
                if l.get('status') == 'withdrawn' or l.get('date') not in days:
                    continue
                it = _item(l['date'], l['sport'], l['home'], l['away'], l.get('kickoff'), _eid(l.get('eventId')))
                it['pick'] = l.get('pick')
                out.setdefault(f"{l['date']}|{l['sport']}|{l['home']}|{l['away']}", it)
    return list(out.values())


# ---------------------------------------------------------------------------
# Event id
# ---------------------------------------------------------------------------
def _row_event(it: Dict[str, Any], results: str) -> Optional[Tuple[int, str]]:
    from tools import injuries
    nh, na = _norm(it['home']), _norm(it['away'])
    for path in glob.glob(os.path.join(results, f"matches_{it['day']}_{it['sport']}*.json")):
        raw = _read(path)
        rows = raw.get('matches', raw) if isinstance(raw, dict) else raw
        rows = rows.values() if isinstance(rows, dict) else rows or []
        for r in rows:
            if isinstance(r, dict) and {_norm(r.get('homeTeam')), _norm(r.get('awayTeam'))} == {nh, na}:
                ev = injuries.event_from_row(r)
                if ev:
                    flip = _norm(r.get('homeTeam')) != nh
                    return ev[0], ({'direct': 'reversed', 'reversed': 'direct'}[ev[1]] if flip else ev[1])
    store = _read(os.path.join(results, f"fanvote_votes_{it['day']}.json")) or {}
    blk = store.get(it['sport']) or {} if isinstance(store, dict) else {}
    for key, flip in ((f"{it['home']}|{it['away']}", False), (f"{it['away']}|{it['home']}", True)):
        v = blk.get(key)
        eid = _eid((v or {}).get('eventId'), (v or {}).get('sofascoreEventId'), (v or {}).get('url')) \
            if isinstance(v, dict) else None
        if eid:
            orient = v.get('orientation') if v.get('orientation') in ('direct', 'reversed') else 'direct'
            if flip:
                orient = {'direct': 'reversed', 'reversed': 'direct'}[orient]
            return eid, orient
    return None


def _search(it: Dict[str, Any]) -> Optional[int]:
    import sofascore_scraper as ss
    d = date.fromisoformat(it['day'])
    for off in (0, -1, 1):
        try:
            eid = ss.search_event_via_api(it['home'], it['away'], sport=it['sport'],
                                          date_str=(d + timedelta(days=off)).isoformat())
        except Exception:                               # noqa: BLE001
            eid = None
        if eid:
            return int(eid)
    return None


def _orient(ev: Dict[str, Any], home: str) -> str:
    import sofascore_scraper as ss
    eh = ((ev.get('homeTeam') or {}).get('name')) or ''
    ea = ((ev.get('awayTeam') or {}).get('name')) or ''
    if _norm(eh) == _norm(home) or ss.names_match(home, eh):
        return 'direct'
    if _norm(ea) == _norm(home) or ss.names_match(home, ea):
        return 'reversed'
    return 'direct'


# ---------------------------------------------------------------------------
# Event -> settlement (pure)
# ---------------------------------------------------------------------------
def settle_event(ev: Dict[str, Any], sport: str, orient: str = 'direct',
                 now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    st = (ev.get('status') or {}).get('type') or ''
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
    base = {'eventId': ev.get('id'), 'source': 'sofascore_event', 'settledAt': stamp}
    if st in VOID:
        return {'status': 'void', 'winner': None, 'score': None, 'normaltime': False, **base}
    if st != 'finished':
        return None
    hs, as_ = ev.get('homeScore') or {}, ev.get('awayScore') or {}
    nt = sport in NORMAL_TIME and hs.get('normaltime') is not None and as_.get('normaltime') is not None
    k = 'normaltime' if nt else 'current'
    h, a = hs.get(k), as_.get(k)
    if h is None or a is None:
        return None
    if h > a:
        w = 'home'
    elif a > h:
        w = 'away'
    elif sport in THREE_WAY:
        w = 'draw'
    else:
        w = {1: 'home', 2: 'away', 3: 'draw'}.get(ev.get('winnerCode'))
    if orient == 'reversed':
        h, a = a, h
        w = {'home': 'away', 'away': 'home'}.get(w, w)
    return {'status': 'settled', 'winner': w, 'score': f'{h}-{a}', 'normaltime': nt, **base}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def _fetch_event(eid: int) -> Optional[Dict[str, Any]]:
    import sofascore_scraper as ss
    data = ss._api_get_json(f'https://www.sofascore.com/api/v1/event/{eid}')
    return (data or {}).get('event') if isinstance(data, dict) else None


def run(days: List[str], results: str = RESULTS, now: Optional[datetime] = None,
        fetch: Callable[[int], Optional[Dict[str, Any]]] = _fetch_event,
        search: Callable[[Dict[str, Any]], Optional[int]] = _search,
        max_calls: int = 400, budget_s: float = 900, log=print) -> Dict[str, int]:
    import top_feed
    now = now or datetime.now(timezone.utc)
    path = os.path.join(results, OUT_NAME)
    done = _read(path) or {}
    index = top_feed.settle_index(results)
    t0, calls = time.monotonic(), 0
    stats = {'settled': 0, 'void': 0, 'unmatched': 0, 'pending': 0}
    changed = False
    for it in collect(days, results):
        key = f"{it['day']}|{it['sport']}|{it['home']}|{it['away']}"
        if key in done:
            continue
        ko = _ts(it.get('kickoff')) or _ts(f"{it['day']}T12:00:00Z")
        if ko and now - ko < timedelta(hours=STARTED_H):
            stats['pending'] += 1
            continue
        if it['sport'] not in NORMAL_TIME[:2] and it.get('pick') and \
                top_feed.settle(it['day'], {'match': f"{it['home']} vs {it['away']}", 'pick': it['pick']},
                                index)['status'] != 'pending':
            continue
        if calls >= max_calls or time.monotonic() - t0 > budget_s:
            stats['pending'] += 1
            continue
        orient = None
        eid = it.get('eventId')
        if not eid:
            got = _row_event(it, results)
            if got:
                eid, orient = got
        if not eid:
            calls += 1
            eid = search(it)
        if not eid:
            stats['unmatched'] += 1
            continue
        calls += 1
        ev = fetch(int(eid))
        if not ev:
            stats['pending'] += 1
            continue
        res = settle_event(ev, it['sport'], orient or _orient(ev, it['home']), now)
        if not res:
            stats['pending'] += 1
            continue
        res['eventId'] = int(eid)
        done[key] = res
        changed = True
        stats['settled' if res['status'] == 'settled' else 'void'] += 1
    if changed:
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(dict(sorted(done.items())), fh, ensure_ascii=False, indent=1)
            fh.write('\n')
    log(f"settled {stats['settled']}, void {stats['void']}, unmatched {stats['unmatched']}, "
        f"pending {stats['pending']} ({calls} API calls)")
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                   # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3)
    ap.add_argument('--from', dest='frm')
    ap.add_argument('--to')
    ap.add_argument('--max-calls', type=int, default=400)
    ap.add_argument('--budget', type=float, default=900, help='seconds')
    a = ap.parse_args(argv)
    if a.frm:
        d0, d1 = date.fromisoformat(a.frm), date.fromisoformat(a.to or a.frm)
    else:
        d1 = datetime.now(timezone.utc).date()
        d0 = d1 - timedelta(days=a.days)
    days = [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]
    run(days, max_calls=a.max_calls, budget_s=a.budget)
    return 0


if __name__ == '__main__':
    sys.exit(main())
