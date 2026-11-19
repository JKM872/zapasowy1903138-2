"""Availability coverage of the main e-mail's qualifying rows.

    python tools/availability_coverage.py DAY [--file results/availability_DAY.json]

Per sport (and per main league): qualifying rows, rows with a record, known
vs unknown status (``availability_agent.status_of``) and the active sources
from ``config/availability_sources.json``.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def qualifying_rows(day: str, results: str = os.path.join(ROOT, 'results')) -> List[Dict[str, Any]]:
    out = []
    for p in sorted(glob.glob(os.path.join(results, f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        try:
            ms = json.load(open(p, encoding='utf-8-sig')).get('matches') or []
        except Exception:
            continue
        for m in ms:
            if isinstance(m, dict) and m.get('qualifies'):
                pick = (m.get('scoring') or {}).get('pick')
                out.append({'sport': sport, 'league': m.get('league'), 'country': m.get('country'),
                            'key': f"{sport}|{m.get('homeTeam') or ''}|{m.get('awayTeam') or ''}",
                            'side': 'home' if pick == '1' else 'away' if pick == '2' else None})
    return out


def coverage(rows: List[Dict[str, Any]], store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{sport: {'rows','records','known','unknown','status': Counter}} plus per-league under 'leagues'."""
    from tools.availability_agent import status_of
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        s = out.setdefault(r['sport'], {'rows': 0, 'records': 0, 'known': 0, 'unknown': 0,
                                        'status': Counter(), 'leagues': defaultdict(lambda: [0, 0])})
        s['rows'] += 1
        rec = store.get(r['key'])
        st = status_of(rec, r['side'] or (rec or {}).get('side')) if rec else 'unknown'
        s['records'] += 1 if rec else 0
        s['known' if st != 'unknown' else 'unknown'] += 1
        s['status'][st] += 1
        lg = s['leagues'][str(r['league'] or '?')]
        lg[0] += 1
        lg[1] += 1 if st != 'unknown' else 0
    return out


def render(day: str, cov: Dict[str, Dict[str, Any]], rows: List[Dict[str, Any]], title: str = '') -> str:
    from tools.availability_sources import sources_for
    lines = [f'# Availability coverage {day} {title}'.rstrip(), '',
             '| sport | qualifying | with record | known | unknown | known share | statuses |',
             '|---|---|---|---|---|---|---|']
    tot = Counter()
    for sp in sorted(cov):
        c = cov[sp]
        tot.update({k: c[k] for k in ('rows', 'records', 'known', 'unknown')})
        share = c['known'] / c['rows'] if c['rows'] else 0
        sts = ', '.join(f'{k} {v}' for k, v in c['status'].most_common())
        lines.append(f"| {sp} | {c['rows']} | {c['records']} | {c['known']} | {c['unknown']} | {share:.0%} | {sts} |")
    if tot['rows']:
        lines.append(f"| **all** | {tot['rows']} | {tot['records']} | {tot['known']} | {tot['unknown']} | "
                     f"{tot['known'] / tot['rows']:.0%} | |")
    lines += ['', '## Per main league (top 4 per sport by qualifying rows)', '',
              '| sport | league | qualifying | known | active sources |', '|---|---|---|---|---|']
    country = {(r['sport'], str(r['league'] or '?')): r.get('country') for r in rows}
    for sp in sorted(cov):
        for lg, (n, k) in sorted(cov[sp]['leagues'].items(), key=lambda x: -x[1][0])[:4]:
            srcs = ', '.join(sources_for(sp, lg, country.get((sp, lg))))
            lines.append(f'| {sp} | {lg} | {n} | {k} ({k / n:.0%}) | {srcs} |')
    return '\n'.join(lines) + '\n'


def main(argv: Optional[List[str]] = None) -> str:
    ap = argparse.ArgumentParser()
    ap.add_argument('day')
    ap.add_argument('--file', default=None)
    ap.add_argument('--title', default='')
    a = ap.parse_args(argv)
    path = a.file or os.path.join(ROOT, 'results', f'availability_{a.day}.json')
    try:
        store = json.load(open(path, encoding='utf-8-sig'))
    except Exception:
        store = {}
    rows = qualifying_rows(a.day)
    txt = render(a.day, coverage(rows, store), rows, a.title)
    return txt


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(main())
