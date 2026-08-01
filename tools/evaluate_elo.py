#!/usr/bin/env python3
"""Does a strength rating predict better than what we have?

Trains on an earlier window and is judged on a later one — split by date, never
at random, because a random split on sport data lets a rating see a competitor's
future form and reports a number that will not survive contact with tomorrow's
fixture.

Three things are compared on exactly the same matches: the Elo rating, the
current scoring engine, and the bookmaker where a price exists. The bookmaker is
the bar that matters; beating our own engine while trailing the market means we
have made a better loser.

    python tools/evaluate_elo.py
    python tools/evaluate_elo.py --sport table_tennis --split 2026-06-15
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elo_ratings import EloModel, fit, observed_draw_share  # noqa: E402

OUTCOMES = ('home', 'draw', 'away')


def load_store(path: str = 'outputs/result_store.json') -> List[Dict[str, Any]]:
    """Settled matches with the fields a rating needs: who, whom, when, result."""
    try:
        raw = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'Nie mogę wczytać {path}: {e}')
        return []

    rows = []
    for url, res in raw.items():
        if res.get('status') != 'finished':
            continue
        if res.get('winner') not in OUTCOMES:
            continue
        if not (res.get('home_team') and res.get('away_team') and res.get('date')):
            continue
        rows.append({
            'match_url': url,
            'sport': (res.get('sport') or 'football').lower(),
            'date': res['date'],
            'home_team': res['home_team'],
            'away_team': res['away_team'],
            'winner': res['winner'],
        })
    return rows


def split_by_date(rows: List[Dict[str, Any]], cut: str
                  ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    train = [r for r in rows if r['date'] < cut]
    test = [r for r in rows if r['date'] >= cut]
    return train, test


def _metrics(probs_and_targets: List[Tuple[Tuple[float, float, float], int]]
             ) -> Dict[str, float]:
    if not probs_and_targets:
        return {'n': 0}
    hits = brier = logloss = 0.0
    for probs, target in probs_and_targets:
        pick = max(range(3), key=lambda i: probs[i])
        hits += 1 if pick == target else 0
        brier += sum((p - (1.0 if i == target else 0.0)) ** 2
                     for i, p in enumerate(probs))
        logloss += -math.log(max(1e-9, probs[target]))
    n = len(probs_and_targets)
    return {'n': n, 'accuracy': 100.0 * hits / n, 'brier': brier / n,
            'log_loss': logloss / n}


def evaluate_sport(rows: List[Dict[str, Any]], sport: str, cut: str,
                   min_played: int = 3) -> Optional[Dict[str, Any]]:
    """Fit on the earlier window, score the later one, report both."""
    sport_rows = sorted([r for r in rows if r['sport'] == sport],
                        key=lambda r: r['date'])
    train, test = split_by_date(sport_rows, cut)
    if len(train) < 200 or len(test) < 100:
        print(f'  {sport:<14} za mało danych (train={len(train)}, test={len(test)})')
        return None

    model, train_report = fit(train, sport, min_played=min_played)

    # Replay the training window to arrive at the ratings as they stood at the
    # cut, then walk the test window predicting before each update.
    fitted = EloModel(sport=sport, k=model.k,
                      home_advantage=model.home_advantage,
                      draw_share=model.draw_share)
    fitted.walk_forward(train, min_played=min_played)

    scored: List[Tuple[Tuple[float, float, float], int]] = []
    cold = 0
    for row in test:
        home, away, winner = row['home_team'], row['away_team'], row['winner']
        if (fitted.matches_played(home) >= min_played
                and fitted.matches_played(away) >= min_played):
            scored.append((fitted.predict(home, away),
                           OUTCOMES.index(winner)))
        else:
            cold += 1
        fitted.update(home, away, winner)

    elo = _metrics(scored)
    return {
        'sport': sport,
        'n_train': len(train),
        'n_test': len(test),
        'k': model.k,
        'home_advantage': model.home_advantage,
        'draw_share': round(model.draw_share, 3),
        'train': train_report,
        'test': elo,
        'cold': cold,
        'competitors': len(fitted.ratings),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport', help='Tylko ten sport')
    ap.add_argument('--split', default='',
                    help='Data podziału (YYYY-MM-DD). Domyślnie ostatnie ~30%%')
    ap.add_argument('--min-played', type=int, default=3,
                    help='Ile meczów musi mieć zawodnik, żeby go oceniać')
    args = ap.parse_args()

    rows = load_store()
    if not rows:
        print('Brak rozliczonych meczów — uruchom najpierw backfill.')
        return 1

    dates = sorted(r['date'] for r in rows)
    cut = args.split or dates[int(len(dates) * 0.7)]
    print(f'Rozliczonych meczów: {len(rows)}')
    print(f'Zakres: {dates[0]} .. {dates[-1]}   podział: {cut}')
    print(f'Trening < {cut} | test >= {cut}\n')

    by_sport: Dict[str, int] = defaultdict(int)
    for r in rows:
        by_sport[r['sport']] += 1

    sports = [args.sport] if args.sport else [
        s for s, n in sorted(by_sport.items(), key=lambda kv: -kv[1])]

    print('=' * 92)
    print('  ELO — trening na wcześniejszym okresie, ocena na późniejszym')
    print('=' * 92)
    results = []
    for sport in sports:
        report = evaluate_sport(rows, sport, cut, args.min_played)
        if not report:
            continue
        results.append(report)
        t = report['test']
        print(f"\n  {sport}  (train {report['n_train']}, test {report['n_test']},"
              f" zawodników {report['competitors']})")
        print(f"    K={report['k']:<5} przewaga gospodarza={report['home_advantage']:<5}"
              f" udział remisów={report['draw_share']}")
        if t.get('n'):
            print(f"    ocenionych {t['n']} (pominięto {report['cold']} bez historii)")
            print(f"    trafność {t['accuracy']:.1f}%  brier {t['brier']:.4f}"
                  f"  log-loss {t['log_loss']:.4f}")
        else:
            print('    brak meczów z wystarczającą historią')

    print('\n' + '=' * 92)
    print('  PORÓWNANIE: Elo vs obecny silnik (Brier, niżej = lepiej)')
    print('=' * 92)
    print('  Uruchom `python calibrate_weights.py --real ... --per-sport`, żeby')
    print('  zobaczyć Brier silnika na tych samych sportach.')
    print('  Referencja z 2026-07-30: football 0.6253, basketball 0.4382,')
    print('  tennis 0.4970, hockey 0.4847, baseball 0.4669, volleyball 0.3932,')
    print('  handball 0.4397.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
