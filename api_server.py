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
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Directory with scraper results
RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')

# Sport mappings
SPORT_INFO = {
    'football': {'name': 'Football', 'icon': 'Circle'},
    'basketball': {'name': 'Basketball', 'icon': 'Disc'},
    'volleyball': {'name': 'Volleyball', 'icon': 'Circle'},
    'handball': {'name': 'Handball', 'icon': 'Target'},
    'hockey': {'name': 'Hockey', 'icon': 'Zap'},
    'tennis': {'name': 'Tennis', 'icon': 'Circle'}
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
        with open(filepath, 'r', encoding='utf-8') as f:
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
        # Odds
        'odds': {
            'home': match.get('home_odds') or match.get('odds', {}).get('home'),
            'draw': match.get('draw_odds') or match.get('odds', {}).get('draw'),
            'away': match.get('away_odds') or match.get('odds', {}).get('away'),
            'bookmaker': match.get('odds_bookmaker') or match.get('odds', {}).get('bookmaker', 'Unknown'),
        },
        # Forebet
        'forebet': {
            'prediction': match.get('forebet_prediction') or match.get('forebet', {}).get('prediction'),
            'probability': match.get('forebet_probability') or match.get('forebet', {}).get('probability'),
            'exactScore': match.get('forebet_score') or match.get('forebet', {}).get('exactScore'),
            'overUnder': match.get('forebet_over_under') or match.get('forebet', {}).get('overUnder'),
            'btts': match.get('forebet_btts') or match.get('forebet', {}).get('btts'),
        } if match.get('forebet_prediction') or match.get('forebet') else None,
        # SofaScore
        'sofascore': {
            'home': match.get('sofascore_home_win_prob') or match.get('sofascore', {}).get('home'),
            'draw': match.get('sofascore_draw_prob') or match.get('sofascore', {}).get('draw'),
            'away': match.get('sofascore_away_win_prob') or match.get('sofascore', {}).get('away'),
            'votes': match.get('sofascore_total_votes') or match.get('sofascore', {}).get('votes', 0),
        } if match.get('sofascore_home_win_prob') or match.get('sofascore') else None,
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
        'resultsExist': os.path.exists(RESULTS_DIR)
    })


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
