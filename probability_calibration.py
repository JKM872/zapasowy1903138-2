"""Map a stated probability onto the frequency actually observed.

The reliability table said the model's numbers could not be believed: picks
stated at 42% won 83% of the time, picks stated at 91% won 83%. A single
softmax temperature cannot repair that — it moves the whole curve one way, and
this curve is wrong in both directions at once. Fitting one on 1000 settled
matches improved Brier (0.455 -> 0.360) while making the practical problem
worse: positive-EV flags rose from 241 to 257 of 293 priced games, because
sharpening a probability inflates every expected value computed from it.

Isotonic regression fits the shape instead of shifting it. It learns a
monotone step function from stated probability to observed win rate — monotone
because "more confident should never mean less likely to win" is the one
assumption worth keeping, and non-parametric because the curve's shape is not
ours to assume.

    curve = fit_isotonic([(0.42, 1), (0.91, 0), ...])
    honest = apply_isotonic(curve, 0.42)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# A bin needs some support before its observed rate means anything.
MIN_BIN_WEIGHT = 8


def fit_isotonic(pairs: Sequence[Tuple[float, float]],
                 min_weight: int = MIN_BIN_WEIGHT,
                 ) -> List[Tuple[float, float]]:
    """Fit a monotone mapping from stated probability to observed rate.

    *pairs* is ``(stated_probability, outcome)`` with outcome 1 for a win and 0
    for a loss. Uses pool-adjacent-violators: sort by stated probability, then
    repeatedly merge any neighbouring blocks whose observed rates go the wrong
    way, until the sequence is non-decreasing.

    Returns ``[(upper_bound, calibrated_probability), ...]`` sorted ascending;
    an empty list when there is nothing to learn from.
    """
    clean: List[Tuple[float, float]] = []
    for p, y in pairs:
        try:
            p = float(p)
            y = float(y)
        except (TypeError, ValueError):
            continue
        if p != p or y != y:            # NaN
            continue
        clean.append((min(1.0, max(0.0, p)), 1.0 if y >= 0.5 else 0.0))

    if len(clean) < min_weight * 2:
        return []

    clean.sort(key=lambda t: t[0])

    # Each block: [sum_of_outcomes, count, highest_probability_in_block]
    blocks: List[List[float]] = [[y, 1.0, p] for p, y in clean]

    merged = True
    while merged:
        merged = False
        out: List[List[float]] = []
        for block in blocks:
            out.append(block)
            # Merge while the previous block's rate exceeds this one's, or while
            # either block is too small to trust on its own.
            while len(out) > 1:
                prev, cur = out[-2], out[-1]
                prev_rate = prev[0] / prev[1]
                cur_rate = cur[0] / cur[1]
                if prev_rate > cur_rate or prev[1] < min_weight:
                    out[-2] = [prev[0] + cur[0], prev[1] + cur[1],
                               max(prev[2], cur[2])]
                    out.pop()
                    merged = True
                else:
                    break
        blocks = out

    # A trailing block below the weight floor is folded back into its neighbour.
    while len(blocks) > 1 and blocks[-1][1] < min_weight:
        last = blocks.pop()
        blocks[-1] = [blocks[-1][0] + last[0], blocks[-1][1] + last[1],
                      max(blocks[-1][2], last[2])]

    curve = [(round(block[2], 6), round(block[0] / block[1], 6))
             for block in blocks]
    # The last bin must cover everything up to certainty.
    if curve:
        curve[-1] = (1.0, curve[-1][1])
    return curve


def apply_isotonic(curve: Sequence[Tuple[float, float]], prob: float) -> float:
    """Map *prob* through the fitted curve. Returns *prob* when there is none."""
    if not curve:
        return prob
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return prob
    for upper, value in curve:
        if p <= upper:
            return value
    return curve[-1][1]


def calibrate_triplet(curve: Sequence[Tuple[float, float]],
                      probs: Sequence[float]) -> List[float]:
    """Recalibrate the leading outcome and rescale the rest to keep the sum at 1.

    Only the pick's probability has an observed frequency to be checked
    against, so that is the one the curve corrects; the remaining mass is
    redistributed in proportion, which preserves their relative order and any
    structural zero (a sport with no draw keeps its zero).
    """
    values = [max(0.0, float(p)) for p in probs]
    total = sum(values)
    if total <= 0:
        return list(values)
    values = [v / total for v in values]

    if not curve:
        return values

    lead = max(range(len(values)), key=lambda i: values[i])
    target = min(0.99, max(0.01, apply_isotonic(curve, values[lead])))
    rest = 1.0 - target
    others_total = sum(v for i, v in enumerate(values) if i != lead)

    out = []
    for i, v in enumerate(values):
        if i == lead:
            out.append(target)
        elif others_total > 0:
            out.append(rest * v / others_total)
        else:
            out.append(rest / max(1, len(values) - 1))
    return out


def load_curves(data: Optional[Dict[str, Any]]) -> Dict[str, List[Tuple[float, float]]]:
    """Read ``{'isotonic': {sport: [[x, y], ...]}}`` from a calibration payload."""
    curves: Dict[str, List[Tuple[float, float]]] = {}
    if not isinstance(data, dict):
        return curves
    raw = data.get('isotonic')
    if not isinstance(raw, dict):
        return curves
    for sport, points in raw.items():
        if not isinstance(points, list):
            continue
        parsed: List[Tuple[float, float]] = []
        for point in points:
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0.0 <= y <= 1.0:
                parsed.append((x, y))
        if parsed:
            parsed.sort(key=lambda t: t[0])
            curves[str(sport).lower()] = parsed
    return curves


__all__ = [
    'MIN_BIN_WEIGHT',
    'apply_isotonic',
    'calibrate_triplet',
    'fit_isotonic',
    'load_curves',
]
