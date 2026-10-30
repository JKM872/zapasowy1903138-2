"""Fan Favourites board for the website (/api/fan-favourites).

Reads ``results/fanvote_<day>.json`` (tools/fan_favourites.py). The newest
days come from raw GitHub like top_feed (Heroku sees repo files only after a
deploy). Picks without a stored result are settled on the fly against
``results/forebet_settled.json``.

Paywall like TOP: pending picks are reduced to sport/league/kickoff/band for
non-subscribers; settled picks are public. The record counts only
``status: "pick"`` entries (odds limit passed), flat 1 unit at the best price;
a football draw is a loss.
"""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import fan_limits
import top_feed
from top_feed import _read_json, _remote_json

RESULTS_DIR = top_feed.RESULTS_DIR
_DAY_RE = re.compile(r'fanvote_(\d{4}-\d{2}-\d{2})\.json$')
MAX_DAYS = 14
BANDS = ['60-70', '70-80', '80-90', '90+']
_LOCKED_KEEP = ('id', 'sport', 'league', 'kickoff', 'time', 'band', 'date')


def _settled(p: Dict[str, Any]) -> Optional[str]:
    st = (p.get('result') or {}).get('status')
    return st if st in ('won', 'lost') else None


def _record(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    rs = [p for p in picks if p.get('status') == 'pick' and _settled(p)]
    n = len(rs)
    won = sum(1 for p in rs if _settled(p) == 'won')
    price = lambda p: (p.get('bestPrice') or {}).get('price') or 0  # noqa: E731
    profit = sum(price(p) - 1 for p in rs if _settled(p) == 'won') - (n - won)
    return {'n': n, 'won': won,
            'hitPct': round(100 * won / n, 1) if n else None,
            'roiPct': round(100 * profit / n, 1) if n else None,
            'profitUnits': round(profit, 2) if n else None,
            'avgOdds': round(sum(price(p) for p in rs) / n, 2) if n else None}


def _locked(p: Dict[str, Any]) -> Dict[str, Any]:
    v = {k: p.get(k) for k in _LOCKED_KEEP}
    v['locked'] = True
    return v


def load_fan(results_dir: str = RESULTS_DIR, is_subscriber: bool = False,
             sport: Optional[str] = None, date: Optional[str] = None,
             remote: Optional[bool] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if remote is None:
        remote = top_feed._remote_auto(results_dir)
    paths = {}
    for p in glob.glob(os.path.join(results_dir, 'fanvote_*.json')):
        m = _DAY_RE.search(os.path.basename(p))
        if m:
            paths[m.group(1)] = p
    recent = {(now.date() - timedelta(days=i)).isoformat() for i in range(-1, top_feed.REMOTE_DAYS)}
    all_days = set(paths) | (recent if remote else set())
    index = top_feed._forebet_settled(results_dir)
    everything: List[Dict[str, Any]] = []
    days = []
    for day in sorted(all_days, reverse=True):
        raw = None
        if remote and day in recent:
            got = _remote_json(f'fanvote_{day}.json')
            raw = got if isinstance(got, dict) else None
        if raw is None and day in paths:
            raw = _read_json(paths[day])
        if not isinstance(raw, dict):
            continue
        sports_out = {}
        for sp, blk in sorted((raw.get('sports') or {}).items()):
            picks = []
            for p in (blk or {}).get('picks') or []:
                if not isinstance(p, dict):
                    continue
                if not p.get('result'):
                    res = top_feed.settle(day, {'match': p.get('match'), 'pick': p.get('team')}, index)
                    if res['status'] in ('won', 'lost', 'draw'):
                        p = {**p, 'result': {'status': 'won' if res['status'] == 'won' else 'lost',
                                             'score': res.get('score'), 'draw': res['status'] == 'draw'}}
                picks.append(p)
                everything.append(p)
            if sport and sp != sport:
                continue
            visible = [p if is_subscriber or _settled(p) else _locked(p) for p in picks]
            sports_out[sp] = {'generatedAt': (blk or {}).get('generatedAt'),
                              'watch': bool((blk or {}).get('watch')), 'picks': visible,
                              'locked': sum(1 for p in visible if p.get('locked'))}
        if date and day != date:
            continue
        days.append({'date': day, 'generatedAt': raw.get('generatedAt'), 'sports': sports_out})
    if not date:
        days = days[:MAX_DAYS]
    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    by_band: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BANDS}
    for p in everything:
        by_sport.setdefault(p.get('sport') or 'unknown', []).append(p)
        if p.get('band') in by_band:
            by_band[p['band']].append(p)
    return {
        'days': days,
        'record': {'all': _record(everything),
                   'bySport': {s: _record(v) for s, v in sorted(by_sport.items())},
                   'byBand': {b: _record(v) for b, v in by_band.items()}},
        'thresholds': {'minVotes': fan_limits.MIN_VOTES,
                       'fanPct': {**fan_limits.FAN_MIN, 'default': fan_limits.FAN_MIN_DEFAULT},
                       'oddsLimit': {s: fan_limits.odds_limit(s) for s in
                                     ('football', 'basketball', 'hockey', 'tennis', 'volleyball',
                                      'handball', 'baseball', 'rugby', 'table_tennis')}},
        'isSubscriber': is_subscriber,
    }
