#!/usr/bin/env python3
"""Recover the outcomes of matches we already scraped.

``results/*.json`` holds 164k scraped fixtures with their pre-match features,
of which 149k carry a link with a match id. Their outcomes were never stored:
``result_store.json`` had 261 results, 0.2% of the history. Supabase's
``actual_result`` is unusable — '1' for all 1000 rows it returned — so without
this backfill there is nothing to calibrate on and nothing to train on.

Two sources, both plain HTTP, verified live:

* Livesport ``mid`` -> ``local-global.flashscore.ninja/2/x/feed/df_sui_1_{mid}``
  returns the score period by period (``IG``/``IH`` per ``AC`` period).
* SofaScore event id -> ``/api/v1/event/{id}`` returns the final score directly.

The bulk endpoint ``/sport/{slug}/scheduled-events/{date}`` is refused outright,
which is also why ``auto_result_updater`` has been writing nothing.

Orientation is never assumed: the feed reports the source's own home/away, and
our rows do not always agree with it, so the two teams are matched by name and
the score is flipped when they are reversed.

    python tools/backfill_results.py --month 2026-03 --limit 200
    python tools/backfill_results.py --month 2026-03            # cały miesiąc
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from result_resolver import same_competitor  # noqa: E402
from result_store import ResultStore  # noqa: E402

FEED_BASE = 'https://local-global.flashscore.ninja/2/x/feed/'
FEED_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/126.0.0.0 Safari/537.36'),
    'Referer': 'https://www.livesport.com/',
    'x-fsign': 'SW9D1eZo',
}

# Sports scored by sets: the winner is whoever took more sets, not more points.
SET_SPORTS = {'tennis', 'table_tennis', 'volleyball'}

_MID_RE = re.compile(r'[?&]mid=([A-Za-z0-9]+)')
_LS_PATH_RE = re.compile(r'/mecz/[^/]+/([^/]+)/([^/?]+)')
_SOFA_ID_RE = re.compile(r'sofascore\.com/.*?/(\d{5,})')
_FIELD_RE = re.compile(r'([A-Z]{2,3})\xf7([^\xac\xb6~]*)')


# ---------------------------------------------------------------------------
# Parsing (pure)
# ---------------------------------------------------------------------------

def parse_feed_periods(text: str) -> List[Tuple[int, int]]:
    """Extract ``[(home, away), ...]`` per period from a Livesport feed body.

    The body is a flat ``KEY÷VALUE`` stream delimited by ``¬`` and ``~``; each
    period block carries ``IG`` (first team) and ``IH`` (second team).
    """
    periods: List[Tuple[int, int]] = []
    for block in (text or '').split('~'):
        fields = dict(_FIELD_RE.findall(block))
        if 'IG' not in fields or 'IH' not in fields:
            continue
        try:
            periods.append((int(fields['IG']), int(fields['IH'])))
        except (TypeError, ValueError):
            continue
    return periods


def final_score(periods: List[Tuple[int, int]], sport: str
                ) -> Optional[Tuple[int, int]]:
    """Collapse period scores into the figure that decides the match."""
    if not periods:
        return None
    key = (sport or '').lower()
    if key in SET_SPORTS:
        # Sets won, not points scored — 3-1 in sets can be fewer points overall.
        first = sum(1 for h, a in periods if h > a)
        second = sum(1 for h, a in periods if a > h)
        return first, second
    return sum(h for h, _ in periods), sum(a for _, a in periods)


def outcome_from_scores(home: int, away: int, sport: str) -> Optional[str]:
    if home > away:
        return 'home'
    if away > home:
        return 'away'
    return 'draw' if (sport or '').lower() not in SET_SPORTS else None


def livesport_mid(url: str) -> Optional[str]:
    match = _MID_RE.search(url or '')
    return match.group(1) if match else None


def livesport_team_slugs(url: str) -> Optional[Tuple[str, str]]:
    """The two team slugs from a Livesport path, in the source's own order."""
    match = _LS_PATH_RE.search(url or '')
    if not match:
        return None

    def clean(slug: str) -> str:
        # 'fenerbahce-rDhoZR1l' -> 'fenerbahce'
        return re.sub(r'-[A-Za-z0-9]{6,10}$', '', slug).replace('-', ' ')

    return clean(match.group(1)), clean(match.group(2))


def sofascore_event_id(url: str) -> Optional[str]:
    match = _SOFA_ID_RE.search(url or '')
    return match.group(1) if match else None


def orient(row_home: str, row_away: str,
           source_first: str, source_second: str) -> Optional[bool]:
    """True when the source's first team is our home team.

    Returns None when neither arrangement is convincing — better an unlabelled
    match than a result attributed to the wrong side.
    """
    forward = (same_competitor(row_home, source_first)
               and same_competitor(row_away, source_second))
    reverse = (same_competitor(row_home, source_second)
               and same_competitor(row_away, source_first))

    # Both sides must agree. Accepting a single strong side is how
    # auto_result_updater ends up attaching a stranger's fixture: 'Beta' and
    # 'Delta' score as similar strings, so one match is not evidence.
    if forward and not reverse:
        return True
    if reverse and not forward:
        return False
    return None


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _get(url: str, headers: Dict[str, str], timeout: int = 20):
    try:
        from curl_cffi import requests as creq
        return creq.get(url, headers=headers, impersonate='chrome',
                        timeout=timeout)
    except ImportError:
        import requests
        return requests.get(url, headers=headers, timeout=timeout)


def fetch_livesport(mid: str, sport: str) -> Optional[Dict[str, Any]]:
    """Final score for a Livesport match id, in the source's orientation."""
    try:
        resp = _get(f'{FEED_BASE}df_sui_1_{mid}', FEED_HEADERS)
    except Exception:
        return None
    if getattr(resp, 'status_code', 0) != 200 or len(resp.text or '') < 5:
        return None

    periods = parse_feed_periods(resp.text)
    score = final_score(periods, sport)
    if not score:
        return None
    return {'first': score[0], 'second': score[1], 'periods': len(periods),
            'source': 'livesport_feed'}


def _sofascore_json(url: str) -> Optional[Dict[str, Any]]:
    """Fetch JSON from SofaScore, with or without the scraper module.

    ``sofascore_scraper`` brings the Cloudflare handling, but it is a heavy
    module: on a runner without selenium it failed at import time on a type
    annotation, and a NameError is not an ImportError, so the first backfill run
    died on its first SofaScore link. Catching every exception and falling back
    to a plain request keeps a 63k-match job alive for the sake of the 2k rows
    that need this source.
    """
    try:
        from sofascore_scraper import _api_get_json
        return _api_get_json(url, timeout=20)
    except Exception:
        pass

    try:
        resp = _get(url, {
            'User-Agent': FEED_HEADERS['User-Agent'],
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        })
        if getattr(resp, 'status_code', 0) == 200:
            return resp.json()
    except Exception:
        return None
    return None


# SofaScore's sport slugs, for resolving by name when there is no id to use.
SOFA_SLUGS = {
    'table_tennis': 'table-tennis', 'tennis': 'tennis', 'football': 'football',
    'basketball': 'basketball', 'baseball': 'baseball', 'handball': 'handball',
    'volleyball': 'volleyball', 'hockey': 'ice-hockey',
}

# name -> finished events, cached for the run. A table-tennis regular appears in
# up to 167 of our fixtures, so one lookup serves dozens of matches.
_SCHEDULE_CACHE: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
_SCHEDULE_PAGES = 6          # ~30 events per page; six covers our history


def _player_finished_events(name: str, sport: str) -> List[Dict[str, Any]]:
    """Every finished event on this competitor's recent schedule.

    Needed for AiScore fixtures, which carry no id we can query: the page turns
    out to be a Nuxt shell that fetches its score client-side, so the HTML holds
    no result and guessing at their API led nowhere. Walking the opponent's
    schedule on SofaScore is the reliable route, and it is cheap because the same
    players recur constantly.
    """
    slug = SOFA_SLUGS.get((sport or '').lower())
    if not name or not slug:
        return []

    key = (name.strip().lower(), slug)
    if key in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[key]

    events: List[Dict[str, Any]] = []
    try:
        from sofascore_scraper import find_team_by_name
        team = find_team_by_name(name, slug)
    except Exception:
        team = None

    if team and team.get('id'):
        for page in range(_SCHEDULE_PAGES):
            data = _sofascore_json(
                'https://api.sofascore.com/api/v1/team/'
                f"{team['id']}/events/last/{page}")
            batch = (data or {}).get('events') or []
            if not batch:
                break
            events.extend(batch)

    _SCHEDULE_CACHE[key] = events
    return events


def resolve_by_names(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find a fixture on a competitor's schedule, matched by opponent and date.

    The date is mandatory: these players meet each other repeatedly — one pair
    met 31 times in our history — so an opponent match alone would settle the
    wrong meeting.
    """
    if not row.get('date'):
        return None

    candidates: List[Dict[str, Any]] = []
    for primary in (row['home'], row['away']):
        for event in _player_finished_events(primary, row['sport']):
            if ((event.get('status') or {}).get('type') or '') != 'finished':
                continue
            if _event_date(event) != row['date']:
                continue

            ev_home = (event.get('homeTeam') or {}).get('name', '')
            ev_away = (event.get('awayTeam') or {}).get('name', '')
            # Only the same arrangement is accepted. A reversed pairing on the
            # same day is a different fixture, not this one told backwards:
            # these players meet twice in a day with the sides swapped, and
            # accepting the mirror is what produced eight wrong labels out of 97
            # — every one of them an exact mirror image.
            if orient(row['home'], row['away'], ev_home, ev_away) is not True:
                continue

            home = (event.get('homeScore') or {}).get('current')
            away = (event.get('awayScore') or {}).get('current')
            if home is None or away is None:
                continue
            if not any(c.get('id') == event.get('id') for c in candidates):
                candidates.append(event)

    # Two identical pairings on one date cannot be told apart, so neither is
    # settled. An unlabelled match costs a row; a mirrored one corrupts training.
    if len(candidates) != 1:
        return None

    event = candidates[0]
    return _shape({'first': int((event.get('homeScore') or {}).get('current')),
                   'second': int((event.get('awayScore') or {}).get('current')),
                   'source': 'sofascore_schedule'}, row, True)


def _event_date(event: Dict[str, Any]) -> Optional[str]:
    ts = event.get('startTimestamp')
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d')
    except (TypeError, ValueError, OSError):
        return None


def fetch_sofascore(event_id: str) -> Optional[Dict[str, Any]]:
    """Final score for a SofaScore event id, with its own team names."""
    data = _sofascore_json(
        f'https://api.sofascore.com/api/v1/event/{event_id}')
    event = (data or {}).get('event') or {}
    if ((event.get('status') or {}).get('type') or '') != 'finished':
        return None
    home = (event.get('homeScore') or {}).get('current')
    away = (event.get('awayScore') or {}).get('current')
    if home is None or away is None:
        return None
    return {
        'first': int(home), 'second': int(away),
        'first_name': (event.get('homeTeam') or {}).get('name', ''),
        'second_name': (event.get('awayTeam') or {}).get('name', ''),
        'source': 'sofascore_event',
    }


# ---------------------------------------------------------------------------
# Walking the scraped history
# ---------------------------------------------------------------------------

def iter_history(month: Optional[str] = None, sport: Optional[str] = None,
                 ) -> List[Dict[str, Any]]:
    """Every scraped fixture that carries a usable link."""
    pattern = f'results/matches_{month}*' if month else 'results/matches_*'
    rows: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(pattern + '.json')):
        try:
            doc = json.load(open(path, encoding='utf-8'))
        except (OSError, ValueError):
            continue
        matches = doc.get('matches') if isinstance(doc, dict) else doc
        if not isinstance(matches, list):
            continue
        file_sport = (doc.get('sport') if isinstance(doc, dict) else None) or ''
        file_date = (doc.get('date') if isinstance(doc, dict) else None) or ''
        if not file_date:
            found = re.search(r'matches_(\d{4}-\d{2}-\d{2})', path)
            file_date = found.group(1) if found else ''

        for raw in matches:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get('matchUrl') or raw.get('match_url') or '')
            if not url or '...' in url:
                continue
            row_sport = str(raw.get('sport') or file_sport or '').lower()
            if sport and row_sport != sport.lower():
                continue
            rows.append({
                'url': url,
                'sport': row_sport,
                'date': str(raw.get('date') or file_date),
                'home': str(raw.get('homeTeam') or raw.get('home_team') or ''),
                'away': str(raw.get('awayTeam') or raw.get('away_team') or ''),
            })
    return rows


def resolve(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fetch and orient one fixture's result, or None when unresolvable."""
    url, sport = row['url'], row['sport']

    event_id = sofascore_event_id(url)
    if event_id:
        got = fetch_sofascore(event_id)
        if got:
            flip = orient(row['home'], row['away'],
                          got.get('first_name', ''), got.get('second_name', ''))
            if flip is None:
                return None
            return _shape(got, row, flip)

    mid = livesport_mid(url)
    if mid:
        got = fetch_livesport(mid, sport)
        if not got:
            return None
        # The feed's first/second is the real home/away, and so is the scraped
        # row's — measured against 40 independently resolved matches: taking the
        # feed as-is agreed 24/24, while orienting by the URL slugs disagreed
        # 15/16. It is the slug order that does not mean home-away, which is the
        # same trap that made the manifest look wrong earlier today.
        return _shape(got, row, True)

    # AiScore and anything else without a queryable id: match by name and date
    # on the competitor's SofaScore schedule.
    return resolve_by_names(row)


def _shape(got: Dict[str, Any], row: Dict[str, Any], forward: bool
           ) -> Optional[Dict[str, Any]]:
    home = got['first'] if forward else got['second']
    away = got['second'] if forward else got['first']
    winner = outcome_from_scores(home, away, row['sport'])
    if winner is None:
        return None
    return {
        'status': 'finished',
        'score_home': home,
        'score_away': away,
        'winner': winner,
        'source': got['source'],
        'orientation_flipped': not forward,
    }


def _store(path: str = '') -> ResultStore:
    """The result store, optionally at an explicit path.

    ResultStore defaults to a path derived from its own module location, so
    without this the destination cannot be redirected — neither by a test nor by
    a CI job that wants to write somewhere specific.
    """
    return ResultStore(path) if path else ResultStore()


def _known_urls(shard_path: str = '', store_path: str = '') -> set:
    """URLs already settled, in the main store and in this shard.

    Consulting the main store as well means a sport-sharded run never re-fetches
    what nightly settlement has already recorded.
    """
    known = set(_store(store_path)._data)
    if shard_path and os.path.isfile(shard_path):
        try:
            with open(shard_path, encoding='utf-8') as fh:
                known |= set(json.load(fh))
        except (OSError, ValueError):
            pass
    return known


def merge_shards(paths: List[str], store_path: str = '') -> int:
    """Fold per-sport shards into the main result store.

    Parallel jobs cannot share one file without fighting over it, so each writes
    its own and this runs once at the end. A finished result already in the main
    store is never overwritten.
    """
    if not paths:
        paths = sorted(glob.glob('outputs/result_store_shards/*.json'))
    store = _store(store_path)
    before = len(store)
    added = skipped = 0

    for path in paths:
        try:
            with open(path, encoding='utf-8') as fh:
                shard = json.load(fh)
        except (OSError, ValueError) as e:
            print(f'  pomijam {path}: {e}')
            continue
        for url, res in (shard or {}).items():
            if store.add_result(match_url=url, result=res,
                                sport=res.get('sport', ''),
                                home_team=res.get('home_team', ''),
                                away_team=res.get('away_team', ''),
                                date=res.get('date', '')):
                added += 1
            else:
                skipped += 1
        print(f'  {path}: {len(shard)} wyników')

    store.save()
    print(f'\nStore: {before} -> {len(store)} (+{added}, pominięte {skipped})')
    return 0


def validate(limit: int = 60, delay: float = 0.2) -> float:
    """Cross-check the backfill against independently resolved outcomes.

    The existing store was settled by name through SofaScore, so it is an
    honest referee. Run this before trusting a large backfill: a mirrored
    orientation produces results that look perfectly plausible and are wrong,
    which is exactly what the first version of this tool did on 15 of 16
    flipped matches.
    """
    store = ResultStore()
    settled = [(url, res) for url, res in store._data.items()
               if res.get('status') == 'finished'
               and res.get('winner') in ('home', 'away', 'draw')]

    # Validate each resolution path on its own sample. The AiScore rows go
    # through the name-and-date schedule lookup, which is a different mechanism
    # from the Livesport feed and can be wrong in different ways.
    known = [(u, r) for u, r in settled if 'mid=' in u][:limit]
    by_name = [(u, r) for u, r in settled if 'aiscore.com' in u][:limit]
    if by_name:
        print(f'  próbka po nazwach (AiScore): {len(by_name)}')
        known = known + by_name
    if not known:
        print('Brak niezależnych wyników do walidacji.')
        return 0.0

    agree = disagree = unresolved = 0
    for url, ref in known:
        row = {'url': url, 'sport': (ref.get('sport') or '').lower(),
               'date': ref.get('date', ''),
               'home': ref.get('home_team', ''),
               'away': ref.get('away_team', '')}
        got = resolve(row)
        if not got:
            unresolved += 1
        elif got['winner'] == ref['winner']:
            agree += 1
        else:
            disagree += 1
            print(f"  ROZBIEŻNOŚĆ {row['home'][:20]} vs {row['away'][:20]}: "
                  f"referencja={ref['winner']} backfill={got['winner']}")
        time.sleep(delay)

    total = agree + disagree
    share = 100.0 * agree / total if total else 0.0
    print(f'\nWalidacja: {agree}/{total} zgodnych ({share:.1f}%), '
          f'nierozstrzygniętych {unresolved}')
    if share < 95.0 and total:
        print('  ⚠️ Poniżej 95% — nie uruchamiaj pełnego backfillu, '
              'orientacja albo parsowanie wyniku jest błędne.')
    return share


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--validate', action='store_true',
                    help='Sprawdź zgodność z niezależnie rozstrzygniętymi wynikami')
    ap.add_argument('--month', help='Ogranicz do miesiąca, np. 2026-03')
    ap.add_argument('--sport', help='Ogranicz do jednego sportu')
    ap.add_argument('--limit', type=int, default=0, help='Maksymalnie N meczów')
    ap.add_argument('--delay', type=float, default=0.3,
                    help='Przerwa między żądaniami (s)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Nie zapisuj, tylko pokaż co by wyszło')
    ap.add_argument('--store', default='',
                    help='Plik wyników (domyślnie outputs/result_store.json). '
                         'Równoległe zadania powinny pisać do własnych szardów.')
    ap.add_argument('--max-seconds', type=int, default=0,
                    help='Zakończ i zapisz po tym czasie. GitHub Actions ubija '
                         'zadanie po 6 h, a wtedy tracisz cały postęp.')
    ap.add_argument('--merge', nargs='*', metavar='SZARD',
                    help='Scal podane szardy do głównego store i zakończ')
    args = ap.parse_args()

    if args.merge is not None:
        return merge_shards(args.merge)

    if args.validate:
        share = validate(delay=args.delay)
        return 0 if share >= 95.0 else 1

    rows = iter_history(args.month, args.sport)
    # A shard per sport keeps parallel jobs from fighting over the same file.
    # They are merged in one step afterwards.
    store = ResultStore(args.store) if args.store else ResultStore()
    already = _known_urls(args.store)
    todo = [r for r in rows if r['url'] not in already]

    print(f'Historia: {len(rows)} meczów z linkiem'
          f' | już rozstrzygniętych: {len(rows) - len(todo)}'
          f' | do pobrania: {len(todo)}')
    if args.max_seconds:
        print(f'  budżet czasu: {args.max_seconds}s '
              f'(~{int(args.max_seconds * 3.6)} meczów przy 3.6/s)')
    if args.limit:
        todo = todo[:args.limit]
        print(f'  ograniczam do {len(todo)}')

    stats = {'ok': 0, 'brak': 0, 'flip': 0}
    started = time.time()
    for i, row in enumerate(todo, 1):
        # One bad fixture must never end a job that has hours of work banked.
        try:
            got = resolve(row)
        except Exception as e:
            print(f'  ⚠️ {row["home"][:24]} vs {row["away"][:24]}: '
                  f'{type(e).__name__}: {str(e)[:70]}')
            got = None
        if got:
            stats['ok'] += 1
            if got.get('orientation_flipped'):
                stats['flip'] += 1
            if not args.dry_run:
                store.add_result(match_url=row['url'], result=got,
                                 sport=row['sport'], home_team=row['home'],
                                 away_team=row['away'], date=row['date'])
        else:
            stats['brak'] += 1

        if i % 25 == 0 or i == len(todo):
            rate = i / max(0.001, time.time() - started)
            print(f'  [{i}/{len(todo)}] ok={stats["ok"]} brak={stats["brak"]} '
                  f'odwrócone={stats["flip"]}  {rate:.1f}/s')
            if not args.dry_run:
                store.save()

        # Stop on our own terms. A job killed at the 6 h ceiling loses whatever
        # it had not yet written; the tool is resumable, so the next run picks up
        # exactly where this one stopped.
        if args.max_seconds and (time.time() - started) >= args.max_seconds:
            print(f'  ⏱️ budżet czasu wyczerpany po {i} meczach — '
                  f'zapisuję i kończę, resztę dobierze następny przebieg')
            break
        time.sleep(args.delay)

    if not args.dry_run:
        store.save()

    # Divide by what was actually attempted, not by the whole queue — a run that
    # stops on its time budget otherwise reports a success rate of a few percent.
    attempted = stats['ok'] + stats['brak']
    print(f'\nZapisane wyniki w store: {len(store)}')
    print(f'Przetworzone: {attempted}/{len(todo)}'
          f' | skuteczność: {100 * stats["ok"] / max(1, attempted):.1f}%'
          f' | zostało: {len(todo) - attempted}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
