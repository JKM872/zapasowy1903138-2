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
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS


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
    print(f"[WARNING] Supabase not available: {e}")
    supabase = None
    SUPABASE_AVAILABLE = False

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

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
        print(f"Error loading {filepath}: {e}")
        return []


def normalize_match(match):
    """Normalize match data to frontend format."""
    # Handle different key naming conventions
    return {
        'id': match.get('id') or hash(f"{match.get('home_team', match.get('homeTeam', ''))}_{match.get('away_team', match.get('awayTeam', ''))}"),
        'homeTeam': match.get('home_team') or match.get('homeTeam', ''),
        'awayTeam': match.get('away_team') or match.get('awayTeam', ''),
        'time': match.get('time') or match.get('match_time', ''),
        'date': match.get('date') or match.get('match_date', ''),
        'league': match.get('league') or match.get('tournament', ''),
        'country': match.get('country', ''),
        'sport': match.get('sport', 'football'),
        'matchUrl': match.get('match_url') or match.get('url', ''),
        'qualifies': match.get('qualifies', False),
        # H2H Data
        'h2h': {
            'home': match.get('h2h_home_wins') or match.get('h2h', {}).get('home', 0),
            'draw': match.get('h2h_draws') or match.get('h2h', {}).get('draw', 0),
            'away': match.get('h2h_away_wins') or match.get('h2h', {}).get('away', 0),
            'total': match.get('h2h_total') or match.get('h2h', {}).get('total', 5),
            'winRate': match.get('h2h_win_rate') or match.get('h2h', {}).get('winRate', 0),
        },
        # Form Data
        'homeForm': match.get('home_form') or match.get('homeForm', []),
        'awayForm': match.get('away_form') or match.get('awayForm', []),
        'homeFormHome': match.get('home_form_home') or match.get('homeFormHome', []),
        'awayFormAway': match.get('away_form_away') or match.get('awayFormAway', []),
        'formAdvantage': match.get('form_advantage') or match.get('formAdvantage', False),
        # Odds - używamy safe_value() aby filtrować NaN
        'odds': {
            'home': safe_value(match.get('home_odds')) or safe_value(match.get('odds', {}).get('home')),
            'draw': safe_value(match.get('draw_odds')) or safe_value(match.get('odds', {}).get('draw')),
            'away': safe_value(match.get('away_odds')) or safe_value(match.get('odds', {}).get('away')),
            'bookmaker': match.get('odds_bookmaker') or match.get('odds', {}).get('bookmaker', 'Unknown'),
        },
        # Forebet - używamy safe_value() dla probability
        'forebet': {
            'prediction': match.get('forebet_prediction') or match.get('forebet', {}).get('prediction'),
            'probability': safe_value(match.get('forebet_probability')) or safe_value(match.get('forebet', {}).get('probability')),
            'exactScore': match.get('forebet_score') or match.get('forebet', {}).get('exactScore'),
            'overUnder': match.get('forebet_over_under') or match.get('forebet', {}).get('overUnder'),
            'btts': match.get('forebet_btts') or match.get('forebet', {}).get('btts'),
        } if match.get('forebet_prediction') or match.get('forebet') else None,
        # SofaScore - używamy safe_value() aby filtrować NaN
        'sofascore': {
            'home': safe_value(match.get('sofascore_home_win_prob')) or safe_value(match.get('sofascore', {}).get('home')),
            'draw': safe_value(match.get('sofascore_draw_prob')) or safe_value(match.get('sofascore', {}).get('draw')),
            'away': safe_value(match.get('sofascore_away_win_prob')) or safe_value(match.get('sofascore', {}).get('away')),
            'votes': safe_value(match.get('sofascore_total_votes'), 0) or safe_value(match.get('sofascore', {}).get('votes'), 0),
        } if safe_value(match.get('sofascore_home_win_prob')) or match.get('sofascore') else None,
        # Focus team
        'focusTeam': match.get('focus_team') or match.get('focusTeam', 'home'),
    }


@app.route('/api/matches', methods=['GET'])
def get_matches():
    """Get matches for a specific date and sport."""
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    sport = request.args.get('sport', 'all')
    only_qualifying = request.args.get('qualifying', 'false').lower() == 'true'
    
    # Find matching files
    files = find_result_files(date_str, sport if sport != 'all' else None)
    
    all_matches = []
    for f in files:
        matches = load_matches_from_file(f)
        for m in matches:
            normalized = normalize_match(m)
            if sport != 'all' and normalized['sport'] != sport:
                continue
            if only_qualifying and not normalized['qualifies']:
                continue
            all_matches.append(normalized)
    
    # Calculate stats
    qualifying_count = sum(1 for m in all_matches if m['qualifies'])
    form_adv_count = sum(1 for m in all_matches if m.get('formAdvantage'))
    
    # Group by sport for counts
    sport_counts = {}
    for m in all_matches:
        s = m['sport']
        sport_counts[s] = sport_counts.get(s, 0) + 1
    
    return jsonify({
        'date': date_str,
        'sport': sport,
        'matches': all_matches,
        'stats': {
            'total': len(all_matches),
            'qualifying': qualifying_count,
            'formAdvantage': form_adv_count
        },
        'sportCounts': sport_counts
    })


@app.route('/api/sports', methods=['GET'])
def get_sports():
    """Get list of available sports with counts."""
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    files = find_result_files(date_str)
    
    sport_counts = {}
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
    
    files = glob.glob(os.path.join(RESULTS_DIR, '*.json'))
    dates = set()
    
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
# USER BETS ENDPOINTS
# =============================================================================

@app.route('/api/bets', methods=['GET'])
def get_bets():
    """Get user bets with optional filters."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    status = request.args.get('status')  # pending, won, lost, void
    days = request.args.get('days', type=int)
    limit = request.args.get('limit', 100, type=int)
    
    bets = supabase.get_user_bets(status=status, days=days, limit=limit)
    
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
def create_bet():
    """Create a new user bet."""
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
    bet_data = {
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
            print(f"[WARNING] Supabase error, falling back to local: {e}")
    
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
            
            print(f"[OK] Saved bet locally: {bet_data['home_team']} vs {bet_data['away_team']} - {bet_data['bet_selection']} @ {bet_data['odds_at_bet']}")
        except Exception as e:
            print(f"[ERROR] Failed to save bet locally: {e}")
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
def update_bet(bet_id):
    """Update bet result (settle bet)."""
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
def delete_bet(bet_id):
    """Delete a user bet."""
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
def get_betting_stats():
    """Get user betting statistics."""
    if not SUPABASE_AVAILABLE:
        return jsonify({'error': 'Supabase not available'}), 503
    
    stats = supabase.get_user_betting_stats()
    
    return jsonify(stats)


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


if __name__ == '__main__':
    # Create results directory if it doesn't exist
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    print("=" * 60)
    print("BigOne API Server")
    print("=" * 60)
    print(f"Results directory: {RESULTS_DIR}")
    print(f"Starting server on http://localhost:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
