"""Shared price layer (design K0): every component prices a pick the same way.

* ``two_way`` – hockey/basketball/baseball quotes that carry a draw (regulation
  3-way) are settled on the final winner incl. OT, so they are re-priced to the
  2-way equivalent before any statistic. Football/handball stay 3-way (draw = loss).
* ``haircut_profit`` – flat 1u profit after a 5% price haircut.
* ``floor_price`` – break-even price after the haircut for a hit rate ``p``.
* ``parse_kickoff`` – kickoff in UTC: explicit source timestamp (Pinnacle
  ``startTime`` / OddsSafari) first, else Forebet ``time`` read as Europe/Warsaw.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

TWO_WAY_EQUIV_SPORTS = {'hockey', 'basketball', 'baseball'}
THREE_WAY_SPORTS = {'football', 'handball'}
HAIRCUT = 0.05
# Forebet `time` is meant to be Europe/Warsaw (forebet_pipeline.FOREBET_DISPLAY_TZ),
# but the check against Pinnacle startTime on 2026-10-26 (49 matched rows,
# tests/fixtures/edge/kickoff_verification.json) showed a different offset per
# sport file: football UTC+3, basketball Europe/Warsaw, tennis/hockey/volleyball/
# baseball UTC. Single place to change: FOREBET_TZ (default) + FOREBET_TZ_BY_SPORT.
FOREBET_TZ = 'Europe/Warsaw'
FOREBET_TZ_BY_SPORT = {
    'football': 'Etc/GMT-3',       # = UTC+3
    'basketball': 'Europe/Warsaw',
    'tennis': 'UTC', 'hockey': 'UTC', 'volleyball': 'UTC', 'baseball': 'UTC',
}
# A day file also lists the night after it: times before 05:00 are on day+1.
NIGHT_WRAP_HOUR = 5
MAX_SOURCE_SKEW = timedelta(days=3)


def _price(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def two_way(odds: Optional[Dict[str, Any]], sport: str
            ) -> Tuple[Optional[float], Optional[float], str]:
    """(home2, away2, market) – market ``2way_equiv`` | ``2way`` | ``3way``."""
    odds = odds or {}
    h, a, d = _price(odds.get('home')), _price(odds.get('away')), _price(odds.get('draw'))
    if sport in TWO_WAY_EQUIV_SPORTS and d:
        if not (h and a):
            return None, None, '2way_equiv'
        ph, pa, pd = 1 / h, 1 / a, 1 / d
        over = ph + pa + pd

        def conv(ps: float, po: float) -> float:
            p2 = (ps + pd * ps / (ps + po)) / over      # fair prob incl. OT
            return round(1 / (p2 * over), 3)             # same overround applied
        return conv(ph, pa), conv(pa, ph), '2way_equiv'
    if sport in THREE_WAY_SPORTS or (d and sport not in TWO_WAY_EQUIV_SPORTS):
        return h, a, '3way'
    return h, a, '2way'


def side_price(odds: Optional[Dict[str, Any]], sport: str, side: str
               ) -> Tuple[Optional[float], str]:
    """(odds2, market) for ``side`` ('home'/'away')."""
    h, a, market = two_way(odds, sport)
    return (h if side == 'home' else a), market


def haircut_profit(odds: float, won: bool) -> float:
    return (1 - HAIRCUT) * (float(odds) - 1) if won else -1.0


def floor_price(p: float) -> float:
    """Break-even decimal price after the 5% haircut, rounded up to 0.01."""
    x = 1 + (1 - p) / ((1 - HAIRCUT) * p)
    return math.ceil(round(x * 100, 6)) / 100


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        t = float(v)
        if t > 1e11:            # milliseconds
            t /= 1000
        return datetime.fromtimestamp(t, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt.tzinfo is None:       # explicit sources are UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def forebet_tz(sport: Optional[str]) -> str:
    return FOREBET_TZ_BY_SPORT.get(sport or '', FOREBET_TZ)


def parse_kickoff(day: str, hhmm: Optional[str],
                  sources: Optional[Iterable[Any]] = None,
                  sport: Optional[str] = None) -> Optional[str]:
    """Kickoff as ISO UTC ('...Z'), or None when nothing usable.

    ``sources``: explicit UTC timestamps in priority order (ISO strings or epoch
    seconds/ms). A source more than 3 days away from the Forebet day/time is
    rejected. Fallback: ``day`` + ``hhmm`` read in ``forebet_tz(sport)``; times
    before NIGHT_WRAP_HOUR belong to the night after ``day``.
    """
    local = None
    try:
        from zoneinfo import ZoneInfo
        h, mi = (int(x) for x in str(hhmm).split(':')[:2])
        d = datetime.strptime(str(day)[:10], '%Y-%m-%d')
        if h < NIGHT_WRAP_HOUR:
            d += timedelta(days=1)
        local = d.replace(hour=h, minute=mi,
                          tzinfo=ZoneInfo(forebet_tz(sport))).astimezone(timezone.utc)
    except Exception:
        local = None
    ref = local
    if ref is None:
        try:
            ref = datetime.strptime(str(day)[:10], '%Y-%m-%d').replace(
                hour=12, tzinfo=timezone.utc)
        except ValueError:
            ref = None
    for s in sources or ():
        dt = _parse_ts(s)
        if dt is None:
            continue
        if ref is not None and abs(dt - ref) > MAX_SOURCE_SKEW:
            continue
        return _iso(dt)
    return _iso(local) if local else None
