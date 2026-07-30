#!/usr/bin/env python3
"""Which kinds of picks actually pay — measured, not assumed.

Reads the accuracy reports in ``outputs/results_summary_*.json`` and splits the
settled picks by sport, grade, model probability, price and whether the pick
agreed with the market. Every row shows the break-even hit rate for its own
average odds, so a segment is judged against what it needed rather than against
50%.

This exists because the filters steering the mail were untested. A/B grading
decided what got sent while nothing measured whether Grade A beats Grade C, and
the odds floor was set by intuition. The first run of this on 26-29 July showed
44.7% on 76 priced picks against a 56.7% break-even — the picks were below the
line in every single segment, which is not something a threshold can fix.

    python tools/segment_performance.py
    python tools/segment_performance.py --min-n 20 --stake 100
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_settled(pattern: str = 'outputs/results_summary_*.json',
                 ) -> List[Dict[str, Any]]:
    """Every pick with a win/loss outcome, from every report on disk."""
    rows: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(pattern)):
        if '_telegram' in path:
            continue                      # same picks, different channel
        try:
            doc = json.load(open(path, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        date = doc.get('date')
        for m in (doc.get('matches') or doc.get('details') or []):
            if m.get('outcome') in ('won', 'lost'):
                rows.append(dict(m, _date=m.get('match_date') or date))
    return rows


def picked_odds(row: Dict[str, Any]) -> Optional[float]:
    """The price we would have been paid, or None when the pick was unpriced."""
    side = row.get('predicted')
    value = row.get('home_odds') if side == 'home' else row.get('away_odds')
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(odds) or odds <= 1.0:
        return None
    return odds


def measure(rows: List[Dict[str, Any]], stake: float = 100.0,
            ) -> Optional[Dict[str, float]]:
    """Hit rate, average price, break-even and ROI for one segment."""
    priced = [(r, picked_odds(r)) for r in rows]
    priced = [(r, o) for r, o in priced if o is not None]
    if not priced:
        return None

    wins = sum(1 for r, _ in priced if r['outcome'] == 'won')
    net = sum((o * stake - stake) if r['outcome'] == 'won' else -stake
              for r, o in priced)
    n = len(priced)
    avg_odds = sum(o for _, o in priced) / n
    return {
        'n': n,
        'n_unpriced': len(rows) - n,
        'accuracy': 100.0 * wins / n,
        'avg_odds': avg_odds,
        'breakeven': 100.0 / avg_odds,
        'roi': 100.0 * net / (n * stake),
        'net': net,
    }


def _line(label: str, res: Optional[Dict[str, float]], min_n: int) -> str:
    if not res:
        return f'  {label:<26} —  (żaden typ nie miał kursu)'
    flag = '' if res['n'] >= min_n else '  ⚠ próbka za mała'
    return (f"  {label:<26} n={res['n']:<4} traf={res['accuracy']:>5.1f}%"
            f"  śr.kurs={res['avg_odds']:.2f}  próg={res['breakeven']:>5.1f}%"
            f"  ROI={res['roi']:>+7.1f}%  netto={res['net']:>+8.0f}{flag}")


def _bucket(rows, field, lo, hi):
    out = []
    for r in rows:
        try:
            v = float(r.get(field))
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        if lo <= v < hi:
            out.append(r)
    return out


def report(rows: List[Dict[str, Any]], stake: float = 100.0,
           min_n: int = 30) -> Dict[str, Any]:
    """Print every segmentation and return the raw numbers."""
    out: Dict[str, Any] = {}

    print('=' * 100)
    print(f'  SKUTECZNOŚĆ PO SEGMENTACH — {len(rows)} rozliczonych typów')
    print(f"  próg = trafność potrzebna przy tym średnim kursie, żeby wyjść na zero")
    print('=' * 100)

    total = measure(rows, stake)
    print(_line('WSZYSTKO', total, min_n))
    out['all'] = total
    if total and total['n_unpriced']:
        print(f"  ({total['n_unpriced']} typów bez kursu — nierozliczalne finansowo)")

    for title, groups in (
        ('PER SPORT', _by(rows, lambda r: (r.get('sport') or '?').lower())),
        ('PER GRADE', _by(rows, lambda r: r.get('prediction_grade') or 'brak')),
        ('CZY TYP = FAWORYT RYNKU', _by(rows, _market_side)),
    ):
        print('\n' + '-' * 100)
        print(f'  {title}')
        print('-' * 100)
        section = {}
        for key in sorted(groups, key=lambda k: -len(groups[k])):
            res = measure(groups[key], stake)
            print(_line(str(key), res, min_n))
            section[str(key)] = res
        out[title] = section

    print('\n' + '-' * 100)
    print('  PO PRAWDOPODOBIEŃSTWIE MODELU')
    print('-' * 100)
    prob_section = {}
    for lo, hi in ((0, 55), (55, 65), (65, 75), (75, 85), (85, 101)):
        sel = _bucket(rows, 'scoring_prob', lo, hi)
        if sel:
            res = measure(sel, stake)
            print(_line(f'prob {lo}-{hi}%', res, min_n))
            prob_section[f'{lo}-{hi}'] = res
    if not prob_section:
        print('  brak scoring_prob w danych — starsze raporty go nie zapisywały')
    out['probability'] = prob_section

    print('\n' + '-' * 100)
    print('  PO KURSIE')
    print('-' * 100)
    odds_section = {}
    for lo, hi in ((1.0, 1.35), (1.35, 1.60), (1.60, 1.90), (1.90, 2.20),
                   (2.20, 2.50), (2.50, 99.0)):
        sel = [r for r in rows
               if (picked_odds(r) or 0) and lo <= picked_odds(r) < hi]
        if sel:
            res = measure(sel, stake)
            print(_line(f'kurs {lo:.2f}-{hi:.2f}', res, min_n))
            odds_section[f'{lo}-{hi}'] = res
    out['odds'] = odds_section

    print('\n' + '-' * 100)
    print('  PO EV MODELU')
    print('-' * 100)
    ev_section = {}
    for label, lo, hi in (('EV > 0', 1e-9, 1e9), ('EV <= 0', -1e9, 1e-9)):
        sel = _bucket(rows, 'scoring_ev', lo, hi)
        if sel:
            res = measure(sel, stake)
            print(_line(label, res, min_n))
            ev_section[label] = res
    if not ev_section:
        print('  brak scoring_ev w danych')
    out['ev'] = ev_section

    print('\n' + '=' * 100)
    if total and total['n'] < min_n:
        print(f"  UWAGA: {total['n']} rozliczonych typów z kursem to za mało, "
              f"żeby odróżnić przewagę od szumu (chcemy ≥{min_n}).")
    elif total:
        verdict = ('powyżej progu — segment do dalszej obserwacji'
                   if total['roi'] > 0 else
                   'poniżej progu opłacalności')
        print(f"  Całość: {verdict}.")
    print('=' * 100)
    return out


def _by(rows, key_fn):
    groups = defaultdict(list)
    for r in rows:
        groups[key_fn(r)].append(r)
    return groups


def _market_side(row: Dict[str, Any]) -> str:
    try:
        home, away = float(row.get('home_odds')), float(row.get('away_odds'))
        if math.isnan(home) or math.isnan(away):
            return 'brak kursów'
    except (TypeError, ValueError):
        return 'brak kursów'
    mine = home if row.get('predicted') == 'home' else away
    other = away if row.get('predicted') == 'home' else home
    if mine == other:
        return 'kursy równe'
    return 'typ = faworyt rynku' if mine < other else 'typ = underdog'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stake', type=float, default=100.0)
    ap.add_argument('--min-n', type=int, default=30,
                    help='Below this a segment is flagged as too small to trust')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    rows = load_settled()
    if not rows:
        print('Brak rozliczonych typów — uruchom najpierw Check Results.')
        return 0

    result = report(rows, stake=args.stake, min_n=args.min_n)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
