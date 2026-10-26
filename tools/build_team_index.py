"""Build the team-history index served by /api/teams (design K6).

Sources
- outputs/result_store.json (primary): every finished game with score and
  home/away, Livesport spelling.
- Supabase ``predictions`` rows with a score (secondary), merged only when the
  same game (date, sport, both teams in either orientation) is not already in
  result_store. Needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in the
  environment; without them it prints ``WARNING supabase skipped`` and builds
  from result_store alone. The key is sent only in request headers and never
  printed.

Outputs (last ``--days`` days, default 400)
- outputs/team_index/<sport>.json.gz:
  {version, sport, built, from, to, teams: {key: [spellings, most used first]},
   games: [[date, homeKey, awayKey, scoreHome, scoreAway, src]]} with src 0 =
  result_store, 1 = supabase; written with a fixed gzip mtime, so an unchanged
  index is byte-identical and git sees no diff.
- outputs/team_aliases.json: {version, built, aliases: {"sport|folded": key}}
  for names that fold to a different key than the one the index stores:
  country-tagged spellings of a team that also appears untagged
  (``legia warszawa (pol)`` -> ``legia warszawa``, only when the base has one
  tag) and Forebet spellings paired with Livesport ones through
  results/forebet_settled.json (same day, same score, the other side equal).

Usage: python tools/build_team_index.py [--days 400] [--no-supabase] [--root DIR]
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from tools.team_names import fold, strip_country_tag  # noqa: E402

DAYS = 400
SRC_STORE, SRC_SUPABASE = 0, 1
SUPABASE_PAGE = 1000
SUPABASE_TIMEOUT_S = 30

Game = Tuple[str, str, str, str, int, int, int]  # date, sport, home, away, sh, sa, src


def _score(x: Any) -> Optional[int]:
    try:
        v = int(float(x))
    except (TypeError, ValueError):
        return None
    return v if 0 <= v < 1000 else None


def _row(d: Any, sport: Any, home: Any, away: Any, sh: Any, sa: Any, src: int,
         since: str) -> Optional[Tuple[str, str, str, str, int, int, int]]:
    d = str(d or '')[:10]
    sport = str(sport or '').strip().lower()
    sh, sa = _score(sh), _score(sa)
    if len(d) != 10 or d < since or not sport or sh is None or sa is None:
        return None
    if not str(home or '').strip() or not str(away or '').strip():
        return None
    return (d, sport, str(home).strip(), str(away).strip(), sh, sa, src)


def load_store(path: str, since: str) -> List[Game]:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            store = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f'ERROR result_store unreadable: {type(e).__name__}', file=sys.stderr)
        return []
    out = []
    for v in store.values() if isinstance(store, dict) else []:
        if not isinstance(v, dict) or v.get('status') != 'finished':
            continue
        r = _row(v.get('date'), v.get('sport'), v.get('home_team'), v.get('away_team'),
                 v.get('score_home'), v.get('score_away'), SRC_STORE, since)
        if r:
            out.append(r)
    return out


def load_supabase(since: str) -> List[Game]:
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
    if not url or not key:
        print('WARNING supabase skipped: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set',
              file=sys.stderr)
        return []
    import requests
    headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
    params = {'select': 'id,match_date,sport,home_team,away_team,home_score,away_score',
              'home_score': 'not.is.null', 'away_score': 'not.is.null',
              'match_date': f'gte.{since}', 'order': 'id.asc'}
    out: List[Game] = []
    start = 0
    while True:
        try:
            r = requests.get(f'{url}/rest/v1/predictions', params=params, timeout=SUPABASE_TIMEOUT_S,
                             headers={**headers, 'Range': f'{start}-{start + SUPABASE_PAGE - 1}'})
        except Exception as e:
            print(f'WARNING supabase skipped: {type(e).__name__}', file=sys.stderr)
            return []
        if r.status_code not in (200, 206):
            print(f'WARNING supabase skipped: HTTP {r.status_code}', file=sys.stderr)
            return []
        rows = r.json() if r.content else []
        for x in rows if isinstance(rows, list) else []:
            g = _row(x.get('match_date'), x.get('sport'), x.get('home_team'), x.get('away_team'),
                     x.get('home_score'), x.get('away_score'), SRC_SUPABASE, since)
            if g:
                out.append(g)
        if not isinstance(rows, list) or len(rows) < SUPABASE_PAGE:
            break
        start += SUPABASE_PAGE
    return out


def merge(store: Iterable[Game], extra: Iterable[Game]) -> Tuple[List[Game], Dict[str, int]]:
    """result_store first; a secondary game is added only when the same
    (date, sport, folded teams in either orientation) is not there yet."""
    seen = set()
    games: List[Game] = []
    stats = Counter()
    for g in list(store) + list(extra):
        d, sport, h, a = g[0], g[1], fold(g[2], g[1]), fold(g[3], g[1])
        if not h or not a or h == a:
            continue
        k = (d, sport) + tuple(sorted((h, a)))
        if k in seen:
            stats['duplicate'] += 1
            continue
        seen.add(k)
        games.append(g)
        stats['store' if g[6] == SRC_STORE else 'supabase'] += 1
    return games, dict(stats)


def _forebet_pairs(path: str, games: List[Game], canon) -> Dict[Tuple[str, str], str]:
    """Forebet spelling -> index key, from forebet_settled entries whose day,
    score and one side match exactly one stored game."""
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            settled = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    by_day = defaultdict(list)
    for g in games:
        by_day[(g[0], g[1])].append(g)
    votes: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    for k, v in settled.items() if isinstance(settled, dict) else []:
        parts = str(k).split('|')
        if len(parts) != 4 or not isinstance(v, dict) or v.get('status') != 'settled':
            continue
        d, sport, fh_, fa_ = parts
        sc = str(v.get('score') or '').replace(':', '-').split('-')
        if len(sc) != 2 or _score(sc[0]) is None or _score(sc[1]) is None:
            continue
        sh, sa = _score(sc[0]), _score(sc[1])
        fh_k, fa_k = canon(sport, fold(fh_, sport)), canon(sport, fold(fa_, sport))
        hits = []
        for g in by_day.get((d, sport), []):
            gh, ga = canon(sport, fold(g[2], sport)), canon(sport, fold(g[3], sport))
            if (g[4], g[5]) == (sh, sa) and (gh == fh_k) != (ga == fa_k):
                hits.append((fa_k, ga) if gh == fh_k else (fh_k, gh))
            elif (g[4], g[5]) == (sa, sh) and (gh == fa_k) != (ga == fh_k):
                hits.append((fh_k, ga) if gh == fa_k else (fa_k, gh))
        if len(hits) == 1:
            src, dst = hits[0]
            if src and dst and src != dst:
                votes[(sport, src)][dst] += 1
    out = {}
    for (sport, src), c in votes.items():
        dst, n = c.most_common(1)[0]
        if n * 3 >= sum(c.values()) * 2:     # clear majority only
            out[(sport, src)] = dst
    return out


def build(games: List[Game], forebet_settled: Optional[str] = None
          ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """Per-sport index dicts and the alias table."""
    spellings: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    for g in games:
        for raw in (g[2], g[3]):
            spellings[(g[1], fold(raw, g[1]))][raw] += 1

    # Country-tagged spelling of a team also seen untagged, one tag per base.
    keys_by_sport = defaultdict(set)
    for sport, k in spellings:
        keys_by_sport[sport].add(k)
    alias: Dict[Tuple[str, str], str] = {}
    for sport, keys in keys_by_sport.items():
        tagged = defaultdict(list)
        for k in keys:
            base = strip_country_tag(k)
            if base != k:
                tagged[base].append(k)
        for base, ks in tagged.items():
            if base in keys and len(ks) == 1:
                alias[(sport, ks[0])] = base

    def canon(sport: str, k: str) -> str:
        return alias.get((sport, k), k)

    if forebet_settled:
        for (sport, src), dst in _forebet_pairs(forebet_settled, games, canon).items():
            if src not in keys_by_sport[sport]:      # never re-point a stored team
                alias[(sport, src)] = dst

    built = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    per: Dict[str, Dict[str, Any]] = {}
    for g in sorted(games, key=lambda g: (g[0], g[1], g[2], g[3])):
        sport = g[1]
        h, a = canon(sport, fold(g[2], sport)), canon(sport, fold(g[3], sport))
        idx = per.setdefault(sport, {'version': 1, 'sport': sport, 'built': built,
                                     'from': g[0], 'to': g[0], 'teams': {}, 'games': []})
        idx['games'].append([g[0], h, a, g[4], g[5], g[6]])
        idx['to'] = g[0]
    for (sport, k), c in spellings.items():
        teams = per[sport]['teams']
        key = canon(sport, k)
        merged = Counter(dict(teams.get(key) or {}))
        merged.update(c)
        teams[key] = merged
    for idx in per.values():
        idx['teams'] = {k: [n for n, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]
                        for k, c in sorted(idx['teams'].items())}
    aliases = {f'{s}|{k}': v for (s, k), v in sorted(alias.items())}
    return per, aliases


def _write_gz(path: str, obj: Any) -> int:
    raw = json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    buf = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    data = buf.getvalue()
    tmp = path + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)
    return len(data)


def _same_except_built(path: str, obj: Dict[str, Any]) -> bool:
    """True when the file on disk equals obj apart from the build stamp."""
    try:
        if path.endswith('.gz'):
            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                old = json.load(fh)
        else:
            with open(path, 'r', encoding='utf-8') as fh:
                old = json.load(fh)
    except (OSError, ValueError):
        return False
    return {**old, 'built': None} == {**obj, 'built': None}


def write(per: Dict[str, Dict[str, Any]], aliases: Dict[str, str], out_dir: str,
          aliases_path: str) -> Dict[str, int]:
    os.makedirs(out_dir, exist_ok=True)
    sizes = {}
    for sport, idx in sorted(per.items()):
        path = os.path.join(out_dir, f'{sport}.json.gz')
        if _same_except_built(path, idx):
            sizes[sport] = os.path.getsize(path)
            continue
        sizes[sport] = _write_gz(path, idx)
    doc = {'version': 1, 'built': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'aliases': aliases}
    if not _same_except_built(aliases_path, doc):
        tmp = aliases_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=0, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, aliases_path)
    return sizes


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--days', type=int, default=DAYS)
    ap.add_argument('--no-supabase', action='store_true')
    args = ap.parse_args(argv)
    t0 = time.time()
    since = (date.today() - timedelta(days=args.days)).isoformat()
    store = load_store(os.path.join(args.root, 'outputs', 'result_store.json'), since)
    if not store:
        print('ERROR no result_store games - index not rebuilt', file=sys.stderr)
        return 1
    extra = [] if args.no_supabase else load_supabase(since)
    games, stats = merge(store, extra)
    per, aliases = build(games, os.path.join(args.root, 'results', 'forebet_settled.json'))
    sizes = write(per, aliases, os.path.join(args.root, 'outputs', 'team_index'),
                  os.path.join(args.root, 'outputs', 'team_aliases.json'))
    print(f'team index since {since}: store {len(store)} rows, supabase {len(extra)} rows, '
          f'kept store {stats.get("store", 0)} + supabase {stats.get("supabase", 0)}, '
          f'duplicates {stats.get("duplicate", 0)}; aliases {len(aliases)}')
    for sport in sorted(per):
        print(f'  {sport}: {len(per[sport]["teams"])} teams, {len(per[sport]["games"])} games, '
              f'{sizes[sport] / 1e6:.2f} MB ({per[sport]["from"]}..{per[sport]["to"]})')
    print(f'  total {sum(sizes.values()) / 1e6:.2f} MB in {time.time() - t0:.0f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
