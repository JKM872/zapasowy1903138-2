"""Published TOP picks, settled against stored results, shaped for the website.

``results/top_<date>.json`` is exactly what was mailed that day, so this is the
honest record: no back-filled picks, no re-scored history. Each pick is settled
against ``outputs/result_store.json`` by date and team names.

The paywall lives here rather than in the UI: picks for matches that have not
been settled yet are withheld from non-subscribers on the server, so they
cannot be read out of the page source. Settled picks stay public — they are the
proof that the product works. A withdrawn pick is public at once (status and
reason) but its selection and prices stay locked until kick-off.

Freshness (design K8): Heroku only sees repo files after a deploy, so the last
two days' ``top_<day>.json`` and ``top_live_<day>.json`` (closing odds, CLV,
withdrawals written by tools/top_live.py) are read from raw.githubusercontent.com
with a short timeout and TTL, falling back to the slug copy on any error.

Record maths: the headline record is priced at ``odds2`` (hockey/basketball/
baseball 3-way quotes re-priced 2-way incl. OT, tools/pricing.py); the figure at
the published price is returned next to it as ``roiAsStored``. Withdrawn picks
are excluded from hit rate, ROI and bankroll, but count in CLV and in their own
tally.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools import pricing, staking  # noqa: E402

RESULTS_DIR = os.path.join(ROOT, 'results')
STORE_PATH = os.path.join(ROOT, 'outputs', 'result_store.json')
_TOP_RE = re.compile(r'top_(\d{4}-\d{2}-\d{2})\.json$')

logger = logging.getLogger(__name__)

# Raw GitHub copy of the newest days (public repo).
RAW_BASE = 'https://raw.githubusercontent.com/JKM872/zapasowy1903138-2/main/results/'
REMOTE_DAYS = 2
REMOTE_TIMEOUT_S = 3
REMOTE_TTL_S = 120
REMOTE_WARN_EVERY_S = 600
_MISS = object()
_remote_cache: Dict[str, Tuple[float, Any]] = {}
_remote_warned = {'at': 0.0}

BANKROLL_START = 100.0
SETTLED = ('won', 'lost', 'draw')
TWO_WAY_SPORTS = {'tennis', 'volleyball'}

# Removed from a withdrawn pick for non-subscribers until kick-off.
_LOCKED_FIELDS = ('pick', 'odds', 'odds2', 'oddsMarket', 'form', 'h2h', 'signals',
                  'availabilityNote', 'stakePct', 'floorOdds', 'segment', 'learnedDecision',
                  'bestOdds', 'bestOddsSource', 'bestOddsAt', 'booksCount',
                  'closingOdds', 'closingSource', 'closingAt', 'closingApprox',
                  'closingMarket', 'clvPct')

_store_cache: Dict[str, Any] = {'mtime': None, 'index': {}}
_odds_cache: Dict[str, Tuple[Optional[float], Dict[Tuple[str, str], Dict[str, Any]]]] = {}


def _norm(name: Any) -> str:
    s = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _store_index(path: str = STORE_PATH) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """(date, home, away) -> finished result. Rebuilt only when the file changes."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _store_cache['mtime'] == mtime and _store_cache.get('path') == path:
        return _store_cache['index']
    since = _first_top_day() if os.path.getsize(path) > STORE_STREAM_BYTES else ''
    index = {}
    try:
        for v in _iter_store_values(path):
            if (isinstance(v, dict) and v.get('status') == 'finished' and v.get('winner')
                    and str(v.get('date') or '') >= (since or '')):
                index[(v.get('date'), _norm(v.get('home_team')), _norm(v.get('away_team')))] = {
                    'winner': v.get('winner'), 'score_home': v.get('score_home'),
                    'score_away': v.get('score_away')}
    except (OSError, ValueError):
        return {}
    _store_cache.update(mtime=mtime, index=index, path=path)
    return index


# The store is ~80 MB of JSON. json.load of it took ~300 MB (more in a child
# process: the dyno quota counts every process), which pushed the 512 MB dyno
# into R14/R15. Entries are decoded one at a time instead, and only the few
# fields settle() needs are kept; a large store keeps only rows from the first
# published TOP day on (TOP settles nothing older).
STORE_STREAM_BYTES = 5 * 1024 * 1024


def _first_top_day() -> Optional[str]:
    days = [m.group(1) for p in glob.glob(os.path.join(RESULTS_DIR, 'top_*.json'))
            for m in [re.search(r'top_(\d{4}-\d{2}-\d{2})', os.path.basename(p))] if m]
    return min(days) if days else None


def _iter_store_values(path: str):
    """Values of the top-level store object, one entry in memory at a time.

    result_store.py writes ``json.dump(indent=1)``: each entry starts with
    ``\\n "key": {`` and ends with ``\\n }``. Any other layout falls back to a
    plain json.load (small test stores)."""
    with open(path, 'r', encoding='utf-8') as fh:
        if fh.readline().strip() != '{':
            fh.seek(0)
            data = json.load(fh)
            yield from (data.values() if isinstance(data, dict) else [])
            return
        buf: List[str] = []
        for line in fh:
            if not buf:
                if line.startswith(' "'):
                    _key, sep, rest = line.partition('": ')
                    if not sep:
                        raise ValueError('unexpected result_store layout')
                    if rest.rstrip().endswith('{'):
                        buf.append(rest)
                    else:
                        yield json.loads(rest.rstrip().rstrip(','))
                elif line.strip() not in ('}', ''):
                    raise ValueError('unexpected result_store layout')
                continue
            buf.append(line)
            if line.startswith(' }'):
                yield json.loads(''.join(buf).rstrip().rstrip(','))
                buf = []


def _split_match(match: str) -> Tuple[str, str]:
    parts = re.split(r'\s+vs\.?\s+', str(match or ''), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (str(match or ''), '')


def settle(day: str, pick: Dict[str, Any],
           index: Dict[Tuple[str, str, str], Dict[str, Any]]) -> Dict[str, Any]:
    """'won' / 'lost' / 'draw' / 'pending' for one published pick. Pure."""
    home, away = _split_match(pick.get('match'))
    picked = _norm(pick.get('pick'))
    side = 'home' if picked == _norm(home) else 'away' if picked == _norm(away) else None

    res = index.get((day, _norm(home), _norm(away)))
    flipped = False
    if not res:
        res = index.get((day, _norm(away), _norm(home)))
        flipped = bool(res)
    if not res or side is None:
        return {'status': 'pending'}

    winner = res.get('winner')
    if flipped:
        winner = {'home': 'away', 'away': 'home'}.get(winner, winner)
    sh, sa = res.get('score_home'), res.get('score_away')
    score = f'{sa}-{sh}' if flipped else f'{sh}-{sa}'
    if winner == 'draw':
        return {'status': 'draw', 'score': score}
    return {'status': 'won' if winner == side else 'lost', 'score': score}


# ---------------------------------------------------------------------------
# Summary: record, CLV, withdrawn tally, bankroll
# ---------------------------------------------------------------------------
def _status(p: Dict[str, Any]) -> str:
    return p.get('status') or (p.get('result') or {}).get('status') or 'pending'


def _price(p: Dict[str, Any]) -> Optional[float]:
    """Price used for money maths: 2-way equivalent when known, else as stored."""
    return p.get('odds2') or p.get('odds')


def _mean(xs: List[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 1) if xs else None


def _clv(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline over Pinnacle closes only; OddsSafari closes reported apart.
    Withdrawn picks count (they were published). Missing closes are excluded."""
    rows = [p for p in picks if _num(p.get('clvPct')) is not None]
    pin = [_num(p['clvPct']) for p in rows if p.get('closingSource') == 'pinnacle']
    osf = [_num(p['clvPct']) for p in rows if p.get('closingSource') == 'oddssafari']
    return {
        'avgPct': _mean(pin),
        'beatClosePct': round(sum(1 for x in pin if x > 0) / len(pin) * 100, 1) if pin else None,
        'n': len(pin),
        'since': min((p['date'] for p in rows), default=None),
        'nOddsSafari': len(osf),
        'avgPctOddsSafari': _mean(osf),
        'nApprox': sum(1 for p in rows if p.get('closingApprox')),
    }


def _summary(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Single place for the record (API and report). Withdrawn picks are
    excluded from hit rate / ROI and counted in ``withdrawn`` instead."""
    settled = [p for p in picks if _status(p) in SETTLED]
    won = [p for p in settled if _status(p) == 'won']
    withdrawn = [p for p in picks if _status(p) == 'withdrawn']
    n = len(settled)
    profit = sum((_price(p) or 0) for p in won) - n
    stored = sum((p.get('odds') or 0) for p in won) - n
    return {
        'picks': len(picks) - len(withdrawn),
        'settled': n,
        'won': len(won),
        'pending': sum(1 for p in picks if _status(p) == 'pending'),
        'hitRate': round(len(won) / n * 100, 1) if n else None,
        'roi': round(profit / n * 100, 1) if n else None,
        'profitUnits': round(profit, 2) if n else None,
        'roiAsStored': round(stored / n * 100, 1) if n else None,
        'profitUnitsAsStored': round(stored, 2) if n else None,
        # Settled picks with no 2-way conversion available (priced as stored).
        'pricedAsStored': sum(1 for p in settled if p.get('odds2') is None),
        'withdrawn': {
            'n': len(withdrawn),
            'availability': sum(1 for p in withdrawn if p.get('withdrawKind') == 'availability'),
            'price': sum(1 for p in withdrawn if p.get('withdrawKind') == 'price'),
        },
        'clv': _clv(picks),
    }


def _kick_sort(p: Dict[str, Any]) -> Tuple[str, str]:
    return (p.get('kickoffUtc') or f"{p['date']}T{p.get('time') or '00:00'}", p.get('match') or '')


def _bankroll(picks: List[Dict[str, Any]], start: float = BANKROLL_START) -> Dict[str, Any]:
    """Stake ``stakePct`` % of the current bankroll per settled pick, in
    kick-off order, profit at ``odds2``; plus a flat 1-unit curve on the same
    scale (1 unit = 1% of the start). Withdrawn and pending picks are skipped."""
    value = flat = peak = start
    mdd = 0.0
    points = []
    for p in sorted((p for p in picks if _status(p) in SETTLED), key=_kick_sort):
        o = _price(p) or 0
        stake = value * (_num(p.get('stakePct')) or staking.BASE_PCT) / 100
        if _status(p) == 'won':
            value += stake * (o - 1)
            flat += o - 1
        else:
            value -= stake
            flat -= 1
        peak = max(peak, value)
        if peak > 0:
            mdd = max(mdd, (peak - value) / peak * 100)
        points.append({'t': p.get('kickoffUtc') or p['date'],
                       'value': round(value, 2), 'flat': round(flat, 2)})
    return {'start': start, 'points': points, 'final': round(value, 2),
            'maxDrawdownPct': round(mdd, 1)}


def _forebet_settled(results_dir: str) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """The audit's own settlement of Forebet picks — same names as TOP, so it
    matches where the Livesport-named result store does not."""
    try:
        with open(os.path.join(results_dir, 'forebet_settled.json'), encoding='utf-8-sig') as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for key, v in raw.items():
        parts = key.split('|')
        if len(parts) == 4 and isinstance(v, dict) and v.get('status') == 'settled':
            score = str(v.get('score') or '')
            sh, _, sa = score.partition('-')
            out[(parts[0], _norm(parts[2]), _norm(parts[3]))] = {
                'winner': v.get('winner'), 'score_home': sh, 'score_away': sa}
    return out


# ---------------------------------------------------------------------------
# Inputs: slug files + raw GitHub for the newest days
# ---------------------------------------------------------------------------
def _read_json(path: str) -> Any:
    try:
        with open(path, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _http_get_json(url: str, timeout: float) -> Any:
    req = urllib.request.Request(url, headers={'User-Agent': 'pickly-top-feed'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return json.loads(resp.read().decode('utf-8-sig'))


def _warn_remote(msg: str) -> None:
    now = time.monotonic()
    if not _remote_warned['at'] or now - _remote_warned['at'] >= REMOTE_WARN_EVERY_S:
        _remote_warned['at'] = now
        logger.warning('%s; using the deployed copy', msg)


def _remote_json(name: str) -> Any:
    """Parsed ``results/<name>`` from raw GitHub, or _MISS. Cached REMOTE_TTL_S
    (misses too, so an outage costs one 3 s timeout per file per TTL)."""
    now = time.monotonic()
    hit = _remote_cache.get(name)
    if hit and now - hit[0] < REMOTE_TTL_S:
        return hit[1]
    try:
        data = _http_get_json(RAW_BASE + name, REMOTE_TIMEOUT_S)
    except Exception as e:                               # noqa: BLE001 - any failure -> slug
        _warn_remote(f'raw GitHub fetch of {name} failed ({type(e).__name__}: {e})')
        data = _MISS
    _remote_cache[name] = (now, data)
    return data


def _top_list(raw: Any) -> Optional[List[Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get('picks') or raw.get('top') or []
    return None


def _odds_index(results_dir: str, day: str, sport: str) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(home, away) -> 1X2 odds from the Forebet file TOP was built from."""
    path = os.path.join(results_dir, f'matches_{day}_{sport}_forebet.json')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _odds_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    raw = _read_json(path)
    rows = raw.get('matches') if isinstance(raw, dict) else raw
    idx = {}
    for m in rows if isinstance(rows, list) else []:
        if isinstance(m, dict) and isinstance(m.get('odds'), dict):
            idx[(_norm(m.get('homeTeam')), _norm(m.get('awayTeam')))] = m['odds']
    _odds_cache[path] = (mtime, idx)
    return idx


def _two_way(results_dir: str, day: str, r: Dict[str, Any],
             odds: Optional[float]) -> Tuple[Optional[float], Optional[str]]:
    """(odds2, oddsMarket) for a pick: stored fields first (C2+ picks), else
    derived. Hockey/basketball/baseball keep the published price and apply the
    2-way factor of the Forebet quote (side2/side); None when not derivable."""
    o2, market = _num(r.get('odds2')), r.get('oddsMarket')
    if o2 and market:
        return o2, market
    sport = r.get('sport')
    if odds is None:
        return None, None
    if sport in pricing.THREE_WAY_SPORTS:
        return odds, '3way'
    if sport in TWO_WAY_SPORTS:
        return odds, '2way'
    if sport not in pricing.TWO_WAY_EQUIV_SPORTS:
        return None, None
    home, away = _split_match(r.get('match'))
    picked = _norm(r.get('pick'))
    side = 'home' if picked == _norm(home) else 'away' if picked == _norm(away) else None
    q = _odds_index(results_dir, day, sport).get((_norm(home), _norm(away)))
    if not side or not q:
        return None, None
    s3 = _num(q.get(side))
    s2, mk = pricing.side_price(q, sport, side)
    if not s3 or not s2:
        return None, None
    if mk != '2way_equiv':
        return odds, mk
    return round(odds * s2 / s3, 3), mk


def _parse_utc(s: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _latest_avail(live: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    checks = [c for c in live.get('checks') or [] if isinstance(c, dict) and 'avail' in c]
    return checks[-1] if checks else None


def _entry(day: str, r: Dict[str, Any], live: Dict[str, Any], index, results_dir: str
           ) -> Dict[str, Any]:
    odds = _num(r.get('odds'))
    sport = r.get('sport') or 'unknown'
    odds2, market = _two_way(results_dir, day, r, odds)
    kick, approx = r.get('kickoffUtc'), r.get('kickoffApprox')
    if not kick:
        kick, approx = pricing.parse_kickoff(day, r.get('time'), sport=sport), True
    best = live.get('bestOdds') or r.get('bestOdds')
    src = live if live.get('bestOdds') else r
    stake = _num(r.get('stakePct'))
    if stake is None:
        stake = staking.stake_pct(r.get('grade'), r.get('pCal'), best or odds2 or odds)

    withdrawn = bool(r.get('withdrawn') or live.get('withdrawn'))
    w = r if r.get('withdrawn') else live
    if withdrawn:
        reason = w.get('withdrawReason') or ''
        result = {'status': 'withdrawn', 'reason': reason}
    else:
        result = settle(day, r, index)
    av = _latest_avail(live)
    return {
        'date': day, 'sport': sport, 'time': r.get('time') or '',
        'league': r.get('league') or '', 'match': r.get('match') or '',
        'pick': r.get('pick') or '', 'odds': odds, 'grade': r.get('grade') or '',
        'form': r.get('form') or '', 'h2h': r.get('h2h') or '',
        'signals': r.get('signals') or '',
        'result': result,
        'status': result['status'],
        'availabilityNote': r.get('availabilityNote') or '',
        'odds2': odds2, 'oddsMarket': market,
        'kickoffUtc': kick, 'kickoffApprox': bool(approx),
        'publishedAt': r.get('publishedAt'),
        'stakePct': stake,
        'floorOdds': _num(r.get('floorOdds')),
        'segment': r.get('segment'), 'rulesMode': r.get('rulesMode'),
        'learnedDecision': r.get('learnedDecision'),
        'bestOdds': _num(best), 'bestOddsSource': src.get('bestOddsSource'),
        'bestOddsAt': src.get('bestOddsAt'), 'booksCount': src.get('booksCount'),
        'closingOdds': _num(live.get('closingOdds')), 'closingSource': live.get('closingSource'),
        'closingAt': live.get('closingAt'), 'closingApprox': bool(live.get('closingApprox')),
        'closingMarket': live.get('closingMarket'), 'clvPct': _num(live.get('clvPct')),
        'withdrawReason': (w.get('withdrawReason') or '') if withdrawn else None,
        'withdrawKind': (w.get('withdrawKind') or 'availability') if withdrawn else None,
        'withdrawnAt': w.get('withdrawnAt') if withdrawn else None,
        # Last line-up check by the live job (none = "Line-ups unverified").
        'availStatus': av.get('avail') if av else None,
        'availMinsToKick': av.get('minsToKick') if av else None,
        'availAgeMin': av.get('availAgeMin') if av else None,
        'finalCheckMissed': live.get('finalCheckMissed'),
    }


def _locked_view(p: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """What a non-subscriber sees: None = hidden (pending); withdrawn before
    kick-off = status + reason without selection or prices."""
    st = p['status']
    if st == 'pending':
        return None
    if st == 'withdrawn':
        kick = _parse_utc(p.get('kickoffUtc'))
        if kick is None:
            kick = _parse_utc(f"{p['date']}T00:00:00Z") + timedelta(days=2)
        if now < kick:
            v = {k: val for k, val in p.items() if k not in _LOCKED_FIELDS}
            v['selectionLocked'] = True
            return v
    return p


def _remote_auto(results_dir: str) -> bool:
    return (os.path.abspath(results_dir) == os.path.abspath(RESULTS_DIR)
            and os.environ.get('TOP_FEED_REMOTE', '1') != '0')


def load_top(results_dir: str = RESULTS_DIR, store_path: str = STORE_PATH,
             is_subscriber: bool = False, remote: Optional[bool] = None,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every published TOP day, newest first, settled and paywalled.

    ``remote`` (default: only for the deployed results dir) reads the last
    REMOTE_DAYS days from raw GitHub, slug copy on any error."""
    now = now or datetime.now(timezone.utc)
    if remote is None:
        remote = _remote_auto(results_dir)
    # Audit settlement first (Forebet names), result store as fallback.
    index = {**_store_index(store_path), **_forebet_settled(results_dir)}

    day_paths = {}
    for path in glob.glob(os.path.join(results_dir, 'top_*.json')):
        m = _TOP_RE.search(os.path.basename(path))
        if m:
            day_paths[m.group(1)] = path
    recent = {(now.date() - timedelta(days=i)).isoformat() for i in range(REMOTE_DAYS)}
    days_all = set(day_paths) | (recent if remote else set())

    days: List[Dict[str, Any]] = []
    everything: List[Dict[str, Any]] = []
    by_sport: Dict[str, List[Dict[str, Any]]] = {}

    for day in sorted(days_all, reverse=True):
        raw = None
        live_raw = None
        if remote and day in recent:
            got = _remote_json(f'top_{day}.json')
            raw = _top_list(got) if got is not _MISS else None
            got = _remote_json(f'top_live_{day}.json')
            live_raw = got if isinstance(got, dict) else None
        if raw is None and day in day_paths:
            raw = _top_list(_read_json(day_paths[day]))
        if raw is None:
            continue
        if live_raw is None:
            live_raw = _read_json(os.path.join(results_dir, f'top_live_{day}.json'))
        live_raw = live_raw if isinstance(live_raw, dict) else {}

        picks = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            live = live_raw.get(f"{r.get('sport')}|{r.get('match')}")
            entry = _entry(day, r, live if isinstance(live, dict) else {}, index, results_dir)
            picks.append(entry)
            everything.append(entry)
            by_sport.setdefault(entry['sport'], []).append(entry)

        # Paywall: an unsettled pick is the thing being sold.
        visible = []
        locked = 0
        for p in picks:
            v = p if is_subscriber else _locked_view(p, now)
            if v is None:
                locked += 1
            else:
                visible.append(v)
        days.append({'date': day, 'summary': _summary(picks),
                     'picks': visible, 'locked': locked})

    summary = _summary(everything)
    summary['bankroll'] = _bankroll(everything)
    return {
        'days': days,
        'summary': summary,
        'bySport': {s: _summary(v) for s, v in sorted(by_sport.items(), key=lambda kv: -len(kv[1]))},
        'isSubscriber': is_subscriber,
    }
