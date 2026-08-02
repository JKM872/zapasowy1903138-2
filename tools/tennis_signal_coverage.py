#!/usr/bin/env python3
"""Which tennis signals are actually present, and which ones pay?

The tennis engine reads seven sources but real rows fill two or three, so most
predictions rest on the price plus noise — the engine scores Brier 0.5060 where
the bookmaker scores 0.4157. Before adding anything new it is worth knowing
which of the signals we already support are missing, and whether the matches
that do carry them return more.

Coverage answers "what is worth collecting". The ROI split answers "is it worth
collecting" — a signal present in 5% of rows that changes nothing is not a gap.

    python tools/tennis_signal_coverage.py
    python tools/tennis_signal_coverage.py --sport table_tennis
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.evaluate_elo_vs_market import _f, load_settled
from tools.segment_roi import Bucket, score_rows


def _has_form(row: Dict[str, Any], *keys: str) -> bool:
    from tennis_scoring_engine import _parse_form_list
    return any(len(_parse_form_list(row.get(k, []))) >= 3 for k in keys)


SIGNALS: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    'kursy': lambda r: _f(r.get('home_odds')) > 1 and _f(r.get('away_odds')) > 1,
    'H2H (>=1 mecz)': lambda r: (_f(r.get('h2h_count'))
                                 + _f(r.get('home_wins_in_h2h_last5'))
                                 + _f(r.get('away_wins_in_h2h_last5'))) > 0,
    'ranking obu': lambda r: bool(r.get('ranking_a')) and bool(r.get('ranking_b')),
    'forma obu': lambda r: (_has_form(r, 'form_a', 'home_form_overall', 'home_form')
                            and _has_form(r, 'form_b', 'away_form_overall',
                                          'away_form')),
    'forma na korcie': lambda r: (_has_form(r, 'surface_form_a')
                                  and _has_form(r, 'surface_form_b')),
    'fan vote (realny)': lambda r: (_f(r.get('sofascore_home_win_prob')) > 0
                                    and _f(r.get('sofascore_total_votes')) > 0),
    'ostatni mecz (data)': lambda r: bool(r.get('last_match_a_date')
                                          and r.get('last_match_b_date')),
    'forebet': lambda r: _f(r.get('forebet_probability')) > 0,
}


# Klucze, na których opiera się każdy test — służą do rozpoznania, czy pole
# w ogóle istnieje w eksporcie.
SIGNAL_KEYS: Dict[str, tuple] = {
    'kursy': ('home_odds', 'away_odds'),
    'H2H (>=1 mecz)': ('h2h_count', 'home_wins_in_h2h_last5'),
    'ranking obu': ('ranking_a', 'ranking_b'),
    'forma obu': ('form_a', 'home_form_overall', 'home_form'),
    'forma na korcie': ('surface_form_a', 'surface_form_b'),
    'fan vote (realny)': ('sofascore_home_win_prob', 'sofascore_total_votes'),
    'ostatni mecz (data)': ('last_match_a_date', 'last_match_b_date'),
    'forebet': ('forebet_probability',),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport', default='tennis')
    ap.add_argument('--min-n', type=int, default=40)
    args = ap.parse_args()

    rows = [r for r in load_settled() if r['_sport'] == args.sport]
    if not rows:
        print(f'Brak rozliczonych meczów z kursami dla {args.sport}.')
        return 1

    print(f'{args.sport}: {len(rows)} meczów z wynikiem i kursami')
    dates = sorted(r['_date'] for r in rows)
    print(f'Zakres: {dates[0]} .. {dates[-1]}\n')

    # Które klucze w ogóle występują w eksporcie. Bez tego "0% pokrycia" czyta
    # się jak "scraper tego nie zbiera", a może po prostu znaczyć "export_settled
    # tego nie zapisuje" — dokładnie ta pomyłka kazała mi raz zarekomendować
    # naprawę rankingu, którego wcale nie zmierzyłem.
    exported: set = set()
    for r in rows:
        exported |= set(r.keys())

    print('=' * 84)
    print('  POKRYCIE SYGNAŁÓW — czego silnikowi brakuje')
    print('=' * 84)
    print(f'  {"sygnał":<22}{"obecny":>9}{"udział":>9}   uwaga')
    print('  ' + '-' * 80)
    present: Dict[str, List[Dict[str, Any]]] = {}
    for name, test in SIGNALS.items():
        try:
            hits = [r for r in rows if test(r)]
        except Exception as e:
            print(f'  {name:<22}  BŁĄD TESTU: {e}')
            continue
        present[name] = hits
        note = ''
        needed = SIGNAL_KEYS.get(name, ())
        if needed and not (set(needed) & exported):
            note = 'BRAK POLA W EKSPORCIE — nie zmierzone'
        print(f'  {name:<22}{len(hits):>9}{100.0 * len(hits) / len(rows):>8.1f}%'
              f'   {note}')

    counts = defaultdict(int)
    for r in rows:
        n = sum(1 for name, test in SIGNALS.items()
                if name in present and r in present[name])
        counts[n] += 1

    scored = score_rows(rows)
    by_url = {r.get('match_url'): r for r in scored}

    print('\n' + '=' * 84)
    print('  CZY DANY SYGNAŁ SIĘ OPŁACA — ROI z nim i bez niego')
    print('=' * 84)
    print(f'  {"sygnał":<22}{"n z":>7}{"traf.":>9}{"ROI":>9}'
          f'{"n bez":>8}{"traf.":>9}{"ROI":>9}')
    print('  ' + '-' * 80)
    for name in SIGNALS:
        if name not in present:
            continue
        urls_with = {r.get('match_url') for r in present[name]}
        with_b, without_b = Bucket(), Bucket()
        for url, s in by_url.items():
            target = with_b if url in urls_with else without_b
            target.add(s['_won'], s['_odds'], s['_ev'] > 0)
        if with_b.n < args.min_n or without_b.n < args.min_n:
            print(f'  {name:<22}{with_b.n:>7}   za mała próba po jednej stronie')
            continue
        print(f'  {name:<22}{with_b.n:>7}{100.0 * with_b.hits / with_b.n:>8.1f}%'
              f'{100.0 * with_b.pnl / with_b.n:>8.1f}%'
              f'{without_b.n:>8}{100.0 * without_b.hits / without_b.n:>8.1f}%'
              f'{100.0 * without_b.pnl / without_b.n:>8.1f}%')

    print('\n  Sygnał wart zbierania to taki, który jest RZADKI i którego')
    print('  obecność wiąże się z lepszym ROI.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
