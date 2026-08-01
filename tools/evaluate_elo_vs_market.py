#!/usr/bin/env python3
"""Does Elo add anything once the engine already has the odds?

The earlier comparison ran on the result store, which holds no prices, so the
engine was scored with its strongest source removed. Elo won every sport, and
that told us Elo beats form — not that Elo beats the pipeline. This runs on
settled rows that carry both a real bookmaker price and a real outcome, and asks
the only question that decides whether Elo ships: blended with the engine, at
what weight, does it lower Brier and raise ROI?

Everything is judged on the same later window, and Elo only ever sees matches
that finished strictly before the fixture it is predicting.

    python tools/evaluate_elo_vs_market.py
    python tools/evaluate_elo_vs_market.py --sport tennis
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

from elo_ratings import EloModel, fit  # noqa: E402
from team_form import FORM_WINDOW, FormProvider  # noqa: E402
from tools.evaluate_elo import load_store  # noqa: E402

OUTCOMES = ('home', 'draw', 'away')
RESULT_TO_INDEX = {'1': 0, 'X': 1, '2': 2}

# Blend weights swept for Elo against the engine. 0.0 is the engine untouched,
# which is the incumbent any candidate has to beat.
BLEND_WEIGHTS = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 1.0)

# Minimum store appearances required before store form is trusted to fill a gap.
MIN_HISTORY_GATES = (5, 10, 20)


def load_settled(path: str = 'outputs/settled_all.json') -> List[Dict[str, Any]]:
    """Rows carrying an outcome, a date, both names and a usable price."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        print(f'Nie mogę wczytać {path}: {e}')
        print('Odtwórz: python export_settled.py --source local --sport all')
        return []

    if isinstance(data, dict):
        for key in ('matches', 'results', 'predictions', 'data'):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    rows = []
    for r in data:
        result = str(r.get('actual_result', '')).strip().upper()
        if result not in RESULT_TO_INDEX:
            continue
        date = r.get('match_date') or r.get('date')
        if not (date and r.get('home_team') and r.get('away_team')):
            continue
        if _f(r.get('home_odds')) <= 1 or _f(r.get('away_odds')) <= 1:
            continue
        r['_date'] = str(date)
        r['_target'] = RESULT_TO_INDEX[result]
        r['_sport'] = (r.get('sport') or 'football').lower()
        rows.append(r)
    return rows


def _f(val: Any) -> float:
    try:
        f = float(val)
        return 0.0 if math.isnan(f) else f
    except (TypeError, ValueError):
        return 0.0


def market_probs(row: Dict[str, Any]) -> Tuple[float, float, float]:
    """Implied probabilities with the bookmaker margin removed."""
    ih = 1.0 / _f(row.get('home_odds'))
    ia = 1.0 / _f(row.get('away_odds'))
    od = _f(row.get('draw_odds'))
    idr = (1.0 / od) if od > 1 else 0.0
    total = ih + idr + ia
    return ih / total, idr / total, ia / total


class Metric:
    """Brier, log-loss, hit rate and flat-stake ROI for one predictor."""

    def __init__(self, label: str):
        self.label = label
        self.n = 0
        self.hits = 0
        self.brier = 0.0
        self.logloss = 0.0
        self.bets = 0
        self.pnl = 0.0

    def add(self, probs: Tuple[float, float, float], target: int,
            odds: Tuple[float, float, float]) -> None:
        total = sum(probs) or 1.0
        p = [x / total for x in probs]
        self.n += 1
        self.brier += sum((v - (1.0 if i == target else 0.0)) ** 2
                          for i, v in enumerate(p))
        self.logloss += -math.log(max(1e-9, p[target]))
        pick = max(range(3), key=lambda i: p[i])
        if pick == target:
            self.hits += 1

        # Stake only where the model sees positive expected value, which is how
        # the pipeline actually decides. Accuracy without this hides that a
        # model can be right often and still lose money on short prices.
        best_ev, best_i = 0.0, None
        for i in range(3):
            o = odds[i]
            if o <= 1:
                continue
            ev = p[i] * o - 1.0
            if ev > best_ev:
                best_ev, best_i = ev, i
        if best_i is not None:
            self.bets += 1
            self.pnl += (odds[best_i] - 1.0) if best_i == target else -1.0

    def row(self) -> str:
        if not self.n:
            return f'  {self.label:<26} brak danych'
        roi = (100.0 * self.pnl / self.bets) if self.bets else 0.0
        return (f'  {self.label:<26}{self.n:>6}{100.0 * self.hits / self.n:>9.1f}%'
                f'{self.brier / self.n:>10.4f}{self.logloss / self.n:>10.4f}'
                f'{self.bets:>7}{roi:>9.1f}%')


def _engine_probs(engine, row: Dict[str, Any], sport: str
                  ) -> Tuple[float, float, float]:
    if sport in ('tennis', 'table_tennis'):
        from tennis_scoring_engine import TennisScoringEngine
        st = TennisScoringEngine().score_match(row)
        return st.cal_a, 0.0, st.cal_b
    sm = engine.score_match(row)
    return sm.cal_home, sm.cal_draw, sm.cal_away


def blend(engine_p: Tuple[float, float, float],
          elo_p: Tuple[float, float, float], w: float
          ) -> Tuple[float, float, float]:
    return tuple((1.0 - w) * e + w * l for e, l in zip(engine_p, elo_p))


def evaluate_sport(settled: List[Dict[str, Any]], store: List[Dict[str, Any]],
                   provider: FormProvider, sport: str, cut: str,
                   min_played: int = 3) -> None:
    store_rows = sorted([r for r in store if r['sport'] == sport],
                        key=lambda r: r['date'])
    train = [r for r in store_rows if r['date'] < cut]
    later = [r for r in store_rows if r['date'] >= cut]
    test = sorted([r for r in settled if r['_sport'] == sport
                   and r['_date'] >= cut], key=lambda r: r['_date'])

    if len(train) < 200 or len(test) < 60:
        print(f'\n  {sport:<14} za mało danych (train={len(train)}, '
              f'test z kursami={len(test)})')
        return

    model, _ = fit(train, sport, min_played=min_played)
    elo = EloModel(sport=sport, k=model.k, home_advantage=model.home_advantage,
                   draw_share=model.draw_share)
    elo.walk_forward(train, min_played=min_played)

    import football_scoring_engine as fse
    engine = fse.FootballScoringEngine()

    metrics: Dict[str, Metric] = {
        'market': Metric('rynek (bukmacher)'),
        'engine': Metric('silnik (forma scrapera)'),
        # Two ways to use store form, and they are not the same experiment.
        # `fill` only supplies form where the scraper left none, which is what
        # the pipeline does. `replace` overwrites the scraper everywhere, which
        # is what the store-only comparison implicitly tested because there was
        # no scraper form to preserve. Measuring only the latter would have us
        # judge a configuration we do not ship.
        'engine_form_fill': Metric('silnik + forma 10 (braki)'),
        'engine_form10': Metric('silnik + forma 10 (podmiana)'),
        'elo': Metric('Elo'),
    }
    for h in MIN_HISTORY_GATES:
        metrics[f'fill{h}'] = Metric(f'braki, min. historia {h}')
    for w in BLEND_WEIGHTS:
        if w not in (0.0, 1.0):
            metrics[f'blend{w}'] = Metric(f'silnik10 + Elo w={w:.2f}')

    cursor = 0
    scored = 0
    cold = 0
    for row in test:
        date = row['_date']
        # Advance the ratings through every store match that finished before
        # this fixture. Same-day matches stay out: a morning result must not
        # inform an afternoon prediction that was made before it existed.
        while cursor < len(later) and later[cursor]['date'] < date:
            nxt = later[cursor]
            elo.update(nxt['home_team'], nxt['away_team'], nxt['winner'])
            cursor += 1

        home, away = row['home_team'], row['away_team']
        if (elo.matches_played(home) < min_played
                or elo.matches_played(away) < min_played):
            cold += 1
            continue

        target = row['_target']
        odds = (_f(row.get('home_odds')), _f(row.get('draw_odds')),
                _f(row.get('away_odds')))
        elo_p = elo.predict(home, away)
        eng_p = _engine_probs(engine, dict(row), sport)

        replaced = dict(row)
        provider.attach(replaced, window=FORM_WINDOW, overwrite=True)
        eng10_p = _engine_probs(engine, replaced, sport)

        filled = dict(row)
        provider.attach(filled, window=FORM_WINDOW, overwrite=False)
        engfill_p = _engine_probs(engine, filled, sport)

        metrics['market'].add(market_probs(row), target, odds)
        metrics['engine'].add(eng_p, target, odds)
        metrics['engine_form_fill'].add(engfill_p, target, odds)
        metrics['engine_form10'].add(eng10_p, target, odds)

        for h in MIN_HISTORY_GATES:
            gated = dict(row)
            provider.attach(gated, window=FORM_WINDOW, overwrite=False,
                            min_history=h)
            metrics[f'fill{h}'].add(_engine_probs(engine, gated, sport),
                                    target, odds)
        metrics['elo'].add(elo_p, target, odds)
        for w in BLEND_WEIGHTS:
            if w not in (0.0, 1.0):
                metrics[f'blend{w}'].add(blend(eng10_p, elo_p, w), target, odds)
        scored += 1

    print(f'\n{"=" * 88}')
    print(f'  {sport.upper()}   ocenionych {scored} '
          f'(pominięto {cold} bez historii Elo), K={model.k}')
    print(f'  {"wariant":<26}{"n":>6}{"trafność":>10}{"brier":>10}'
          f'{"log-loss":>10}{"zakł.":>7}{"ROI":>10}')
    print('  ' + '-' * 84)
    usable = [m for m in metrics.values() if m.n]
    if not usable:
        print('  brak meczów z wystarczającą historią')
        return
    best = min(m.brier / m.n for m in usable)
    for key in ('market', 'engine', 'engine_form_fill', 'engine_form10'):
        print(metrics[key].row())
    for h in MIN_HISTORY_GATES:
        print(metrics[f'fill{h}'].row())
    print(metrics['elo'].row())
    for w in BLEND_WEIGHTS:
        if w not in (0.0, 1.0):
            print(metrics[f'blend{w}'].row())
    winner = [m.label for m in usable if abs(m.brier / m.n - best) < 1e-9]
    print(f'  najniższy Brier: {winner[0]} ({best:.4f})')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport')
    ap.add_argument('--split', default='')
    ap.add_argument('--min-played', type=int, default=3)
    args = ap.parse_args()

    settled = load_settled()
    store = load_store()
    if not settled or not store:
        return 1

    store_dates = sorted(r['date'] for r in store)
    cut = args.split or store_dates[int(len(store_dates) * 0.7)]
    print(f'Rozliczonych z kursami: {len(settled)} | '
          f'magazyn: {len(store)} | podział: {cut}')
    print('Elo trenowane wyłącznie na meczach sprzed danego spotkania.')
    print('ROI: stawka płaska tam, gdzie model widzi dodatnie EV.\n')

    provider = FormProvider.from_rows(
        [{'status': 'finished', 'winner': r['winner'], 'date': r['date'],
          'home_team': r['home_team'], 'away_team': r['away_team'],
          'sport': r['sport']} for r in store])

    counts: Dict[str, int] = defaultdict(int)
    for r in settled:
        counts[r['_sport']] += 1
    sports = [args.sport] if args.sport else [
        s for s, _ in sorted(counts.items(), key=lambda kv: -kv[1])]

    for sport in sports:
        evaluate_sport(settled, store, provider, sport, cut, args.min_played)

    print('\nJeśli żadna waga w>0 nie bije silnika, Elo nie wchodzi do produkcji.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
