#!/usr/bin/env python3
"""Is form worth what we are about to pay for it?

Compares, on identical matches from a held-out later window:

  * the scoring engine with the form it gets today (whatever the scrapers left)
  * the same engine with form rebuilt from the result store, last 6
  * the same engine with form rebuilt from the result store, last 10
  * Elo
  * the sport's base rate, as the floor any of this has to clear

There are no odds in the result store, so the engine here runs without its
strongest source. That makes these numbers a measure of the *form* machinery
only, not of live pipeline accuracy — a distinction worth keeping, because the
form weight is what we are deciding whether to change.

Form is always built with matches strictly earlier than the fixture being
scored, so the later window cannot inform its own predictions.

    python tools/evaluate_form.py
    python tools/evaluate_form.py --sport football --limit 2000
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import football_scoring_engine as fse  # noqa: E402
from elo_ratings import EloModel, fit  # noqa: E402
from football_scoring_engine import SPORT_PROFILES  # noqa: E402
from team_form import FormProvider  # noqa: E402
from tools.evaluate_elo import OUTCOMES, load_store, split_by_date  # noqa: E402


def _metrics(rows: List[Tuple[Tuple[float, float, float], int]]) -> Dict[str, float]:
    if not rows:
        return {'n': 0, 'accuracy': 0.0, 'brier': float('nan'),
                'log_loss': float('nan')}
    hits = brier = logloss = 0.0
    for probs, target in rows:
        total = sum(probs) or 1.0
        p = [x / total for x in probs]
        hits += 1 if max(range(3), key=lambda i: p[i]) == target else 0
        brier += sum((v - (1.0 if i == target else 0.0)) ** 2
                     for i, v in enumerate(p))
        logloss += -math.log(max(1e-9, p[target]))
    n = len(rows)
    return {'n': n, 'accuracy': 100.0 * hits / n, 'brier': brier / n,
            'log_loss': logloss / n}


def _engine_probs(engine, row: Dict[str, Any], sport: str
                  ) -> Tuple[float, float, float]:
    """Score one row, routing racket sports to the two-outcome engine."""
    if sport in ('tennis', 'table_tennis'):
        from tennis_scoring_engine import TennisScoringEngine
        st = TennisScoringEngine().score_match(row)
        return st.cal_a, 0.0, st.cal_b
    sm = engine.score_match(row)
    return sm.cal_home, sm.cal_draw, sm.cal_away


def _prior(sport: str) -> Tuple[float, float, float]:
    p = SPORT_PROFILES.get(sport, SPORT_PROFILES['football'])
    h = p.get('home_advantage', 0.46)
    d = p.get('draw_rate', 0.26)
    a = p.get('away_rate', 0.28)
    t = h + d + a
    return h / t, d / t, a / t


def evaluate_sport(all_rows: List[Dict[str, Any]], provider: FormProvider,
                   sport: str, cut: str, limit: int,
                   min_played: int = 3) -> Optional[Dict[str, Any]]:
    sport_rows = sorted([r for r in all_rows if r['sport'] == sport],
                        key=lambda r: r['date'])
    train, test = split_by_date(sport_rows, cut)
    if len(train) < 200 or len(test) < 100:
        print(f'  {sport:<14} za mało danych (train={len(train)}, test={len(test)})')
        return None

    # Elo, trained on the earlier window then walked through the later one.
    model, _ = fit(train, sport, min_played=min_played)
    elo = EloModel(sport=sport, k=model.k, home_advantage=model.home_advantage,
                   draw_share=model.draw_share)
    elo.walk_forward(train, min_played=min_played)

    # Evenly spaced sample so the subset spans the whole window rather than
    # just its start.
    step = max(1, len(test) // limit) if limit else 1
    sampled = set(range(0, len(test), step))

    engine = fse.FootballScoringEngine()
    scored: Dict[str, List[Tuple[Tuple[float, float, float], int]]] = defaultdict(list)
    original_cap = fse.FORM_DECAY_WINDOW

    for idx, row in enumerate(test):
        home, away, winner = row['home_team'], row['away_team'], row['winner']
        target = OUTCOMES.index(winner)
        warm = (elo.matches_played(home) >= min_played
                and elo.matches_played(away) >= min_played)

        if idx in sampled and warm:
            scored['elo'].append((elo.predict(home, away), target))
            scored['prior'].append((_prior(sport), target))

            for label, window in (('form6', 6), ('form10', 10)):
                base = {'home_team': home, 'away_team': away, 'sport': sport,
                        'match_date': row['date']}
                provider.attach(base, window=window, overwrite=True)
                fse.FORM_DECAY_WINDOW = window
                try:
                    scored[label].append(
                        (_engine_probs(engine, base, sport), target))
                finally:
                    fse.FORM_DECAY_WINDOW = original_cap

            bare = {'home_team': home, 'away_team': away, 'sport': sport,
                    'match_date': row['date']}
            scored['no_form'].append((_engine_probs(engine, bare, sport), target))

        elo.update(home, away, winner)

    return {'sport': sport, 'n_train': len(train), 'n_test': len(test),
            'k': model.k,
            'results': {k: _metrics(v) for k, v in scored.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport')
    ap.add_argument('--split', default='')
    ap.add_argument('--limit', type=int, default=1500,
                    help='Ile meczów testowych ocenić per sport (0 = wszystkie)')
    ap.add_argument('--min-played', type=int, default=3)
    args = ap.parse_args()

    rows = load_store()
    if not rows:
        print('Brak rozliczonych meczów.')
        return 1

    dates = sorted(r['date'] for r in rows)
    cut = args.split or dates[int(len(dates) * 0.7)]
    print(f'Rozliczonych: {len(rows)} | zakres {dates[0]}..{dates[-1]} | podział {cut}')
    print('Forma budowana wyłącznie z meczów WCZEŚNIEJSZYCH niż oceniany mecz.')
    print('Uwaga: w magazynie nie ma kursów, więc silnik pracuje bez '
          'najmocniejszego źródła.\n')

    provider = FormProvider.from_rows(
        [{'status': 'finished', 'winner': r['winner'], 'date': r['date'],
          'home_team': r['home_team'], 'away_team': r['away_team'],
          'sport': r['sport']} for r in rows])

    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r['sport']] += 1
    sports = [args.sport] if args.sport else [
        s for s, _ in sorted(counts.items(), key=lambda kv: -kv[1])]

    labels = [('no_form', 'silnik bez formy'), ('form6', 'silnik + forma 6'),
              ('form10', 'silnik + forma 10'), ('elo', 'Elo'),
              ('prior', 'bazowa częstość')]

    for sport in sports:
        report = evaluate_sport(rows, provider, sport, cut, args.limit,
                                args.min_played)
        if not report:
            continue
        print(f"\n{'=' * 78}\n  {sport.upper()}  (test {report['n_test']}, K={report['k']})")
        print(f"{'  wariant':<28}{'n':>7}{'trafność':>11}{'brier':>10}{'log-loss':>11}")
        print('  ' + '-' * 74)
        res = report['results']
        best = min((m['brier'] for m in res.values() if m['n']), default=None)
        for key, name in labels:
            m = res.get(key)
            if not m or not m['n']:
                continue
            mark = ' <=' if best is not None and abs(m['brier'] - best) < 1e-9 else ''
            print(f"  {name:<26}{m['n']:>7}{m['accuracy']:>10.1f}%"
                  f"{m['brier']:>10.4f}{m['log_loss']:>11.4f}{mark}")

    print('\nZnacznik <= wskazuje najniższy Brier w danym sporcie.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
