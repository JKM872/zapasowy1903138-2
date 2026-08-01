#!/usr/bin/env python3
"""Anchor the model to the price, and bet only where it still disagrees.

Every filter tried so far — grade, odds band, favourite/underdog, EV sign —
selected picks from the model's own output and none survived a later window.
That is the expected result when the model's probabilities are worse than the
bookmaker's: in tennis the engine scores Brier 0.5060 against the market's
0.4157, so "the model sees value here" mostly means "the model is wrong here".
Filtering harder just concentrates the errors.

This tests the other direction. Blend the engine with the market

    p = (1 - w) * p_engine + w * p_market

and sweep w. At w=0 nothing changes. At w=1 we hold the bookmaker's own numbers
and, after his margin, see no value at all — so bet count must fall to nearly
zero. If ROI peaks somewhere in between, that interior point is the honest
answer: stay anchored to the price and stake only where a market-anchored
estimate still disagrees with it.

Judged on a held-out later window, because that is what killed every earlier
candidate.

    python tools/market_blend.py
    python tools/market_blend.py --sport tennis
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.evaluate_elo_vs_market import (_engine_probs, _f, load_settled,
                                          market_probs)

WEIGHTS = (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.0)

# Minimum expected value required before staking. 0.0 is today's rule: any
# positive EV is published. Larger values demand the disagreement be big enough
# to survive our own noise.
EV_FLOORS = (0.0, 0.05, 0.10)


class Result:
    __slots__ = ('n', 'hits', 'brier', 'logloss', 'bets', 'wins', 'pnl')

    def __init__(self) -> None:
        self.n = self.hits = self.bets = self.wins = 0
        self.brier = self.logloss = self.pnl = 0.0

    def add(self, probs: Tuple[float, float, float], target: int,
            odds: Tuple[float, float, float], ev_floor: float) -> None:
        total = sum(probs) or 1.0
        p = [x / total for x in probs]
        self.n += 1
        self.brier += sum((v - (1.0 if i == target else 0.0)) ** 2
                          for i, v in enumerate(p))
        self.logloss += -math.log(max(1e-9, p[target]))
        if max(range(3), key=lambda i: p[i]) == target:
            self.hits += 1

        best_ev, best_i = ev_floor, None
        for i in range(3):
            if odds[i] <= 1:
                continue
            ev = p[i] * odds[i] - 1.0
            if ev > best_ev:
                best_ev, best_i = ev, i
        if best_i is None:
            return
        self.bets += 1
        if best_i == target:
            self.wins += 1
            self.pnl += odds[best_i] - 1.0
        else:
            self.pnl -= 1.0

    def row(self, label: str) -> str:
        if not self.n:
            return f'  {label:<22} brak danych'
        roi = (100.0 * self.pnl / self.bets) if self.bets else 0.0
        hit = (100.0 * self.wins / self.bets) if self.bets else 0.0
        return (f'  {label:<22}{self.n:>7}{self.brier / self.n:>9.4f}'
                f'{self.bets:>8}{hit:>9.1f}%{roi:>9.1f}%{self.pnl:>10.1f}')


def run(rows: List[Dict[str, Any]], sport: str, label: str,
        ev_floor: float) -> Dict[float, Result]:
    import football_scoring_engine as fse
    engine = fse.FootballScoringEngine()

    out = {w: Result() for w in WEIGHTS}
    for row in rows:
        target = row['_target']
        odds = (_f(row.get('home_odds')), _f(row.get('draw_odds')),
                _f(row.get('away_odds')))
        try:
            eng = _engine_probs(engine, dict(row), sport)
        except Exception:
            continue
        mkt = market_probs(row)
        for w in WEIGHTS:
            blended = tuple((1.0 - w) * e + w * m for e, m in zip(eng, mkt))
            out[w].add(blended, target, odds, ev_floor)
    return out


def report(title: str, results: Dict[float, Result]) -> Optional[float]:
    print(f'\n  {title}')
    print(f'  {"waga rynku":<22}{"n":>7}{"brier":>9}{"zakł.":>8}'
          f'{"traf.":>9}{"ROI":>9}{"wynik":>10}')
    print('  ' + '-' * 74)
    best_w, best_roi = None, None
    for w in WEIGHTS:
        r = results[w]
        print(r.row(f'w={w:.2f}'))
        if r.bets >= 30:
            roi = r.pnl / r.bets
            if best_roi is None or roi > best_roi:
                best_w, best_roi = w, roi
    return best_w


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport')
    ap.add_argument('--split', default='2026-06-15',
                    help='Data podziału: trening < data, ocena >= data')
    args = ap.parse_args()

    rows = load_settled()
    if not rows:
        return 1
    if args.sport:
        rows = [r for r in rows if r['_sport'] == args.sport]

    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r['_sport']] += 1
    sports = [args.sport] if args.sport else [
        s for s, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n >= 300]

    print(f'Meczów z wynikiem i kursami: {len(rows)}')
    print(f'Podział: wcześniej < {args.split} <= okno odłożone')
    print('w=0.00 to dzisiejszy silnik. w=1.00 to same kursy bukmachera.')
    print('ROI: stawka płaska na typ z EV powyżej progu.')

    for sport in sports:
        early = [r for r in rows if r['_sport'] == sport
                 and r['_date'] < args.split]
        late = [r for r in rows if r['_sport'] == sport
                and r['_date'] >= args.split]
        if len(early) < 200 or len(late) < 100:
            continue

        print(f'\n{"=" * 88}')
        print(f'  {sport.upper()}   wcześniej {len(early)} | odłożone {len(late)}')
        print('=' * 88)
        for floor in EV_FLOORS:
            tag = 'dzisiejsza reguła' if floor == 0 else f'próg EV {floor:+.2f}'
            best_early = report(f'[{tag}] okres wcześniejszy',
                                run(early, sport, 'early', floor))
            best_late = report(f'[{tag}] OKNO ODŁOŻONE',
                               run(late, sport, 'late', floor))
            if best_early is not None and best_late is not None:
                verdict = ('ZGODNE' if best_early == best_late
                           else 'ROZBIEŻNE — nie wdrażać')
                print(f'  najlepsza waga: wcześniej w={best_early:.2f}, '
                      f'odłożone w={best_late:.2f}  → {verdict}')

    print('\nWdrażamy tylko wagę, która wygrywa w OBU okresach.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
