"""Thresholds and odds limits shared by Fan Favourites, the Weekend Slip and
their backtest (tools/fanvote_backtest.py).

``odds_limit(sport, price, side)`` is the minimum decimal price for the side we
back. It is the highest of:

* the qualifying pipeline's per-sport minimum (``qualification_gate.SPORT_MIN_ODDS``,
  the same values as ``api_server._passes_sport_odds_threshold``),
* the TOP floors: football >= 2.0 (``tools/top_picks.MIN_ODDS``) and the
  tennis/basketball 1.80 safe gate (``tools/top_rules.FALLBACK_EXCLUDE``),
* the don't-bet-below ``floorOdds`` of an ``allow`` segment in
  ``outputs/top_rules.json`` matching sport x odds band (x side), if any.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from qualification_gate import SPORT_MIN_ODDS, SPORT_MIN_ODDS_FALLBACK

ROOT = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(ROOT, 'outputs', 'top_rules.json')

TOP_FLOORS = {'football': 2.0, 'tennis': 1.8, 'basketball': 1.8}
FAN_MIN = {'football': 60.0}
FAN_MIN_DEFAULT = 70.0
MIN_VOTES = 100
FAN_BANDS = [(60, 70), (70, 80), (80, 90), (90, 101)]
# Sports without a settled record yet: listed as "watch" until this many
# settled board picks exist for the sport.
WATCH_SPORTS = {'volleyball', 'handball', 'rugby', 'table_tennis'}
WATCH_MIN_SETTLED = 50

_rules_cache: Dict[str, Any] = {}


def _segments(path: str = RULES_PATH) -> Dict[str, Any]:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _rules_cache.get('key') != (path, mtime):
        try:
            with open(path, encoding='utf-8-sig') as fh:
                segs = (json.load(fh) or {}).get('segments') or {}
        except (OSError, ValueError):
            segs = {}
        _rules_cache.update(key=(path, mtime), segs=segs)
    return _rules_cache['segs']


def _band(o: Optional[float]) -> Optional[str]:
    from tools.top_rules import band
    return band(o)


def odds_limit(sport: str, price: Optional[float] = None, side: Optional[str] = None,
               rules_path: str = RULES_PATH) -> Dict[str, Any]:
    """{'min': float, 'source': str} for the side we back."""
    base = SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK)
    lim, src = base, 'sport_floor'
    top = TOP_FLOORS.get(sport)
    if top and top > lim:
        lim, src = top, 'top_floor'
    if price:
        b = _band(price)
        segs = _segments(rules_path)
        for key in ([f'{sport}|{b}|{side}'] if side else []) + [f'{sport}|{b}']:
            s = segs.get(key) or {}
            f = s.get('floorOdds')
            if s.get('decision') == 'allow' and isinstance(f, (int, float)) and f > lim:
                lim, src = float(f), f'top_rules:{key}'
                break
    return {'min': round(float(lim), 2), 'source': src}


def passes_limit(sport: str, price: Optional[float], side: Optional[str] = None) -> bool:
    return bool(price) and price >= odds_limit(sport, price, side)['min']


def fan_threshold(sport: str) -> float:
    return FAN_MIN.get(sport, FAN_MIN_DEFAULT)


def band(pct: float) -> str:
    for lo, hi in FAN_BANDS:
        if lo <= pct < hi:
            return f'{lo}-{hi}' if hi <= 100 else f'{lo}+'
    return '<60'


def fan_side(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{'side', 'fanPct', 'votes'} of the Fan Vote favourite of a forebet row."""
    ss = row.get('sofascore') or {}
    if not ss.get('found') or row.get('oddsOrientationUnknown'):
        return None
    try:
        hp, ap = float(ss.get('homeProb')), float(ss.get('awayProb'))
    except (TypeError, ValueError):
        return None
    side, pct = ('home', hp) if hp >= ap else ('away', ap)
    try:
        votes = int(float(ss.get('votes') or 0))
    except (TypeError, ValueError):
        votes = 0
    return {'side': side, 'fanPct': pct, 'votes': votes}


def select(sport: str, fan_pct: float, votes: int, min_votes: int = MIN_VOTES) -> bool:
    """Fan Vote threshold for the board (odds limit checked separately)."""
    return fan_pct >= fan_threshold(sport) and votes >= min_votes
