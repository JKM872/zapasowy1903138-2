"""Structured, readable H2H built from already-scraped ``h2h_last5`` rows.

No network access: works on lists like
``[{'date': '12.04.26', 'home': 'Arsenal', 'away': 'Chelsea', 'score': '2 - 1'}]``.
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

NO_H2H = 'No previous meetings'
_SCORE = re.compile(r'(\d+)\s*[:\-]\s*(\d+)')


def _norm(name: Any) -> str:
    s = re.sub(r'[^a-z0-9 ]', ' ', str(name or '').lower())
    return ' '.join(w for w in s.split() if w not in ('fc', 'cf', 'sc', 'ac', 'afc', 'fk'))


def same_team(a: Any, b: Any) -> bool:
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    return x == y or x in y or y in x


def norm_date(value: Any) -> str:
    """Return YYYY-MM-DD when parseable, else the trimmed original text."""
    s = str(value or '').strip()
    if not s:
        return ''
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y', '%d/%m/%y', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(s[:19] if 'T' in s else s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return s


def meetings(rows: Any, home: str = '', away: str = '') -> List[Dict[str, Any]]:
    """Normalise H2H rows; ``winner`` is a team name or 'draw'. Newest first."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        mh, ma = str(r.get('home') or '').strip(), str(r.get('away') or '').strip()
        sm = _SCORE.search(str(r.get('score') or ''))
        if not (mh and ma and sm):
            continue
        gh, ga = int(sm.group(1)), int(sm.group(2))
        winner = mh if gh > ga else (ma if ga > gh else 'draw')
        out.append({'date': norm_date(r.get('date')), 'home': mh, 'away': ma,
                    'score': f'{gh}-{ga}', 'winner': winner})
    out.sort(key=lambda m: m['date'] if re.match(r'\d{4}-', m['date']) else '', reverse=True)
    return out


def summarize(rows: Any, home: str, away: str) -> Dict[str, Any]:
    """{meetings, last, edge} with W-D-L counted from the home team's side."""
    ms = meetings(rows, home, away)
    if not ms:
        return {'meetings': [], 'last': None, 'edge': None}
    w = d = l = 0
    for m in ms:
        if m['winner'] == 'draw':
            d += 1
        elif same_team(m['winner'], home):
            w += 1
        elif same_team(m['winner'], away):
            l += 1
    last = ms[0]
    edge_team = home if w > l else (away if l > w else 'even')
    return {
        'meetings': ms,
        'last': {'date': last['date'], 'score': last['score'], 'winner': last['winner'],
                 'home': last['home'], 'away': last['away']},
        'edge': {'team': edge_team, 'wins': w, 'draws': d, 'losses': l,
                 'record': f'{w}-{d}-{l}', 'even': w == l},
    }


def format_line(summary: Optional[Dict[str, Any]], home: str = '', away: str = '',
                perspective: Optional[str] = None) -> str:
    """'H2H: Arsenal 3-1-1 (last: 2026-04-12 Arsenal 2-1 Chelsea)'.

    ``perspective`` = team name whose W-D-L is shown (default: the edge team).
    """
    if not summary or not summary.get('edge'):
        return NO_H2H
    e, last = summary['edge'], summary['last']
    w, d, l = e['wins'], e['draws'], e['losses']
    team = perspective or (e['team'] if not e['even'] else home)
    if team and same_team(team, away) and not same_team(team, home):
        w, l = l, w
    lead = f"{team} {w}-{d}-{l}" + (' (even)' if e['even'] else '')
    ltxt = ' '.join(x for x in (last.get('date'), last.get('home'), last.get('score'),
                                last.get('away')) if x) if last else ''
    return f"H2H: {lead} (last: {ltxt})" if ltxt else f"H2H: {lead}"


def last_line(summary: Optional[Dict[str, Any]]) -> str:
    if not summary or not summary.get('last'):
        return NO_H2H
    last = summary['last']
    who = 'draw' if last['winner'] == 'draw' else f"{last['winner']} won"
    return f"{last['date']} {last['home']} {last['score']} {last['away']} ({who})".strip()
