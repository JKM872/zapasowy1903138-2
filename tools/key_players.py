"""Key players of a team from data SofaScore already gives us.

"Star missing" should mean a player who carries a large share of the team's
output, not any absence. For a team we read its last finished matches
(``/team/{id}/events/last/0``) and each match's ``/event/{id}/lineups``
player statistics, then rank players by their share of the team's output:

  football    goals + assists (minutes kept for context)
  basketball  points
  hockey      goals + assists; goalies by saves
  handball    goals
  volleyball  points

Key = top ``n`` by share with at least 2 appearances. The team's next fixture
(``/team/{id}/events/next/0``) gives the rotation ("likely reserves") signal.

Results are cached per team per day in ``results/key_players_<day>.json``.
Every network failure gives ``[]`` / ``None``; pure functions (``aggregate``,
``status_for``, ``fmt_line``, ``tier``, ``reserves_reason``) are unit-tested.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'https://api.sofascore.com/api/v1/'
N_EVENTS = int(os.getenv('AVAIL_KP_EVENTS', '5'))
KEY_SHARE = 0.20          # a key player out with >= 20% of the team's output is a "star out"
RESERVES_DAYS = 4.0       # next match within 4 days ...
STATS: Dict[str, int] = {}

# sport -> (stat keys summed, short unit for the e-mail line, Polish label for the badge)
METRIC = {
    'football': (('goals', 'goalAssist'), 'G+A', 'goli i asyst'),
    'basketball': (('points',), 'pts', 'punktów'),
    'hockey': (('goals', 'assists'), 'pts', 'punktów'),
    'handball': (('goals',), 'goals', 'goli'),
    'volleyball': (('points',), 'pts', 'punktów'),
}
GOALIE_METRIC = ('saves',)
SPORTS = set(METRIC)

CACHE_PATH = None   # override for dry runs; default results/key_players_<day>.json
_cache: Dict[str, Dict[str, Any]] = {}


def _stat(k: str) -> None:
    STATS[k] = STATS.get(k, 0) + 1


# ── pure logic ────────────────────────────────────────────────────────────────

def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _is_goalie(sport: str, p: Dict[str, Any]) -> bool:
    return sport == 'hockey' and str(p.get('position') or '').upper() == 'G'


def aggregate(sport: str, matches: List[List[Dict[str, Any]]], n: int = 3) -> List[Dict[str, Any]]:
    """Per-player output over ``matches`` (newest first; each a list of
    {'id','name','position','substitute','stats'}) -> key players.

    share = player's total / team's total of the sport metric (goalies: saves
    against all goalies' saves). Players with < 2 appearances are skipped."""
    keys, unit, _ = METRIC.get(sport, (('points',), 'pts', ''))
    agg: Dict[Any, Dict[str, Any]] = {}
    team_total = goalie_total = 0.0
    for mi, players in enumerate(matches):
        for p in players or []:
            st = p.get('stats') or {}
            played = _num(st.get('minutesPlayed')) > 0 or _num(st.get('secondsPlayed')) > 0 or any(
                _num(st.get(k)) for k in keys + GOALIE_METRIC)
            if not played:
                continue
            g = _is_goalie(sport, p)
            val = sum(_num(st.get(k)) for k in (GOALIE_METRIC if g else keys))
            pid = p.get('id') or p.get('name')
            a = agg.setdefault(pid, {'id': p.get('id'), 'name': p.get('name'), 'goalie': g,
                                     'apps': 0, 'starts': 0, 'total': 0.0, 'last': None, 'minutes': 0.0})
            a['apps'] += 1
            a['starts'] += 0 if p.get('substitute') else 1
            a['total'] += val
            a['minutes'] += _num(st.get('minutesPlayed')) or _num(st.get('secondsPlayed')) / 60.0
            if a['last'] is None and mi == 0:
                a['last'] = val
            if g:
                goalie_total += val
            else:
                team_total += val
    out = []
    for a in agg.values():
        if a['apps'] < 2:
            continue
        denom = goalie_total if a['goalie'] else team_total
        share = a['total'] / denom if denom > 0 else 0.0
        if share <= 0:
            continue
        out.append({'id': a['id'], 'name': a['name'], 'goalie': a['goalie'], 'apps': a['apps'],
                    'starts': a['starts'], 'avg': round(a['total'] / a['apps'], 1),
                    'last': a['last'] if a['last'] is not None else 0.0, 'share': round(share, 3),
                    'minutes': round(a['minutes'] / a['apps'], 1),
                    'unit': 'saves' if a['goalie'] else unit})
    skaters = sorted((p for p in out if not p['goalie']), key=lambda p: (-p['share'], -p['avg']))[:n]
    goalies = sorted((p for p in out if p['goalie']), key=lambda p: -p['share'])[:1]
    return skaters + [g for g in goalies if g['share'] >= 0.5]


def _norm(s: Any) -> str:
    from tools.availability_sources import norm
    return norm(s)


def _same_player(kp: Dict[str, Any], row: Dict[str, Any]) -> bool:
    if kp.get('id') and row.get('id'):
        return kp['id'] == row['id']
    a, b = _norm(kp.get('name')).split(), _norm(row.get('name')).split()
    if not a or not b or a[-1] != b[-1]:
        return False
    # same surname; when both carry a first name/initial it must agree
    return len(a) == 1 or len(b) == 1 or a[0][0] == b[0][0]


BENCH_SPORTS = {'football'}   # a starter on the bench means something; elsewhere subs rotate in


def status_for(players: List[Dict[str, Any]], rec: Optional[Dict[str, Any]], side: str,
               sport: str = 'football') -> List[Dict[str, Any]]:
    """Key players + 'status' (plays|out|doubtful|bench|unknown) and 'source'.

    'plays' needs a confirmed line-up or a source listing him as playing.
    With a confirmed matchday squad: not in it = 'out'; a football substitute =
    'bench'. No information = 'unknown'."""
    rec = rec or {}
    li = rec.get('lineupInfo') or {}
    squad = (li.get('squad') or {}).get(side) or [] if li.get('confirmed') else []
    rows = [dict(r, source=r.get('source') or 'sofascore') for r in (rec.get(side) or []) if isinstance(r, dict)]
    rows += [r for r in ((rec.get('extra') or {}).get(side) or []) if isinstance(r, dict)]
    li = rec.get('lineupInfo') or {}
    if rec.get('confirmed'):
        starters = (rec.get('lineup') or {}).get(side) or []
    elif li.get('confirmed'):
        starters = (li.get('lineup') or {}).get(side) or []
    else:
        starters = []
    out = []
    for kp in players or []:
        st, src, reason = 'unknown', None, ''
        hits = [r for r in rows if _same_player(kp, r)]
        bad = [r for r in hits if r.get('status') in ('out', 'doubtful')]
        if bad:
            r = next((x for x in bad if x['status'] == 'out'), bad[0])
            st, src, reason = r['status'], r.get('source'), r.get('reason') or ''
            if 'bench' in reason:
                st = 'bench'
        elif starters and any(_same_player(kp, s) for s in starters if isinstance(s, dict)):
            st, src, reason = 'plays', 'sofascore', 'confirmed line-up'
        elif squad:
            hit = next((s for s in squad if isinstance(s, dict) and _same_player(kp, s)), None)
            if hit is None:
                st, src, reason = 'out', 'sofascore', 'not in the matchday squad'
            elif hit.get('sub') and sport in BENCH_SPORTS:
                st, src, reason = 'bench', 'sofascore', 'on the bench (confirmed line-up)'
            else:
                st, src, reason = 'plays', 'sofascore', 'in the confirmed squad'
        elif starters and sport in BENCH_SPORTS:
            st, src, reason = 'bench', 'sofascore', 'not in the confirmed line-up'
        elif any(r.get('status') == 'plays' for r in hits):
            r = next(x for x in hits if x.get('status') == 'plays')
            st, src, reason = 'plays', r.get('source'), r.get('reason') or ''
        out.append({**kp, 'status': st, 'source': src, 'reason': reason})
    return out


def fmt_line(p: Dict[str, Any]) -> str:
    """'Name (avg 24.5, last 31 pts): OUT – rotowire'."""
    def f(v):
        v = float(v or 0)
        return f'{v:.0f}' if v == int(v) else f'{v:.1f}'
    st = str(p.get('status') or 'unknown').upper()
    src = f" – {p['source']}" if p.get('source') else ''
    return f"{p.get('name')} (avg {f(p.get('avg'))}, last {f(p.get('last'))} {p.get('unit') or ''}): {st}{src}".replace(' )', ')')


_CONT = re.compile(r'champions league|europa league|conference league|libertadores|sudamericana|'
                   r'euroleague|eurocup|ehf |ehf$|cev |afc champions|concacaf champions|club world cup|'
                   r'basketball champions league|fiba europe cup', re.I)
_CUP = re.compile(r'\bcup\b|pokal|copa del rey|coppa italia|coupe de france|ta[cç]a de portugal|puchar|'
                  r'beker|carabao|\bcopa\b|coupe|knvb', re.I)
# Forebet league codes of continental club competitions (EuroLeague, Champions
# League in basketball/handball/volleyball, CEV/EHF European cups).
_CONT_CODES = {'EUR', 'CHL', 'ECC', 'EC', 'ECL', 'EHF', 'CEV'}
_LATE = re.compile(r'quarter|semi|final|1/4|1/2', re.I)


def tier(tournament: Any, round_name: Any = '') -> int:
    """3 = continental club competition, 2 = domestic cup from the quarter-final on, 1 = rest."""
    t = str(tournament or '')
    if _CONT.search(t) or t.strip().upper() in _CONT_CODES:
        return 3
    if _CUP.search(t) and _LATE.search(str(round_name or '')):
        return 2
    return 1


_DAYS_PL = ['pon.', 'wt.', 'śr.', 'czw.', 'pt.', 'sob.', 'niedz.']
_DAYS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def reserves_reason(cur_tier: int, cur_ts: Optional[float], nxt: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """'likely reserves' when the next match is within RESERVES_DAYS and in a
    higher-priority competition than this one."""
    if not nxt or not cur_ts or not nxt.get('ts'):
        return None
    days = (float(nxt['ts']) - float(cur_ts)) / 86400.0
    if days <= 0 or days > RESERVES_DAYS or int(nxt.get('tier') or 1) <= int(cur_tier or 1):
        return None
    wd = datetime.fromtimestamp(float(nxt['ts']), timezone.utc).weekday()
    kind = 'cup' if int(nxt['tier']) == 2 else 'European' if int(nxt['tier']) == 3 else 'important'
    return {'kind': 'reserves', 'reason': f"{kind} match {_DAYS_EN[wd]}", 'reasonPl':
            f"{'puchar' if kind == 'cup' else 'puchary' if kind == 'European' else 'ważny mecz'} {_DAYS_PL[wd]}",
            'competition': nxt.get('tournament'), 'days': round(days, 1)}


# ── network (cached, budgeted) ────────────────────────────────────────────────

def _get(path: str) -> Optional[Dict[str, Any]]:
    try:
        import sofascore_scraper as ss
        d = ss._api_get_json(API + path, timeout=10)
    except Exception:
        d = None
    _stat('api_ok' if isinstance(d, dict) and d else 'api_fail')
    return d if isinstance(d, dict) else None


def _cache_file(day: str) -> str:
    return CACHE_PATH or os.path.join(ROOT, 'results', f'key_players_{day}.json')


def _load(day: str) -> Dict[str, Any]:
    if day not in _cache:
        try:
            _cache[day] = json.load(open(_cache_file(day), encoding='utf-8'))
        except Exception:
            _cache[day] = {}
    return _cache[day]


def save(day: str) -> None:
    if day not in _cache:
        return
    try:
        p = _cache_file(day)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(_cache[day], fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass


def _players_of(lineups: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    out = []
    for x in ((lineups or {}).get(side) or {}).get('players') or []:
        pl = x.get('player') or {}
        if not isinstance(x.get('statistics'), dict) or not x['statistics']:
            continue
        out.append({'id': pl.get('id'), 'name': pl.get('shortName') or pl.get('name'),
                    'position': x.get('position') or pl.get('position'),
                    'substitute': bool(x.get('substitute')), 'stats': x['statistics']})
    return out


def team_key_players(sport: str, team_id: Any, day: str, n: int = 3,
                     deadline: Optional[float] = None) -> List[Dict[str, Any]]:
    """Key players of ``team_id`` (cached per day). [] on any failure."""
    if sport not in SPORTS or not team_id:
        return []
    store = _load(day)
    k = f'{sport}|{team_id}'
    if isinstance((store.get(k) or {}).get('players'), list):
        return store[k]['players']
    d = _get(f'team/{team_id}/events/last/0') or {}
    evs = [e for e in d.get('events') or [] if (e.get('status') or {}).get('type') == 'finished']
    evs = sorted(evs, key=lambda e: -(e.get('startTimestamp') or 0))[:N_EVENTS]
    matches: List[List[Dict[str, Any]]] = []
    for i, e in enumerate(evs):
        if deadline is not None and time.monotonic() > deadline:
            _stat('kp_deadline')
            return []          # not cached: try again on the next run
        side = 'home' if (e.get('homeTeam') or {}).get('id') == team_id else 'away'
        ps = _players_of(_get(f"event/{e.get('id')}/lineups") or {}, side)
        if i == 0 and not ps:
            _stat('kp_no_stats')   # league without player statistics: one call, not five
            break
        matches.append(ps)
    players = aggregate(sport, matches, n) if matches else []
    store[k] = {'players': players, 'events': len(matches),
                'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    return players


def next_fixture(team_id: Any, after_ts: Optional[float], exclude_eid: Any = None,
                 day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The team's first match after ``after_ts``: {'ts','tournament','round','tier','eid'}."""
    if not team_id:
        return None
    store = _load(day) if day else {}
    k = f'next|{team_id}|{int(after_ts or 0)}'
    if k in store:
        return store[k]
    d = _get(f'team/{team_id}/events/next/0')
    if d is None:
        return None
    res = None
    for e in sorted(d.get('events') or [], key=lambda e: e.get('startTimestamp') or 0):
        ts = e.get('startTimestamp') or 0
        if e.get('id') == exclude_eid or (after_ts and ts <= after_ts):
            continue
        tn = (e.get('tournament') or {})
        name = (tn.get('uniqueTournament') or {}).get('name') or tn.get('name')
        rnd = (e.get('roundInfo') or {}).get('name') or ''
        res = {'ts': ts, 'tournament': name, 'round': rnd, 'tier': tier(name, rnd), 'eid': e.get('id')}
        break
    if day:
        store[k] = res
    return res
