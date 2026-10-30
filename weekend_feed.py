"""Weekend Slip for the website (/api/weekend-slip).

Reads ``results/weekend_<friday>.json`` (tools/weekend_slip.py); the current
weekend comes from raw GitHub like top_feed (Heroku sees repo files only after
a deploy). Pending legs are settled on the fly against
``results/forebet_settled.json``.

Paywall like TOP: for non-subscribers a leg that is not settled shows only
sport, kickoff and status; settled legs and finished slips are public. The
record counts finished slips (won/lost) at flat 1 unit on the combined odds.
"""
from __future__ import annotations

import copy
import glob
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import top_feed
from top_feed import _read_json, _remote_json
from tools import weekend_slip

RESULTS_DIR = top_feed.RESULTS_DIR
_RE = re.compile(r'weekend_(\d{4}-\d{2}-\d{2})\.json$')
MAX_WEEKENDS = 8
_LOCKED_KEEP = ('id', 'sport', 'date', 'kickoff', 'status', 'withdrawnReason')


def _locked(leg: Dict[str, Any]) -> Dict[str, Any]:
    v = {k: leg.get(k) for k in _LOCKED_KEEP}
    v['locked'] = True
    return v


def _record(slips: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [s for s in slips if s.get('status') in ('won', 'lost')]
    won = [s for s in done if s['status'] == 'won']
    n = len(done)
    profit = sum((s.get('combinedOdds') or 0) - 1 for s in won) - (n - len(won))
    legs = [l for s in slips for l in s.get('legs') or [] if l.get('status') in ('won', 'lost')]
    return {'slips': n, 'won': len(won),
            'hitPct': round(100 * len(won) / n, 1) if n else None,
            'roiPct': round(100 * profit / n, 1) if n else None,
            'profitUnits': round(profit, 2) if n else None,
            'legs': len(legs), 'legsWon': sum(1 for l in legs if l['status'] == 'won'),
            'void': sum(1 for s in slips if s.get('status') == 'void')}


def load_weekend(results_dir: str = RESULTS_DIR, is_subscriber: bool = False,
                 friday: Optional[str] = None, remote: Optional[bool] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if remote is None:
        remote = top_feed._remote_auto(results_dir)
    paths = {}
    for p in glob.glob(os.path.join(results_dir, 'weekend_*.json')):
        m = _RE.search(os.path.basename(p))
        if m:
            paths[m.group(1)] = p
    today = now.astimezone(weekend_slip._TZ).date()
    cur = weekend_slip.friday_of(today) or today - timedelta(days=(today.weekday() - 4) % 7)
    current = cur.isoformat()
    fridays = set(paths) | ({current} if remote else set())
    index = top_feed._forebet_settled(results_dir)
    weekends = []
    for fr in sorted(fridays, reverse=True):
        raw = None
        if remote and fr == current:
            got = _remote_json(f'weekend_{fr}.json')
            raw = got if isinstance(got, dict) else None
        if raw is None and fr in paths:
            raw = _read_json(paths[fr])
        if not isinstance(raw, dict):
            continue
        raw = copy.deepcopy(raw)
        slips = raw.get('slips') or []
        weekend_slip.settle_slips(slips, index)
        weekends.append({**raw, 'slips': slips})
    record = _record([s for w in weekends for s in w['slips']])
    if friday:
        weekends = [w for w in weekends if w.get('friday') == friday]
    weekends = weekends[:MAX_WEEKENDS]
    if not is_subscriber:
        for w in weekends:
            for s in w['slips']:
                if s.get('status') in ('won', 'lost', 'void'):
                    continue
                s['legs'] = [l if l.get('status') in ('won', 'lost') else _locked(l) for l in s['legs']]
                s['locked'] = sum(1 for l in s['legs'] if l.get('locked'))
    return {'current': current, 'weekends': weekends, 'record': record,
            'note': weekend_slip.NOTE, 'stakePct': weekend_slip.STAKE_PCT,
            'maxLegs': weekend_slip.MAX_LEGS, 'isSubscriber': is_subscriber}
