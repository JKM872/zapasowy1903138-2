#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Injury & Availability Data Fetcher
====================================

Fetches player injury/availability/lineup data from multiple sources:
  1. ESPN API — team injuries (football/soccer, basketball, hockey)
  2. SofaScore API — event lineups (all sports with SofaScore event IDs)

Populates PlayerAvailability / AvailabilityReport from prediction_data_contract.

Usage:
    python injury_data_fetcher.py --team "Arsenal" --sport football
    python injury_data_fetcher.py --event-id 12345 --source sofascore
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    import requests
    _requests_ok = True
except ImportError:
    requests = None  # type: ignore[assignment]
    _requests_ok = False


# ═══════════════════════════════════════════════════════════════════════════
# INJURY CACHE (avoid re-fetching same team within 4 hours)
# ═══════════════════════════════════════════════════════════════════════════

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')
INJURY_CACHE_FILE = os.path.join(CACHE_DIR, 'injury_cache.json')
CACHE_TTL_HOURS = 4


def _load_cache() -> Dict[str, Any]:
    try:
        if os.path.isfile(INJURY_CACHE_FILE):
            with open(INJURY_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_cache(cache: Dict[str, Any]):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(INJURY_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def _cache_key(source: str, identifier: str) -> str:
    return f'{source}:{identifier}'


def _is_cache_valid(entry: Dict[str, Any]) -> bool:
    cached_at = entry.get('cached_at', '')
    if not cached_at:
        return False
    try:
        dt = datetime.fromisoformat(cached_at)
        return (datetime.now() - dt) < timedelta(hours=CACHE_TTL_HOURS)
    except (ValueError, TypeError):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# ESPN INJURY FETCHER
# ═══════════════════════════════════════════════════════════════════════════

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports'

ESPN_SPORT_PATHS = {
    'football': [
        'soccer/eng.1', 'soccer/esp.1', 'soccer/ger.1',
        'soccer/ita.1', 'soccer/fra.1', 'soccer/uefa.champions',
    ],
    'basketball': ['basketball/nba'],
    'hockey': ['hockey/nhl'],
}

# Mapping from common team names to ESPN team IDs.
# This is populated dynamically via search or cached.
_espn_team_cache: Dict[str, Dict[str, Any]] = {}


def _espn_session() -> Optional[Any]:
    if not _requests_ok or requests is None:
        return None
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    })
    return session


def espn_search_team(team_name: str, sport: str = 'football') -> Optional[Dict[str, Any]]:
    """Search for a team on ESPN and return {id, name, abbreviation}."""
    cache_k = f'espn_team:{team_name.lower()}'
    if cache_k in _espn_team_cache:
        return _espn_team_cache[cache_k]

    session = _espn_session()
    if not session:
        return None

    # Try search via scoreboard teams
    paths = ESPN_SPORT_PATHS.get(sport, ESPN_SPORT_PATHS.get('football', []))
    for path in paths:
        try:
            url = f'{ESPN_BASE}/{path}/teams'
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            teams = data.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', [])
            for t_entry in teams:
                team = t_entry.get('team', {})
                name = team.get('displayName', '')
                short = team.get('shortDisplayName', '')
                abbr = team.get('abbreviation', '')
                if (team_name.lower() in name.lower()
                    or team_name.lower() in short.lower()
                    or team_name.lower() == abbr.lower()):
                    result: Dict[str, Any] = {
                        'id': team.get('id'),
                        'name': name,
                        'abbreviation': abbr,
                        'sport_path': path,
                    }
                    _espn_team_cache[cache_k] = result
                    return result
        except Exception:
            continue

    return None


def espn_get_team_injuries(team_id: str, sport_path: str) -> List[Dict[str, Any]]:
    """Fetch injury report for a team from ESPN.

    Returns list of {name, position, status, injury_type, detail}.
    """
    cache = _load_cache()
    ck = _cache_key('espn_injuries', f'{sport_path}:{team_id}')
    if ck in cache and _is_cache_valid(cache[ck]):
        return cache[ck].get('injuries', [])

    session = _espn_session()
    if not session:
        return []

    injuries: List[Dict[str, Any]] = []
    try:
        url = f'{ESPN_BASE}/{sport_path}/teams/{team_id}/injuries'
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        for item in data.get('injuries', []):
            for athlete_entry in item.get('injuries', []):
                athlete = athlete_entry.get('athlete', {})
                status_obj = athlete_entry.get('status', '')
                detail: Dict[str, Any] = athlete_entry.get('details', {})

                injuries.append({
                    'name': athlete.get('displayName', ''),
                    'position': athlete.get('position', {}).get('abbreviation', ''),
                    'status': status_obj if isinstance(status_obj, str)
                              else status_obj.get('type', 'unknown'),
                    'injury_type': detail.get('type', ''),
                    'detail': detail.get('detail', ''),
                    'return_date': detail.get('returnDate', ''),
                })

    except Exception as e:
        print(f'  ESPN injury fetch error for {team_id}: {e}')

    # Cache result
    cache[ck] = {
        'injuries': injuries,
        'cached_at': datetime.now().isoformat(),
    }
    _save_cache(cache)

    return injuries


def fetch_injuries_for_match(
    home_team: str, away_team: str, sport: str = 'football'
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch injuries for both teams in a match via ESPN.

    Returns {'home': [...], 'away': [...]}.
    """
    result: Dict[str, List[Dict[str, Any]]] = {'home': [], 'away': []}

    if sport not in ESPN_SPORT_PATHS:
        return result

    for side, team_name in [('home', home_team), ('away', away_team)]:
        team_info = espn_search_team(team_name, sport)
        if not team_info or not team_info.get('id'):
            continue
        injuries = espn_get_team_injuries(team_info['id'], team_info['sport_path'])
        result[side] = injuries

    return result


# ═══════════════════════════════════════════════════════════════════════════
# SOFASCORE LINEUP FETCHER
# ═══════════════════════════════════════════════════════════════════════════

SOFASCORE_API = 'https://api.sofascore.com/api/v1'

SOFASCORE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Origin': 'https://www.sofascore.com',
    'Referer': 'https://www.sofascore.com/',
}


def _sofascore_session() -> Optional[Any]:
    if not _requests_ok or requests is None:
        return None
    session = requests.Session()
    session.headers.update(SOFASCORE_HEADERS)
    return session


def sofascore_get_lineups(event_id: int) -> Optional[Dict[str, Any]]:
    """Fetch confirmed lineups for an event from SofaScore.

    Returns {home: {confirmed, players: [...]}, away: {...} } or None.
    """
    cache = _load_cache()
    ck = _cache_key('sofascore_lineup', str(event_id))
    if ck in cache and _is_cache_valid(cache[ck]):
        return cache[ck].get('lineups')

    session = _sofascore_session()
    if not session:
        return None

    try:
        url = f'{SOFASCORE_API}/event/{event_id}/lineups'
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        result: Dict[str, Any] = {}

        for side in ('home', 'away'):
            lineup = data.get(side, {})
            players: List[Dict[str, Any]] = []
            for p in lineup.get('players', []):
                player = p.get('player', {})
                players.append({
                    'name': player.get('name', ''),
                    'position': player.get('position', ''),
                    'substitute': p.get('substitute', False),
                    'missing': p.get('missing', False),
                    'missingReason': p.get('missingReason', ''),
                })
            result[side] = {
                'confirmed': lineup.get('confirmed', False),
                'players': players,
                'missing_count': sum(1 for p in players if p.get('missing')),
            }

        # Cache
        cache[ck] = {
            'lineups': result,
            'cached_at': datetime.now().isoformat(),
        }
        _save_cache(cache)

        return result

    except Exception as e:
        print(f'  SofaScore lineup fetch error for event {event_id}: {e}')
        return None


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED ENRICHMENT — For scrape_and_notify.py pipeline
# ═══════════════════════════════════════════════════════════════════════════

def enrich_availability_from_injuries(
    row: Dict[str, Any],
    avail: Optional[Any] = None,
) -> Dict[str, Any]:
    """Enrich a match row with injury/availability data.

    Tries ESPN injuries for team sports.
    Updates the row's 'availability' dict in place.

    Args:
        row: Match row dict
        avail: Existing AvailabilityReport (optional, will be read from row if absent)

    Returns:
        Updated row dict
    """
    sport = (row.get('sport') or 'football').lower()
    home_team = row.get('home_team', '')
    away_team = row.get('away_team', '')

    # Skip tennis — handled separately via last_match data
    if sport == 'tennis':
        return row

    # Only fetch for sports with ESPN coverage
    if sport not in ('football',):
        return row

    try:
        injuries = fetch_injuries_for_match(home_team, away_team, sport)
    except Exception:
        return row

    # Count significant absences
    home_key_out = 0
    away_key_out = 0

    out_statuses = ('out', 'day-to-day', 'injured', 'suspended', 'doubtful')

    for inj in injuries.get('home', []):
        status = str(inj.get('status', '')).lower()
        if any(s in status for s in out_statuses):
            home_key_out += 1

    for inj in injuries.get('away', []):
        status = str(inj.get('status', '')).lower()
        if any(s in status for s in out_statuses):
            away_key_out += 1

    # Update availability dict
    avail_dict: Dict[str, Any] = row.get('availability', {}) or {}
    avail_dict['home_key_absences'] = home_key_out
    avail_dict['away_key_absences'] = away_key_out

    if home_key_out > 0 or away_key_out > 0:
        avail_dict['injury_data_source'] = 'espn'
        avail_dict['home_injuries'] = injuries.get('home', [])[:5]  # Top 5 only
        avail_dict['away_injuries'] = injuries.get('away', [])[:5]

        # Recalculate availability impact
        impact: float = float(avail_dict.get('availability_impact', 0.0))
        if home_key_out >= 3 or away_key_out >= 3:
            impact = max(impact, 0.3)
        elif home_key_out >= 1 or away_key_out >= 1:
            impact = max(impact, 0.15)
        avail_dict['availability_impact'] = round(min(1.0, impact), 2)

    row['availability'] = avail_dict
    return row


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Injury & Availability Data Fetcher')
    parser.add_argument('--team', help='Team name to search for injuries')
    parser.add_argument('--sport', default='football', help='Sport (football, basketball, hockey)')
    parser.add_argument('--event-id', type=int, help='SofaScore event ID for lineups')
    parser.add_argument('--test', action='store_true', help='Run test with sample teams')

    args = parser.parse_args()

    if args.team:
        print(f'\n🔍 Searching for {args.team} ({args.sport})...')
        team_info = espn_search_team(args.team, args.sport)
        if team_info:
            print(f'   Found: {team_info["name"]} (ID: {team_info["id"]})')
            injuries = espn_get_team_injuries(team_info['id'], team_info['sport_path'])
            if injuries:
                print(f'\n🏥 Injuries ({len(injuries)}):')
                for inj in injuries:
                    print(f'   {inj["name"]} ({inj["position"]}) — {inj["status"]}: {inj["injury_type"]}')
            else:
                print('   No injuries reported')
        else:
            print(f'   ❌ Team not found on ESPN')

    if args.event_id:
        print(f'\n📋 Fetching lineups for event {args.event_id}...')
        lineups = sofascore_get_lineups(args.event_id)
        if lineups:
            for side in ('home', 'away'):
                info = lineups[side]
                print(f'\n{side.upper()} (confirmed: {info["confirmed"]}, missing: {info["missing_count"]}):')
                for p in info['players'][:11]:  # Show first 11
                    status = '❌ MISSING' if p.get('missing') else '✅'
                    print(f'   {status} {p["name"]} ({p["position"]})')
        else:
            print('   ❌ Lineups not available')

    if args.test:
        print('\n🧪 Testing with sample teams...')
        for team in ['Arsenal', 'Barcelona', 'Bayern Munich']:
            result = fetch_injuries_for_match(team, 'Test Opponent', 'football')
            home_injuries = result.get('home', [])
            print(f'   {team}: {len(home_injuries)} injuries')
            for inj in home_injuries[:3]:
                print(f'      {inj["name"]}: {inj["status"]}')


if __name__ == '__main__':
    main()
