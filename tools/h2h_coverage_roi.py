#!/usr/bin/env python3
"""Are matches without head-to-head history worth betting?

The qualification gate leans on H2H, so fixtures where the pair has never met
are dropped — 60 of 138 tennis matches on 2026-08-02 had a 0-0 record. Opening
that gate to form instead would add volume, and the only question that matters
is whether those fixtures return anything.

Splits settled matches carrying real prices by how much H2H history they have,
and reports hit rate and flat-stake ROI for each band. Judged on a held-out
later window too, because a band that only works in the earlier period is the
same trap as the grade filter.

    python tools/h2h_coverage_roi.py
    python tools/h2h_coverage_roi.py --sport tennis
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.evaluate_elo_vs_market import _f, load_settled
from tools.segment_roi import Bucket, score_rows


def _h2h_count(row: Dict[str, Any]) -> int:
    n = _f(row.get('h2h_count'))
    if n > 0:
        return int(n)
    return int(_f(row.get('home_wins_in_h2h_last5'))
               + _f(row.get('away_wins_in_h2h_last5')))


def _form_len(row: Dict[str, Any], *keys: str) -> int:
    from football_scoring_engine import _parse_form
    best = 0
    for key in keys:
        best = max(best, len(_parse_form(row.get(key, []))))
    return best


def report(title: str, buckets: Dict[str, Bucket], order: List[str],
           min_n: int) -> None:
    print(f'\n{"=" * 86}')
    print(f'  {title}')
    print(f'  {"segment":<26}{"n":>7}{"traf.":>9}{"ROI":>9}'
          f'{"n(EV+)":>8}{"traf.":>8}{"ROI":>9}')
    print('  ' + '-' * 82)
    for key in order:
        b = buckets.get(key)
        if not b or not b.n:
            continue
        flag = '' if b.n >= min_n else '  (mała próba)'
        print(b.row(key) + flag)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport')
    ap.add_argument('--split', default='2026-06-15')
    ap.add_argument('--min-n', type=int, default=50)
    args = ap.parse_args()

    rows = load_settled()
    if not rows:
        return 1
    if args.sport:
        rows = [r for r in rows if r['_sport'] == args.sport]
    if not rows:
        print('Brak meczów po filtrach.')
        return 1

    print(f'Meczów z wynikiem i kursami: {len(rows)}')
    print(f'Podział: wcześniej < {args.split} <= okno odłożone')
    print('Typ przeliczony obecnym silnikiem (z kotwicą rynkową).')

    scored = score_rows(rows)
    print(f'Ocenionych: {len(scored)}')

    H2H_ORDER = ['bez H2H (0)', 'H2H 1-2', 'H2H 3-4', 'H2H 5+']
    FORM_ORDER = ['bez H2H, forma 0', 'bez H2H, forma 1-4',
                  'bez H2H, forma 5+']

    def h2h_band(r):
        n = _h2h_count(r)
        if n == 0:
            return 'bez H2H (0)'
        if n <= 2:
            return 'H2H 1-2'
        if n <= 4:
            return 'H2H 3-4'
        return 'H2H 5+'

    for window, keep in (('WCZEŚNIEJ', lambda r: r['_date'] < args.split),
                         ('OKNO ODŁOŻONE', lambda r: r['_date'] >= args.split)):
        subset = [r for r in scored if keep(r)]
        if not subset:
            continue

        by_h2h: Dict[str, Bucket] = defaultdict(Bucket)
        by_form: Dict[str, Bucket] = defaultdict(Bucket)
        for r in subset:
            won, odds, pos = r['_won'], r['_odds'], r['_ev'] > 0
            by_h2h[h2h_band(r)].add(won, odds, pos)
            if _h2h_count(r) == 0:
                n = _form_len(r, 'home_form_overall', 'home_form',
                              'away_form_overall', 'away_form')
                label = ('bez H2H, forma 0' if n == 0
                         else 'bez H2H, forma 1-4' if n < 5
                         else 'bez H2H, forma 5+')
                by_form[label].add(won, odds, pos)

        report(f'{window} — ile historii H2H', by_h2h, H2H_ORDER, args.min_n)
        report(f'{window} — mecze BEZ H2H, wg dostępnej formy', by_form,
               FORM_ORDER, args.min_n)

    print('\nOtwieramy bramę na formę tylko jeśli mecze bez H2H nie tracą')
    print('w OBU okresach — inaczej dosypiemy wolumenu, który kosztuje.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
