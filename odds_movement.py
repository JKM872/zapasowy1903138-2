"""Odds movement per pick from data we already scrape (no extra page loads).

Sources, in order:
  1. OddsSafari dropping-odds archive ``outputs/oddssafari_dropping_<day>_<sport>.json``
     (opening vs current price per 1/X/2 outcome),
  2. TOP live checks ``results/top_live_<day>.json`` (first vs latest best price).

``oddsMove`` = {pick: {opening, current, changePct, direction, since, source},
                opponent: {...} | None, line: str}
Odds dropping on our pick means the market agrees; rising means it is against us.
"""
import glob
import json
import os
from typing import Any, Dict, List, Optional

from h2h_summary import same_team

ROOT = os.path.dirname(os.path.abspath(__file__))
FLAT_PCT = 2.0


def compute(opening: Any, current: Any, since: Optional[str] = None,
            source: Optional[str] = None, flat_pct: float = FLAT_PCT) -> Optional[Dict[str, Any]]:
    try:
        o, c = float(opening), float(current)
    except (TypeError, ValueError):
        return None
    if o <= 1.0 or c <= 1.0:
        return None
    pct = round((c - o) / o * 100.0, 1)
    direction = 'flat' if abs(pct) < flat_pct else ('down' if pct < 0 else 'up')
    return {'opening': round(o, 3), 'current': round(c, 3), 'changePct': pct,
            'direction': direction, 'since': since, 'source': source}


def arrow(mv: Optional[Dict[str, Any]]) -> str:
    if not mv:
        return ''
    if mv['direction'] == 'flat':
        return f"= {mv['changePct']:+.0f}%"
    return f"{'▼' if mv['direction'] == 'down' else '▲'}{abs(mv['changePct']):.0f}%"


def stance(mv: Optional[Dict[str, Any]]) -> Optional[str]:
    """with / against / flat from the movement on OUR pick."""
    if not mv:
        return None
    return {'down': 'with', 'up': 'against'}.get(mv['direction'], 'flat')


def line(move: Optional[Dict[str, Any]]) -> str:
    if not move:
        return ''
    mv = move.get('pick')
    op = move.get('opponent')
    if not mv:
        if not op:
            return ''
        txt = f"Opponent odds {op['opening']:.2f} → {op['current']:.2f} ({arrow(op)})"
        return txt + {'down': ': market against our pick', 'up': ': market with our pick',
                      'flat': ': stable'}[op['direction']]
    txt = f"Odds on our pick {mv['opening']:.2f} → {mv['current']:.2f} ({arrow(mv)})"
    txt += {'with': ': dropping, market agrees', 'against': ': rising, market against',
            'flat': ': stable'}[stance(mv)]
    if op and op['direction'] != 'flat':
        txt += f"; opponent {arrow(op)}"
    return txt


def _read(path: str) -> Any:
    try:
        with open(path, encoding='utf-8-sig') as fh:
            return json.load(fh)
    except Exception:
        return None


def build_index(day: str, root: str = ROOT) -> Dict[str, Any]:
    """{'drop': {sport: [ {home, away, outcomes{1|X|2: move}} ]}, 'live': {...}}"""
    drop: Dict[str, Dict[tuple, Dict[str, Any]]] = {}
    from datetime import date as _date, timedelta as _td
    try:
        d0 = _date.fromisoformat(day)
        prev_day, ddmm = (d0 - _td(days=1)).isoformat(), d0.strftime('%d/%m')
    except ValueError:
        prev_day, ddmm = None, None
    paths = sorted(glob.glob(os.path.join(root, 'outputs', f'oddssafari_dropping_{prev_day}_*.json'))) \
        if prev_day else []
    paths += sorted(glob.glob(os.path.join(root, 'outputs', f'oddssafari_dropping_{day}_*.json')))
    for p in paths:
        d = _read(p)
        if not isinstance(d, dict):
            continue
        since = (d.get('meta') or {}).get('generated_at')
        for e in d.get('events') or []:
            if not isinstance(e, dict) or e.get('outcome') not in ('1', 'X', '2'):
                continue
            if ddmm and e.get('event_date') and e['event_date'] != ddmm:
                continue  # yesterday's file also lists today's games; keep only this day
            sport = e.get('sport') or ''
            k = (e.get('home_team') or '', e.get('away_team') or '')
            rec = drop.setdefault(sport, {}).setdefault(k, {'home': k[0], 'away': k[1], 'outcomes': {}})
            prev = rec['outcomes'].get(e['outcome'])
            opening = prev['opening'] if prev else e.get('open_odds')
            mv = compute(opening, e.get('current_odds'), (prev or {}).get('since') or since, 'oddssafari')
            if mv:
                rec['outcomes'][e['outcome']] = mv
    live = _read(os.path.join(root, 'results', f'top_live_{day}.json')) or {}
    return {'drop': {s: list(v.values()) for s, v in drop.items()},
            'live': live if isinstance(live, dict) else {}}


def _find_drop(index: Dict[str, Any], sport: str, home: str, away: str):
    for r in (index.get('drop') or {}).get(sport) or []:
        if same_team(r['home'], home) and same_team(r['away'], away):
            return r['outcomes'], False
        if same_team(r['home'], away) and same_team(r['away'], home):
            return r['outcomes'], True
    return None, False


def for_pick(index: Dict[str, Any], sport: str, home: str, away: str,
             side: Optional[str]) -> Optional[Dict[str, Any]]:
    """Movement for our side ('home'/'away') and the opponent; None if no data."""
    if side not in ('home', 'away') or not home or not away:
        return None
    pick = opp = None
    outs, swapped = _find_drop(index, sport, home, away)
    if outs:
        h, a = ('2', '1') if swapped else ('1', '2')
        pick, opp = (outs.get(h), outs.get(a)) if side == 'home' else (outs.get(a), outs.get(h))
    if pick is None:
        rec = (index.get('live') or {}).get(f'{sport}|{home} vs {away}') or {}
        checks = [c for c in rec.get('checks') or [] if c.get('best')]
        if len(checks) >= 2:
            pick = compute(checks[0]['best'], checks[-1]['best'], checks[0].get('at'), 'top_live')
    if pick is None and opp is None:
        return None
    st = stance(pick)
    if st is None and opp:
        st = {'down': 'against', 'up': 'with'}.get(opp['direction'], 'flat')
    out = {'pick': pick, 'opponent': opp, 'stance': st}
    out['line'] = line(out)
    return out


_CTX: Dict[str, Any] = {}


def context(day: str, root: str = ROOT, ttl: float = 300.0) -> Dict[str, Any]:
    """Movement index + availability store for a day, cached for ttl seconds."""
    import time
    hit = _CTX.get(day)
    if hit and time.time() - hit['t'] < ttl and hit['root'] == root:
        return hit
    try:
        avail = _read(os.path.join(root, 'results', f'availability_{day}.json')) or {}
    except Exception:
        avail = {}
    hit = {'t': time.time(), 'root': root, 'index': build_index(day, root), 'avail': avail}
    _CTX[day] = hit
    return hit


def enrich(item: Dict[str, Any], day: str, sport: str, home: str, away: str,
           side: Optional[str], live: Optional[Dict[str, Any]] = None, root: str = ROOT) -> Dict[str, Any]:
    """Add oddsMove and teamNews to a pick/match dict in place."""
    if not day:
        return item
    ctx = context(day, root)
    index = ctx['index']
    if live is not None:
        index = {**index, 'live': {f'{sport}|{home} vs {away}': live}}
    mv = for_pick(index, sport, home, away, side)
    if mv:
        item['oddsMove'] = mv
    try:
        from tools.availability_agent import team_news
        tn = team_news(ctx['avail'].get(f'{sport}|{home}|{away}'), side)
    except Exception:
        tn = None
    if tn:
        item['teamNews'] = tn
    return item


def mail_lines(day: str, sport: str, home: str, away: str, side: Optional[str],
               news: bool = True, root: str = ROOT) -> List[str]:
    """Short e-mail lines: odds movement (if known) and team news (TOP/Fan only)."""
    out = []
    try:
        item = enrich({}, day, sport, home, away, side, root=root)
    except Exception:
        return out
    if (item.get('oddsMove') or {}).get('line'):
        out.append('📈 ' + item['oddsMove']['line'])
    if news:
        try:
            from tools.availability_agent import email_line
            out.append('🩹 ' + email_line(context(day, root)['avail'].get(f'{sport}|{home}|{away}')))
        except Exception:
            pass
    return out


def side_of_pick(pick: Any, home: str, away: str) -> Optional[str]:
    if pick in ('1', 'home'):
        return 'home'
    if pick in ('2', 'away'):
        return 'away'
    if pick and same_team(pick, home):
        return 'home'
    if pick and same_team(pick, away):
        return 'away'
    return None


def our_picks(day: str, root: str = ROOT) -> List[Dict[str, Any]]:
    """TOP, Fan Favourites and A/B board picks for a day as {sport, home, away, side, team, source}."""
    out: List[Dict[str, Any]] = []
    for t in _read(os.path.join(root, 'results', f'top_{day}.json')) or []:
        h, _, a = (t.get('match') or '').partition(' vs ')
        side = side_of_pick(t.get('pick'), h, a)
        if side:
            out.append({'sport': t.get('sport'), 'home': h, 'away': a, 'side': side,
                        'team': t.get('pick'), 'source': 'TOP'})
    fan = _read(os.path.join(root, 'results', f'fanvote_{day}.json')) or {}
    for blk in (fan.get('sports') or {}).values():
        for p in (blk or {}).get('picks') or []:
            if p.get('side') in ('home', 'away'):
                out.append({'sport': p.get('sport'), 'home': p.get('home'), 'away': p.get('away'),
                            'side': p['side'], 'team': p.get('team'), 'source': 'Fan Favourites'})
    for p in sorted(glob.glob(os.path.join(root, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        for m in (_read(p) or {}).get('matches') or []:
            if not isinstance(m, dict) or not m.get('qualifies'):
                continue
            if (m.get('predictionGrade') or '') not in ('A', 'B'):
                continue
            side = side_of_pick((m.get('scoring') or {}).get('pick'), m.get('homeTeam'), m.get('awayTeam'))
            if side:
                out.append({'sport': sport, 'home': m.get('homeTeam'), 'away': m.get('awayTeam'),
                            'side': side, 'team': m.get('homeTeam' if side == 'home' else 'awayTeam'),
                            'source': f"Forebet {m.get('predictionGrade')}"})
    return out


def compare_dropping(events: List[Dict[str, Any]], picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each dropping-odds event: do we have a pick, and is it with the move?

    events: dropping_odds_feed rows (homeTeam/awayTeam/outcome or home_team/...)
    picks:  [{sport, home, away, side, source}] from TOP / Fan Favourites / A-B board.
    """
    out = []
    for e in events:
        sport = e.get('sport') or ''
        h = e.get('homeTeam') or e.get('home_team') or ''
        a = e.get('awayTeam') or e.get('away_team') or ''
        dropped = e.get('outcome') or e.get('dropped_outcome')
        dside = {'1': 'home', '2': 'away', 'X': 'draw'}.get(str(dropped))
        hit = None
        for p in picks:
            if p.get('sport') != sport:
                continue
            if same_team(p['home'], h) and same_team(p['away'], a):
                hit = (p, p['side'])
            elif same_team(p['home'], a) and same_team(p['away'], h):
                hit = (p, {'home': 'away', 'away': 'home'}.get(p['side']))
            if hit:
                break
        row = {'sport': sport, 'match': f'{h} vs {a}', 'dropped': dside,
               'openOdds': e.get('openOdds', e.get('open_odds')),
               'currentOdds': e.get('currentOdds', e.get('current_odds')),
               'dropPct': e.get('dropPct', e.get('drop_pct')),
               'ourPick': None, 'ourSource': None, 'relation': 'no_pick'}
        if hit:
            p, our = hit
            row['ourPick'] = p.get('team') or our
            row['ourSource'] = p.get('source')
            row['relation'] = 'with' if our == dside else 'against'
        out.append(row)
    return out
