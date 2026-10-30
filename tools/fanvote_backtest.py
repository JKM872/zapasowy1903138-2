"""Backtests for Fan Favourites (SofaScore Fan Vote board) and the Weekend Slip.

Usage:
    python tools/fanvote_backtest.py [--json out.json] [--md out.md]

Data: results/matches_<day>_<sport>_forebet.json rows (sofascore, odds, scoring,
forebet), settled through tools.top_rules.Settler (outputs/result_store.json +
results/forebet_settled.json). Supabase is only cross-checked (count) when
SUPABASE_URL + key are set.

Flat stake 1u at the listed odds on the fan side (draw = loss in football).

Standard odds limits (``odds_limit``): the qualifying pipeline's per-sport
minimum (qualification_gate.SPORT_MIN_ODDS), raised to the TOP floors -
football >= 2.0 (top_picks.MIN_ODDS) and tennis/basketball >= 1.80 (the
top_rules safe gate; learned per-segment floors in outputs/top_rules.json are
not enforced, so the safe gate is what TOP applies). Applied to the odds of the
side we back.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import top_rules  # noqa: E402
from tools.top_rules import Settler, fold, structural  # noqa: E402
import fan_limits  # noqa: E402
from fan_limits import FAN_BANDS, band as fan_band, fan_threshold as fan_min  # noqa: E402,F401

VOTE_STEPS = [0, 50, 100, 200, 500, 1000]
SLIP_SIZES = (3, 4, 5)
# Rows before the 2026-09-26 side-orientation fix carry odds of the wrong team
# (e.g. Torino-Roma 2026-09-14: Roma 83% fans at "5.5"); fan-board ROI there is
# +47% with 62% hits at avg odds 4.0 for odds >= 3, which is not real. Rows
# 2026-09-27..2026-10-16 have no Fan Vote %. ROI uses rows from this day only.
CLEAN_FROM = '2026-09-27'


def odds_limit(sport: str) -> float:
    return fan_limits.odds_limit(sport)['min']


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _model_p(m: Dict[str, Any], side: str) -> Optional[float]:
    sc, fb = m.get('scoring') or {}, m.get('forebet') or {}
    if sc.get('pick') == ('1' if side == 'home' else '2') and _f(sc.get('prob')):
        return _f(sc['prob']) / 100
    v = _f(fb.get('homeProb' if side == 'home' else 'awayProb'))
    return v / 100 if v else None


def load_rows(root: str = ROOT) -> List[Dict[str, Any]]:
    """One row per settled match that has a SofaScore fan vote and fan-side odds."""
    st = Settler(root)
    seen, out = set(), []
    for f in sorted(glob.glob(os.path.join(root, 'results', 'matches_*_forebet.json'))):
        mm = re.match(r'matches_(\d{4}-\d{2}-\d{2})_(.+)_forebet\.json$', os.path.basename(f))
        if not mm:
            continue
        day, sport = mm.group(1), mm.group(2)
        try:
            data = json.load(open(f, encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        for m in (data.get('matches') if isinstance(data, dict) else data) or []:
            ss, od = m.get('sofascore') or {}, m.get('odds') or {}
            if not ss.get('found') or m.get('oddsOrientationUnknown'):
                continue
            hp, ap = _f(ss.get('homeProb')), _f(ss.get('awayProb'))
            sc = m.get('scoring') or {}
            comp = _f((sc.get('components') or {}).get('sofascore'))
            if hp is not None and ap is not None:
                side, fan = ('home', hp) if hp >= ap else ('away', ap)
            elif comp is not None and comp > 0.5 and sc.get('pick') in ('1', '2'):
                # Older rows (before 2026-10-17) keep only the fan share of the
                # scoring pick in scoring.components.sofascore (checked equal to
                # the raw homeProb/awayProb on 1413 newer rows); > 50% means it
                # is the fan favourite side.
                side, fan = ('home' if sc['pick'] == '1' else 'away'), round(comp * 100, 1)
            else:
                continue
            odds = _f(od.get(side))
            if not odds or odds <= 1.0:
                continue
            key = (day, sport, fold(m.get('homeTeam')), fold(m.get('awayTeam')))
            if key in seen:
                continue
            seen.add(key)
            w = st.winner(day, m)
            if w not in ('home', 'away', 'draw'):
                continue
            p = _model_p(m, side)
            out.append({
                'day': day, 'sport': sport, 'league': f"{m.get('country') or ''}|{m.get('league') or ''}",
                'home': m.get('homeTeam'), 'away': m.get('awayTeam'), 'side': side,
                'fan': fan, 'votes': int(_f(ss.get('votes')) or 0), 'odds': odds,
                'won': w == side, 'p': p, 'edge': (p * odds - 1) if p else None,
                'top': structural(m) and (m.get('scoring') or {}).get('pick') == ('1' if side == 'home' else '2'),
                'grade': m.get('predictionGrade'),
            })
    return out


def stats(rs: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rs)
    if not n:
        return {'n': 0, 'hit': None, 'roi': None, 'avgOdds': None}
    won = sum(r['won'] for r in rs)
    profit = sum((r['odds'] - 1) if r['won'] else -1 for r in rs)
    return {'n': n, 'hit': round(100 * won / n, 1), 'roi': round(100 * profit / n, 1),
            'avgOdds': round(sum(r['odds'] for r in rs) / n, 2)}


def fan_backtest(rows: List[Dict[str, Any]], min_votes: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for limited in (False, True):
        sel = [r for r in rows if r['fan'] >= 60 and r['votes'] >= min_votes
               and (not limited or r['odds'] >= odds_limit(r['sport']))]
        by_sport, by_band, by_sb = defaultdict(list), defaultdict(list), defaultdict(list)
        board = []
        for r in sel:
            b = fan_band(r['fan'])
            by_band[b].append(r)
            by_sb[f"{r['sport']}|{b}"].append(r)
            if r['fan'] >= fan_min(r['sport']):
                by_sport[r['sport']].append(r)
                board.append(r)
        out['limits' if limited else 'noLimits'] = {
            'board': stats(board),
            'bySport': {k: stats(v) for k, v in sorted(by_sport.items())},
            'byBand': {k: stats(v) for k, v in sorted(by_band.items())},
            'bySportBand': {k: stats(v) for k, v in sorted(by_sb.items())},
        }
    return out


def vote_scan(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    res = {}
    for v in VOTE_STEPS:
        b = [r for r in rows if r['fan'] >= fan_min(r['sport']) and r['votes'] >= v]
        bl = [r for r in b if r['odds'] >= odds_limit(r['sport'])]
        res[str(v)] = {'noLimits': stats(b), 'limits': stats(bl)}
    return res


# ── Weekend Slip ───────────────────────────────────────────────────────────

def _friday(d: date) -> Optional[date]:
    wd = d.weekday()  # Fri=4 Sat=5 Sun=6
    return d - timedelta(days=wd - 4) if wd >= 4 else None


def build_slips(legs: List[Dict[str, Any]], sizes=SLIP_SIZES) -> List[List[Dict[str, Any]]]:
    """Greedy, disjoint slips: best edge first, one leg per league, no team twice."""
    cand = sorted(legs, key=lambda r: (-(r['edge'] if r['edge'] is not None else -9), -r['fan']))
    pos = [r for r in cand if r['edge'] is not None and r['edge'] > 0]
    pool = pos + [r for r in cand if r not in pos]
    used, slips = set(), []
    for size in sizes:
        slip, leagues, teams = [], set(), set()
        for r in pool:
            k = id(r)
            t = {fold(r['home']), fold(r['away'])}
            if k in used or r['league'] in leagues or teams & t:
                continue
            slip.append(r)
            leagues.add(r['league'])
            teams |= t
            if len(slip) == size:
                break
        if len(slip) < 3:
            break
        used |= {id(r) for r in slip}
        slips.append(slip)
    return slips


def slip_backtest(rows: List[Dict[str, Any]], min_votes: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    weekends = defaultdict(list)
    for r in rows:
        fr = _friday(date.fromisoformat(r['day']))
        if fr:
            weekends[fr.isoformat()].append(r)
    for limited in (False, True):
        slips_all, per_wk = [], []
        for fr, rs in sorted(weekends.items()):
            legs = []
            for r in rs:
                fan_ok = r['fan'] >= fan_min(r['sport']) and r['votes'] >= min_votes
                top_ok = r['top'] and (r['sport'] != 'football' or r['odds'] >= 2.0)
                if not (fan_ok or top_ok):
                    continue
                if limited and r['odds'] < odds_limit(r['sport']):
                    continue
                legs.append(r)
            slips = build_slips(legs)
            for s in slips:
                odds = 1.0
                p = 1.0
                for r in s:
                    odds *= r['odds']
                    p *= r['p'] or (1 / r['odds'])
                won = all(r['won'] for r in s)
                slips_all.append({'friday': fr, 'legs': len(s), 'odds': round(odds, 2),
                                  'pModel': round(p, 4), 'ev': round(p * odds - 1, 3), 'won': won,
                                  'legsWon': sum(r['won'] for r in s)})
            per_wk.append({'friday': fr, 'candidates': len(legs), 'slips': len(slips)})
        n = len(slips_all)
        won = sum(s['won'] for s in slips_all)
        profit = sum((s['odds'] - 1) if s['won'] else -1 for s in slips_all)
        legs_n = sum(s['legs'] for s in slips_all)
        by_size = {}
        for k in SLIP_SIZES:
            ss = [s for s in slips_all if s['legs'] == k]
            if ss:
                by_size[str(k)] = {'n': len(ss), 'hit': round(100 * sum(s['won'] for s in ss) / len(ss), 1),
                                   'roi': round(100 * sum((s['odds'] - 1) if s['won'] else -1 for s in ss) / len(ss), 1),
                                   'avgOdds': round(sum(s['odds'] for s in ss) / len(ss), 2)}
        out['limits' if limited else 'noLimits'] = {
            'weekends': len(per_wk), 'slips': n, 'won': won,
            'hit': round(100 * won / n, 1) if n else None,
            'roi': round(100 * profit / n, 1) if n else None,
            'avgOdds': round(sum(s['odds'] for s in slips_all) / n, 2) if n else None,
            'avgModelEv': round(sum(s['ev'] for s in slips_all) / n, 3) if n else None,
            'legHit': round(100 * sum(s['legsWon'] for s in slips_all) / legs_n, 1) if legs_n else None,
            'bySize': by_size, 'perWeekend': per_wk, 'slipList': slips_all,
        }
    return out


def supabase_check() -> Dict[str, Any]:
    return top_rules._supabase_count('2026-01-01', date.today().isoformat())


def _tbl(title: str, d: Dict[str, Dict[str, Any]]) -> List[str]:
    lines = [f'**{title}**', '', '| segment | n | hit % | ROI % | avg odds |', '|---|---:|---:|---:|---:|']
    for k, s in d.items():
        lines.append(f"| {k} | {s['n']} | {s['hit']} | {s['roi']:+} | {s['avgOdds']} |" if s['n']
                     else f'| {k} | 0 | – | – | – |')
    return lines + ['']


def report_md(res: Dict[str, Any]) -> str:
    L = [f"# Fan Favourites / Weekend Slip backtest", '',
         f"Data: {res['range']}, {res['rows']} settled matches with Fan Vote + fan-side odds. "
         f"Supabase: {res['supabase']}. Flat 1u stake at the listed odds, no haircut.", '',
         f"Excluded rows before {CLEAN_FROM} (odds side-orientation bug): board n={res['excludedOld']['n']}, "
         f"hit {res['excludedOld']['hit']}% (ROI {res['excludedOld']['roiUnreliable']}% is not trustworthy).", '',
         '## Odds limits (side we back)', '',
         '| sport | limit |', '|---|---:|']
    L += [f'| {s} | {v} |' for s, v in res['oddsLimits'].items()] + ['']
    L += ['## Minimum votes scan (board thresholds: football >= 60%, others >= 70%)', '',
          '| min votes | n | hit % | ROI % | n (limits) | hit % | ROI % |', '|---:|---:|---:|---:|---:|---:|---:|']
    for v, s in res['voteScan'].items():
        a, b = s['noLimits'], s['limits']
        L.append(f"| {v} | {a['n']} | {a['hit']} | {a['roi']} | {b['n']} | {b['hit']} | {b['roi']} |")
    L += ['', f"## Fan Favourites (min votes {res['minVotes']})", '']
    for k, lab in (('noLimits', 'without odds limits'), ('limits', 'with odds limits')):
        f = res['fan'][k]
        L += [f"### {lab}: board n={f['board']['n']} hit={f['board']['hit']}% ROI={f['board']['roi']}%", '']
        L += _tbl('Per sport (board thresholds)', f['bySport'])
        L += _tbl('Per Fan Vote band (all sports, >= 60%)', f['byBand'])
        L += _tbl('Per sport x band', f['bySportBand'])
    L += ['## Weekend Slip (Fri-Sun, disjoint slips of 3/4/5 legs, one leg per league)', '',
          '| variant | weekends | slips | won | hit % | ROI % | avg odds | model EV | leg hit % |',
          '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k in ('noLimits', 'limits'):
        s = res['slip'][k]
        L.append(f"| {k} | {s['weekends']} | {s['slips']} | {s['won']} | {s['hit']} | {s['roi']} | "
                 f"{s['avgOdds']} | {s['avgModelEv']} | {s['legHit']} |")
    L += ['']
    for k in ('noLimits', 'limits'):
        L += _tbl(f'Slip size ({k})', res['slip'][k]['bySize'])
    return '\n'.join(L) + '\n'


def run(min_votes: int = 100) -> Dict[str, Any]:
    allrows = load_rows()
    rows = [r for r in allrows if r['day'] >= CLEAN_FROM]
    old = [r for r in allrows if r['day'] < CLEAN_FROM and r['fan'] >= fan_min(r['sport'])
           and r['votes'] >= min_votes]
    days = sorted({r['day'] for r in rows})
    return {
        'range': f'{days[0]}..{days[-1]}' if days else 'none', 'rows': len(rows),
        'excludedOld': {'n': len(old), 'hit': stats(old)['hit'], 'roiUnreliable': stats(old)['roi']},
        'minVotes': min_votes, 'supabase': supabase_check(),
        'oddsLimits': {s: odds_limit(s) for s in sorted({r['sport'] for r in rows})},
        'voteScan': vote_scan(rows), 'fan': fan_backtest(rows, min_votes),
        'slip': slip_backtest(rows, min_votes),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-votes', type=int, default=100)
    ap.add_argument('--json')
    ap.add_argument('--md')
    a = ap.parse_args(argv)
    res = run(a.min_votes)
    md = report_md(res)
    if a.json:
        json.dump(res, open(a.json, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    if a.md:
        open(a.md, 'w', encoding='utf-8').write(md)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
