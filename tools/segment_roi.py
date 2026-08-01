#!/usr/bin/env python3
"""Where does the money actually go?

`tools/segment_performance.py` answers this from mailed results, which is a few
hundred picks. This answers it from every settled match that carries a real
bookmaker price — 18k rows over five months — by re-scoring each one with the
current engine and recomputing the grade exactly as the mail does.

The question it exists to settle: the grade filter and the probability
thresholds decide what gets sent, and until now nothing measured whether Grade A
actually returns more than Grade C, or whether a sport is profitable at all. A
filter defended by intuition is a filter that can be quietly losing money.

ROI is flat-stake on the pick the engine would publish. Both arms are reported:
every pick, and only picks the engine sees positive expected value on.

    python tools/segment_roi.py
    python tools/segment_roi.py --sport tennis --min-n 50
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.evaluate_elo_vs_market import _f, load_settled  # noqa: E402

PICK_TO_INDEX = {'1': 0, 'X': 1, '2': 2}


class Bucket:
    """Hit rate and flat-stake return for one segment."""

    __slots__ = ('n', 'hits', 'pnl', 'ev_n', 'ev_hits', 'ev_pnl')

    def __init__(self) -> None:
        self.n = 0
        self.hits = 0
        self.pnl = 0.0
        self.ev_n = 0
        self.ev_hits = 0
        self.ev_pnl = 0.0

    def add(self, won: bool, odds: float, positive_ev: bool) -> None:
        self.n += 1
        gain = (odds - 1.0) if won else -1.0
        self.hits += won
        self.pnl += gain
        if positive_ev:
            self.ev_n += 1
            self.ev_hits += won
            self.ev_pnl += gain

    def row(self, label: str) -> str:
        acc = 100.0 * self.hits / self.n if self.n else 0.0
        roi = 100.0 * self.pnl / self.n if self.n else 0.0
        ev_acc = 100.0 * self.ev_hits / self.ev_n if self.ev_n else 0.0
        ev_roi = 100.0 * self.ev_pnl / self.ev_n if self.ev_n else 0.0
        return (f'  {label:<24}{self.n:>7}{acc:>8.1f}%{roi:>9.1f}%'
                f'{self.ev_n:>8}{ev_acc:>8.1f}%{ev_roi:>9.1f}%')


def score_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-score with the current engine and recompute the mail's grade."""
    import football_scoring_engine as fse
    import prediction_data_contract as pdc
    from tennis_scoring_engine import TennisScoringEngine

    engine = fse.FootballScoringEngine()
    tennis = TennisScoringEngine()
    out: List[Dict[str, Any]] = []

    for row in rows:
        sport = row['_sport']
        try:
            if sport in ('tennis', 'table_tennis'):
                st = tennis.score_match(row)
                probs = (st.cal_a, 0.0, st.cal_b)
                pick = '1' if st.cal_a >= st.cal_b else '2'
                ev, odds_used = st.ev, st.best_odds
            else:
                sm = engine.score_match(row)
                probs = (sm.cal_home, sm.cal_draw, sm.cal_away)
                pick = sm.best_pick
                ev, odds_used = sm.ev, sm.best_odds
        except Exception:
            continue

        idx = PICK_TO_INDEX.get(pick)
        if idx is None:
            continue
        price = odds_used if odds_used > 1 else _odds_for(row, idx)
        if price <= 1:
            continue

        enriched = dict(row)
        enriched['scoring_pick'] = pick
        enriched['scoring_prob'] = round(probs[idx] * 100, 1)
        enriched['scoring_ev'] = round(ev, 4)
        try:
            enriched = pdc.enrich_match_with_contract(enriched)
        except Exception:
            enriched['prediction_grade'] = 'F'

        enriched['_pick_index'] = idx
        enriched['_prob'] = probs[idx]
        enriched['_odds'] = price
        enriched['_ev'] = ev
        enriched['_won'] = idx == row['_target']
        out.append(enriched)
    return out


def _odds_for(row: Dict[str, Any], idx: int) -> float:
    return _f(row.get(('home_odds', 'draw_odds', 'away_odds')[idx]))


def _band(value: float, edges: Tuple[float, ...], suffix: str = '') -> str:
    for lo, hi in zip(edges, edges[1:]):
        if lo <= value < hi:
            return f'{lo:g}-{hi:g}{suffix}'
    return f'{edges[-1]:g}+{suffix}'


def report(title: str, buckets: Dict[str, Bucket], min_n: int,
           order: Optional[List[str]] = None) -> None:
    print(f'\n{"=" * 86}')
    print(f'  {title}')
    print(f'  {"segment":<24}{"n":>7}{"traf.":>9}{"ROI":>9}'
          f'{"n(EV+)":>8}{"traf.":>8}{"ROI":>9}')
    print('  ' + '-' * 82)
    keys = order or sorted(buckets, key=lambda k: -buckets[k].n)
    shown = 0
    for key in keys:
        b = buckets.get(key)
        if not b or b.n < min_n:
            continue
        print(b.row(key))
        shown += 1
    if not shown:
        print(f'  (żaden segment nie ma {min_n}+ meczów)')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sport')
    ap.add_argument('--min-n', type=int, default=30,
                    help='Poniżej tylu meczów segment jest szumem')
    ap.add_argument('--split', default='',
                    help='Licz tylko mecze od tej daty (YYYY-MM-DD)')
    args = ap.parse_args()

    rows = load_settled()
    if not rows:
        return 1
    if args.split:
        rows = [r for r in rows if r['_date'] >= args.split]
    if args.sport:
        rows = [r for r in rows if r['_sport'] == args.sport]
    if not rows:
        print('Brak meczów po filtrach.')
        return 1

    print(f'Meczów z wynikiem i kursami: {len(rows)}')
    dates = sorted(r['_date'] for r in rows)
    print(f'Zakres: {dates[0]} .. {dates[-1]}')
    print('Typ i grade przeliczone obecnym silnikiem, tak jak liczy je mail.')
    print('ROI: stawka płaska 1 jednostka na typ. Kolumny EV+ to podzbiór,')
    print('w którym silnik widzi dodatnią wartość oczekiwaną.')

    scored = score_rows(rows)
    print(f'Ocenionych: {len(scored)}')
    if not scored:
        return 1

    by_sport: Dict[str, Bucket] = defaultdict(Bucket)
    by_grade: Dict[str, Bucket] = defaultdict(Bucket)
    by_prob: Dict[str, Bucket] = defaultdict(Bucket)
    by_odds: Dict[str, Bucket] = defaultdict(Bucket)
    by_sport_grade: Dict[str, Bucket] = defaultdict(Bucket)

    prob_edges = (0.0, 0.5, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90, 1.01)
    odds_edges = (1.0, 1.3, 1.5, 1.8, 2.2, 3.0, 5.0, 100.0)

    for r in scored:
        won, odds, ev = r['_won'], r['_odds'], r['_ev']
        pos = ev > 0
        grade = str(r.get('prediction_grade') or 'F').strip().upper()
        by_sport[r['_sport']].add(won, odds, pos)
        by_grade[grade].add(won, odds, pos)
        by_prob[_band(r['_prob'], prob_edges)].add(won, odds, pos)
        by_odds[_band(odds, odds_edges)].add(won, odds, pos)
        by_sport_grade[f"{r['_sport']} / {grade}"].add(won, odds, pos)

    report('ROI PER SPORT', by_sport, args.min_n)
    report('ROI PER GRADE  (czy A naprawdę bije C?)', by_grade, args.min_n,
           order=['A', 'B', 'C', 'D', 'F'])
    report('ROI PER PRAWDOPODOBIEŃSTWO TYPU', by_prob, args.min_n,
           order=[_band(e, prob_edges) for e in prob_edges[:-1]])
    report('ROI PER KURS', by_odds, args.min_n,
           order=[_band(e, odds_edges) for e in odds_edges[:-1]])
    report('ROI PER SPORT I GRADE', by_sport_grade, args.min_n)

    total = Bucket()
    for r in scored:
        total.add(r['_won'], r['_odds'], r['_ev'] > 0)
    print(f'\n{"=" * 86}')
    print(total.row('RAZEM'))

    report_candidate_filters(scored, args.min_n)
    return 0


# Sports whose ROI is negative across every grade in the measurement above.
# Named here rather than inlined so the candidate rules read as intent.
LOSING_SPORTS = {'tennis', 'football', 'handball'}


def report_candidate_filters(scored: List[Dict[str, Any]], min_n: int) -> None:
    """Score whole filter sets, not just single dimensions.

    Segments tell you where money leaks; they do not tell you what the leak is
    worth once the filters interact. A rule that looks good on odds alone can
    be redundant with the grade rule, and only a combined count shows that.
    """
    grade = lambda r: str(r.get('prediction_grade') or 'F').strip().upper()

    candidates: List[Tuple[str, Any]] = [
        ('wszystko (dzisiaj)', lambda r: True),
        ('grade A/B', lambda r: grade(r) in ('A', 'B')),
        ('grade A/B/C', lambda r: grade(r) in ('A', 'B', 'C')),
        ('kurs < 5', lambda r: r['_odds'] < 5.0),
        ('kurs 1.3-5', lambda r: 1.3 <= r['_odds'] < 5.0),
        ('A/B + kurs < 5',
         lambda r: grade(r) in ('A', 'B') and r['_odds'] < 5.0),
        ('A/B + kurs 1.3-5',
         lambda r: grade(r) in ('A', 'B') and 1.3 <= r['_odds'] < 5.0),
        ('A/B + kurs 1.5-3.5',
         lambda r: grade(r) in ('A', 'B') and 1.5 <= r['_odds'] <= 3.5),
        ('A/B + EV > 0',
         lambda r: grade(r) in ('A', 'B') and r['_ev'] > 0),
        ('A/B + kurs<5 + EV>0',
         lambda r: (grade(r) in ('A', 'B') and r['_odds'] < 5.0
                    and r['_ev'] > 0)),
        ('bez tenisa/piłki/ręcznej', lambda r: r['_sport'] not in LOSING_SPORTS),
        ('A/B + bez tych sportów',
         lambda r: grade(r) in ('A', 'B') and r['_sport'] not in LOSING_SPORTS),
        ('A/B + kurs<5 + bez tych',
         lambda r: (grade(r) in ('A', 'B') and r['_odds'] < 5.0
                    and r['_sport'] not in LOSING_SPORTS)),
    ]

    print(f'\n{"=" * 86}')
    print('  KANDYDACI NA FILTR — co by się stało, gdybyśmy wysyłali tylko to')
    print(f'  {"regula":<34}{"n":>7}{"traf.":>9}{"ROI":>9}{"zysk/1000":>12}')
    print('  ' + '-' * 82)
    for label, keep in candidates:
        rows = [r for r in scored if keep(r)]
        if len(rows) < min_n:
            print(f'  {label:<34}{len(rows):>7}   za mała próba')
            continue
        hits = sum(1 for r in rows if r['_won'])
        pnl = sum((r['_odds'] - 1.0) if r['_won'] else -1.0 for r in rows)
        n = len(rows)
        roi = 100.0 * pnl / n
        # Przy stawce 100 PLN na typ: ile zostaje z 1000 postawionych jednostek.
        print(f'  {label:<34}{n:>7}{100.0 * hits / n:>8.1f}%{roi:>8.1f}%'
              f'{10.0 * roi:>11.0f}')
    print('\n  zysk/1000 = wynik na 1000 postawionych jednostek stawki')


if __name__ == '__main__':
    sys.exit(main())
