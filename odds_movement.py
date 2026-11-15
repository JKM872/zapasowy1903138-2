"""Odds movement per pick from data we already scrape (no extra page loads).

Sources, in order:
  1. OddsSafari dropping-odds archive ``outputs/oddssafari_dropping_<day>_<sport>.json``
     (opening vs current price per 1/X/2 outcome),
  2. TOP live checks ``results/top_live_<day>.json`` (first vs latest best price),
  3. our own per-day snapshots ``results/odds_snapshots_<day>_<src>.json``
     (src = top / fan / live / weekend; one file per writer so concurrent
     workflows never conflict on rebase), first vs latest price.

Freshness: on Heroku (``DYNO`` set, or ``ODDS_MOVE_REMOTE=1``) every input file
is read from raw GitHub (main) with a per-file 10-minute TTL, falling back to
the slug copy, so new data shows up without a redeploy. Only the small derived
index is kept per day (max 3 days); raw files are dropped after parsing.

``oddsMove`` = {pick: {opening, current, changePct, direction, since, source},
                opponent: {...} | None, line: str}
Odds dropping on our pick means the market agrees; rising means it is against us.
"""
import glob
import json
import os
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

from h2h_summary import same_team

ROOT = os.path.dirname(os.path.abspath(__file__))
FLAT_PCT = 2.0
RAW_BASE = 'https://raw.githubusercontent.com/JKM872/zapasowy1903138-2/main/'
TTL_S = 600.0
REMOTE_TIMEOUT_S = 4.0
SPORTS = ('football', 'basketball', 'tennis', 'hockey', 'handball', 'volleyball',
          'rugby', 'baseball', 'esports')
SNAP_SOURCES = ('top', 'fan', 'live', 'weekend')
SNAP_MAX = 60  # per match key
_MISS = object()
_remote_cache: Dict[str, Any] = {}


def _remote_on(root: str) -> bool:
    if os.path.abspath(root) != ROOT:
        return False
    flag = os.environ.get('ODDS_MOVE_REMOTE')
    if flag is None:
        flag = '1' if os.environ.get('DYNO') else '0'
    return flag == '1'


def _remote(rel: str) -> Any:
    """Parsed raw-GitHub file or _MISS. Files are fetched only when the per-day
    context is rebuilt (once per TTL); a miss is cached for TTL so an outage
    costs one timeout per file per TTL. Raw files are never kept in memory."""
    now = time.monotonic()
    hit = _remote_cache.get(rel)
    if hit and now - hit[0] < TTL_S and hit[1] is not None:
        return hit[1]
    try:
        req = urllib.request.Request(RAW_BASE + rel, headers={'User-Agent': 'pickly-odds-move'})
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT_S) as resp:  # noqa: S310
            data = json.loads(resp.read().decode('utf-8-sig'))
    except Exception:
        data = _MISS
    if len(_remote_cache) > 500:
        _remote_cache.clear()
    # Only misses are remembered; parsed data lives in the per-day context.
    _remote_cache[rel] = (now, None if data is not _MISS else data)
    return data


def _load(rel: str, root: str) -> Any:
    """results/... or outputs/... : raw GitHub when enabled, else/fallback local."""
    if _remote_on(root):
        data = _remote(rel)
        if data is not _MISS:
            return data
    return _read(os.path.join(root, *rel.split('/')))


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
    days = [x for x in (prev_day, day) if x]
    if _remote_on(root):
        rels = [f'outputs/oddssafari_dropping_{x}_{sp}.json' for x in days for sp in SPORTS]
    else:
        rels = []
        for x in days:
            rels += ['outputs/' + os.path.basename(p) for p in
                     sorted(glob.glob(os.path.join(root, 'outputs', f'oddssafari_dropping_{x}_*.json')))]
    for rel in rels:
        d = _load(rel, root)
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
    live = _load(f'results/top_live_{day}.json', root) or {}
    return {'drop': {s: list(v.values()) for s, v in drop.items()},
            'live': live if isinstance(live, dict) else {},
            'snaps': load_snapshots(day, root)}


# ---------------------------------------------------------------------------
# Own odds snapshots (no page loads: prices our runs already fetched)
def snap_key(sport: str, home: str, away: str) -> str:
    return f'{sport}|{home} vs {away}'


def load_snapshots(day: str, root: str = ROOT) -> Dict[str, List[Dict[str, Any]]]:
    """All writers merged: key -> snapshots sorted by ts."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for src in SNAP_SOURCES:
        d = _load(f'results/odds_snapshots_{day}_{src}.json', root)
        for k, rows in (d.items() if isinstance(d, dict) else ()):
            if isinstance(rows, list):
                out.setdefault(k, []).extend(r for r in rows if isinstance(r, dict))
    for rows in out.values():
        rows.sort(key=lambda r: str(r.get('ts') or ''))
    return out


def record_snapshots(day: str, src: str, rows: List[Dict[str, Any]], root: str = ROOT,
                     ts: Optional[str] = None) -> int:
    """Append {ts, home, draw, away, source} per match key to the writer's file.
    A row equal to the last one for that key is skipped. Returns rows added."""
    from datetime import datetime, timezone
    ts = ts or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    path = os.path.join(root, 'results', f'odds_snapshots_{day}_{src}.json')
    data = _read(path)
    data = data if isinstance(data, dict) else {}
    added = 0
    for r in rows:
        k = snap_key(r.get('sport') or '', r.get('home') or '', r.get('away') or '')
        snap = {'ts': ts}
        for c in ('home', 'draw', 'away'):
            try:
                v = float((r.get('odds') or {}).get(c))
                snap[c] = round(v, 3) if v > 1.0 else None
            except (TypeError, ValueError):
                snap[c] = None
        if not any(snap[c] for c in ('home', 'draw', 'away')):
            continue
        snap['source'] = r.get('source') or src
        lst = data.setdefault(k, [])
        if lst and all(lst[-1].get(c) == snap[c] for c in ('home', 'draw', 'away')):
            continue
        lst.append(snap)
        del lst[:-SNAP_MAX]
        added += 1
    if added:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    return added


def _snap_move(index: Dict[str, Any], sport: str, home: str, away: str, col: str):
    snaps = index.get('snaps') or {}
    rows = snaps.get(snap_key(sport, home, away))
    swapped = False
    if rows is None:
        for k, v in snaps.items():
            sp, _, m = k.partition('|')
            h, _, a = m.partition(' vs ')
            if sp != sport:
                continue
            if same_team(h, home) and same_team(a, away):
                rows = v
                break
            if same_team(h, away) and same_team(a, home):
                rows, swapped = v, True
                break
    if not rows:
        return None
    if swapped and col != 'draw':
        col = 'away' if col == 'home' else 'home'
    pts = [r for r in rows if r.get(col)]
    if len(pts) < 2:
        return None
    return compute(pts[0][col], pts[-1][col], pts[0].get('ts'), 'snapshots')


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
    if side not in ('home', 'away', 'draw') or not home or not away:
        return None
    pick = opp = None
    outs, swapped = _find_drop(index, sport, home, away)
    if outs:
        h, a = ('2', '1') if swapped else ('1', '2')
        if side == 'draw':
            pick = outs.get('X')
        else:
            pick, opp = (outs.get(h), outs.get(a)) if side == 'home' else (outs.get(a), outs.get(h))
    if pick is None and side != 'draw':
        rec = (index.get('live') or {}).get(f'{sport}|{home} vs {away}') or {}
        checks = [c for c in rec.get('checks') or [] if c.get('best')]
        if len(checks) >= 2:
            pick = compute(checks[0]['best'], checks[-1]['best'], checks[0].get('at'), 'top_live')
    if pick is None:
        pick = _snap_move(index, sport, home, away, side)
        if opp is None and side != 'draw':
            opp = _snap_move(index, sport, home, away, 'away' if side == 'home' else 'home')
    if pick is None and opp is None:
        return None
    st = stance(pick)
    if st is None and opp:
        st = {'down': 'against', 'up': 'with'}.get(opp['direction'], 'flat')
    out = {'pick': pick, 'opponent': opp, 'stance': st}
    out['line'] = line(out)
    return out


_CTX: Dict[Any, Any] = {}
_CTX_LOCK = threading.Lock()


def context(day: str, root: str = ROOT, ttl: float = TTL_S) -> Dict[str, Any]:
    """Movement index + availability store for a day, rebuilt at most every ttl s."""
    key = (day, root)
    hit = _CTX.get(key)
    if hit and time.time() - hit['t'] < ttl:
        return hit
    with _CTX_LOCK:  # one rebuild at a time (RSS), others reuse its result
        hit = _CTX.get(key)
        if hit and time.time() - hit['t'] < ttl:
            return hit
        return _rebuild(key, day, root)


def _rebuild(key, day: str, root: str) -> Dict[str, Any]:
    try:
        avail = _load(f'results/availability_{day}.json', root)
        avail = avail if isinstance(avail, dict) else {}
    except Exception:
        avail = {}
    hit = {'t': time.time(), 'root': root, 'index': build_index(day, root), 'avail': avail}
    _CTX[key] = hit
    while len(_CTX) > 3:  # memory: keep only the newest few days
        _CTX.pop(min(_CTX, key=lambda k: _CTX[k]['t']))
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


def displayed_pick(m: Dict[str, Any]) -> Optional[str]:
    """The pick the site/e-mail shows (MatchRow.tsx order): our engine, then
    Forebet, then the SofaScore vote majority. Works on raw and normalized rows."""
    sc = m.get('scoring') if isinstance(m.get('scoring'), dict) else {}
    if sc.get('pick'):
        return str(sc['pick'])
    if m.get('scoring_pick'):
        return str(m['scoring_pick'])
    fb = m.get('forebet') if isinstance(m.get('forebet'), dict) else {}
    pred = m.get('forebet_prediction') or fb.get('prediction')
    if pred:
        return str(pred)
    ss = m.get('sofascore') if isinstance(m.get('sofascore'), dict) else {}
    vals = []
    for k in ('home', 'draw', 'away'):
        try:
            vals.append(float(ss.get(k) or 0))
        except (TypeError, ValueError):
            vals.append(0.0)
    mx = max(vals)
    if mx > 0:
        return '1' if mx == vals[0] else 'X' if mx == vals[1] else '2'
    return None


def side_of_pick(pick: Any, home: str, away: str) -> Optional[str]:
    if pick in ('X', 'x', 'draw', '0'):
        return 'draw'
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
            side = side_of_pick(displayed_pick(m), m.get('homeTeam'), m.get('awayTeam'))
            if side:
                out.append({'sport': sport, 'home': m.get('homeTeam'), 'away': m.get('awayTeam'),
                            'side': side,
                            'team': {'home': m.get('homeTeam'), 'away': m.get('awayTeam')}.get(side, 'X'),
                            'source': f"Forebet {m.get('predictionGrade')}"})
    for p in glob.glob(os.path.join(root, 'results', 'weekend_*.json')):
        for slip in (_read(p) or {}).get('slips') or []:
            for leg in (slip or {}).get('legs') or []:
                if leg.get('date') == day and leg.get('side') in ('home', 'away', 'draw'):
                    out.append({'sport': leg.get('sport'), 'home': leg.get('home'), 'away': leg.get('away'),
                                'side': leg['side'], 'team': leg.get('pick'), 'source': 'Weekend'})
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


# ---------------------------------------------------------------------------
# Snapshot writers (run by workflows; they only read files the run already
# wrote, so no extra page loads).
def _rows_top(day, root):
    out = []
    for t in _read(os.path.join(root, 'results', f'top_{day}.json')) or []:
        if not isinstance(t, dict):
            continue
        h, _, a = (t.get('match') or '').partition(' vs ')
        side = side_of_pick(t.get('pick'), h, a)
        price = t.get('bestOdds') or t.get('odds2') or t.get('odds')
        if side:
            out.append({'sport': t.get('sport'), 'home': h, 'away': a, 'odds': {side: price},
                        'source': t.get('bestOddsSource') or 'top'})
    for p in sorted(glob.glob(os.path.join(root, 'results', f'matches_{day}_*_forebet.json'))):
        sport = os.path.basename(p)[len(f'matches_{day}_'):-len('_forebet.json')]
        for m in (_read(p) or {}).get('matches') or []:
            if isinstance(m, dict) and m.get('qualifies') and (m.get('predictionGrade') or '') in ('A', 'B'):
                o = m.get('odds') if isinstance(m.get('odds'), dict) else {}
                out.append({'sport': sport, 'home': m.get('homeTeam'), 'away': m.get('awayTeam'),
                            'odds': o, 'source': o.get('bookmaker') or o.get('source') or 'forebet'})
    return out


def _rows_fan(day, root):
    out = []
    fan = _read(os.path.join(root, 'results', f'fanvote_{day}.json')) or {}
    for blk in (fan.get('sports') or {}).values():
        for p in (blk or {}).get('picks') or []:
            # Board 1X2 (one feed, so first vs latest is a real move; best price
            # switches bookmakers between runs and would fake movement).
            o = dict(p.get('odds') or {})
            if not any(o.get(c) for c in ('home', 'draw', 'away')):
                bp = p.get('bestPrice') or {}
                if bp.get('price') and p.get('side') in ('home', 'away'):
                    o[p['side']] = bp['price']
            out.append({'sport': p.get('sport'), 'home': p.get('home'), 'away': p.get('away'),
                        'odds': o, 'source': 'fan'})
    return out


def _rows_live(day, root):
    out = []
    live = _read(os.path.join(root, 'results', f'top_live_{day}.json')) or {}
    top = {f"{t.get('sport')}|{t.get('match')}": t
           for t in _read(os.path.join(root, 'results', f'top_{day}.json')) or [] if isinstance(t, dict)}
    for k, rec in (live.items() if isinstance(live, dict) else ()):
        checks = [c for c in (rec or {}).get('checks') or [] if c.get('best')]
        t = top.get(k)
        if not checks or not t:
            continue
        sport, _, m = k.partition('|')
        h, _, a = m.partition(' vs ')
        side = side_of_pick(t.get('pick'), h, a)
        if side:
            out.append({'sport': sport, 'home': h, 'away': a, 'odds': {side: checks[-1]['best']},
                        'source': checks[-1].get('bestSource') or 'top_live'})
    return out


def _rows_weekend(day, root):
    out = []
    for p in glob.glob(os.path.join(root, 'results', 'weekend_*.json')):
        for slip in (_read(p) or {}).get('slips') or []:
            for leg in (slip or {}).get('legs') or []:
                if leg.get('date') == day and leg.get('side') in ('home', 'away', 'draw') and leg.get('price'):
                    out.append({'sport': leg.get('sport'), 'home': leg.get('home'), 'away': leg.get('away'),
                                'odds': {leg['side']: leg['price']}, 'source': leg.get('bookmaker') or 'weekend'})
    return out


_WRITERS = {'top': _rows_top, 'fan': _rows_fan, 'live': _rows_live, 'weekend': _rows_weekend}


def snapshot(src: str, days: List[str], root: str = ROOT) -> int:
    n = 0
    for day in days:
        try:
            n += record_snapshots(day, src, _WRITERS[src](day, root), root)
        except Exception as e:  # noqa: BLE001 - never fail the workflow
            print(f'odds snapshot {src} {day} failed: {type(e).__name__}: {e}')
    return n


if __name__ == '__main__':
    import argparse
    from datetime import datetime, timedelta, timezone
    ap = argparse.ArgumentParser(description='Record odds snapshots for our picks (no page loads).')
    ap.add_argument('src', choices=sorted(_WRITERS))
    ap.add_argument('days', nargs='*', help='YYYY-MM-DD (default: yesterday, today, tomorrow UTC)')
    a = ap.parse_args()
    today = datetime.now(timezone.utc).date()
    ds = a.days or [(today + timedelta(days=d)).isoformat() for d in (-1, 0, 1)]
    print(f'odds snapshots ({a.src}): {snapshot(a.src, ds)} new rows for {", ".join(ds)}')
