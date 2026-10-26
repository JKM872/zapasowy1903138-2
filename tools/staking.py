"""Suggested stake (design K5): cautious quarter Kelly, 1–2% of the bankroll.

``pCal`` is the segment hit rate from outputs/top_rules.json (Beta-shrunk on the
tuning window), not the model's ``scoring.prob``. Only grade A with a positive
edge at the price we can get earns more than the base 1%; everything else –
including the built-in rules fallback (``pCal`` None) – stakes 1%.
"""
from __future__ import annotations

from typing import Any, Optional

BASE_PCT = 1.0
MAX_PCT = 2.0
KELLY_FRACTION = 0.25


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None          # NaN -> None


def stake_pct(grade: Optional[str], pCal: Any, odds: Any) -> float:
    """Stake in % of the bankroll: clamp(round(100 * 0.25 * edge / (o - 1), 1), 1, 2)."""
    p, o = _num(pCal), _num(odds)
    if grade != 'A' or p is None or o is None or o <= 1.0 or not 0 < p < 1:
        return BASE_PCT
    edge = p * o - 1
    if edge <= 0:
        return BASE_PCT
    f = KELLY_FRACTION * edge / (o - 1)
    return min(MAX_PCT, max(BASE_PCT, round(100 * f, 1)))
