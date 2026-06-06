"""
BigOne API Server
=================
Flask API do serwowania danych meczów dla frontendu React.

Endpoints:
- GET /api/matches?date=2024-12-16&sport=football
- GET /api/sports - lista dostępnych sportów
- GET /api/dates - lista dostępnych dat

Run:
    python api_server.py
    
Server: http://localhost:5000
"""

import os
import json
import glob
import math
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.DEBUG if os.environ.get('FLASK_ENV') == 'development' else logging.INFO,
)
logger = logging.getLogger('api_server')

# Auth middleware
from auth_middleware import require_auth, optional_auth

# ---------------------------------------------------------------------------
# Per-sport minimum odds thresholds (same as email_notifier)
# ---------------------------------------------------------------------------
SPORT_MIN_ODDS = {
    'football': 1.50,
    'basketball': 1.30,
    'handball': 1.45,
    'volleyball': 1.30,
    'hockey': 1.50,
    'tennis': 1.35,
}
SPORT_MIN_ODDS_FALLBACK = 1.35


def _passes_sport_odds_threshold(sport, home_odds, away_odds):
    """Return True when at least ONE of home/away odds meets the sport's threshold."""
    threshold = SPORT_MIN_ODDS.get(sport, SPORT_MIN_ODDS_FALLBACK)
    ho_ok = False
    ao_ok = False
    try:
        if home_odds is not None:
            ho_ok = float(home_odds) >= threshold
    except (ValueError, TypeError):
        pass
    try:
        if away_odds is not None:
            ao_ok = float(away_odds) >= threshold
    except (ValueError, TypeError):
        pass
    return ho_ok or ao_ok


def safe_value(val, default=None):
    """
    Zamienia NaN na None, zwraca default dla brakujących wartości.
    Zapobiega wyświetlaniu 'nan' w interfejsie użytkownika.
    """
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    return val

# Import Supabase manager for user bets
try:
    from supabase_manager import SupabaseManager
    supabase = SupabaseManager()
    SUPABASE_AVAILABLE = True
except Exception as e:
    logger.warning('Supabase not available: %s', e)
    supabase = None
    SUPABASE_AVAILABLE = False

# Import ESPN API client for live scores
try:
    from espn_api_client import ESPNAPIClient
    espn_client = ESPNAPIClient()
    ESPN_AVAILABLE = True
except Exception as e:
    logger.warning('ESPN API not available: %s', e)
    espn_client = None
    ESPN_AVAILABLE = False

# Live scores cache (30 second TTL)
_live_scores_cache: dict = {'data': [], 'timestamp': 0}

app = Flask(__name__)
CORS(app, origins=[
    'http://localhost:3000',
    'http://localhost:5000',
    'https://pickly-dashboard.vercel.app',
    'https://pickly-dashboard-*.vercel.app',
    'https://pickly-67e87ed00f70.herokuapp.com',
])  # Enable CORS for frontend (Vercel production + previews + local dev)


# ---------------------------------------------------------------------------
# Global error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(e):
    logger.exception('Unhandled server error')
    return jsonify({'error': 'Internal server error'}), 500


@app.after_request
def log_request(response):
    if request.path.startswith('/api/'):
        logger.info('%s %s %s', request.method, request.path, response.status_code)
    return response

# Directory with scraper results
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')

# Sport mappings
SPORT_INFO = {
    'football': {'name': 'Football', 'icon': 'MdSportsSoccer'},
    'basketball': {'name': 'Basketball', 'icon': 'MdSportsBasketball'},
    'volleyball': {'name': 'Volleyball', 'icon': 'MdSportsVolleyball'},
    'handball': {'name': 'Handball', 'icon': 'MdSportsHandball'},
    'hockey': {'name': 'Hockey', 'icon': 'MdSportsHockey'},
    'tennis': {'name': 'Tennis', 'icon': 'MdSportsTennis'}
}


def find_result_files(date_str=None, sport=None):
    """Find result JSON files matching criteria."""
    pattern = os.path.join(RESULTS_DIR, '*.json')
    files = glob.glob(pattern)
    
    results = []
    for f in files:
        basename = os.path.basename(f)
        # Expected format: matches_2024-12-16_football.json or similar
        if date_str and date_str not in basename:
            continue
        if sport and sport not in basename.lower():
            continue
        results.append(f)
    
    return results


def load_matches_from_file(filepath):
    """Load and parse matches from a JSON file."""
    try:
        # Use utf-8-sig to handle files with BOM (Byte Order Mark)
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            
        # Handle different data structures
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            if 'matches' in data:
                return data['matches']
            elif 'results' in data:
                return data['results']
            else:
                # Single match or nested structure
                return [data] if 'homeTeam' in data or 'home_team' in data else []
        return []
    except Exception as e:
        logger.error('Error loading %s: %s', filepath, e)
        return []


def normalize_supabase_match(row):
    """Normalize a Supabase predictions row to frontend format."""
    return {
        'id': row.get('id', 0),
        'homeTeam': row.get('home_team', ''),
        'awayTeam': row.get('away_team', ''),
        'time': row.get('match_time', ''),
        'date': row.get('match_date', ''),
        'league': row.get('league', ''),
        'country': '',
        'sport': row.get('sport', 'football'),
        'matchUrl': row.get('match_url', ''),
        'qualifies': row.get('qualifies', False),
        # H2H Data
        'h2h': {
            'home': row.get('livesport_h2h_home_wins') or 0,
            'draw': 0,
            'away': row.get('livesport_h2h_away_wins') or 0,
            'total': 5,
            'winRate': safe_value(row.get('livesport_win_rate'), 0),
        },
        # Form Data
        'homeForm': list(row.get('livesport_home_form') or '') if isinstance(row.get('livesport_home_form'), str) else (row.get('livesport_home_form') or []),
        'awayForm': list(row.get('livesport_away_form') or '') if isinstance(row.get('livesport_away_form'), str) else (row.get('livesport_away_form') or []),
        'homeFormHome': [],
        'awayFormAway': [],
        'formAdvantage': False,
        # Odds
        'odds': {
            'home': safe_value(row.get('forebet_home_odds')),
            'draw': safe_value(row.get('forebet_draw_odds')),
            'away': safe_value(row.get('forebet_away_odds')),
            'bookmaker': 'Forebet',
        } if row.get('forebet_home_odds') else None,
        # Forebet
        'forebet': {
            'prediction': row.get('forebet_prediction'),
            'probability': safe_value(row.get('forebet_probability')),
            'exactScore': None,
            'overUnder': None,
            'btts': None,
        } if row.get('forebet_prediction') else None,
        # SofaScore
        'sofascore': {
            'home': safe_value(row.get('sofascore_home_win_prob')),
            'draw': safe_value(row.get('sofascore_draw_prob')),
            'away': safe_value(row.get('sofascore_away_win_prob')),
            'votes': safe_value(row.get('sofascore_total_votes'), 0),
        } if row.get('sofascore_home_win_prob') else None,
        # Gemini AI
        'gemini': {
            'prediction': row.get('gemini_prediction'),
            'confidence': safe_value(row.get('gemini_confidence')),
            'recommendation': row.get('gemini_recommendation'),
            'reasoning': row.get('gemini_reasoning'),
        } if row.get('gemini_prediction') else None,
        # Scoring engine output
        'scoring': {
            'pick': row.get('scoring_pick', ''),
            'prob': safe_value(row.get('scoring_prob')),
            'ev': safe_value(row.get('scoring_ev')),
            'edge': safe_value(row.get('scoring_edge')),
            'kelly': safe_value(row.get('scoring_kelly')),
            'confidence': safe_value(row.get('scoring_confidence')),
            'dataQuality': safe_value(row.get('scoring_data_quality')),
        } if row.get('scoring_pick') else None,
        # Tennis metadata
        'tennis': {
            'surface': row.get('surface', ''),
            'rankingA': row.get('ranking_a'),
            'rankingB': row.get('ranking_b'),
            'probA': safe_value(row.get('scoring_prob_a')),
            'probB': safe_value(row.get('scoring_prob_b')),
        } if row.get('sport') == 'tennis' else None,
        # Top-level confidence: gemini > scoring > forebet
        'confidence': safe_value(row.get('gemini_confidence'))
                      or safe_value(row.get('scoring_confidence'))
                      or safe_value(row.get('forebet_probability'))
                      or 0,
        # Value bet: EV > 0 from scoring engine
        'value_bet': safe_value(row.get('scoring_ev'), 0) > 0,
        # Focus team
        'focusTeam': 'home',
    }


def _resolve_ai_prediction(match):
    """Return AI prediction dict — use pre-computed or generate on the fly."""
    # Pre-computed in pipeline (preferred)
    ai = match.get('ai_prediction')
    if ai and isinstance(ai, dict) and ai.get('pick'):
        return ai
    # Generate on the fly for API-only requests
    try:
        from ai_prediction_engine import generate_ai_prediction
        return generate_ai_prediction(match).to_dict()
    except Exception:
        return None


def normalize_match(match):
    """Normalize match data to frontend format."""
    # Handle different key naming conventions
    
    # v4: Extract match time - prefer HH:MM format
    raw_time = match.get('time') or match.get('match_time', '')
    if raw_time and len(raw_time) > 5 and ':' in raw_time:
        # If it contains date+time like '19.02.2026 20:00', extract just the time
        parts = raw_time.strip().split()
        raw_time = parts[-1] if len(parts) > 1 else raw_time
    
    # v4: Build forebet with all 3 probabilities
    forebet_data = None
    if match.get('forebet_prediction') or match.get('forebet'):
        fb = match.get('forebet') or {}
        forebet_data = {
            'prediction': match.get('forebet_prediction') or fb.get('prediction'),
            'probability': safe_value(match.get('forebet_probability')) or safe_value(fb.get('probability')),
            'exactScore': match.get('forebet_exact_score') or match.get('forebet_score') or fb.get('exactScore'),
            'overUnder': match.get('forebet_over_under') or fb.get('overUnder'),
            'btts': match.get('forebet_btts') or fb.get('btts'),
            'homeProb': safe_value(match.get('forebet_home_prob')) or safe_value(fb.get('homeProb')),
            'drawProb': safe_value(match.get('forebet_draw_prob')) or safe_value(fb.get('drawProb')),
            'awayProb': safe_value(match.get('forebet_away_prob')) or safe_value(fb.get('awayProb')),
        }
    
    # v4: Build gemini from JSON files (was missing before!)
    gemini_data = None
    if match.get('gemini_prediction') or match.get('gemini'):
        gm = match.get('gemini') or {}
        gemini_data = {
            'prediction': match.get('gemini_prediction') or gm.get('prediction'),
            'confidence': safe_value(match.get('gemini_confidence')) or safe_value(gm.get('confidence')),
            'recommendation': match.get('gemini_recommendation') or gm.get('recommendation'),
            'reasoning': match.get('gemini_reasoning') or gm.get('reasoning'),
        }
    
    # Team logos – prefer pre-resolved, else resolve via TheSportsDB
    home_team_val = match.get('home_team') or match.get('homeTeam', '')
    away_team_val = match.get('away_team') or match.get('awayTeam', '')
    home_logo = match.get('home_logo_url') or match.get('homeLogo') or ''
    away_logo = match.get('away_logo_url') or match.get('awayLogo') or ''
    if not home_logo or not away_logo:
        try:
            from team_logo_resolver import get_logo_url
            if not home_logo and home_team_val:
                home_logo = get_logo_url(home_team_val) or ''
            if not away_logo and away_team_val:
                away_logo = get_logo_url(away_team_val) or ''
        except Exception:
            pass

    return {
        'id': match.get('id') or hash(f"{home_team_val}_{away_team_val}"),
        'homeTeam': home_team_val,
        'awayTeam': away_team_val,
        'homeLogo': home_logo,
        'awayLogo': away_logo,
        'time': raw_time,
        'date': match.get('date') or match.get('match_date', ''),
        'league': match.get('league') or match.get('tournament', ''),
        'country': match.get('country', ''),
        'sport': match.get('sport', 'football'),
        'matchUrl': match.get('match_url') or match.get('url', ''),
        'qualifies': match.get('qualifies', False),
        # H2H Data
        'h2h': {
            'home': match.get('h2h_home_wins') or match.get('home_wins_in_h2h_last5') or (match.get('h2h') or {}).get('home', 0),
            'draw': match.get('h2h_draws') or (match.get('h2h') or {}).get('draw', 0),
            'away': match.get('h2h_away_wins') or match.get('away_wins_in_h2h_last5') or (match.get('h2h') or {}).get('away', 0),
            'total': match.get('h2h_total') or match.get('h2h_count') or (match.get('h2h') or {}).get('total', 5),
            'winRate': safe_value(match.get('h2h_win_rate')) or safe_value(match.get('win_rate')) or safe_value((match.get('h2h') or {}).get('winRate', 0)),
        },
        # Form Data
        'homeForm': match.get('home_form') or match.get('homeForm', []),
        'awayForm': match.get('away_form') or match.get('awayForm', []),
        'homeFormHome': match.get('home_form_home') or match.get('homeFormHome', []),
        'awayFormAway': match.get('away_form_away') or match.get('awayFormAway', []),
        'formAdvantage': match.get('form_advantage') or match.get('formAdvantage', False),
        # Odds - używamy safe_value() aby filtrować NaN
        'odds': {
            'home': safe_value(match.get('home_odds')) or safe_value((match.get('odds') or {}).get('home')),
            'draw': safe_value(match.get('draw_odds')) or safe_value((match.get('odds') or {}).get('draw')),
            'away': safe_value(match.get('away_odds')) or safe_value((match.get('odds') or {}).get('away')),
            'bookmaker': match.get('odds_bookmaker') or (match.get('odds') or {}).get('bookmaker', 'Unknown'),
        },
        # Forebet - v4: includes all 3 probabilities
        'forebet': forebet_data,
        # SofaScore - używamy safe_value() aby filtrować NaN
        'sofascore': {
            'home': safe_value(match.get('sofascore_home_win_prob')) or safe_value((match.get('sofascore') or {}).get('home')),
            'draw': safe_value(match.get('sofascore_draw_prob')) or safe_value((match.get('sofascore') or {}).get('draw')),
            'away': safe_value(match.get('sofascore_away_win_prob')) or safe_value((match.get('sofascore') or {}).get('away')),
            'votes': safe_value(match.get('sofascore_total_votes'), 0) or safe_value((match.get('sofascore') or {}).get('votes'), 0),
        } if safe_value(match.get('sofascore_home_win_prob')) or match.get('sofascore') else None,
        # Gemini AI - v4: now included for JSON files too!
        'gemini': gemini_data,
        # Scoring engine output (passed through from JSON export)
        'scoring': match.get('scoring') or ({
            'pick': match.get('scoring_pick', ''),
            'prob': safe_value(match.get('scoring_prob')),
            'ev': safe_value(match.get('scoring_ev')),
            'edge': safe_value(match.get('scoring_edge')),
            'kelly': safe_value(match.get('scoring_kelly')),
            'confidence': safe_value(match.get('scoring_confidence')),
            'dataQuality': safe_value(match.get('scoring_data_quality')),
        } if match.get('scoring_pick') else None),
        # Tennis metadata (passed through from JSON export)
        'tennis': match.get('tennis') or ({
            'surface': match.get('surface', ''),
            'rankingA': match.get('ranking_a'),
            'rankingB': match.get('ranking_b'),
            'probA': safe_value(match.get('scoring_prob_a')),
            'probB': safe_value(match.get('scoring_prob_b')),
        } if match.get('sport') == 'tennis' else None),
        # Top-level confidence: gemini > scoring > forebet
        'confidence': (
            safe_value((gemini_data or {}).get('confidence'))
            or safe_value((match.get('scoring') or {}).get('confidence'))
            or safe_value(match.get('scoring_confidence'))
            or safe_value((forebet_data or {}).get('probability'))
            or 0
        ),
        # Value bet: scoring EV > 0
        'value_bet': (
            safe_value((match.get('scoring') or {}).get('ev'))
            or safe_value(match.get('scoring_ev'))
            or 0
        ) > 0,
        # Focus team
        'focusTeam': match.get('focus_team') or match.get('focusTeam', 'home'),
        # AI Prediction (Ultra PRO analysis)
        'aiPrediction': _resolve_ai_prediction(match),
    }


@app.route('/api/matches', methods=['GET'])
def get_matches():
    """Get matches for a specific date and sport. Supabase first, file fallback."""
    user_date = request.args.get('date')          # explicitly requested by client
    date_str = user_date
    sport = request.args.get('sport', 'all')
    search = request.args.get('search', '').strip().lower()
    only_qualifying = request.args.get('qualifying', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    
    all_matches = []
    source = 'none'
    
    # ── Try Supabase first ──────────────────────────────────────────
    if SUPABASE_AVAILABLE:
        try:
            # If no date, get latest from Supabase
            if not date_str:
                dates = supabase.get_available_dates()
                if dates:
                    date_str = dates[0]
            
            if date_str:
                rows = supabase.get_predictions(date=date_str, sport=sport if sport != 'all' else None)
            else:
                rows = []
            
            if rows:
                source = 'supabase'
                for row in rows:
                    normalized = normalize_supabase_match(row)
                    if sport != 'all' and normalized['sport'] != sport:
                        continue
                    if only_qualifying and not normalized['qualifies']:
                        continue
                    if search:
                        text = f"{normalized['homeTeam']} {normalized['awayTeam']} {normalized.get('league','')}".lower()
                        if search not in text:
                            continue
                    all_matches.append(normalized)
        except Exception as e:
            logger.warning('Supabase fetch failed: %s', e)
    
    # ── Fallback to local JSON files ────────────────────────────────
    if not all_matches:
        # Auto-detect latest date from files when user didn't specify one
        if not user_date:
            import re
            date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
            all_dates = set()
            for f in glob.glob(os.path.join(RESULTS_DIR, '*.json')):
                m = date_pattern.search(os.path.basename(f))
                if m:
                    all_dates.add(m.group(1))
            if all_dates:
                date_str = sorted(all_dates, reverse=True)[0]
            elif not date_str:
                date_str = datetime.now().strftime('%Y-%m-%d')
        
        files = find_result_files(date_str, sport if sport != 'all' else None)
        
        for f in files:
            matches = load_matches_from_file(f)
            for m in matches:
                normalized = normalize_match(m)
                if sport != 'all' and normalized['sport'] != sport:
                    continue
                if only_qualifying and not normalized['qualifies']:
                    continue
                if search:
                    text = f"{normalized['homeTeam']} {normalized['awayTeam']} {normalized.get('league','')}".lower()
                    if search not in text:
                        continue
                all_matches.append(normalized)
        
        if all_matches:
            source = 'files'
    
    # ── Per-sport odds threshold filter (OR condition) ──────────────
    if only_qualifying:
        before = len(all_matches)
        all_matches = [
            m for m in all_matches
            if _passes_sport_odds_threshold(
                m.get('sport', 'football'),
                (m.get('odds') or {}).get('home'),
                (m.get('odds') or {}).get('away'),
            )
        ]
        logger.debug('Per-sport odds filter: %d -> %d matches', before, len(all_matches))

    # Calculate stats
    qualifying_count = sum(1 for m in all_matches if m['qualifies'])
    form_adv_count = sum(1 for m in all_matches if m.get('formAdvantage'))
    
    # Group by sport for counts
    sport_counts = {}
    for m in all_matches:
        s = m['sport']
        sport_counts[s] = sport_counts.get(s, 0) + 1
    
    # Pagination
    start = (page - 1) * per_page
    end = start + per_page
    
    return jsonify({
        'date': date_str,
        'sport': sport,
        'source': source,
        'data': all_matches[start:end],
        'meta': {
            'total': len(all_matches),
            'page': page,
            'per_page': per_page,
            'pages': max(1, math.ceil(len(all_matches) / per_page)),
        },
        'stats': {
            'total': len(all_matches),
            'qualifying': qualifying_count,
            'formAdvantage': form_adv_count
        },
        'sportCounts': sport_counts
    })


@app.route('/api/matches/<match_id>', methods=['GET'])
def get_match(match_id):
    """Get a single match by ID."""
    # Search all available dates
    files = find_result_files()
    for f in files:
        matches = load_matches_from_file(f)
        for m in matches:
            normalized = normalize_match(m)
            if str(normalized['id']) == str(match_id):
                return jsonify(normalized)
    return jsonify({'error': 'Match not found'}), 404


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get aggregated statistics for the dashboard."""
    days = request.args.get('days', 30, type=int)
    
    # Collect matches from recent days
    total_matches = 0
    matches_with_predictions = 0
    matches_with_sofascore = 0
    matches_with_odds = 0
    sport_map = {}  # sport -> { total, with_preds }
    
    for d in range(days):
        date_str = (datetime.now() - timedelta(days=d)).strftime('%Y-%m-%d')
        files = find_result_files(date_str)
        for f in files:
            for m in load_matches_from_file(f):
                nm = normalize_match(m)
                total_matches += 1
                sport = nm['sport']
                if sport not in sport_map:
                    sport_map[sport] = {'total': 0, 'with_predictions': 0}
                sport_map[sport]['total'] += 1
                if nm.get('forebet'):
                    matches_with_predictions += 1
                    sport_map[sport]['with_predictions'] += 1
                if nm.get('sofascore'):
                    matches_with_sofascore += 1
                if nm.get('odds', {}).get('home'):
                    matches_with_odds += 1
    
    sport_breakdown = [
        {
            'sport': s,
            'total': info['total'],
            'with_predictions': info['with_predictions'],
            'accuracy': None  # TODO: compute from settled results
        }
        for s, info in sorted(sport_map.items(), key=lambda x: x[1]['total'], reverse=True)
    ]
    
    return jsonify({
        'total_matches': total_matches,
        'matches_with_predictions': matches_with_predictions,
        'matches_with_sofascore': matches_with_sofascore,
        'matches_with_odds': matches_with_odds,
        'accuracy_7d': None,
        'accuracy_30d': None,
        'roi_7d': None,
        'roi_30d': None,
        'sport_breakdown': sport_breakdown
    })


@app.route('/api/sports', methods=['GET'])
def get_sports():
    """Get list of available sports with counts."""
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    sport_counts = {}
    
    # Try Supabase first
    if SUPABASE_AVAILABLE:
        try:
            sport_counts = supabase.get_sport_counts(date_str)
        except Exception as e:
            logger.warning('Supabase sport counts failed: %s', e)
    
    # Fallback to files
    if not sport_counts:
        files = find_result_files(date_str)
        for f in files:
            matches = load_matches_from_file(f)
            for m in matches:
                sport = m.get('sport', 'football')
                sport_counts[sport] = sport_counts.get(sport, 0) + 1
    
    sports = []
    for sport_id, info in SPORT_INFO.items():
        count = sport_counts.get(sport_id, 0)
        sports.append({
            'id': sport_id,
            'name': info['name'],
            'icon': info['icon'],
            'count': count
        })
    
    # Add "all" option
    total = sum(sport_counts.values())
    sports.insert(0, {'id': 'all', 'name': 'All Sports', 'icon': 'Activity', 'count': total})
    
    return jsonify(sports)


@app.route('/api/dates', methods=['GET'])
def get_available_dates():
    """Get list of dates with available data."""
    import re
    
    dates = set()
    
    # Try Supabase first
    if SUPABASE_AVAILABLE:
        try:
            sb_dates = supabase.get_available_dates()
            if sb_dates:
                dates.update(sb_dates)
        except Exception as e:
            logger.warning('Supabase dates failed: %s', e)
    
    # Also check local files
    files = glob.glob(os.path.join(RESULTS_DIR, '*.json'))
    date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
    for f in files:
        match = date_pattern.search(os.path.basename(f))
        if match:
            dates.add(match.group(1))
    
    # Sort descending (newest first)
    sorted_dates = sorted(dates, reverse=True)
    
    return jsonify({
        'dates': sorted_dates,
        'count': len(sorted_dates)
    })


@app.route('/api/streaks', methods=['GET'])
def get_streaks():
    """Get hot/cold team streaks."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from streak_analyzer import StreakAnalyzer
        
        days = int(request.args.get('days', 30))
        analyzer = StreakAnalyzer()
        matches = analyzer.load_matches_from_files(days)
        
        hot_teams = analyzer.find_hot_teams(matches, min_streak=3)
        cold_teams = analyzer.find_cold_teams(matches, min_streak=3)
        
        return jsonify({
            'hot': [t.to_dict() for t in hot_teams[:10]],
            'cold': [t.to_dict() for t in cold_teams[:10]],
            'period': days
        })
    except Exception as e:
        return jsonify({
            'hot': [],
            'cold': [],
            'error': str(e)
        })


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'resultsDir': RESULTS_DIR,
        'resultsExist': os.path.exists(RESULTS_DIR),
        'supabaseAvailable': SUPABASE_AVAILABLE
    })


# =============================================================================
# 🏆 WORLD CUP — broad analytical package (Pinnacle full markets)
# =============================================================================
def _worldcup_files():
    """Return World Cup result files sorted newest-first."""
    pattern = os.path.join(RESULTS_DIR, 'worldcup_*.json')
    return sorted(glob.glob(pattern), reverse=True)


def _load_worldcup_payload(date_str=None):
    """Load a World Cup payload dict for a date (or latest). Returns dict or None."""
    import re
    files = _worldcup_files()
    if not files:
        return None
    target = None
    if date_str:
        for f in files:
            if date_str in os.path.basename(f):
                target = f
                break
    else:
        target = files[0]
    if not target:
        return None
    try:
        with open(target, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)
    except Exception as e:  # noqa: BLE001
        logger.error('Error loading World Cup file %s: %s', target, e)
        return None


@app.route('/api/worldcup', methods=['GET'])
def get_worldcup():
    """
    Get the full World Cup analytical package for a date (or latest available).

    Query params:
      - date: YYYY-MM-DD (optional; defaults to latest generated day)
      - value: 'true' to return only matches with detected value bets
      - search: filter by team/league substring
    """
    date_str = request.args.get('date')
    only_value = request.args.get('value', 'false').lower() == 'true'
    search = request.args.get('search', '').strip().lower()

    payload = _load_worldcup_payload(date_str)
    if not payload:
        return jsonify({
            'tournament': 'FIFA World Cup 2026',
            'date': date_str,
            'count': 0,
            'matches': [],
            'message': 'No World Cup analysis available yet',
        })

    matches = payload.get('matches', [])

    if only_value:
        matches = [m for m in matches if (m.get('worldcup') or {}).get('value_bets')]
    if search:
        matches = [
            m for m in matches
            if search in f"{m.get('homeTeam', '')} {m.get('awayTeam', '')} "
                         f"{m.get('league', '')}".lower()
        ]

    # Lightweight aggregate stats for the dashboard
    all_matches = payload.get('matches', [])
    value_count = sum(1 for m in all_matches
                      if (m.get('worldcup') or {}).get('value_bets'))
    signal_count = sum(1 for m in all_matches
                       if (m.get('worldcup') or {}).get('signals'))
    kelly_count = sum(1 for m in all_matches
                      if ((m.get('worldcup') or {}).get('kelly') or {}).get('best_value'))
    extras_count = sum(1 for m in all_matches
                       if (m.get('worldcup') or {}).get('forebet_extras'))

    return jsonify({
        'tournament': payload.get('tournament', 'FIFA World Cup 2026'),
        'date': payload.get('date', date_str),
        'generatedAt': payload.get('generatedAt'),
        'bookmaker': payload.get('bookmaker', 'Pinnacle'),
        'count': len(matches),
        'matches': matches,
        'stats': {
            'total': len(all_matches),
            'withValueBets': value_count,
            'withMarketSignals': signal_count,
            'withKellyValue': kelly_count,
            'withForebetExtras': extras_count,
        },
    })


@app.route('/api/worldcup/dates', methods=['GET'])
def get_worldcup_dates():
    """List dates for which a World Cup analytical package exists."""
    import re
    date_pattern = re.compile(r'worldcup_(\d{4}-\d{2}-\d{2})\.json$')
    dates = []
    for f in _worldcup_files():
        m = date_pattern.search(os.path.basename(f))
        if m:
            dates.append(m.group(1))
    return jsonify({'dates': sorted(set(dates), reverse=True)})


# =============================================================================
# USER BETS ENDPOINTS
# =============================================================================

@app.route('/api/bets', methods=['GET'])
@optional_auth
def get_bets():
    """Get user bets with optional filters."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    status = request.args.get('status')  # pending, won, lost, void
    days = request.args.get('days', type=int)
    limit = request.args.get('limit', 100, type=int)
    user_id = getattr(request, 'user_id', 'anonymous')
    
    bets = supabase.get_user_bets(status=status, days=days, limit=limit, user_id=user_id)
    
    return jsonify({
        'bets': bets,
        'count': len(bets),
        'filters': {
            'status': status,
            'days': days,
            'limit': limit
        }
    })


@app.route('/api/bets', methods=['POST'])
@require_auth
def create_bet():
    """Create a new user bet (requires auth)."""
    data = request.get_json()
    
    # Validate required fields
    required = ['home_team', 'away_team', 'match_date', 'bet_selection', 'odds_at_bet']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}'}), 400
    
    # Validate bet_selection
    if data['bet_selection'] not in ('1', 'X', '2'):
        return jsonify({'error': 'bet_selection must be 1, X, or 2'}), 400
    
    # Save bet
    user_id = getattr(request, 'user_id', 'anonymous')
    bet_data = {
        'user_id': user_id,
        'prediction_id': data.get('prediction_id'),
        'match_date': data['match_date'],
        'match_time': data.get('match_time'),
        'home_team': data['home_team'],
        'away_team': data['away_team'],
        'sport': data.get('sport', 'football'),
        'league': data.get('league'),
        'bet_selection': data['bet_selection'],
        'odds_at_bet': float(data['odds_at_bet']),
        'stake': float(data.get('stake', 10.00)),
        'notes': data.get('notes'),
    }
    
    bet_id = None
    
    # Try Supabase first
    if SUPABASE_AVAILABLE:
        try:
            bet_id = supabase.save_user_bet(bet_data)
        except Exception as e:
            logger.warning('Supabase error, falling back to local: %s', e)
    
    # Fallback to local JSON storage
    if not bet_id:
        import time
        bets_file = os.path.join(RESULTS_DIR, 'user_bets.json')
        try:
            if os.path.exists(bets_file):
                with open(bets_file, 'r', encoding='utf-8-sig') as f:
                    bets = json.load(f)
            else:
                bets = []
            
            # Generate local bet ID
            bet_id = int(time.time() * 1000)
            bet_data['id'] = bet_id
            bet_data['status'] = 'pending'
            bet_data['created_at'] = datetime.now().isoformat()
            bets.append(bet_data)
            
            with open(bets_file, 'w', encoding='utf-8') as f:
                json.dump(bets, f, ensure_ascii=False, indent=2)
            
            logger.info('Saved bet locally: %s vs %s - %s @ %s', bet_data['home_team'], bet_data['away_team'], bet_data['bet_selection'], bet_data['odds_at_bet'])
        except Exception as e:
            logger.error('Failed to save bet locally: %s', e)
            return jsonify({'error': f'Failed to create bet: {str(e)}'}), 500
    
    if bet_id:
        return jsonify({
            'success': True,
            'bet_id': bet_id,
            'message': f'Bet created for {data["home_team"]} vs {data["away_team"]}'
        }), 201
    else:
        return jsonify({'error': 'Failed to create bet'}), 500


@app.route('/api/bets/<int:bet_id>', methods=['PUT'])
@require_auth
def update_bet(bet_id):
    """Update bet result (settle bet). Requires auth."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    data = request.get_json()
    
    # Validate required fields for settling
    required = ['actual_result', 'home_score', 'away_score']
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}'}), 400
    
    success = supabase.update_bet_result(
        bet_id=bet_id,
        actual_result=data['actual_result'],
        home_score=int(data['home_score']),
        away_score=int(data['away_score'])
    )
    
    if success:
        return jsonify({
            'success': True,
            'message': f'Bet {bet_id} settled'
        })
    else:
        return jsonify({'error': 'Failed to update bet'}), 500


@app.route('/api/bets/<int:bet_id>', methods=['DELETE'])
@require_auth
def delete_bet(bet_id):
    """Delete a user bet. Requires auth."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    success = supabase.delete_bet(bet_id)
    
    if success:
        return jsonify({
            'success': True,
            'message': f'Bet {bet_id} deleted'
        })
    else:
        return jsonify({'error': 'Failed to delete bet'}), 500


@app.route('/api/bets/stats', methods=['GET'])
@optional_auth
def get_betting_stats():
    """Get user betting statistics."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    stats = supabase.get_user_betting_stats()
    
    return jsonify(stats)


# =============================================================================
# LIVE SCORES ENDPOINT
# =============================================================================

@app.route('/api/live-scores', methods=['GET'])
def get_live_scores():
    """Get live scores from ESPN API with 30-second cache."""
    import time as _time

    sport = request.args.get('sport', 'football')
    now = _time.time()

    # Return cached data if fresh (< 30s)
    cache_key = f"{sport}"
    if (_live_scores_cache.get('key') == cache_key and
            now - _live_scores_cache.get('timestamp', 0) < 30):
        return jsonify({
            'scores': _live_scores_cache['data'],
            'cached': True,
            'sport': sport,
            'timestamp': datetime.now().isoformat()
        })

    if not ESPN_AVAILABLE:
        return jsonify({'scores': [], 'error': 'ESPN API not available', 'sport': sport})

    try:
        # Fetch from multiple soccer leagues for football
        all_matches = []
        if sport == 'football':
            for league in ['premier_league', 'la_liga', 'bundesliga', 'serie_a',
                           'ligue_1', 'champions_league', 'europa_league']:
                try:
                    matches = espn_client.get_soccer_scores(league)
                    all_matches.extend(matches)
                except Exception:
                    continue
        else:
            all_matches = espn_client.get_live_scores(sport)

        scores = [m.to_dict() for m in all_matches]

        # Update cache
        _live_scores_cache['data'] = scores
        _live_scores_cache['timestamp'] = now
        _live_scores_cache['key'] = cache_key

        return jsonify({
            'scores': scores,
            'cached': False,
            'sport': sport,
            'count': len(scores),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'scores': [], 'error': str(e), 'sport': sport})


# Serve sample data for development
@app.route('/api/sample', methods=['GET'])
def get_sample_data():
    """Return sample data for frontend development."""
    sample_matches = [
        {
            'id': 1,
            'homeTeam': 'Arsenal',
            'awayTeam': 'Chelsea', 
            'time': '19:00',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'league': 'Premier League',
            'country': 'England',
            'sport': 'football',
            'qualifies': True,
            'h2h': {'home': 4, 'draw': 1, 'away': 0, 'total': 5, 'winRate': 80},
            'homeForm': ['W', 'W', 'W', 'L', 'W'],
            'awayForm': ['L', 'W', 'D', 'L', 'L'],
            'formAdvantage': True,
            'odds': {'home': 1.85, 'draw': 3.50, 'away': 4.20, 'bookmaker': 'Pinnacle'},
            'forebet': {'prediction': '1', 'probability': 72, 'exactScore': '2-0'},
            'sofascore': {'home': 68, 'draw': 18, 'away': 14, 'votes': 1250},
            'focusTeam': 'home'
        },
        {
            'id': 2,
            'homeTeam': 'Real Madrid',
            'awayTeam': 'Barcelona',
            'time': '20:00', 
            'date': datetime.now().strftime('%Y-%m-%d'),
            'league': 'La Liga',
            'country': 'Spain',
            'sport': 'football',
            'qualifies': True,
            'h2h': {'home': 3, 'draw': 2, 'away': 0, 'total': 5, 'winRate': 60},
            'homeForm': ['W', 'W', 'W', 'W', 'W'],
            'awayForm': ['W', 'W', 'D', 'W', 'L'],
            'formAdvantage': True,
            'odds': {'home': 2.40, 'draw': 3.30, 'away': 2.90, 'bookmaker': 'Pinnacle'},
            'forebet': {'prediction': '1', 'probability': 48},
            'sofascore': {'home': 45, 'draw': 22, 'away': 33, 'votes': 8750},
            'focusTeam': 'home'
        },
        {
            'id': 3,
            'homeTeam': 'Lakers',
            'awayTeam': 'Celtics',
            'time': '02:30',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'league': 'NBA',
            'country': 'USA',
            'sport': 'basketball',
            'qualifies': True,
            'h2h': {'home': 3, 'draw': 0, 'away': 2, 'total': 5, 'winRate': 60},
            'homeForm': ['W', 'W', 'L', 'W', 'W'],
            'awayForm': ['W', 'L', 'W', 'W', 'W'],
            'formAdvantage': False,
            'odds': {'home': 1.95, 'away': 1.90, 'bookmaker': 'Pinnacle'},
            'forebet': {'prediction': '1', 'probability': 55},
            'sofascore': {'home': 52, 'away': 48, 'votes': 890},
            'focusTeam': 'home'
        }
    ]
    
    return jsonify({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'sport': 'all',
        'matches': sample_matches,
        'stats': {
            'total': len(sample_matches),
            'qualifying': 3,
            'formAdvantage': 2
        },
        'sportCounts': {'football': 2, 'basketball': 1}
    })


# =============================================================================
# WEATHER ENDPOINT (Open-Meteo – free, no API key needed)
# =============================================================================

# Simple in-memory cache for weather data (city → data, keyed with date)
_weather_cache: dict = {}

# Mapping of popular football cities → lat/lon
_CITY_COORDS: dict = {
    'london': (51.50, -0.13), 'manchester': (53.48, -2.24), 'liverpool': (53.41, -2.98),
    'madrid': (40.42, -3.70), 'barcelona': (41.39, 2.17), 'seville': (37.39, -5.98),
    'munich': (48.14, 11.58), 'dortmund': (51.51, 7.47), 'berlin': (52.52, 13.40),
    'paris': (48.86, 2.35), 'lyon': (45.76, 4.84), 'marseille': (43.30, 5.37),
    'milan': (45.46, 9.19), 'rome': (41.90, 12.50), 'turin': (45.07, 7.69), 'naples': (40.85, 14.27),
    'amsterdam': (52.37, 4.90), 'lisbon': (38.72, -9.14), 'porto': (41.16, -8.63),
    'warsaw': (52.23, 21.01), 'krakow': (50.06, 19.94), 'lodz': (51.75, 19.47),
    'istanbul': (41.01, 28.98), 'athens': (37.98, 23.73), 'moscow': (55.76, 37.62),
    'buenos aires': (-34.60, -58.38), 'sao paulo': (-23.55, -46.63),
    'new york': (40.71, -74.01), 'los angeles': (34.05, -118.24),
}


def _guess_city_coords(team_or_city: str) -> tuple | None:
    """Try to match a team/city name to known coordinates."""
    lower = team_or_city.lower()
    for city, coords in _CITY_COORDS.items():
        if city in lower:
            return coords
    return None


@app.route('/api/weather', methods=['GET'])
def get_weather():
    """
    Get weather for a match location using Open-Meteo (free, no key).
    Params: ?city=London or ?lat=51.5&lon=-0.13  &date=2026-02-20
    Returns: { temp, feelsLike, windSpeed, humidity, precipitation, weatherCode, description }
    """
    import time as _time
    import urllib.request
    import urllib.error

    city = request.args.get('city', '')
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    # Resolve coordinates
    if lat is None or lon is None:
        coords = _guess_city_coords(city)
        if coords:
            lat, lon = coords
        else:
            return jsonify({'error': f'Unknown city: {city}. Provide lat/lon params.'}), 400

    # Cache key
    cache_key = f"{lat:.2f},{lon:.2f},{date}"
    now = _time.time()
    cached = _weather_cache.get(cache_key)
    if cached and now - cached['ts'] < 3600:  # 1 hour cache
        return jsonify(cached['data'])

    # Fetch from Open-Meteo
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
        f"precipitation_sum,windspeed_10m_max,weathercode"
        f"&timezone=auto&start_date={date}&end_date={date}"
    )

    # Weather code descriptions
    WMO_DESCRIPTIONS = {
        0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
        45: 'Fog', 48: 'Depositing rime fog',
        51: 'Light drizzle', 53: 'Moderate drizzle', 55: 'Dense drizzle',
        61: 'Slight rain', 63: 'Moderate rain', 65: 'Heavy rain',
        66: 'Light freezing rain', 67: 'Heavy freezing rain',
        71: 'Slight snow', 73: 'Moderate snow', 75: 'Heavy snow',
        77: 'Snow grains', 80: 'Slight rain showers', 81: 'Moderate rain showers',
        82: 'Violent rain showers', 85: 'Slight snow showers', 86: 'Heavy snow showers',
        95: 'Thunderstorm', 96: 'Thunderstorm with slight hail', 99: 'Thunderstorm with heavy hail',
    }

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'BigOneSportsApp/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode())

        daily = raw.get('daily', {})
        temp_max = daily.get('temperature_2m_max', [None])[0]
        temp_min = daily.get('temperature_2m_min', [None])[0]
        feels_like = daily.get('apparent_temperature_max', [None])[0]
        precip = daily.get('precipitation_sum', [None])[0]
        wind = daily.get('windspeed_10m_max', [None])[0]
        code = daily.get('weathercode', [None])[0]

        result = {
            'city': city or f'{lat},{lon}',
            'date': date,
            'tempMax': temp_max,
            'tempMin': temp_min,
            'feelsLike': feels_like,
            'precipitation': precip,
            'windSpeed': wind,
            'weatherCode': code,
            'description': WMO_DESCRIPTIONS.get(code, 'Unknown'),
            'unit': '°C',
        }

        _weather_cache[cache_key] = {'data': result, 'ts': now}
        # Prune old cache entries
        if len(_weather_cache) > 200:
            oldest = sorted(_weather_cache.items(), key=lambda x: x[1]['ts'])[:50]
            for k, _ in oldest:
                _weather_cache.pop(k, None)

        return jsonify(result)

    except (urllib.error.URLError, Exception) as e:
        return jsonify({'error': f'Weather fetch failed: {str(e)}'}), 502


# =============================================================================
# FOOTBALL-DATA.ORG ENDPOINTS (free tier: 10 req/min, token via env)
# =============================================================================

_fd_cache: dict = {}  # key → {data, ts}
_FD_TTL = 600  # 10-minute cache

_FD_COMPETITIONS = {
    'PL': 'Premier League',
    'PD': 'La Liga',
    'BL1': 'Bundesliga',
    'SA': 'Serie A',
    'FL1': 'Ligue 1',
    'CL': 'Champions League',
    'EL': 'Europa League',
    'PPL': 'Primeira Liga',
    'DED': 'Eredivisie',
}


def _fd_fetch(path: str) -> dict | None:
    """Fetch from football-data.org with caching and rate-limit awareness."""
    import time as _time
    import urllib.request, urllib.error

    api_key = os.environ.get('FOOTBALL_DATA_API_KEY', '')
    if not api_key:
        return None

    now = _time.time()
    cached = _fd_cache.get(path)
    if cached and now - cached['ts'] < _FD_TTL:
        return cached['data']

    url = f'https://api.football-data.org/v4{path}'
    req = urllib.request.Request(url, headers={
        'X-Auth-Token': api_key,
        'User-Agent': 'BigOneSportsApp/1.0',
    })

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        _fd_cache[path] = {'data': data, 'ts': now}
        return data
    except Exception as e:
        logger.warning('football-data.org %s: %s', path, e)
        return None


@app.route('/api/standings', methods=['GET'])
def get_standings():
    """Get league standings. ?league=PL (default: Premier League)."""
    league = request.args.get('league', 'PL').upper()
    if league not in _FD_COMPETITIONS:
        return jsonify({'error': f'Unknown league code. Available: {list(_FD_COMPETITIONS.keys())}'}), 400

    data = _fd_fetch(f'/competitions/{league}/standings')
    if not data:
        return jsonify({'error': 'Football-Data.org unavailable or API key missing. Set FOOTBALL_DATA_API_KEY env var.'}), 503

    standings = []
    for table in data.get('standings', []):
        if table.get('type') != 'TOTAL':
            continue
        for row in table.get('table', []):
            standings.append({
                'position': row.get('position'),
                'team': row.get('team', {}).get('name', ''),
                'teamCrest': row.get('team', {}).get('crest', ''),
                'played': row.get('playedGames', 0),
                'won': row.get('won', 0),
                'draw': row.get('draw', 0),
                'lost': row.get('lost', 0),
                'goalsFor': row.get('goalsFor', 0),
                'goalsAgainst': row.get('goalsAgainst', 0),
                'goalDifference': row.get('goalDifference', 0),
                'points': row.get('points', 0),
                'form': row.get('form', ''),
            })

    return jsonify({
        'league': _FD_COMPETITIONS.get(league, league),
        'leagueCode': league,
        'season': data.get('season', {}).get('startDate', ''),
        'standings': standings,
    })


@app.route('/api/standings/leagues', methods=['GET'])
def get_available_leagues():
    """Return available league codes for standings."""
    return jsonify({
        'leagues': [{'code': k, 'name': v} for k, v in _FD_COMPETITIONS.items()]
    })


# =============================================================================
# THESPORTSDB ENDPOINTS (free test key = "1", logos & metadata)
# =============================================================================

_tsdb_cache: dict = {}
_TSDB_TTL = 3600  # 1-hour cache for metadata


def _tsdb_fetch(path: str) -> dict | None:
    """Fetch from TheSportsDB free API with caching."""
    import time as _time
    import urllib.request, urllib.error

    api_key = os.environ.get('THESPORTSDB_API_KEY', '1')  # free test key
    now = _time.time()
    cached = _tsdb_cache.get(path)
    if cached and now - cached['ts'] < _TSDB_TTL:
        return cached['data']

    url = f'https://www.thesportsdb.com/api/v1/json/{api_key}{path}'
    req = urllib.request.Request(url, headers={'User-Agent': 'BigOneSportsApp/1.0'})

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        _tsdb_cache[path] = {'data': data, 'ts': now}
        return data
    except Exception as e:
        logger.warning('TheSportsDB %s: %s', path, e)
        return None


@app.route('/api/team-info', methods=['GET'])
def get_team_info():
    """Get team metadata (logo, stadium, description). ?team=Arsenal"""
    team = request.args.get('team', '').strip()
    if not team:
        return jsonify({'error': 'team parameter required'}), 400

    data = _tsdb_fetch(f'/searchteams.php?t={team.replace(" ", "%20")}')
    if not data or not data.get('teams'):
        return jsonify({'error': f'Team not found: {team}'}), 404

    t = data['teams'][0]
    return jsonify({
        'name': t.get('strTeam', ''),
        'nameShort': t.get('strTeamShort', ''),
        'badge': t.get('strBadge', ''),
        'logo': t.get('strLogo', ''),
        'jersey': t.get('strEquipment', ''),
        'stadium': t.get('strStadium', ''),
        'stadiumCapacity': t.get('intStadiumCapacity', ''),
        'stadiumThumb': t.get('strStadiumThumb', ''),
        'country': t.get('strCountry', ''),
        'league': t.get('strLeague', ''),
        'description': (t.get('strDescriptionEN') or '')[:500],
        'formedYear': t.get('intFormedYear', ''),
        'website': t.get('strWebsite', ''),
    })


@app.route('/api/league-info', methods=['GET'])
def get_league_info():
    """Get league metadata. ?league=English Premier League"""
    league = request.args.get('league', '').strip()
    if not league:
        return jsonify({'error': 'league parameter required'}), 400

    data = _tsdb_fetch(f'/search_all_leagues.php?s=Soccer&c={league.replace(" ", "%20")}')
    if not data or not data.get('countrys'):
        # Try direct league search
        data = _tsdb_fetch(f'/search_all_leagues.php?l={league.replace(" ", "%20")}')

    leagues = data.get('countrys') or data.get('leagues') or [] if data else []
    if not leagues:
        return jsonify({'error': f'League not found: {league}'}), 404

    lg = leagues[0]
    return jsonify({
        'name': lg.get('strLeague', ''),
        'badge': lg.get('strBadge', ''),
        'logo': lg.get('strLogo', ''),
        'country': lg.get('strCountry', ''),
        'description': (lg.get('strDescriptionEN') or '')[:500],
    })


# ============================================================================
# Serve Next.js static export (frontend)
# ============================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sports-dashboard', 'out')


@app.route('/')
def serve_frontend():
    """Serve the main index page."""
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.isfile(index_path):
        return send_from_directory(FRONTEND_DIR, 'index.html')
    return jsonify({'error': 'Frontend not built. Run: cd sports-dashboard && npm run build'}), 404


@app.route('/_next/<path:filename>')
def serve_next_static(filename):
    """Serve Next.js static assets (JS, CSS, fonts)."""
    return send_from_directory(os.path.join(FRONTEND_DIR, '_next'), filename)


@app.route('/<path:path>')
def serve_frontend_pages(path):
    """Catch-all: serve frontend pages, static files, or SPA fallback."""
    # Skip API routes (handled by dedicated endpoints above)
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404

    # Try exact file (e.g. favicon.ico, robots.txt)
    exact = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(exact):
        return send_from_directory(FRONTEND_DIR, path)

    # Try with .html extension (e.g. /leaderboard → leaderboard.html)
    html_file = path + '.html'
    if os.path.isfile(os.path.join(FRONTEND_DIR, html_file)):
        return send_from_directory(FRONTEND_DIR, html_file)

    # Try as directory with index.html (e.g. /my-bets → my-bets/index.html)
    dir_index = os.path.join(FRONTEND_DIR, path, 'index.html')
    if os.path.isfile(dir_index):
        return send_from_directory(os.path.join(FRONTEND_DIR, path), 'index.html')

    # SPA fallback – let client-side router handle it
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.isfile(index_path):
        return send_from_directory(FRONTEND_DIR, 'index.html')

    return jsonify({'error': 'Not found'}), 404


if __name__ == '__main__':
    # Create results directory if it doesn't exist
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    # Get port from environment variable (Heroku) or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    logger.info('BigOne API Server — results=%s, port=%d', RESULTS_DIR, port)
    
    # Use debug=False in production (when PORT is set by Heroku)
    app.run(host='0.0.0.0', port=port, debug=('PORT' not in os.environ))
