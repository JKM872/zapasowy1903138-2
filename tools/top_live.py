"""Live job for published TOP picks (design K2 + K3): closing odds / CLV and the
pre-kickoff final check. Run every 10 min by .github/workflows/top_live.yml.

Each run reads ``results/top_<today>.json`` and ``top_<yesterday>.json``
(after-midnight kickoffs) and selects picks with kickoff in (now-5, now+100] min:

* every run with 0 < minsToKick <= 90 appends a check to ``checks[]``: best
  current price (tools/best_price.py) and the closing quote (Pinnacle, else
  OddsSafari) with its own market;
* 0 < minsToKick <= 25: ``closingOdds`` is overwritten (last write before
  kickoff wins). When kickoff passes without such a check, the latest quote with
  minsToKick <= 60 becomes ``closingOdds`` with ``closingApprox: true``, else
  ``closingOdds: null`` (excluded from CLV);
* ``clvPct`` = publication odds2 / closing odds2 - 1 (in %), only when both are
  the same market (2way/2way_equiv vs 3way), else null;
* 20 <= minsToKick <= 90 is the final check: availability from
  ``results/availability_<pick day>.json`` (written by the availability agent)
  withdraws the pick iff the record says ``top_block``, is not ``unknown`` and was
  checked at most 180 min ago; the best price below ``floorOdds`` withdraws it too
  (it keeps closing/CLV tracking). Withdrawals are sticky.

Writes only ``results/top_live_<pick day>.json`` (dict keyed ``sport|match``).
Never writes ``top_<day>.json``.

Usage: python tools/top_live.py [--dry-run] [--now 2026-10-26T22:30:00Z] [--due]
  --dry-run  print checks and the records that would change, write nothing
  --due      print how many picks need a price check now (0 = nothing to fetch)
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools import best_price, pricing  # noqa: E402

RESULTS = os.path.join(ROOT, 'results')
WINDOW_PAST_MIN = 5          # select kickoffs in (now-5, now+100]
WINDOW_AHEAD_MIN = 100
CHECK_MAX_MIN = 90           # checks[] in (0, 90]
CLOSE_MAX_MIN = 25           # closingOdds overwritten in (0, 25]
APPROX_MAX_MIN = 60          # fallback closing from a check <= 60 min before kickoff
FINAL_MIN, FINAL_MAX = 20, 90
AVAIL_MAX_AGE_MIN = 180
FINALIZE_LOOKBACK = timedelta(hours=24)
CLOSE_SOURCES = ('pinnacle', 'oddssafari')
# Older picks have no oddsMarket; tennis/volleyball never carry a draw and
# football/handball are 3-way. Hockey/basketball/baseball stay unknown (the stored
# price may be a regulation 3-way quote) -> no CLV for them.
MARKET_BY_SPORT = {'football': '3way', 'handball': '3way', 'tennis': '2way', 'volleyball': '2way'}

try:                                     # C6 folding rules when available
    from tools.team_names import fold as _team_fold  # type: ignore
except Exception:                        # noqa: BLE001
    _team_fold = None


def _warn(msg: str) -> None:
    print(f'WARNING top_live: {msg}', file=sys.stderr, flush=True)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _key(p: Dict[str, Any]) -> str:
    return f"{p.get('sport')}|{p.get('match')}"


def _fold(s: Any) -> str:
    if _team_fold:
        try:
            return _team_fold(s)
        except Exception:                # noqa: BLE001
            pass
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', s.lower())


# ---------------------------------------------------------------- files

def _read_json(path: str) -> Any:
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def load_picks(day: str) -> List[Dict[str, Any]]:
    p = os.path.join(RESULTS, f'top_{day}.json')
    if not os.path.exists(p):
        return []
    try:
        data = _read_json(p)
    except Exception as e:               # noqa: BLE001
        _warn(f'top_{day}.json unreadable ({type(e).__name__})')
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def load_live(day: str) -> Dict[str, Any]:
    p = os.path.join(RESULTS, f'top_live_{day}.json')
    if not os.path.exists(p):
        return {}
    try:
        data = _read_json(p)
    except Exception as e:               # noqa: BLE001
        _warn(f'top_live_{day}.json unreadable ({type(e).__name__}) - starting empty')
        return {}
    return data if isinstance(data, dict) else {}


def save_live(day: str, live: Dict[str, Any]) -> str:
    p = os.path.join(RESULTS, f'top_live_{day}.json')
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(live, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, p)
    return p


_AVAIL: Dict[str, Dict[str, Any]] = {}


def load_availability(day: str) -> Dict[str, Any]:
    """results/availability_<day>.json once per run; missing/malformed -> {}."""
    if day not in _AVAIL:
        p = os.path.join(RESULTS, f'availability_{day}.json')
        data: Any = {}
        if os.path.exists(p):
            try:
                data = _read_json(p)
            except Exception as e:       # noqa: BLE001
                _warn(f'availability_{day}.json malformed ({type(e).__name__}) - line-ups unknown')
                data = {}
        if not isinstance(data, dict):
            _warn(f'availability_{day}.json is not a dict - line-ups unknown')
            data = {}
        _AVAIL[day] = data
    return _AVAIL[day]


# ---------------------------------------------------------------- pick fields

def pick_kickoff(pick: Dict[str, Any], day: str) -> Optional[datetime]:
    """kickoffUtc (C2 picks) else Forebet time read per sport (pricing.parse_kickoff)."""
    k = pick.get('kickoffUtc') or pricing.parse_kickoff(day, pick.get('time'), None, pick.get('sport'))
    return pricing._parse_ts(k) if k else None


def pick_market(pick: Dict[str, Any]) -> Optional[str]:
    return pick.get('oddsMarket') or MARKET_BY_SPORT.get(str(pick.get('sport') or ''))


def pub_odds2(pick: Dict[str, Any], market: Optional[str]) -> Optional[float]:
    """Publication price in the pick's market (odds2; stored odds when the market is plain)."""
    v = pick.get('odds2')
    if v is None and market in ('2way', '3way'):
        v = pick.get('odds')
    try:
        return float(v) if v is not None and float(v) > 1.0 else None
    except (TypeError, ValueError):
        return None


def same_market(a: Optional[str], b: Optional[str]) -> bool:
    """2way and 2way_equiv both include OT; 3way (draw = loss) only matches 3way."""
    if not a or not b:
        return False
    return (a == '3way') == (b == '3way')


def clv_pct(pub2: Optional[float], pub_market: Optional[str],
            close2: Optional[float], close_market: Optional[str]) -> Optional[float]:
    if not pub2 or not close2 or not same_market(pub_market, close_market):
        return None
    return round((pub2 / close2 - 1) * 100, 1)


# ---------------------------------------------------------------- prices

def _raw_quote(src: str, pick: Dict[str, Any], day: str) -> Optional[Dict[str, Any]]:
    """One source's raw 1X2 for the pick, via best_price's source table (modules
    cache their boards, so best_price() already paid for the HTTP calls)."""
    fn = best_price.SOURCES.get(src)
    sport = str(pick.get('sport') or '')
    home, away, _ = best_price._side(pick)
    if not fn or (src, sport) in best_price._DEAD or not home or not away:
        return None
    try:
        mod = best_price._MODULES.get(fn)
        if mod:
            __import__(mod)
        return best_price._timed(lambda: fn(home, away, sport, day),
                                 best_price.BUDGET_S.get(src, best_price.TIMEOUT_S))
    except Exception as e:               # noqa: BLE001
        best_price._DEAD.add((src, sport))
        _warn(f'{src} {sport} closing quote skipped ({type(e).__name__}: {str(e)[:80]})')
        return None


def fetch_prices(pick: Dict[str, Any], day: str) -> Dict[str, Any]:
    """{'best','bestSource','books','quote','quoteSource','quoteMarket'} - never raises."""
    out: Dict[str, Any] = {'best': None, 'bestSource': None, 'books': 0,
                           'quote': None, 'quoteSource': None, 'quoteMarket': None}
    try:
        bp = best_price.best_price(pick, day)
        out.update(best=bp.get('bestOdds'), bestSource=bp.get('bestOddsSource'),
                   books=bp.get('booksCount') or 0)
    except Exception as e:               # noqa: BLE001
        _warn(f'best price failed for {_key(pick)} ({type(e).__name__})')
    _, _, side = best_price._side(pick)
    for src in CLOSE_SOURCES:
        raw = _raw_quote(src, pick, day)
        if not raw:
            continue
        q, market = pricing.side_price(raw, str(pick.get('sport') or ''), side)
        if q is None or not best_price.MIN_QUOTE <= float(q) <= best_price.MAX_QUOTE:
            continue
        out.update(quote=round(float(q), 3), quoteSource=src, quoteMarket=market)
        break
    return out


# ---------------------------------------------------------------- availability

def find_availability(pick: Dict[str, Any], day: str) -> Optional[Dict[str, Any]]:
    data = load_availability(day)
    sport = str(pick.get('sport') or '')
    home, _, away = str(pick.get('match') or '').partition(' vs ')
    rec = data.get(f'{sport}|{home}|{away}')
    if rec is None:
        fh, fa = _fold(home), _fold(away)
        for k, v in data.items():
            parts = str(k).split('|')
            if len(parts) == 3 and parts[0] == sport and _fold(parts[1]) == fh and _fold(parts[2]) == fa:
                rec = v
                break
    return rec


def availability(pick: Dict[str, Any], day: str, now: datetime
                 ) -> Tuple[str, Optional[int], Optional[Dict[str, Any]]]:
    """(avail 'ok'|'block'|'unknown'|'stale', availAgeMin, record)."""
    rec = find_availability(pick, day)
    if rec is None:
        return 'unknown', None, None
    at = pricing._parse_ts(rec.get('checkedAt')) if isinstance(rec, dict) else None
    if (not isinstance(rec, dict) or not isinstance(rec.get('top_block'), bool)
            or not isinstance(rec.get('unknown', False), bool) or at is None):
        _warn(f'availability record for {_key(pick)} malformed - line-ups unknown')
        return 'unknown', None, None
    age = int(round((now - at).total_seconds() / 60))
    if rec.get('unknown'):
        return 'unknown', age, rec
    if age > AVAIL_MAX_AGE_MIN:
        return 'stale', age, rec
    return ('block' if rec['top_block'] else 'ok'), age, rec


def withdraw_reason(rec: Dict[str, Any]) -> str:
    """Key absences on the picked side (out/doubtful x star/key, max 3), else board/netStars."""
    players = rec.get('home' if rec.get('side') == 'home' else 'away') or []
    kept = [p for p in players if isinstance(p, dict)
            and p.get('status') in ('out', 'doubtful') and p.get('importance') in ('star', 'key')]
    if kept:
        return 'Key absence: ' + ', '.join(f"{p.get('name')} ({p.get('status')})" for p in kept[:3])
    return f"Key absence (board: {rec.get('board', '?')}, netStars {rec.get('netStars', 0)})"


# ---------------------------------------------------------------- per-pick steps

def _set_closing(rec: Dict[str, Any], pick: Dict[str, Any], c: Dict[str, Any],
                 approx: bool) -> None:
    market = pick_market(pick)
    rec.update({
        'closingOdds': c['quote'], 'closingAt': c['at'], 'closingSource': c['quoteSource'],
        'closingMarket': c['quoteMarket'], 'closingMinsToKick': c['minsToKick'],
        'closingApprox': approx,
        'clvPct': clv_pct(pub_odds2(pick, market), market, c['quote'], c['quoteMarket']),
    })


def check_pick(pick: Dict[str, Any], day: str, rec: Dict[str, Any], now: datetime,
               mins: float) -> Dict[str, Any]:
    """One check at 0 < mins <= 90: prices, closing, final check / withdrawals."""
    market = pick_market(pick)
    priced = dict(pick, oddsMarket=market) if market else pick
    pr = fetch_prices(priced, day)
    c: Dict[str, Any] = {'at': _iso(now), 'minsToKick': int(round(mins)),
                         'best': pr['best'], 'bestSource': pr['bestSource'], 'books': pr['books'],
                         'quote': pr['quote'], 'quoteSource': pr['quoteSource'],
                         'quoteMarket': pr['quoteMarket']}
    if pr['best'] is not None:
        rec.update(bestOdds=pr['best'], bestOddsSource=pr['bestSource'], bestOddsAt=c['at'],
                   booksCount=pr['books'])
    if mins <= CLOSE_MAX_MIN and pr['quote'] is not None:
        _set_closing(rec, pick, c, approx=False)
    if FINAL_MIN <= mins <= FINAL_MAX:
        state, age, arec = availability(pick, day, now)
        c['avail'], c['availAgeMin'] = state, age
        if not rec.get('withdrawn'):
            floor = float(pick.get('floorOdds') or 1.0)
            if state == 'block' and arec is not None:
                _withdraw(rec, 'availability', withdraw_reason(arec), c['at'])
            elif pr['best'] is not None and pr['best'] < floor:
                _withdraw(rec, 'price', f"Price fell to {pr['best']:.2f}, below the profitable "
                                         f"minimum {floor:.2f}", c['at'])
    rec.setdefault('checks', []).append(c)
    return c


def _withdraw(rec: Dict[str, Any], kind: str, reason: str, at: str) -> None:
    rec.update(withdrawn=True, withdrawKind=kind, withdrawReason=reason, withdrawnAt=at)


def finalize(pick: Dict[str, Any], rec: Dict[str, Any]) -> bool:
    """After kickoff, once: approx/null closing when no check fell in (0, 25];
    flag a missed final check. Returns True when the record changed."""
    if 'finalCheckMissed' in rec:
        return False
    checks = rec.setdefault('checks', [])
    if 'closingOdds' not in rec:
        quoted = [c for c in checks if c.get('quote') is not None]
        last = quoted[-1] if quoted else None
        if last is not None and last.get('minsToKick', 999) <= APPROX_MAX_MIN:
            _set_closing(rec, pick, last, approx=True)
        else:
            rec.update(closingOdds=None, clvPct=None)
    rec['finalCheckMissed'] = not any('avail' in c for c in checks)
    if rec['finalCheckMissed']:
        print(f'   MISS final check: {_key(pick)} (no run {FINAL_MIN}-{FINAL_MAX} min before kick-off)')
    return True


# ---------------------------------------------------------------- run

def _days(now: datetime) -> List[str]:
    d = now.astimezone(timezone.utc).date()
    return [(d - timedelta(days=1)).isoformat(), d.isoformat()]


def _candidates(now: datetime):
    """(day, pick, kickoff, mins) for every non-withdrawn TOP pick of yesterday/today."""
    for day in _days(now):
        for pick in load_picks(day):
            if pick.get('withdrawn'):       # withdrawn in the TOP file by top_picks
                continue
            ko = pick_kickoff(pick, day)
            if ko is None:
                print(f'   INFO no kickoff for {_key(pick)} ({day}) - not checked', file=sys.stderr)
                continue
            yield day, pick, ko, (ko - now).total_seconds() / 60


def due(now: datetime) -> int:
    """Picks that need a price check in this run (0 < minsToKick <= 90)."""
    return sum(1 for _, _, _, m in _candidates(now) if 0 < m <= CHECK_MAX_MIN)


def run(now: datetime, dry_run: bool = False) -> Dict[str, Dict[str, Any]]:
    """One live pass; returns {day: live dict} for the days that changed."""
    lives: Dict[str, Dict[str, Any]] = {}
    changed: Dict[str, set] = {}
    for day, pick, ko, mins in _candidates(now):
        key = _key(pick)
        live = lives.setdefault(day, load_live(day))
        if mins > WINDOW_AHEAD_MIN:
            continue                        # not in the live window (now-5, now+100] yet
        if 0 < mins <= CHECK_MAX_MIN:
            rec = live.setdefault(key, {'checks': []})
            c = check_pick(pick, day, rec, now, mins)
            changed.setdefault(day, set()).add(key)
            print(f"   {day} {key}: {c['minsToKick']} min to kick-off | best {c['best']} "
                  f"({c['bestSource']}, {c['books']} books) | close {c['quote']} "
                  f"{c['quoteSource']} {c['quoteMarket']} | avail {c.get('avail', '-')} "
                  f"age {c.get('availAgeMin', '-')}"
                  + (f" | WITHDRAWN {rec['withdrawKind']}: {rec['withdrawReason']}"
                     if rec.get('withdrawn') else ''))
        elif mins <= 0 and now - ko < FINALIZE_LOOKBACK:
            rec = live.get(key)
            if rec is None:
                rec = {'checks': []}
            if finalize(pick, rec):
                live[key] = rec
                changed.setdefault(day, set()).add(key)
                print(f"   {day} {key}: kicked off | closing {rec.get('closingOdds')} "
                      f"approx {rec.get('closingApprox', False)} | CLV {rec.get('clvPct')}")
    out = {d: lives[d] for d in changed}
    for d, live in out.items():
        if dry_run:
            print(f'--- dry run: results/top_live_{d}.json would change:')
            print(json.dumps({k: live[k] for k in sorted(changed[d])}, ensure_ascii=False, indent=1))
        else:
            print(f'   wrote {save_live(d, live)} ({len(changed[d])} records changed)')
    if not out:
        print('   no TOP pick in the live window')
    return out


def _parse_now(argv: List[str]) -> datetime:
    if '--now' in argv:
        i = argv.index('--now')
        v = argv[i + 1] if i + 1 < len(argv) else ''
        dt = pricing._parse_ts(v)
        if dt is None:
            raise SystemExit(f'bad --now {v!r} (ISO UTC expected)')
        return dt
    return datetime.now(timezone.utc)


def main(argv: List[str]) -> int:
    now = _parse_now(argv)
    if '--due' in argv:
        print(due(now))
        return 0
    print(f'TOP live {_iso(now)}' + (' (dry run)' if '--dry-run' in argv else ''))
    run(now, dry_run='--dry-run' in argv)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
