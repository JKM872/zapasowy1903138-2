"""Backtest: do picks whose side had a star out / likely reserves do worse?

    python tools/availability_backtest.py [--out .agents/tasks/availability-pipeline/backtest.md]

Joins every ``results/availability_<day>.json`` record (status recomputed with
``availability_agent.status_of``; old records without key players fall back to
the SofaScore market-value stars) with the qualifying Forebet row of the same
day (picked side and its odds) and the settled result in
``results/forebet_settled.json`` / ``results/event_settled.json``. Qualifying
rows without any record count as ``unknown``.

Per group (star_out, reserves, lineups_ok, unknown, rest) and sport: n, hit
rate, ROI at the pick odds (1 unit flat), average break-even (1/odds).
Groups with n < 30 are marked "too small".
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIN_N = 30
GROUPS = ('star_out', 'reserves', 'lineups_ok', 'unknown', 'rest')


def group_of(status: str) -> str:
    return status if status in ('star_out', 'reserves', 'lineups_ok', 'unknown') else 'rest'


def aggregate(bets: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """bets: {'group','sport','won': bool,'odds': float} -> {group: {sport|'all': stats}}."""
    acc: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0, 0.0]))
    for b in bets:
        o = float(b['odds'])
        for sp in (b['sport'], 'all'):
            a = acc[b['group']][sp]
            a[0] += 1
            a[1] += 1 if b['won'] else 0
            a[2] += (o - 1.0) if b['won'] else -1.0
            a[3] += 1.0 / o
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for g, by in acc.items():
        out[g] = {sp: {'n': int(a[0]), 'hits': int(a[1]), 'hit_rate': a[1] / a[0], 'roi': a[2] / a[0],
                       'break_even': a[3] / a[0]} for sp, a in by.items()}
    return out


def _load(p: str) -> Any:
    try:
        return json.load(open(p, encoding='utf-8-sig'))
    except Exception:
        return None


def fixture_index(results: str) -> Dict[tuple, List[tuple]]:
    """(sport, team) -> [(day, league)] from every Forebet file (all rows): the
    free fixture list used to replay the "likely reserves" rule on history."""
    idx: Dict[tuple, List[tuple]] = defaultdict(list)
    for p in glob.glob(os.path.join(results, 'matches_*_*_forebet.json')):
        base = os.path.basename(p)[len('matches_'):-len('_forebet.json')]
        day, _, sport = base.partition('_')
        for m in (_load(p) or {}).get('matches') or []:
            if isinstance(m, dict):
                for t in (m.get('homeTeam'), m.get('awayTeam')):
                    if t:
                        idx[(sport, t)].append((day, m.get('league') or ''))
    return idx


def historic_reserves(idx: Dict[tuple, List[tuple]], sport: str, team: str, day: str, league: str) -> bool:
    """Next listed match of ``team`` within RESERVES_DAYS after ``day`` is in a
    higher-tier competition (day granularity)."""
    from datetime import date
    from tools import key_players as kp
    d0 = date.fromisoformat(day)
    nxt = sorted((d, lg) for d, lg in idx.get((sport, team), []) if d > day)
    if not nxt:
        return False
    d, lg = nxt[0]
    gap = (date.fromisoformat(d) - d0).days
    return 0 < gap <= kp.RESERVES_DAYS and kp.tier(lg) > kp.tier(league)


def collect(results: str = os.path.join(ROOT, 'results')) -> List[Dict[str, Any]]:
    from tools.availability_agent import status_of
    idx = fixture_index(results)
    settled = dict(_load(os.path.join(results, 'event_settled.json')) or {})
    settled.update(_load(os.path.join(results, 'forebet_settled.json')) or {})
    bets = []
    days = sorted({os.path.basename(p)[len('availability_'):-len('.json')]
                   for p in glob.glob(os.path.join(results, 'availability_*.json'))})
    for day in days:
        store = _load(os.path.join(results, f'availability_{day}.json')) or {}
        for p in glob.glob(os.path.join(results, f'matches_{day}_*_forebet.json')):
            sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
            for m in (_load(p) or {}).get('matches') or []:
                if not isinstance(m, dict) or not m.get('qualifies'):
                    continue
                pick = (m.get('scoring') or {}).get('pick')
                side = 'home' if pick == '1' else 'away' if pick == '2' else None
                odds = (m.get('odds') or {}).get(side) if side else None
                if not side or not isinstance(odds, (int, float)) or odds <= 1:
                    continue
                h, a = m.get('homeTeam') or '', m.get('awayTeam') or ''
                res = settled.get(f'{day}|{sport}|{h}|{a}') or {}
                if res.get('status') != 'settled' or res.get('winner') not in ('home', 'away', 'draw'):
                    continue
                rec = store.get(f'{sport}|{h}|{a}')
                st = status_of(rec, side) if rec else 'unknown'
                if st not in ('star_out', 'reserves') and not (rec or {}).get('nextFixture') and \
                        historic_reserves(idx, sport, h if side == 'home' else a, day, m.get('league') or ''):
                    st = 'reserves'
                bets.append({'day': day, 'sport': sport, 'group': group_of(st), 'status': st,
                             'won': res['winner'] == side, 'odds': float(odds)})
    return bets


def collect_reserves_full(results: str = os.path.join(ROOT, 'results')) -> List[Dict[str, Any]]:
    """Every settled qualifying pick in the Forebet history: 'reserves' vs 'rest'
    (the rotation rule needs only the fixture list, not availability files)."""
    idx = fixture_index(results)
    settled = dict(_load(os.path.join(results, 'event_settled.json')) or {})
    settled.update(_load(os.path.join(results, 'forebet_settled.json')) or {})
    bets = []
    for p in sorted(glob.glob(os.path.join(results, 'matches_*_*_forebet.json'))):
        base = os.path.basename(p)[len('matches_'):-len('_forebet.json')]
        day, _, sport = base.partition('_')
        for m in (_load(p) or {}).get('matches') or []:
            if not isinstance(m, dict) or not m.get('qualifies'):
                continue
            pick = (m.get('scoring') or {}).get('pick')
            side = 'home' if pick == '1' else 'away' if pick == '2' else None
            odds = (m.get('odds') or {}).get(side) if side else None
            if not side or not isinstance(odds, (int, float)) or odds <= 1:
                continue
            h, a = m.get('homeTeam') or '', m.get('awayTeam') or ''
            res = settled.get(f'{day}|{sport}|{h}|{a}') or {}
            if res.get('status') != 'settled' or res.get('winner') not in ('home', 'away', 'draw'):
                continue
            rs = historic_reserves(idx, sport, h if side == 'home' else a, day, m.get('league') or '')
            bets.append({'day': day, 'sport': sport, 'group': 'reserves' if rs else 'rest',
                         'won': res['winner'] == side, 'odds': float(odds)})
    return bets


def render(agg: Dict[str, Dict[str, Dict[str, float]]], n_days: int) -> str:
    lines = [f'# Availability backtest ({n_days} days with availability files)', '',
             'Flat 1 unit per qualifying pick at the pick odds. Break-even = average 1/odds.', '',
             '| group | sport | n | hit rate | ROI | break-even | note |', '|---|---|---|---|---|---|---|']
    for g in GROUPS:
        by = agg.get(g) or {}
        for sp in ['all'] + sorted(s for s in by if s != 'all'):
            if sp not in by:
                continue
            s = by[sp]
            note = 'too small' if s['n'] < MIN_N else ''
            lines.append(f"| {g} | {sp} | {s['n']} | {s['hit_rate']:.1%} | {s['roi']:+.1%} | "
                         f"{s['break_even']:.1%} | {note} |")
    return '\n'.join(lines) + '\n'


def main(argv: Optional[List[str]] = None) -> str:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, '.agents', 'tasks', 'availability-pipeline', 'backtest.md'))
    a = ap.parse_args(argv)
    bets = collect()
    txt = render(aggregate(bets), len({b['day'] for b in bets}))
    full = collect_reserves_full()
    agg = aggregate(full)
    days = sorted({b['day'] for b in full})
    txt += (f"\n# Likely reserves over the full Forebet history ({len(days)} days"
            f"{', ' + days[0] + '..' + days[-1] if days else ''})\n\n"
            '| group | sport | n | hit rate | ROI | break-even | note |\n|---|---|---|---|---|---|---|\n')
    for g in ('reserves', 'rest'):
        by = agg.get(g) or {}
        for sp in ['all'] + sorted(s for s in by if s != 'all'):
            s = by[sp]
            txt += (f"| {g} | {sp} | {s['n']} | {s['hit_rate']:.1%} | {s['roi']:+.1%} | {s['break_even']:.1%} | "
                    f"{'too small' if s['n'] < MIN_N else ''} |\n")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, 'w', encoding='utf-8').write(txt)
    return txt


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(main())
