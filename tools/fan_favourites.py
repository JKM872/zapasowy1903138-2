"""Fan Favourites board: SofaScore Fan Vote favourites with odds, form, H2H,
model and availability, one sport per run (GitHub matrix job).

    python tools/fan_favourites.py --sport football --day 2026-10-30 [--refresh] [--out part.json]
    python tools/fan_favourites.py --merge DIR          # parts -> results/fanvote_<day>.json
    python tools/fan_favourites.py --settle [--days 3]  # fill result of finished picks

Selection (fan_limits): Fan Vote >= 60% (football) / >= 70% (other sports),
votes >= 100, and the price of the fan side (best price across bookmakers,
fallback the stored quote) >= odds_limit(). Sorted by Fan Vote % descending.
Sports without a settled record (fan_limits.WATCH_SPORTS) are listed with
status "watch" until they have WATCH_MIN_SETTLED settled board picks.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fan_limits  # noqa: E402
import russia_filter  # noqa: E402
from tools import pricing  # noqa: E402

RESULTS = os.path.join(ROOT, 'results')
SPORTS = ['football', 'basketball', 'hockey', 'tennis', 'volleyball', 'handball',
          'baseball', 'rugby', 'table_tennis']
REFRESH_MAX = int(os.getenv('FAN_FILL_MAX_CALLS', '400'))                    # Fan Vote lookups per sport and run
REFRESH_AGE_H = 3
# Wall-clock budget for Fan Vote lookups per sport and day (a lookup can take
# ~25 s when the SofaScore API path falls back to the browser).
REFRESH_BUDGET_S = float(os.getenv('FAN_FILL_BUDGET_S') or os.getenv('FAN_REFRESH_BUDGET_S', '540'))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _read(path: str) -> Any:
    try:
        with open(path, encoding='utf-8-sig') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path: str, data: Any) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def fan_path(day: str, results: str = RESULTS) -> str:
    return os.path.join(results, f'fanvote_{day}.json')


def _rows(day: str, sport: str, results: str) -> List[Dict[str, Any]]:
    raw = _read(os.path.join(results, f'matches_{day}_{sport}_forebet.json'))
    rows = raw.get('matches') if isinstance(raw, dict) else raw
    rows = [r for r in rows or [] if isinstance(r, dict)]
    if sport == 'table_tennis':
        return _aiscore_rows(day, results)
    # Forebet finishes ~12:00 UTC; until then (and for matches Forebet lacks)
    # use the morning Sports Scraper rows so the board fills during the day.
    seen = {((r.get('homeTeam') or '').lower(), (r.get('awayTeam') or '').lower()) for r in rows}
    for r in _scraper_rows(day, sport, results):
        k = ((r.get('homeTeam') or '').lower(), (r.get('awayTeam') or '').lower())
        if k not in seen:
            seen.add(k)
            rows.append(r)
    return rows


def _aiscore_rows(day: str, results: str) -> List[Dict[str, Any]]:
    """Table tennis: union (by names) of the AiScore home/away focus files."""
    out, seen = [], set()
    for focus in ('home', 'away'):
        raw = _read(os.path.join(results, f'matches_{day}_table_tennis_aiscore_{focus}.json'))
        for r in (raw.get('matches') if isinstance(raw, dict) else raw) or []:
            if not isinstance(r, dict) or not r.get('homeTeam') or not r.get('awayTeam'):
                continue
            k = (r['homeTeam'].lower(), r['awayTeam'].lower())
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def _scraper_rows(day: str, sport: str, results: str) -> List[Dict[str, Any]]:
    raw = _read(os.path.join(results, f'matches_{day}_{sport}.json'))
    rows = raw.get('matches') if isinstance(raw, dict) else raw
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get('homeTeam') or not r.get('awayTeam'):
            continue
        r = dict(r)
        ss = r.get('sofascore')
        if isinstance(ss, dict) and 'homeProb' not in ss and ss.get('home') is not None:
            r['sofascore'] = {'found': True, 'homeProb': ss.get('home'), 'drawProb': ss.get('draw'),
                              'awayProb': ss.get('away'), 'votes': ss.get('votes'), 'url': ss.get('url')}
        t = str(r.get('time') or '')
        if ' ' in t:
            r['time'] = t.rsplit(' ', 1)[1]
        r['rowSource'] = 'sports_scraper'
        out.append(r)
    return out


def _file_age_h(day: str, sport: str, results: str, now: datetime) -> float:
    raw = _read(os.path.join(results, f'matches_{day}_{sport}_forebet.json'))
    ts = pricing._parse_ts(raw.get('generatedAt')) if isinstance(raw, dict) else None
    return (now - ts).total_seconds() / 3600 if ts else 99.0


def refresh_votes(rows: List[Dict[str, Any]], sport: str, day: str, stale: bool,
                  now: datetime, log=print, results: str = RESULTS) -> Dict[str, int]:
    """Fan Vote for every upcoming row (tools.fanvote_fill); store per day."""
    from tools import fanvote_fill
    path = fanvote_fill.store_path(day, results)
    store = fanvote_fill.load_store(path)
    st = fanvote_fill.fill_votes(rows, sport, day, now, store, log,
                                 budget_s=REFRESH_BUDGET_S, max_calls=REFRESH_MAX)
    fanvote_fill.save_store(path, store)
    return st


def _form_str(xs: Any) -> str:
    return ''.join(str(x) for x in xs) if isinstance(xs, list) else (xs or '')


def _form(r: Dict[str, Any], side: str) -> Dict[str, str]:
    f = r.get('form') or {}
    op = 'away' if side == 'home' else 'home'
    venue = {'home': 'homeAtHome', 'away': 'awayAtAway'}
    return {'overall': _form_str(f.get(side)), 'venue': _form_str(f.get(venue[side])),
            'opponentOverall': _form_str(f.get(op)), 'opponentVenue': _form_str(f.get(venue[op])),
            'season': _form_str(r.get(f'{side}Season')), 'opponentSeason': _form_str(r.get(f'{op}Season')),
            'venueSeason': _form_str(r.get({'home': 'homeAtHomeSeason', 'away': 'awayAtAwaySeason'}[side]))}


def _h2h(r: Dict[str, Any], side: str) -> Optional[Dict[str, Any]]:
    h = r.get('h2h') or {}
    if not h.get('total'):
        return None
    from tools.top_picks import h2h_texts
    line, last = h2h_texts(r, r.get('homeTeam' if side == 'home' else 'awayTeam'))
    op = 'away' if side == 'home' else 'home'
    return {'total': h.get('total'), 'wins': h.get(f'{side}Wins'), 'losses': h.get(f'{op}Wins'),
            'lastScore': h.get('lastScore'), 'lastDate': h.get('lastDate'),
            'line': line, 'last': last, 'edge': h.get('edge')}


def model_prob(r: Dict[str, Any], side: str) -> Optional[float]:
    sc, fb = r.get('scoring') or {}, r.get('forebet') or {}
    if sc.get('pick') == ('1' if side == 'home' else '2') and _f(sc.get('prob')):
        return round(_f(sc['prob']) / 100, 3)
    v = _f(fb.get('homeProb' if side == 'home' else 'awayProb'))
    return round(v / 100, 3) if v else None


def availability(rec: Optional[Dict[str, Any]], side: str) -> Dict[str, Any]:
    """ok / warn / out for the fan side from results/availability_<day>.json."""
    if not rec or rec.get('unknown') or not isinstance(rec.get('home'), list):
        return {'verdict': 'unknown', 'note': ''}
    from tools import availability_agent as aa
    op = 'away' if side == 'home' else 'home'
    v = aa.verdict(aa.summarize(rec.get(side) or []), aa.summarize(rec.get(op) or []))
    verdict = 'out' if v['board'] == 'drop' else 'warn' if (v['board'] != 'ok' or v['top_block']) else 'ok'
    return {'verdict': verdict, 'note': aa.note({**rec, 'side': side}), 'checkedAt': rec.get('checkedAt')}


def _best(r: Dict[str, Any], sport: str, side: str, day: str, market: str) -> Dict[str, Any]:
    from tools.best_price import best_price
    pick = {'sport': sport, 'match': f"{r.get('homeTeam')} vs {r.get('awayTeam')}",
            'side': side, 'oddsMarket': market}
    return best_price(pick, day)


def settled_count(sport: str, results: str = RESULTS) -> int:
    n = 0
    for p in glob.glob(os.path.join(results, 'fanvote_*.json')):
        raw = _read(p) or {}
        for pk in ((raw.get('sports') or {}).get(sport) or {}).get('picks') or []:
            if (pk.get('result') or {}).get('status') in ('won', 'lost'):
                n += 1
    return n


def build(sport: str, day: str, results: str = RESULTS, refresh: bool = False,
          use_best_price: bool = True, now: Optional[datetime] = None, log=print,
          votes_dir: Optional[str] = None) -> Dict[str, Any]:
    """{'generatedAt', 'picks': [...], 'stats': {...}} for one sport and day."""
    now = now or _now()
    # Rosja w sportach drużynowych (także kody lig Forebet RU1/RUW/…) — przed
    # odświeżaniem Fan Vote, żeby nie zużywać na nie zapytań SofaScore.
    rows = russia_filter.filter_rows(_rows(day, sport, results), 'league', 'country',
                                     'homeTeam', 'awayTeam', label=f'Fan Favourites {sport}',
                                     sport=sport)
    fill: Dict[str, int] = {}
    if refresh and rows:
        fill = refresh_votes(rows, sport, day, _file_age_h(day, sport, results, now) > REFRESH_AGE_H, now, log,
                             results=votes_dir or results) or {}
    avail = _read(os.path.join(results, f'availability_{day}.json')) or {}
    watch = (sport in fan_limits.WATCH_SPORTS
             and settled_count(sport, results) < fan_limits.WATCH_MIN_SETTLED)
    stats = {'rows': len(rows), 'withVote': 0, 'fanOk': 0, 'belowLimit': 0, 'noOdds': 0,
             'voteRequested': int(fill.get('voteRequested', 0)), 'voteFound': int(fill.get('voteFound', 0)),
             'wrongEvent': int(fill.get('wrongEvent', 0)), 'fanThr': 0, 'oddsOk': 0,
             'calls': int(fill.get('calls', 0)), 'budgetHit': int(fill.get('budgetHit', 0))}
    picks, seen = [], set()
    for r in rows:
        fs = fan_limits.fan_side(r)
        if fs is None:
            continue
        stats['withVote'] += 1
        if fs['fanPct'] >= fan_limits.fan_threshold(sport):
            stats['fanThr'] += 1
        if not fan_limits.select(sport, fs['fanPct'], fs['votes']):
            continue
        home, away = r.get('homeTeam') or '', r.get('awayTeam') or ''
        key = (home.lower(), away.lower())
        if key in seen:
            continue
        seen.add(key)
        stats['fanOk'] += 1
        side = fs['side']
        odds = r.get('odds') or {}
        stored, market = pricing.side_price(odds, sport, side)
        kickoff = r.get('kickoffUtc') or pricing.parse_kickoff(day, r.get('time'), [r.get('kickoffUtc')], sport=sport)
        ko = pricing._parse_ts(kickoff)
        bp = None
        if use_best_price and (ko is None or ko > now):
            bp = _best(r, sport, side, day, market)
        price = max((bp or {}).get('bestOdds') or 0, stored or 0) or None
        if not price or not (odds.get('home') and odds.get('away')):
            stats['noOdds'] += 1
            continue
        limit = fan_limits.odds_limit(sport, price, side)
        if price < limit['min'] or not fan_limits.passes_standard(sport, odds.get('home'), odds.get('away')):
            stats['belowLimit'] += 1
            continue
        stats['oddsOk'] += 1
        implied = round(100 / price, 1)
        fb = r.get('forebet') or {}
        ss = r.get('sofascore') or {}
        picks.append({
            'id': f'{sport}|{day}|{home}|{away}', 'sport': sport, 'date': day,
            'league': ' – '.join(x for x in (r.get('country'), r.get('league')) if x),
            'kickoff': kickoff, 'time': r.get('time'),
            'home': home, 'away': away, 'match': f'{home} vs {away}',
            'side': side, 'team': home if side == 'home' else away,
            'fanPct': fs['fanPct'], 'votes': fs['votes'], 'band': fan_limits.band(fs['fanPct']),
            'sofascoreUrl': ss.get('url'), 'matchUrl': ss.get('url'),
            'forebetUrl': r.get('forebetUrl') or r.get('url') or fb.get('url'),
            'eventId': r.get('sofascoreEventId'),
            'odds': {k: _f(odds.get(k)) for k in ('home', 'draw', 'away')},
            'oddsSource': odds.get('bookmaker') or odds.get('source'),
            'oddsMarket': market,
            'bestPrice': {'price': round(price, 2),
                          'bookmaker': (bp or {}).get('bestOddsSource') or odds.get('bookmaker') or odds.get('source'),
                          'pinnacle': ((bp or {}).get('quotes') or {}).get('pinnacle'),
                          'books': (bp or {}).get('booksCount') or 1,
                          'at': (bp or {}).get('bestOddsAt')},
            'impliedPct': implied, 'edgePct': round(fs['fanPct'] - implied, 1),
            'limit': limit,
            'status': 'watch' if watch else 'pick',
            'form': _form(r, side), 'h2h': _h2h(r, side),
            'forebet': {'prob': _f(fb.get('homeProb' if side == 'home' else 'awayProb')),
                        'pick': fb.get('prediction'), 'exactScore': fb.get('exactScore')},
            'modelProb': model_prob(r, side), 'grade': r.get('predictionGrade'),
            'availability': availability(avail.get(f'{sport}|{home}|{away}'), side),
            'result': None,
        })
    picks.sort(key=lambda p: (-p['fanPct'], -p['votes']))
    stats['picks'] = len(picks)
    log(f'   fan favourites {sport} {day}: {stats}')
    return {'generatedAt': _iso(now), 'watch': watch, 'picks': picks, 'stats': stats}


def merge(day: str, sport: str, block: Dict[str, Any], results: str = RESULTS,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Write one sport into results/fanvote_<day>.json, keeping settled results
    of picks that are already there."""
    path = fan_path(day, results)
    data = _read(path) or {}
    old = {p.get('id'): p for p in ((data.get('sports') or {}).get(sport) or {}).get('picks') or []}
    for p in block.get('picks') or []:
        prev = old.pop(p['id'], None)
        if prev and prev.get('result'):
            p['result'] = prev['result']
    # Picks that already started stay on the board even if the new run drops them.
    keep = [p for p in old.values() if p.get('result')
            or (pricing._parse_ts(p.get('kickoff')) or datetime.max.replace(tzinfo=timezone.utc))
            <= (now or _now())]
    block['picks'] = sorted((block.get('picks') or []) + keep, key=lambda p: (-p['fanPct'], -p['votes']))
    data.update(day=day, generatedAt=_iso(now or _now()),
                thresholds={'minVotes': fan_limits.MIN_VOTES, 'minVotesBySport': dict(fan_limits.MIN_VOTES_BY_SPORT),
                            'fanPct': {**fan_limits.FAN_MIN, 'default': fan_limits.FAN_MIN_DEFAULT}})
    data.setdefault('sports', {})[sport] = block
    _write(path, data)
    return data


def settle_file(day: str, index, results: str = RESULTS, now: Optional[datetime] = None) -> int:
    from top_feed import settle
    path = fan_path(day, results)
    data = _read(path)
    if not isinstance(data, dict):
        return 0
    n = 0
    for blk in (data.get('sports') or {}).values():
        for p in blk.get('picks') or []:
            if p.get('result'):
                continue
            res = settle(day, {'match': p['match'], 'pick': p['team']}, index)
            if res['status'] == 'void':
                p['result'] = {'status': 'void', 'settledAt': _iso(now or _now())}
                n += 1
            elif res['status'] in ('won', 'lost', 'draw'):
                p['result'] = {'status': 'won' if res['status'] == 'won' else 'lost',
                               'score': res.get('score'), 'draw': res['status'] == 'draw',
                               'settledAt': _iso(now or _now())}
                n += 1
    if n:
        _write(path, data)
    return n


def settle_recent(days: int = 3, results: str = RESULTS, store: Optional[str] = None,
                  today: Optional[str] = None, log=print) -> int:
    import top_feed
    index = top_feed.settle_index(results, store or top_feed.STORE_PATH)
    d0 = datetime.fromisoformat(today).date() if today else _now().date()
    total = 0
    for i in range(days + 1):
        day = (d0 - timedelta(days=i)).isoformat()
        n = settle_file(day, index, results)
        total += n
        if n:
            log(f'   settled {n} fan favourites for {day}')
    return total


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--sport', choices=SPORTS)
    ap.add_argument('--day', action='append', help='YYYY-MM-DD (repeatable; default today+tomorrow)')
    ap.add_argument('--refresh', action='store_true', help='re-read Fan Vote via SofaScore')
    ap.add_argument('--no-best-price', action='store_true')
    ap.add_argument('--out', help='write parts here instead of results/ (matrix job)')
    ap.add_argument('--merge', metavar='DIR', help='merge part files <sport>_<day>.json')
    ap.add_argument('--settle', action='store_true')
    ap.add_argument('--days', type=int, default=3)
    a = ap.parse_args(argv)
    if a.settle:
        settle_recent(a.days)
        return 0
    if a.merge:
        for p in sorted(glob.glob(os.path.join(a.merge, '**', '*.json'), recursive=True)):
            m = re.match(r'(.+)_(\d{4}-\d{2}-\d{2})\.json$', os.path.basename(p))
            blk = _read(p)
            if m and m.group(1) == 'fanvote_votes' and isinstance(blk, dict):
                from tools import fanvote_fill
                sp = fanvote_fill.store_path(m.group(2), RESULTS)
                cur = fanvote_fill.load_store(sp)
                for s, v in blk.items():
                    cur.setdefault(s, {}).update(v or {})
                fanvote_fill.save_store(sp, cur)
                continue
            if m and isinstance(blk, dict):
                merge(m.group(2), m.group(1), blk)
                print(f'   merged {os.path.basename(p)}: {len(blk.get("picks") or [])} picks')
        return 0
    if not a.sport:
        ap.error('--sport is required')
    today = _now().date()
    days = a.day or [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    for day in days:
        blk = build(a.sport, day, refresh=a.refresh, use_best_price=not a.no_best_price, votes_dir=a.out)
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            _write(os.path.join(a.out, f'{a.sport}_{day}.json'), blk)
        else:
            merge(day, a.sport, blk)
    return 0


if __name__ == '__main__':
    sys.exit(main())
