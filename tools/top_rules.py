"""Data-driven TOP rules (design K1): learn segment decisions on a tuning window,
report before/after on a holdout window the learner never reads.

Usage:
  python tools/top_rules.py --build --report [--tuning-end YYYY-MM-DD]

* ``load_learning_rows(tuning_end)`` filters EVERY source (Forebet files,
  Livesport files, result_store, forebet_settled) to ``date <= tuning_end``
  before dedupe; ``load_holdout_rows`` is used only by ``--report``/the window.
* Segment hierarchy (most specific first): sport|band|side -> sport|band ->
  sport|grade -> sport. n >= 50: allow iff ROI(-5%) > 0 and both tuning halves
  >= 0, else exclude; n < 50: inherit (top level ``sport`` -> exclude).
  ``sport|grade:X`` / ``sport|tier:T`` excludes always apply.
* Allowed segments carry ``pCal`` (Beta-shrunk hit rate, weight 2 toward the
  parent) and ``floorOdds`` = max(break-even after 5% haircut, band lower edge).
* ``load()`` validates outputs/top_rules.json; on any problem it logs
  ``WARNING rules fallback: <reason>`` once and returns the built-in safe gate.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import league_tier, pricing  # noqa: E402

VERSION = 1
TUNING_START = '2026-09-12'
MIN_N = 50
MIN_HOLDOUT_DAYS = 14
MAX_AGE_DAYS = 21
SHRINK = 2
BOOTSTRAP = 1000
BANDS = [1.0, 1.4, 1.6, 1.8, 2.0, 2.5]
GRADES = ('A', 'B', 'C')
DECISIONS = {'allow', 'exclude', 'inherit'}
FALLBACK_EXCLUDE = {'tennis': 1.8, 'basketball': 1.8}   # odds2 below -> excluded
RULES_PATH = os.path.join(ROOT, 'outputs', 'top_rules.json')
REPORT_MD = os.path.join(ROOT, 'outputs', 'top_rules_report.md')
REPORT_JSON = os.path.join(ROOT, 'outputs', 'top_rules_report.json')
RECENCY_FLAGS = ('earlySeason', 'staleModel', 'seasonFormConflict')
LEVELS = ('sport×band×side', 'sport×band', 'sport×grade', 'sport×tier', 'sport')


# ── helpers ────────────────────────────────────────────────────────────────

def fold(s: Any) -> str:
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]', '', s)


def band(o: Optional[float]) -> Optional[str]:
    if not o or o < BANDS[0]:
        return None
    for lo, hi in zip(BANDS, BANDS[1:]):
        if lo <= o < hi:
            return f'{lo:.1f}-{hi:.1f}'
    return f'{BANDS[-1]:.1f}+'


def band_lower(label: str) -> float:
    return float(label.rstrip('+').split('-')[0])


def _float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _iso_day(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── settlement (same joins as the audit baseline) ───────────────────────────

_STORE_CACHE: Dict[str, Dict[str, Any]] = {}


def _store(root: str) -> Dict[str, Any]:
    p = os.path.join(root, 'outputs', 'result_store.json')
    if p not in _STORE_CACHE:
        try:
            _STORE_CACHE[p] = json.load(open(p, encoding='utf-8-sig'))
        except (OSError, ValueError):
            _STORE_CACHE[p] = {}
    return _STORE_CACHE[p]


class Settler:
    """Winner lookup; only uses result entries dated <= ``max_day`` when set."""

    def __init__(self, root: str, max_day: Optional[str] = None):
        ok = (lambda d: str(d or '')[:10] <= max_day) if max_day else (lambda d: True)
        self.by_url: Dict[str, Dict[str, Any]] = {}
        self.by_name: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for u, v in _store(root).items():
            if not isinstance(v, dict) or not ok(v.get('date')):
                continue
            self.by_url[u.split('?mid=')[-1] if '?mid=' in u else u] = v
            self.by_name[(v.get('date'), fold(v.get('home_team')), fold(v.get('away_team')))] = v
        self.fsi: Dict[Tuple[str, str, str], str] = {}
        try:
            fs = json.load(open(os.path.join(root, 'results', 'forebet_settled.json'),
                                encoding='utf-8-sig'))
        except (OSError, ValueError):
            fs = {}
        for k, v in fs.items():
            p = k.split('|')
            if len(p) == 4 and isinstance(v, dict) and v.get('status') == 'settled' and ok(p[0]):
                self.fsi[(p[0], fold(p[2]), fold(p[3]))] = v.get('winner')

    def winner(self, day: str, m: Dict[str, Any]) -> Optional[str]:
        u = m.get('matchUrl') or ''
        if '?mid=' in u:
            v = self.by_url.get(u.split('?mid=')[-1])
            if v:
                return v.get('winner')
        h, a = fold(m.get('homeTeam')), fold(m.get('awayTeam'))
        if (day, h, a) in self.fsi:
            return self.fsi[(day, h, a)]
        v = self.by_name.get((day, h, a))
        if v:
            return v.get('winner')
        v = self.by_name.get((day, a, h))
        if v:
            return {'home': 'away', 'away': 'home'}.get(v.get('winner'), v.get('winner'))
        return None


# ── rows ───────────────────────────────────────────────────────────────────

def _files(root: str, lo: Optional[str], hi: Optional[str],
           sources: Iterable[str]) -> List[Tuple[str, str, str, str]]:
    """(day, sport, src, path) with lo < day <= hi, Forebet files first."""
    out = []
    for f in glob.glob(os.path.join(root, 'results', 'matches_*.json')):
        mm = re.match(r'matches_(\d{4}-\d{2}-\d{2})_(.+)\.json$', os.path.basename(f))
        if not mm:
            continue
        day, rest = mm.group(1), mm.group(2)
        if rest.startswith('table_tennis') or rest == 'all':
            continue
        src = 'forebet' if rest.endswith('_forebet') else 'livesport'
        if src not in sources or (lo and day <= lo) or (hi and day > hi):
            continue
        out.append((day, rest[:-len('_forebet')] if src == 'forebet' else rest, src, f))
    return sorted(out, key=lambda x: (x[2] != 'forebet', x[0], x[1]))


def structural(m: Dict[str, Any]) -> bool:
    """Structural parts of top_picks.evaluate(): recency flags, pick agreement, favourite."""
    if any(m.get(k) for k in RECENCY_FLAGS):
        return False
    pick = (m.get('scoring') or {}).get('pick')
    if pick not in ('1', '2') or (m.get('forebet') or {}).get('prediction') != pick:
        return False
    me, op = ('home', 'away') if pick == '1' else ('away', 'home')
    odds = m.get('odds') or {}
    o_me, o_op = _float(odds.get(me)), _float(odds.get(op))
    return bool(o_me and o_op and o_me <= o_op)


def _row(day: str, sport: str, src: str, m: Dict[str, Any], tp) -> Optional[Dict[str, Any]]:
    g = m.get('predictionGrade')
    if not g or not m.get('qualifies'):
        return None
    pick = (m.get('scoring') or {}).get('pick')
    if pick not in ('1', '2'):
        return None
    side, opp = ('home', 'away') if pick == '1' else ('away', 'home')
    odds = m.get('odds') or {}
    o, oo = _float(odds.get(side)), _float(odds.get(opp))
    if not o or not oo:
        return None
    o2, market = pricing.side_price(odds, sport, side)
    if not o2:
        return None
    top = False
    if src == 'forebet' and tp is not None and g in tp.DEFAULT_GRADES:
        try:
            top = bool(tp.evaluate(m, sport))
        except Exception:
            top = False
    return {'day': day, 'time': m.get('time') or '', 'sport': sport, 'src': src, 'grade': g,
            'side': side, 'odds': o, 'odds2': o2, 'market': market, 'band': band(o2),
            'tier': league_tier.tier(m, sport), 'struct': src == 'forebet' and structural(m),
            'top': top, 'home': m.get('homeTeam'), 'away': m.get('awayTeam'),
            'key': f"{day}|{sport}|{fold(m.get('homeTeam'))}|{fold(m.get('awayTeam'))}"}


def _load_rows(root: str, lo: Optional[str], hi: Optional[str], settle_max: Optional[str],
               sources: Iterable[str], start: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        from tools import top_picks as tp        # lazy: top_picks imports this module
    except Exception:
        tp = None
    settler = Settler(root, settle_max)
    rows, seen = [], set()
    for day, sport, src, path in _files(root, lo, hi, tuple(sources)):
        if start and src == 'forebet' and day < start:
            continue
        try:
            d = json.load(open(path, encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        ms = d.get('matches', []) if isinstance(d, dict) else d
        for m in ms if isinstance(ms, list) else []:
            if not isinstance(m, dict):
                continue
            r = _row(day, sport, src, m, tp)
            if not r or r['key'] in seen:          # dedupe: first source wins
                continue
            seen.add(r['key'])
            w = settler.winner(day, m)
            if w is None:
                continue
            r['won'], r['draw'] = (w == r['side']), (w == 'draw')
            rows.append(r)
    return rows


def load_learning_rows(tuning_end: str, root: str = ROOT,
                       sources: Iterable[str] = ('forebet', 'livesport')) -> List[Dict[str, Any]]:
    """All learning rows with date <= tuning_end; every source filtered before dedupe."""
    return _load_rows(root, None, tuning_end, tuning_end, sources, start=TUNING_START)


def load_holdout_rows(tuning_end: str, root: str = ROOT,
                      sources: Iterable[str] = ('forebet',)) -> List[Dict[str, Any]]:
    """Rows dated after tuning_end (report only; never passed to build_rules)."""
    return _load_rows(root, tuning_end, None, None, sources)


def learning_universe(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Forebet-era candidates TOP could publish (structural gates, grade A/B/C)."""
    return [r for r in rows if r['src'] == 'forebet' and r['struct'] and r['grade'] in GRADES]


# ── stats ──────────────────────────────────────────────────────────────────

def _profit(r: Dict[str, Any], price: str = 'odds2', haircut: bool = True) -> float:
    o = r[price]
    if haircut:
        return pricing.haircut_profit(o, r['won'])
    return (o - 1) if r['won'] else -1.0


def _roi(rs: List[Dict[str, Any]], price: str = 'odds2', haircut: bool = True) -> Optional[float]:
    return 100 * sum(_profit(r, price, haircut) for r in rs) / len(rs) if rs else None


def _rnd(x: Optional[float], k: int = 1) -> Optional[float]:
    return None if x is None else round(x, k)


def segment_keys(sport: str, b: Optional[str], side: str, grade: str,
                 tier: Optional[str]) -> Dict[str, str]:
    return {'sport×band×side': f'{sport}|{b}|{side}', 'sport×band': f'{sport}|{b}',
            'sport×grade': f'{sport}|grade:{grade}', 'sport×tier': f'{sport}|tier:{tier}',
            'sport': sport}


def _parent(level: str, keys: Dict[str, str]) -> Optional[str]:
    return {'sport×band×side': keys['sport×band'], 'sport×band': keys['sport'],
            'sport×grade': keys['sport'], 'sport×tier': keys['sport']}.get(level)


def build_rules(rows: List[Dict[str, Any]], tuning_end: str,
                holdout: Optional[Dict[str, Any]] = None,
                generated_at: Optional[str] = None,
                git_sha: Optional[str] = None) -> Dict[str, Any]:
    """Rules from learning rows only (rows dated after tuning_end are ignored)."""
    uni = [r for r in learning_universe(rows) if r['day'] <= tuning_end]
    if not uni:
        raise ValueError('no learning rows in the tuning window')
    days = sorted(r['day'] for r in uni)
    mid = days[len(days) // 2]
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    level_of: Dict[str, str] = {}
    parent_of: Dict[str, Optional[str]] = {}
    for r in uni:
        keys = segment_keys(r['sport'], r['band'], r['side'], r['grade'], r['tier'])
        for lvl, k in keys.items():
            groups[k].append(r)
            level_of[k] = lvl
            parent_of[k] = _parent(lvl, keys)
    p_all = sum(r['won'] for r in uni) / len(uni)
    hit = {k: sum(r['won'] for r in v) / len(v) for k, v in groups.items()}
    segs: Dict[str, Dict[str, Any]] = {}
    for k in sorted(groups):
        rs, lvl = groups[k], level_of[k]
        n = len(rs)
        roi = _roi(rs)
        h1 = _roi([r for r in rs if r['day'] < mid])
        h2 = _roi([r for r in rs if r['day'] >= mid])
        if n >= MIN_N:
            ok = roi > 0 and h1 is not None and h1 >= 0 and h2 is not None and h2 >= 0
            decision = 'allow' if ok else 'exclude'
        else:
            decision = 'exclude' if lvl == 'sport' else 'inherit'
        s = {'level': lvl, 'n': n, 'hit': _rnd(100 * hit[k]), 'roi': _rnd(roi),
             'roiRaw': _rnd(_roi(rs, haircut=False)), 'h1': _rnd(h1), 'h2': _rnd(h2),
             'decision': decision}
        if decision == 'allow':
            wins = sum(r['won'] for r in rs)
            p_parent = hit.get(parent_of[k], p_all) if parent_of[k] else p_all
            p = min(0.99, max(0.01, (wins + SHRINK * p_parent) / (n + SHRINK)))
            floor = pricing.floor_price(p)
            if lvl in ('sport×band×side', 'sport×band'):
                floor = max(floor, band_lower(k.split('|')[1]))
            s['pCal'] = round(p, 3)
            s['floorOdds'] = round(min(20.0, max(1.01, floor)), 2)
        segs[k] = s
    return {
        'version': VERSION,
        'generatedAt': generated_at or _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'gitSha': git_sha or '',
        'tuning': {'start': days[0], 'end': tuning_end, 'halfSplit': mid, 'n': len(uni)},
        'holdout': holdout or {},
        'haircut': pricing.HAIRCUT, 'minN': MIN_N, 'bands': BANDS,
        'twoWayEquivSports': sorted(pricing.TWO_WAY_EQUIV_SPORTS),
        'segments': segs,
        'defaults': {'decision': 'exclude', 'stakePct': 1.0},
    }


def decide(rules: Dict[str, Any], sport: str, odds2: Optional[float], side: str,
           grade: str, tier: Optional[str] = None) -> Dict[str, Any]:
    """{'decision': allow|exclude, 'segment', 'floorOdds', 'pCal', 'fallback'}."""
    if rules.get('fallback'):
        lim = FALLBACK_EXCLUDE.get(sport)
        ok = not (lim and (odds2 or 0) < lim)
        return {'decision': 'allow' if ok else 'exclude', 'segment': 'fallback',
                'floorOdds': 1.0, 'pCal': None, 'fallback': True}
    segs = rules.get('segments') or {}
    keys = segment_keys(sport, band(odds2), side, grade, tier)
    chosen = None
    for lvl in ('sport×band×side', 'sport×band', 'sport×grade', 'sport'):
        s = segs.get(keys[lvl])
        if s and s.get('decision') != 'inherit':
            chosen = (keys[lvl], s)
            break
    if chosen is None:
        return {'decision': (rules.get('defaults') or {}).get('decision', 'exclude'),
                'segment': None, 'floorOdds': None, 'pCal': None, 'fallback': False}
    k, s = chosen
    if s['decision'] == 'allow':
        for lvl in ('sport×grade', 'sport×tier'):
            if (segs.get(keys[lvl]) or {}).get('decision') == 'exclude':
                return {'decision': 'exclude', 'segment': keys[lvl], 'floorOdds': None,
                        'pCal': None, 'fallback': False}
    return {'decision': s['decision'], 'segment': k, 'floorOdds': s.get('floorOdds'),
            'pCal': s.get('pCal'), 'fallback': False}


# ── load + validation ─────────────────────────────────────────────────────

_CACHE: Dict[str, Dict[str, Any]] = {}
_WARNED: set = set()


def validate(data: Any, now: Optional[datetime] = None) -> Optional[str]:
    """None when valid, else a short reason."""
    if not isinstance(data, dict):
        return 'not an object'
    if data.get('version') != VERSION:
        return f"unknown version {data.get('version')!r}"
    try:
        gen = datetime.fromisoformat(str(data.get('generatedAt')).replace('Z', '+00:00'))
    except ValueError:
        return 'bad generatedAt'
    if gen.tzinfo is None:
        gen = gen.replace(tzinfo=timezone.utc)
    if ((now or _now()) - gen) > timedelta(days=MAX_AGE_DAYS):
        return f"stale (generatedAt {data.get('generatedAt')})"
    tun, hol = data.get('tuning') or {}, data.get('holdout') or {}
    ds = [_iso_day(x) for x in (tun.get('start'), tun.get('end'), hol.get('start'), hol.get('end'))]
    if any(d is None for d in ds):
        return 'bad tuning/holdout dates'
    if not ds[1] < ds[2]:
        return 'tuning.end must be before holdout.start'
    segs = data.get('segments')
    if not isinstance(segs, dict):
        return 'segments missing'
    for k, s in segs.items():
        if not isinstance(s, dict) or s.get('decision') not in DECISIONS:
            return f'bad segment {k}'
        if s['decision'] == 'allow' and ('floorOdds' not in s or 'pCal' not in s):
            return f'allowed segment {k} without floorOdds/pCal'
        for f, lo, hi in (('floorOdds', 1.01, 20), ('pCal', 0.01, 0.99), ('stakePct', 1, 2)):
            if f in s and not (isinstance(s[f], (int, float)) and lo <= s[f] <= hi):
                return f'segment {k} {f} out of range'
    dfl = data.get('defaults') or {}
    if dfl.get('decision') not in ('allow', 'exclude'):
        return 'bad defaults.decision'
    if not (isinstance(dfl.get('stakePct'), (int, float)) and 1 <= dfl['stakePct'] <= 2):
        return 'bad defaults.stakePct'
    return None


def fallback(reason: str) -> Dict[str, Any]:
    return {'version': VERSION, 'fallback': True, 'reason': reason, 'segments': {},
            'defaults': {'decision': 'allow', 'stakePct': 1.0},
            'fallbackExclude': dict(FALLBACK_EXCLUDE), 'floorOdds': 1.0}


def load(path: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Validated rules file, or the built-in fallback (never raises)."""
    p = path or RULES_PATH
    if now is None and p in _CACHE:
        return _CACHE[p]
    try:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
        reason = validate(data, now)
    except FileNotFoundError:
        data, reason = None, 'file missing'
    except (OSError, ValueError) as e:
        data, reason = None, f'invalid JSON ({type(e).__name__})'
    res = fallback(reason) if reason else data
    if reason and reason not in _WARNED:
        _WARNED.add(reason)
        print(f'WARNING rules fallback: {reason}', file=sys.stderr, flush=True)
    if now is None:
        _CACHE[p] = res
    return res


# ── report ────────────────────────────────────────────────────────────────

def _max_dd(rs: List[Dict[str, Any]], price: str) -> float:
    cum = peak = dd = 0.0
    for r in sorted(rs, key=lambda r: (r['day'], r['time'])):
        cum += _profit(r, price)
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return round(dd, 2)


def _ci(rs: List[Dict[str, Any]], price: str, rng: random.Random) -> Optional[List[float]]:
    if len(rs) < 2:
        return None
    pr = [_profit(r, price) for r in rs]
    n = len(pr)
    sims = sorted(100 * sum(rng.choices(pr, k=n)) / n for _ in range(BOOTSTRAP))
    return [round(sims[int(0.025 * BOOTSTRAP)], 1), round(sims[int(0.975 * BOOTSTRAP) - 1], 1)]


def metrics(rs: List[Dict[str, Any]], price: str = 'odds2', days: int = 1,
            rng: Optional[random.Random] = None) -> Dict[str, Any]:
    if not rs:
        return {'n': 0, 'hit': None, 'roiRaw': None, 'roi5': None, 'maxDD': 0.0,
                'perDay': 0.0, 'ci95': None}
    out = {'n': len(rs), 'hit': _rnd(100 * sum(r['won'] for r in rs) / len(rs)),
           'roiRaw': _rnd(_roi(rs, price, haircut=False)), 'roi5': _rnd(_roi(rs, price)),
           'maxDD': _max_dd(rs, price), 'perDay': round(len(rs) / max(1, days), 1)}
    if rng is not None:
        out['ci95'] = _ci(rs, price, rng)
    return out


def _allowed(rules: Dict[str, Any], r: Dict[str, Any]) -> bool:
    d = decide(rules, r['sport'], r['odds2'], r['side'], r['grade'], r['tier'])
    return d['decision'] == 'allow' and r['odds2'] >= (d['floorOdds'] or 1.0)


def _published(root: str, lo: str, hold: List[Dict[str, Any]], days: int) -> Dict[str, Any]:
    """Published results/top_<day>.json picks in the holdout window joined to holdout rows."""
    idx = {(r['day'], r['sport'], fold(r['home']), fold(r['away'])): r for r in hold}
    joined, n = [], 0
    for p in sorted(glob.glob(os.path.join(root, 'results', 'top_*.json'))):
        day = os.path.basename(p)[4:-5]
        if not re.match(r'\d{4}-\d{2}-\d{2}$', day) or day <= lo:
            continue
        try:
            picks = json.load(open(p, encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        for t in picks if isinstance(picks, list) else []:
            if t.get('withdrawn'):
                continue
            n += 1
            h, _, a = str(t.get('match') or '').partition(' vs ')
            r = idx.get((day, t.get('sport'), fold(h), fold(a)))
            if r:
                joined.append(r)
    return {'published': n, 'joined': len(joined),
            'asStored': metrics(joined, 'odds', days), 'twoWay': metrics(joined, 'odds2', days)}


def _supabase_count(lo: str, hi: str) -> Dict[str, Any]:
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    if not url or not key:
        return {'skipped': 'SUPABASE_URL / key not set'}
    try:
        import requests
        r = requests.head(f'{url}/rest/v1/predictions',
                          params={'select': 'id', 'match_date': [f'gte.{lo}', f'lte.{hi}'],
                                  'actual_result': 'not.is.null'},
                          headers={'apikey': key, 'Authorization': f'Bearer {key}',
                                   'Prefer': 'count=exact', 'Range': '0-0'}, timeout=20)
        total = (r.headers.get('content-range') or '').split('/')[-1]
        return {'settledPredictions': int(total)} if total.isdigit() else {'skipped': f'HTTP {r.status_code}'}
    except Exception as e:
        print(f'WARNING supabase cross-check skipped: {type(e).__name__}', file=sys.stderr)
        return {'skipped': type(e).__name__}


def build_report(rules: Dict[str, Any], learn: List[Dict[str, Any]], hold: List[Dict[str, Any]],
                 tuning_end: str, holdout_end: str, root: str = ROOT) -> Dict[str, Any]:
    days = (date.fromisoformat(holdout_end) - date.fromisoformat(tuning_end)).days
    rng = random.Random(20261010)
    hold_fb = [r for r in hold if r['src'] == 'forebet' and r['day'] > tuning_end]
    universes = {'candidates': learning_universe(hold_fb),
                 'topReplay': [r for r in hold_fb if r['top']]}
    out: Dict[str, Any] = {}
    for name, rs in universes.items():
        after = [r for r in rs if _allowed(rules, r)]
        u: Dict[str, Any] = {}
        for price, label in (('odds2', 'twoWay'), ('odds', 'asStored')):
            per = {}
            for sp in sorted({r['sport'] for r in rs}):
                per[sp] = {'before': metrics([r for r in rs if r['sport'] == sp], price, days),
                           'after': metrics([r for r in after if r['sport'] == sp], price, days)}
            u[label] = {'before': metrics(rs, price, days, rng if price == 'odds2' else None),
                        'after': metrics(after, price, days, rng if price == 'odds2' else None),
                        'perSport': per}
        out[name] = u
    ls = [r for r in learn if r['src'] == 'livesport' and r['day'] <= tuning_end]
    segs = rules.get('segments') or {}
    count = defaultdict(int)
    for s in segs.values():
        count[s['decision']] += 1
    return {
        'generatedAt': _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'rulesFallback': rules.get('reason') if rules.get('fallback') else None,
        'tuning': rules.get('tuning'), 'holdout': {'start': (date.fromisoformat(tuning_end)
                                                             + timedelta(days=1)).isoformat(),
                                                   'end': holdout_end, 'days': days},
        'decisions': dict(count),
        'universes': out,
        'published': _published(root, tuning_end, hold_fb, days),
        'livesportContext': {sp: metrics([r for r in ls if r['sport'] == sp])
                             for sp in sorted({r['sport'] for r in ls})},
        'supabase': _supabase_count(TUNING_START, tuning_end),
    }


def _fmt(x: Any, sign: bool = True) -> str:
    if x is None:
        return '—'
    return f'{x:+.1f}%' if sign else f'{x:.1f}%'


def _mrow(label: str, m: Dict[str, Any]) -> str:
    ci = m.get('ci95')
    return (f"| {label} | {m['n']} | {m['perDay']} | {_fmt(m['hit'], False)} | {_fmt(m['roiRaw'])} | "
            f"{_fmt(m['roi5'])} | {'—' if not ci else f'{ci[0]:+.1f} .. {ci[1]:+.1f}'} | {m['maxDD']} |")


def report_md(rep: Dict[str, Any], rules: Dict[str, Any]) -> str:
    t, h = rep['tuning'] or {}, rep['holdout']
    L = ['# TOP rules – holdout report', '',
         f"Generated {rep['generatedAt']}. Tuning {t.get('start')}..{t.get('end')} (n={t.get('n')}, "
         f"halves split at {t.get('halfSplit')}); holdout {h['start']}..{h['end']} ({h['days']} days). "
         'The learner never reads holdout rows. Flat 1u, draw = loss, ROI −5% = profit × 0.95; '
         'hockey/basketball/baseball 3-way quotes re-priced to the 2-way equivalent ("2-way"); '
         '"as stored" = published prices. Max DD in units at −5%. CI = bootstrap 95% (1000×) of ROI −5%.',
         '']
    if rep.get('rulesFallback'):
        L += [f"**Rules fallback in use: {rep['rulesFallback']}**", '']
    L += [f"Segment decisions: {rep['decisions']}", '']
    hdr = '| set | n | picks/day | hit | ROI raw | ROI −5% | CI ROI −5% | max DD |\n|---|---|---|---|---|---|---|---|'
    titles = {'candidates': 'Candidates TOP could publish (structural gates, grade A/B/C)',
              'topReplay': 'TOP replay (current evaluate())'}
    for name, u in rep['universes'].items():
        L += [f'## {titles[name]}', '']
        for label, title in (('twoWay', '2-way prices'), ('asStored', 'as stored')):
            L += [f'### {title}', '', hdr, _mrow('before', u[label]['before']),
                  _mrow('after (rules + floor)', u[label]['after']), '',
                  '| sport | before n | before hit | before ROI raw | before ROI −5% | after n | after hit | after ROI raw | after ROI −5% |',
                  '|---|---|---|---|---|---|---|---|---|']
            for sp, x in u[label]['perSport'].items():
                b, a = x['before'], x['after']
                L.append(f"| {sp} | {b['n']} | {_fmt(b['hit'], False)} | {_fmt(b['roiRaw'])} | {_fmt(b['roi5'])} | "
                         f"{a['n']} | {_fmt(a['hit'], False)} | {_fmt(a['roiRaw'])} | {_fmt(a['roi5'])} |")
            L.append('')
    p = rep['published']
    L += ['## Published TOP files in the holdout window', '',
          f"{p['published']} published (not withdrawn), {p['joined']} joined to settled holdout rows.", '',
          hdr, _mrow('as stored', p['asStored']), _mrow('2-way', p['twoWay']), '']
    L += ['## Rules (tuning window, non-inherit segments)', '',
          '| segment | level | n | hit | ROI −5% | H1 | H2 | decision | pCal | floor |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for k, s in sorted((rules.get('segments') or {}).items()):
        if s['decision'] == 'inherit':
            continue
        L.append(f"| {k} | {s['level']} | {s['n']} | {_fmt(s['hit'], False)} | {_fmt(s['roi'])} | "
                 f"{_fmt(s['h1'])} | {_fmt(s['h2'])} | {s['decision']} | {s.get('pCal', '—')} | "
                 f"{s.get('floorOdds', '—')} |")
    L += ['', '## Context (not used for decisions)', '',
          'Livesport-era qualified graded rows up to tuning.end (older engine, grade semantics differ):', '',
          '| sport | n | hit | ROI −5% |', '|---|---|---|---|']
    for sp, m in rep['livesportContext'].items():
        L.append(f"| {sp} | {m['n']} | {_fmt(m['hit'], False)} | {_fmt(m['roi5'])} |")
    L += ['', f"Supabase cross-check (settled predictions in tuning window): {rep['supabase']}", '']
    return '\n'.join(L)


# ── CLI ───────────────────────────────────────────────────────────────────

def _git_sha(root: str) -> str:
    try:
        return subprocess.run(['git', '-C', root, 'rev-parse', '--short', 'HEAD'],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ''


def _write_json(path: str, data: Any) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    os.replace(tmp, path)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--tuning-end', default=None)
    ap.add_argument('--root', default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not (a.build or a.report):
        ap.error('nothing to do: pass --build and/or --report')
    te = a.tuning_end or (_now().date() - timedelta(days=17)).isoformat()
    if _iso_day(te) is None:
        print(f'ERROR bad --tuning-end {te!r}', file=sys.stderr)
        return 1
    root = a.root
    rules_p = os.path.join(root, 'outputs', 'top_rules.json')
    hold = load_holdout_rows(te, root)
    hold_days = sorted({r['day'] for r in hold})
    if not hold_days:
        print('ERROR no settled holdout rows – old rules file kept', file=sys.stderr)
        return 1
    hs, he = (date.fromisoformat(te) + timedelta(days=1)).isoformat(), hold_days[-1]
    n_days = (date.fromisoformat(he) - date.fromisoformat(hs)).days + 1
    if not hs > te or n_days < MIN_HOLDOUT_DAYS:
        print(f'ERROR holdout {hs}..{he} is {n_days} days (< {MIN_HOLDOUT_DAYS}) – old rules file kept',
              file=sys.stderr)
        return 1
    learn = load_learning_rows(te, root)
    if a.build:
        try:
            rules = build_rules(learn, te, git_sha=_git_sha(root), holdout={
                'start': hs, 'end': he, 'n': len(learning_universe(hold))})
        except ValueError as e:
            print(f'ERROR {e} – old rules file kept', file=sys.stderr)
            return 1
        reason = validate(rules)
        if reason:
            print(f'ERROR built rules invalid ({reason}) – old rules file kept', file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(rules_p), exist_ok=True)
        _write_json(rules_p, rules)
        c = defaultdict(int)
        for s in rules['segments'].values():
            c[s['decision']] += 1
        print(f"rules: tuning {rules['tuning']['start']}..{te} n={rules['tuning']['n']}, "
              f"holdout {hs}..{he}, segments {dict(c)} -> {rules_p}")
    else:
        rules = load(rules_p)
    if a.report:
        rep = build_report(rules, learn, hold, te, he, root)
        out_dir = os.path.join(root, 'outputs')
        _write_json(os.path.join(out_dir, 'top_rules_report.json'), rep)
        with open(os.path.join(out_dir, 'top_rules_report.md'), 'w', encoding='utf-8') as fh:
            fh.write(report_md(rep, rules))
        for name, u in rep['universes'].items():
            b, af = u['twoWay']['before'], u['twoWay']['after']
            print(f"{name}: before n={b['n']} ROI-5% {b['roi5']} | after n={af['n']} ROI-5% {af['roi5']}")
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
