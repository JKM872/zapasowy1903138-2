#!/usr/bin/env python3
"""Weekend Slip: 2-3 suggested accumulators over Fri-Sun fixtures.

Leg pool = published TOP picks (results/top_<day>.json, not withdrawn) +
Fan Favourites with ``status: "pick"`` (results/fanvote_<day>.json), each with
availability not ``out``, price >= fan_limits.odds_limit() and kickoff in the
future. Legs are ranked by edge (model prob - implied; fan % - implied when no
model prob), positive edge first. Slips are disjoint: no shared match or team,
one leg per league, at most MAX_LEGS legs (backtest: 4-5 legs went 0/9).

A published slip is never rebuilt: later runs only re-check its legs
(``--recheck``: withdraw a leg whose side is now ``out`` or whose TOP pick was
withdrawn) and settle them; new slips are added from unused legs while fewer
than MAX_SLIPS exist. Withdrawn legs drop out of the combined odds (slip
``adjusted``); fewer than 2 legs left -> ``void``.

    python tools/weekend_slip.py              # build/refresh (Fri/Sat/Sun only)
    python tools/weekend_slip.py --recheck    # availability re-check + settle
    python tools/weekend_slip.py --settle     # settle previous weekend
    python tools/weekend_slip.py --backtest 2026-10-16 2026-10-23
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fan_limits  # noqa: E402
from tools import pricing  # noqa: E402

RESULTS = os.path.join(ROOT, 'results')
MAX_LEGS = 3
MIN_LEGS = 2
MAX_SLIPS = 3
MAX_NEW_PER_RUN = 2       # Friday leaves room for a Sat/Sun slip
STAKE_PCT = 0.5
RECHECK_MIN = 90
NOTE = ('Accumulators multiply the bookmaker margin with every leg and lose more often '
        'than singles: three legs at ~60% each land about one time in five. Backtest on two '
        'past weekends: 0 of 3 settled slips won with the odds limits, 1 of 6 without '
        '(ROI -100% / -41%). Stake small (0.5% of bankroll) or skip.')

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo('Europe/Warsaw')
except Exception:  # pragma: no cover - tzdata missing
    _TZ = timezone(timedelta(hours=1))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v > 0 else None


def _read(path: str) -> Any:
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(path: str, data: Any) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def friday_of(d: date) -> Optional[date]:
    """Friday of the weekend containing d (Fri/Sat/Sun), else None."""
    wd = d.weekday()
    return d - timedelta(days=wd - 4) if wd >= 4 else None


def weekend_days(friday: date) -> List[str]:
    return [(friday + timedelta(days=i)).isoformat() for i in range(3)]


def slip_path(friday: str, results: str = RESULTS) -> str:
    return os.path.join(results, f'weekend_{friday}.json')


def _norm(s: Any) -> str:
    from top_feed import _norm as n
    return n(s)


# ---------------------------------------------------------------------------
# Leg pool
# ---------------------------------------------------------------------------

def _forebet_row(day: str, sport: str, home: str, away: str, results: str) -> Optional[Dict[str, Any]]:
    from tools.fan_favourites import _rows
    h, a = _norm(home), _norm(away)
    for r in _rows(day, sport, results):
        if _norm(r.get('homeTeam')) == h and _norm(r.get('awayTeam')) == a:
            return r
    return None


def _top_legs(day: str, results: str, avail: Dict[str, Any], now: datetime,
              limits: bool) -> List[Dict[str, Any]]:
    from top_feed import _split_match, _top_list
    from tools.fan_favourites import availability, model_prob
    raw = _top_list(_read(os.path.join(results, f'top_{day}.json')))
    live = _read(os.path.join(results, f'top_live_{day}.json')) or {}
    out = []
    for r in raw or []:
        if not isinstance(r, dict) or r.get('withdrawn'):
            continue
        sport, match = r.get('sport') or '', r.get('match') or ''
        if (live.get(f'{sport}|{match}') or {}).get('withdrawn'):
            continue
        home, away = _split_match(match)
        pk = _norm(r.get('pick'))
        side = 'home' if pk == _norm(home) else 'away' if pk == _norm(away) else None
        if not side:
            continue
        price = _f(r.get('bestOdds')) or _f(r.get('odds2')) or _f(r.get('odds'))
        if not price:
            continue
        limit = fan_limits.odds_limit(sport, price, side)
        if limits and price < limit['min']:
            continue
        row = _forebet_row(day, sport, home, away, results)
        mp = _f(r.get('pCal')) or (model_prob(row, side) if row else None)
        av = availability(avail.get(f'{sport}|{home}|{away}'), side)
        out.append(_leg('top', sport, day, r.get('league') or '', home, away, side, price,
                        r.get('bestOddsSource') or 'stored', mp, None, limit, av,
                        r.get('kickoffUtc') or pricing.parse_kickoff(day, r.get('time'), sport=sport),
                        r.get('grade')))
    return out


def _fan_legs(day: str, results: str, now: datetime, limits: bool,
              rebuild: bool = False) -> List[Dict[str, Any]]:
    """Fan Favourites of a day. ``rebuild`` recomputes them from the forebet
    rows (backtest of days before the board existed)."""
    if rebuild:
        from tools.fan_favourites import SPORTS, build
        picks = []
        for sp in SPORTS:
            if limits:
                picks += build(sp, day, results, use_best_price=False, now=now, log=lambda *_: None)['picks']
            else:
                orig = fan_limits.odds_limit
                fan_limits.odds_limit = lambda *a, **k: {'min': 1.0, 'source': 'none'}
                try:
                    picks += build(sp, day, results, use_best_price=False, now=now, log=lambda *_: None)['picks']
                finally:
                    fan_limits.odds_limit = orig
    else:
        raw = _read(os.path.join(results, f'fanvote_{day}.json')) or {}
        picks = [p for blk in (raw.get('sports') or {}).values() for p in (blk or {}).get('picks') or []]
    out = []
    for p in picks:
        if not isinstance(p, dict) or p.get('status') != 'pick':
            continue
        price = _f((p.get('bestPrice') or {}).get('price'))
        if not price:
            continue
        limit = p.get('limit') or fan_limits.odds_limit(p['sport'], price, p.get('side'))
        if limits and price < limit['min']:
            continue
        out.append(_leg('fan', p['sport'], day, p.get('league') or '', p['home'], p['away'], p['side'],
                        price, (p.get('bestPrice') or {}).get('bookmaker'), _f(p.get('modelProb')),
                        p.get('fanPct'), limit, p.get('availability') or {}, p.get('kickoff'),
                        p.get('grade')))
    return out


def _leg(source, sport, day, league, home, away, side, price, book, model, fan, limit, av,
         kickoff, grade) -> Dict[str, Any]:
    implied = 100 / price
    prob = model * 100 if model else fan
    return {
        'id': f'{sport}|{day}|{home}|{away}', 'source': source, 'sport': sport, 'date': day,
        'league': league, 'match': f'{home} vs {away}', 'home': home, 'away': away,
        'kickoff': kickoff, 'side': side, 'pick': home if side == 'home' else away,
        'price': round(price, 2), 'bookmaker': book, 'modelProb': model, 'fanPct': fan,
        'impliedPct': round(implied, 1),
        'edgePct': round(prob - implied, 1) if prob else None,
        'limit': limit, 'grade': grade,
        'availability': (av or {}).get('verdict') or 'unknown',
        'availabilityNote': (av or {}).get('note') or '',
        'status': 'pending', 'withdrawnReason': None, 'score': None,
    }


def leg_pool(days: List[str], results: str = RESULTS, now: Optional[datetime] = None,
             limits: bool = True, rebuild_fan: bool = False) -> List[Dict[str, Any]]:
    now = now or _now()
    pool: Dict[str, Dict[str, Any]] = {}
    for day in days:
        avail = _read(os.path.join(results, f'availability_{day}.json')) or {}
        for leg in (_top_legs(day, results, avail, now, limits)
                    + _fan_legs(day, results, now, limits, rebuild_fan)):
            ko = pricing._parse_ts(leg['kickoff'])
            if leg['availability'] == 'out' or (ko is not None and ko <= now):
                continue
            prev = pool.get(leg['id'])
            if prev:   # same match from TOP and Fan Favourites: one leg, both sources
                if prev['side'] != leg['side']:
                    pool[leg['id']] = None   # type: ignore[assignment]  # sources disagree: skip
                    continue
                prev['source'] = 'top+fan'
                prev['fanPct'] = prev['fanPct'] or leg['fanPct']
                prev['modelProb'] = prev['modelProb'] or leg['modelProb']
                if leg['price'] > prev['price']:
                    prev.update(price=leg['price'], bookmaker=leg['bookmaker'],
                                impliedPct=leg['impliedPct'], limit=leg['limit'])
                prob = prev['modelProb'] * 100 if prev['modelProb'] else prev['fanPct']
                prev['edgePct'] = round(prob - prev['impliedPct'], 1) if prob else None
            elif leg['id'] not in pool:
                pool[leg['id']] = leg
    legs = [v for v in pool.values() if v]
    legs.sort(key=lambda l: (-(1 if (l['edgePct'] or 0) > 0 else 0), -(l['edgePct'] or -999),
                             -(l['modelProb'] or 0)))
    return legs


# ---------------------------------------------------------------------------
# Slips
# ---------------------------------------------------------------------------

def _teams(leg: Dict[str, Any]) -> set:
    return {_norm(leg['home']), _norm(leg['away'])}


def _league_key(leg: Dict[str, Any]) -> str:
    return f"{leg['sport']}|{_norm(leg['league'])}"


def slip_numbers(slip: Dict[str, Any]) -> None:
    """Combined odds / model prob over legs that are not withdrawn; status."""
    live = [l for l in slip['legs'] if l['status'] != 'withdrawn']
    odds, prob = 1.0, 1.0
    for l in live:
        odds *= l['price']
        prob = prob * l['modelProb'] if (prob is not None and l.get('modelProb')) else None
    slip['combinedOdds'] = round(odds, 2) if live else None
    slip['combinedModelProb'] = round(prob, 3) if (live and prob is not None) else None
    slip['combinedImpliedPct'] = round(100 / odds, 1) if live else None
    adjusted = len(live) < len(slip['legs'])
    if len(live) < MIN_LEGS:
        slip['status'] = 'void'
    elif any(l['status'] == 'lost' for l in live):
        slip['status'] = 'lost'
    elif all(l['status'] == 'won' for l in live):
        slip['status'] = 'won'
    else:
        slip['status'] = 'adjusted' if adjusted else 'pending'
    slip['adjusted'] = adjusted


def build_slips(pool: List[Dict[str, Any]], existing: List[Dict[str, Any]],
                max_slips: int = MAX_SLIPS, max_legs: int = MAX_LEGS,
                max_new: int = MAX_SLIPS) -> List[Dict[str, Any]]:
    used_ids = {l['id'] for s in existing for l in s['legs']}
    used_teams = set().union(*[_teams(l) for s in existing for l in s['legs']]) if existing else set()
    slips = list(existing)
    free = [l for l in pool if l['id'] not in used_ids and not (_teams(l) & used_teams)]
    while len(slips) < max_slips and len(slips) - len(existing) < max_new:
        legs, leagues, teams, days = [], set(), set(), set()
        # First pass: one leg per day (multi-day slip), then fill by rank.
        for spread in (True, False):
            for l in free:
                if len(legs) == max_legs:
                    break
                if (l in legs or _league_key(l) in leagues or _teams(l) & teams
                        or (spread and l['date'] in days)):
                    continue
                legs.append(l)
                leagues.add(_league_key(l))
                teams |= _teams(l)
                days.add(l['date'])
        legs.sort(key=lambda l: (l['kickoff'] or '', l['id']))
        if len(legs) < MIN_LEGS:
            break
        slip = {'id': f'S{len(slips) + 1}', 'legs': [dict(l) for l in legs]}
        slip_numbers(slip)
        slips.append(slip)
        free = [l for l in free if not (_teams(l) & teams)]
    return slips


def _index(results: str, store: Optional[str] = None):
    import top_feed
    return {**top_feed._store_index(store or top_feed.STORE_PATH), **top_feed._forebet_settled(results)}


def settle_slips(slips: List[Dict[str, Any]], index) -> int:
    from top_feed import settle
    n = 0
    for s in slips:
        for l in s['legs']:
            if l['status'] != 'pending':
                continue
            res = settle(l['date'], {'match': l['match'], 'pick': l['pick']}, index)
            if res['status'] in ('won', 'lost', 'draw'):
                l['status'] = 'won' if res['status'] == 'won' else 'lost'   # draw = lost
                l['score'] = res.get('score')
                n += 1
        slip_numbers(s)
    return n


def recheck(slips: List[Dict[str, Any]], results: str, now: datetime) -> int:
    """Withdraw pending legs (kickoff within RECHECK_MIN) whose side is now out
    or whose TOP pick was withdrawn."""
    from tools.fan_favourites import availability
    n = 0
    for s in slips:
        for l in s['legs']:
            ko = pricing._parse_ts(l.get('kickoff'))
            if l['status'] != 'pending' or ko is None or ko <= now \
                    or ko - now > timedelta(minutes=RECHECK_MIN):
                continue
            day = l['date']
            reason = None
            if 'top' in l['source']:
                live = _read(os.path.join(results, f'top_live_{day}.json')) or {}
                e = live.get(f"{l['sport']}|{l['match']}") or {}
                if e.get('withdrawn'):
                    reason = e.get('withdrawReason') or 'TOP pick withdrawn'
            avail = _read(os.path.join(results, f'availability_{day}.json')) or {}
            av = availability(avail.get(f"{l['sport']}|{l['home']}|{l['away']}"), l['side'])
            l['availability'] = av['verdict']
            l['availabilityNote'] = av.get('note') or l.get('availabilityNote') or ''
            if not reason and av['verdict'] == 'out':
                reason = av.get('note') or 'key player out'
            if reason:
                l.update(status='withdrawn', withdrawnReason=reason, withdrawnAt=_iso(now))
                n += 1
            l['checkedAt'] = _iso(now)
        slip_numbers(s)
    return n


def run(friday: str, mode: str = 'build', results: str = RESULTS, now: Optional[datetime] = None,
        store: Optional[str] = None, log=print) -> Dict[str, Any]:
    now = now or _now()
    path = slip_path(friday, results)
    data = _read(path) or {'friday': friday, 'slips': []}
    slips = data.get('slips') or []
    if mode == 'build':
        pool = leg_pool(weekend_days(date.fromisoformat(friday)), results, now)
        before = len(slips)
        slips = build_slips(pool, slips, max_new=MAX_NEW_PER_RUN)
        log(f'   weekend {friday}: pool {len(pool)} legs, slips {before} -> {len(slips)}')
    if mode in ('build', 'recheck'):
        w = recheck(slips, results, now)
        if w:
            log(f'   withdrew {w} legs')
    n = settle_slips(slips, _index(results, store))
    if n:
        log(f'   settled {n} legs')
    data.update(friday=friday, days=weekend_days(date.fromisoformat(friday)),
                generatedAt=data.get('generatedAt') or _iso(now), updatedAt=_iso(now),
                note=NOTE, stakePct=STAKE_PCT, maxLegs=MAX_LEGS, slips=slips)
    _write(path, data)
    return data


# ---------------------------------------------------------------------------
# Backtest and email
# ---------------------------------------------------------------------------

def backtest(fridays: List[str], results: str = RESULTS, store: Optional[str] = None) -> Dict[str, Any]:
    index = _index(results, store)
    out = {}
    for limits in (False, True):
        slips_all, legs_all = [], []
        for fr in fridays:
            start = datetime.combine(date.fromisoformat(fr), datetime.min.time(), _TZ)
            pool = leg_pool(weekend_days(date.fromisoformat(fr)), results, start, limits, rebuild_fan=True)
            slips = build_slips(pool, [])
            settle_slips(slips, index)
            for s in slips:
                s['friday'] = fr
            slips_all += slips
        done = [s for s in slips_all if s['status'] in ('won', 'lost')]
        for s in done:
            legs_all += [l for l in s['legs'] if l['status'] in ('won', 'lost')]
        won = [s for s in done if s['status'] == 'won']
        profit = sum(s['combinedOdds'] - 1 for s in won) - (len(done) - len(won))
        out['limits' if limits else 'noLimits'] = {
            'weekends': len(fridays), 'slips': len(slips_all), 'settled': len(done), 'won': len(won),
            'hitPct': round(100 * len(won) / len(done), 1) if done else None,
            'roiPct': round(100 * profit / len(done), 1) if done else None,
            'avgOdds': round(sum(s['combinedOdds'] for s in done) / len(done), 2) if done else None,
            'legHitPct': round(100 * sum(l['status'] == 'won' for l in legs_all) / len(legs_all), 1)
            if legs_all else None,
            'detail': [{'friday': s['friday'], 'status': s['status'], 'odds': s['combinedOdds'],
                        'legs': [f"{l['pick']} @{l['price']} {l['status']}" for l in s['legs']]}
                       for s in slips_all]}
    return out


def send_email(data: Dict[str, Any]) -> None:
    import smtplib
    from email.mime.text import MIMEText
    from html import escape
    to, frm, pw = os.getenv('EMAIL_RECIPIENT'), os.getenv('EMAIL_SENDER'), os.getenv('EMAIL_PASSWORD')
    if not (to and frm and pw):
        print('   brak EMAIL_* - mail pominiety')
        return
    if not data.get('slips'):
        print('   no slips - mail skipped')
        return
    parts = [f"<h2>Weekend Slip {escape(data['friday'])}</h2><p><i>{escape(NOTE)}</i></p>"]
    for s in data['slips']:
        parts.append(f"<h3>{s['id']} - combined odds {s['combinedOdds']} ({escape(s['status'])}), "
                     f"stake {STAKE_PCT}% bankroll</h3><ul>")
        for l in s['legs']:
            parts.append(f"<li>{escape(l['date'])} {escape(l['sport'])} {escape(l['league'])}: "
                         f"{escape(l['match'])} - <b>{escape(l['pick'])}</b> @ {l['price']} "
                         f"(limit &ge; {l['limit']['min']}, {escape(l['status'])})</li>")
        parts.append('</ul>')
    msg = MIMEText(''.join(parts), 'html', 'utf-8')
    msg['Subject'] = f"Weekend Slip {data['friday']} - {len(data['slips'])} slips"
    msg['From'], msg['To'] = frm, to
    with smtplib.SMTP('smtp.gmail.com', 587) as s:
        s.starttls()
        s.login(frm, pw)
        s.sendmail(frm, [x.strip() for x in to.split(',')], msg.as_string())
    print('   weekend mail sent')


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--recheck', action='store_true')
    g.add_argument('--settle', action='store_true', help='settle the previous weekend')
    g.add_argument('--backtest', nargs='+', metavar='FRIDAY')
    ap.add_argument('--friday', help='YYYY-MM-DD (default: this weekend)')
    ap.add_argument('--email', action='store_true')
    ap.add_argument('--json', help='backtest output file')
    a = ap.parse_args(argv)
    if a.backtest:
        res = backtest(a.backtest)
        for k, v in res.items():
            print(k, {x: y for x, y in v.items() if x != 'detail'})
            for d in v['detail']:
                print('   ', d)
        if a.json:
            _write(a.json, res)
        return 0
    today = _now().astimezone(_TZ).date()
    if a.settle:
        fr = a.friday or (friday_of(today) or today - timedelta(days=(today.weekday() - 4) % 7)).isoformat()
        if os.path.exists(slip_path(fr)):
            run(fr, 'settle')
        return 0
    if a.friday:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.friday) or date.fromisoformat(a.friday).weekday() != 4:
            ap.error('--friday must be a Friday YYYY-MM-DD')
        fr = a.friday
    else:
        f = friday_of(today)
        if not f:
            print('   not a weekend - nothing to do')
            return 0
        fr = f.isoformat()
    data = run(fr, 'recheck' if a.recheck else 'build')
    if a.email:
        send_email(data)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
