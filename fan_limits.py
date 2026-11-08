"""Thresholds and odds limits shared by Fan Favourites, the Weekend Slip and
their backtest (tools/fanvote_backtest.py).

Odds limits are the main qualifying e-mails' rule: home AND away odds >= the
per-sport minimum of ``qualification_gate.SPORT_MIN_ODDS`` (``passes_standard``;
``odds_limit`` returns that minimum with source ``standard``). TOP floors and
learned ``outputs/top_rules.json`` floors do not apply (learned rules are only
recorded). ``min_votes(sport)`` reads ``MIN_VOTES_BY_SPORT`` then ``MIN_VOTES``
(calibrated with ``tools/fanvote_backtest.py --calibrate``).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from qualification_gate import SPORT_MIN_ODDS, SPORT_MIN_ODDS_FALLBACK

ROOT = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(ROOT, 'outputs', 'top_rules.json')

FAN_MIN = {'football': 60.0}
FAN_MIN_DEFAULT = 70.0
# Calibrated 2026-11 (tools/fanvote_backtest.py --calibrate, rows from 2026-09-27):
# 30-49 votes hit 62.2% / ROI +14.3% (n=249) vs base >=100 votes 57.2% / -0.9%.
MIN_VOTES = 30
MIN_VOTES_BY_SPORT: Dict[str, int] = {'basketball': 100, 'hockey': 100}
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
    """{'min': float, 'source': 'standard'}: the qualifying pipeline's per-sport
    minimum, the same limits as the main mails (TOP floors and learned rules
    no longer apply here)."""
    return {'min': round(standard_min(sport), 2), 'source': 'standard'}


def standard_min(sport: str) -> float:
    return float(SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK))


def passes_standard(sport: str, home_odds: Any, away_odds: Any) -> bool:
    """Home AND away odds present and >= the sport minimum."""
    m = standard_min(sport)
    try:
        return bool(home_odds) and bool(away_odds) and float(home_odds) >= m and float(away_odds) >= m
    except (TypeError, ValueError):
        return False


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


def min_votes(sport: str) -> int:
    return int(MIN_VOTES_BY_SPORT.get(sport, MIN_VOTES))


def select(sport: str, fan_pct: float, votes: int, min_votes: Optional[int] = None) -> bool:
    """Fan Vote threshold for the board (odds limit checked separately)."""
    mv = globals()['min_votes'](sport) if min_votes is None else min_votes
    return fan_pct >= fan_threshold(sport) and votes >= mv
