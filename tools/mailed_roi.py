#!/usr/bin/env python3
"""What did the picks we actually sent return?

`tools/segment_roi.py` measures everything settled, including fixtures that
never reached a client. This measures only what went out by mail, across every
manifest on disk, settled with the same `result_resolver` the daily report uses
so the numbers reconcile with what the client saw.

This is the dataset that decides what to stop sending. A single day is noise —
25 decided picks can swing 20 points of ROI either way — so the point here is to
pool every day we have and read the sports whose sample is large enough to mean
something.

    python tools/mailed_roi.py
    python tools/mailed_roi.py --since 2026-06-15 --min-n 20
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check_results import _predicted_winner  # noqa: E402

try:
    from result_resolver import settle_from_result
    _RESOLVER = True
except ImportError:
    _RESOLVER = False


class Bucket:
    __slots__ = ('n', 'won', 'lost', 'draw', 'pending', 'void', 'pnl', 'staked')

    def __init__(self) -> None:
        self.n = self.won = self.lost = self.draw = 0
        self.pending = self.void = 0
        self.pnl = 0.0
        self.staked = 0.0

    def add(self, outcome: str, odds: float, stake: float = 1.0) -> None:
        self.n += 1
        if outcome == 'won':
            self.won += 1
        elif outcome == 'lost':
            self.lost += 1
        elif outcome == 'draw':
            self.draw += 1
        elif outcome == 'void':
            self.void += 1
        else:
            self.pending += 1
            return
        if outcome not in ('won', 'lost') or odds <= 1:
            return
        self.pnl += (odds - 1.0) * stake if outcome == 'won' else -stake
        self.staked += stake

    @property
    def decided(self) -> int:
        return self.won + self.lost

    def row(self, label: str) -> str:
        acc = 100.0 * self.won / self.decided if self.decided else 0.0
        roi = 100.0 * self.pnl / self.staked if self.staked else 0.0
        return (f'  {label:<20}{self.n:>7}{self.decided:>9}{self.won:>6}'
                f'{self.lost:>6}{acc:>9.1f}%{roi:>9.1f}%{self.pnl:>11.1f}')


def load_all_manifests(since: str = '', until: str = '') -> List[Dict[str, Any]]:
    """Every mailed pick on disk, deduplicated by match URL."""
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for path in sorted(glob.glob('outputs/mailed_manifest_*.json')):
        base = os.path.basename(path)
        # mailed_manifest_YYYY-MM-DD[_tag].json
        date = base[len('mailed_manifest_'):][:10]
        if since and date < since:
            continue
        if until and date > until:
            continue
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        for m in data:
            if not isinstance(m, dict):
                continue
            url = m.get('match_url')
            if not url or url in seen:
                continue
            seen.add(url)
            m['_date'] = m.get('match_date') or date
            rows.append(m)
    return rows


def _odds_of_pick(m: Dict[str, Any], predicted: str) -> float:
    key = {'home': 'home_odds', 'away': 'away_odds',
           'draw': 'draw_odds'}.get(predicted)
    try:
        v = float(m.get(key))
        return 0.0 if math.isnan(v) else v
    except (TypeError, ValueError):
        return 0.0


def settle(m: Dict[str, Any], res: Dict[str, Any]) -> Tuple[str, float]:
    """Return (outcome, odds) for one mailed pick."""
    predicted = _predicted_winner(m)
    # `settle_from_result` settles by NAME and therefore needs `winner_name`,
    # which only results freshly fetched by `resolve_result` carry — the stored
    # entries keep just `winner` as home/away/draw. Without this guard every
    # pick raised KeyError, so the fallback below is the normal path here, not
    # an edge case.
    if _RESOLVER and res.get('source') and res.get('winner_name'):
        settled = settle_from_result(m, res)
        outcome = settled.get('outcome', 'pending')
        predicted = settled.get('predicted', predicted) or predicted
    elif res.get('status') == 'finished':
        winner = res.get('winner')
        if winner == 'draw':
            outcome = 'draw'
        elif winner == predicted:
            outcome = 'won'
        else:
            outcome = 'lost'
    else:
        outcome = 'pending'
    return outcome, _odds_of_pick(m, predicted)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--since', default='', help='Od tej daty (YYYY-MM-DD)')
    ap.add_argument('--until', default='', help='Do tej daty (YYYY-MM-DD)')
    ap.add_argument('--min-n', type=int, default=25,
                    help='Poniżej tylu rozstrzygniętych sport jest szumem')
    args = ap.parse_args()

    try:
        with open('outputs/result_store.json', 'r', encoding='utf-8') as fh:
            store = json.load(fh)
    except (OSError, ValueError) as e:
        print(f'Brak magazynu wyników: {e}')
        return 1

    picks = load_all_manifests(args.since, args.until)
    if not picks:
        print('Brak manifestów w podanym zakresie.')
        return 1

    dates = sorted(p['_date'] for p in picks if p.get('_date'))
    print(f'Wysłanych typów: {len(picks)}')
    if dates:
        print(f'Zakres: {dates[0]} .. {dates[-1]}')
    print(f'Rozliczane tym samym resolverem co raport dzienny '
          f'({"aktywny" if _RESOLVER else "BRAK — fallback po pozycji"}).')
    print('ROI: stawka płaska 1 jednostka na typ, tylko rozstrzygnięte.\n')

    by_sport: Dict[str, Bucket] = defaultdict(Bucket)
    by_grade: Dict[str, Bucket] = defaultdict(Bucket)
    total = Bucket()
    no_result = 0

    for m in picks:
        res = store.get(m.get('match_url'))
        if not res:
            no_result += 1
            res = {'status': 'unknown'}
        outcome, odds = settle(m, res)
        sport = (m.get('sport') or 'football').lower()
        grade = str(m.get('prediction_grade') or '?').strip().upper()
        by_sport[sport].add(outcome, odds)
        by_grade[grade].add(outcome, odds)
        total.add(outcome, odds)

    header = (f'  {"segment":<20}{"typy":>7}{"rozstrz.":>9}{"✅":>6}{"❌":>6}'
              f'{"traf.":>10}{"ROI":>10}{"wynik":>11}')

    print('=' * 92)
    print('  CO FAKTYCZNIE WYSŁALIŚMY — PER SPORT')
    print('=' * 92)
    print(header)
    print('  ' + '-' * 88)
    for sport, b in sorted(by_sport.items(), key=lambda kv: -kv[1].decided):
        flag = '' if b.decided >= args.min_n else '   (mała próba)'
        print(by_sport[sport].row(sport) + flag)

    print('\n' + '=' * 92)
    print('  PER GRADE')
    print('=' * 92)
    print(header)
    print('  ' + '-' * 88)
    for grade in ('A', 'B', 'C', 'D', 'F', '?'):
        b = by_grade.get(grade)
        if b and b.n:
            print(b.row(grade))

    print('\n' + '=' * 92)
    print(total.row('RAZEM'))
    if no_result:
        print(f'  ({no_result} typów bez wpisu w magazynie wyników)')

    # Ile zostałoby, gdyby odciąć sporty tracące na dużej próbie.
    print('\n' + '=' * 92)
    print('  GDYBY ODCIĄĆ SPORT — co zostaje z wyniku')
    print('=' * 92)
    print(header)
    print('  ' + '-' * 88)
    for drop in ('tennis', 'football', 'handball', 'table_tennis'):
        kept = Bucket()
        for sport, b in by_sport.items():
            if sport == drop:
                continue
            kept.n += b.n
            kept.won += b.won
            kept.lost += b.lost
            kept.pnl += b.pnl
            kept.staked += b.staked
        if drop in by_sport:
            print(kept.row(f'bez {drop}'))

    _candidate_filters(picks, store, args.min_n)
    return 0


LOSING_ON_LARGE_SAMPLE = {'tennis', 'football', 'handball'}


def _candidate_filters(picks: List[Dict[str, Any]], store: Dict[str, Any],
                       min_n: int) -> None:
    """Score whole rules on the picks that actually went out.

    Single dimensions do not compose: cutting a sport and cutting a grade can
    remove the same losing picks twice over, and only a combined count shows how
    much is really left.
    """
    settled: List[Tuple[Dict[str, Any], str, float]] = []
    for m in picks:
        res = store.get(m.get('match_url')) or {'status': 'unknown'}
        outcome, odds = settle(m, res)
        if outcome in ('won', 'lost') and odds > 1:
            settled.append((m, outcome, odds))

    grade = lambda m: str(m.get('prediction_grade') or '?').strip().upper()
    sport = lambda m: (m.get('sport') or 'football').lower()

    rules: List[Tuple[str, Any]] = [
        ('wszystko (dzisiaj)', lambda m: True),
        ('bez tenisa stołowego', lambda m: sport(m) != 'table_tennis'),
        ('grade A', lambda m: grade(m) == 'A'),
        ('grade A + bez t. stoł.',
         lambda m: grade(m) == 'A' and sport(m) != 'table_tennis'),
        ('bez sportów tracących',
         lambda m: sport(m) not in LOSING_ON_LARGE_SAMPLE
         and sport(m) != 'table_tennis'),
        ('grade A + bez tracących',
         lambda m: grade(m) == 'A'
         and sport(m) not in LOSING_ON_LARGE_SAMPLE
         and sport(m) != 'table_tennis'),
        ('kurs >= 1.6', lambda m: True),  # nadpisane niżej
    ]

    print('\n' + '=' * 92)
    print('  KANDYDACI NA FILTR — na typach, które realnie wyszły mailem')
    print(f'  {"regula":<34}{"rozstrz.":>9}{"traf.":>10}{"ROI":>10}{"wynik":>10}')
    print('  ' + '-' * 88)
    for label, keep in rules:
        if label.startswith('kurs'):
            rows = [(m, o, k) for m, o, k in settled if k >= 1.6]
        else:
            rows = [(m, o, k) for m, o, k in settled if keep(m)]
        if len(rows) < min_n:
            print(f'  {label:<34}{len(rows):>9}   za mała próba')
            continue
        won = sum(1 for _, o, _ in rows if o == 'won')
        pnl = sum((k - 1.0) if o == 'won' else -1.0 for _, o, k in rows)
        n = len(rows)
        print(f'  {label:<34}{n:>9}{100.0 * won / n:>9.1f}%'
              f'{100.0 * pnl / n:>9.1f}%{pnl:>10.1f}')

    print('\n  Uwaga: rozstrzygniętych jest znacznie mniej niż wysłanych,')
    print('  a tenis stołowy ma największą zaległość w etykietach — więc jego')
    print('  ROI liczy się na niereprezentatywnym podzbiorze.')


if __name__ == '__main__':
    sys.exit(main())
