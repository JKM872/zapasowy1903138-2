"""Published TOP picks, settled against stored results, shaped for the website.

``results/top_<date>.json`` is exactly what was mailed that day, so this is the
honest record: no back-filled picks, no re-scored history. Each pick is settled
against ``outputs/result_store.json`` by date and team names.

The paywall lives here rather than in the UI: picks for matches that have not
been settled yet are withheld from non-subscribers on the server, so they
cannot be read out of the page source. Settled picks stay public — they are the
proof that the product works.
"""
from __future__ import annotations

import glob
import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(ROOT, 'results')
STORE_PATH = os.path.join(ROOT, 'outputs', 'result_store.json')
_TOP_RE = re.compile(r'top_(\d{4}-\d{2}-\d{2})\.json$')

_store_cache: Dict[str, Any] = {'mtime': None, 'index': {}}


def _norm(name: Any) -> str:
    s = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _store_index(path: str = STORE_PATH) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """(date, home, away) -> finished result. Rebuilt only when the file changes."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _store_cache['mtime'] == mtime and _store_cache.get('path') == path:
        return _store_cache['index']
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            store = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    index = {}
    for v in store.values():
        if isinstance(v, dict) and v.get('status') == 'finished' and v.get('winner'):
            index[(v.get('date'), _norm(v.get('home_team')), _norm(v.get('away_team')))] = v
    _store_cache.update(mtime=mtime, index=index, path=path)
    return index


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


def _summary(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    settled = [p for p in picks if p['result']['status'] in ('won', 'lost', 'draw')]
    won = [p for p in settled if p['result']['status'] == 'won']
    n = len(settled)
    profit = sum((p['odds'] or 0) for p in won) - n
    return {
        'picks': sum(1 for p in picks if p['result']['status'] != 'withdrawn'),
        'settled': n,
        'won': len(won),
        'pending': sum(1 for p in picks if p['result']['status'] == 'pending'),
        'withdrawn': sum(1 for p in picks if p['result']['status'] == 'withdrawn'),
        'hitRate': round(len(won) / n * 100, 1) if n else None,
        'roi': round(profit / n * 100, 1) if n else None,
        'profitUnits': round(profit, 2) if n else None,
    }


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


def load_top(results_dir: str = RESULTS_DIR, store_path: str = STORE_PATH,
             is_subscriber: bool = False) -> Dict[str, Any]:
    """Every published TOP day, newest first, settled and paywalled."""
    # Audit settlement first (Forebet names), result store as fallback.
    index = {**_store_index(store_path), **_forebet_settled(results_dir)}
    days: List[Dict[str, Any]] = []
    everything: List[Dict[str, Any]] = []
    by_sport: Dict[str, List[Dict[str, Any]]] = {}

    for path in sorted(glob.glob(os.path.join(results_dir, 'top_*.json')), reverse=True):
        m = _TOP_RE.search(os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        try:
            with open(path, 'r', encoding='utf-8-sig') as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        raw = raw if isinstance(raw, list) else (raw.get('picks') or raw.get('top') or [])

        picks = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            try:
                odds = float(r.get('odds'))
            except (TypeError, ValueError):
                odds = None
            entry = {
                'date': day, 'sport': r.get('sport') or 'unknown', 'time': r.get('time') or '',
                'league': r.get('league') or '', 'match': r.get('match') or '',
                'pick': r.get('pick') or '', 'odds': odds, 'grade': r.get('grade') or '',
                'form': r.get('form') or '', 'h2h': r.get('h2h') or '',
                'signals': r.get('signals') or '',
                'result': ({'status': 'withdrawn', 'reason': r.get('withdrawReason') or ''}
                           if r.get('withdrawn') else settle(day, r, index)),
                'availabilityNote': r.get('availabilityNote') or '',
            }
            picks.append(entry)
            everything.append(entry)
            by_sport.setdefault(entry['sport'], []).append(entry)

        # Paywall: an unsettled pick is the thing being sold.
        visible = []
        locked = 0
        for p in picks:
            if is_subscriber or p['result']['status'] != 'pending':
                visible.append(p)
            else:
                locked += 1
        days.append({'date': day, 'summary': _summary(picks),
                     'picks': visible, 'locked': locked})

    return {
        'days': days,
        'summary': _summary(everything),
        'bySport': {s: _summary(v) for s, v in sorted(by_sport.items(), key=lambda kv: -len(kv[1]))},
        'isSubscriber': is_subscriber,
    }
