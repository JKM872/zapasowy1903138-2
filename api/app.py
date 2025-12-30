"""
Flask API Server for Sports Prediction Dashboard
Provides REST endpoints for accessing prediction data from Supabase
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_manager import SupabaseManager

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Initialize Supabase manager
db = SupabaseManager()


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })


@app.route('/api/predictions/recent', methods=['GET'])
def get_recent_predictions():
    """
    Get recent predictions
    Query params:
    - days: number of days to look back (default: 7)
    - sport: filter by sport (optional)
    - qualified: filter qualified only (optional, default: false)
    """
    try:
        days = request.args.get('days', 7, type=int)
        sport = request.args.get('sport', None)
        qualified_only = request.args.get('qualified', 'false').lower() == 'true'
        
        # Build query
        query = db.client.table('predictions').select('*')
        
        # Date filter
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        query = query.gte('match_date', since_date)
        
        # Sport filter
        if sport:
            query = query.eq('sport', sport)
        
        # Qualified filter
        if qualified_only:
            query = query.eq('qualifies', True)
        
        # Order by date descending
        query = query.order('match_date', desc=True).order('match_time', desc=True)
        
        response = query.execute()
        
        return jsonify({
            'success': True,
            'count': len(response.data),
            'predictions': response.data
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/predictions/stats', methods=['GET'])
def get_statistics():
    """
    Get overall statistics
    Query params:
    - days: number of days to look back (default: 30)
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        # Get all predictions in time range
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        response = db.client.table('predictions').select('*').gte('match_date', since_date).execute()
        
        predictions = response.data
        total = len(predictions)
        qualified = sum(1 for p in predictions if p.get('qualifies'))
        with_results = sum(1 for p in predictions if p.get('actual_result'))
        
        # Calculate accuracy by sport
        sports_stats = {}
        for pred in predictions:
            sport = pred.get('sport', 'unknown')
            if sport not in sports_stats:
                sports_stats[sport] = {'total': 0, 'qualified': 0, 'with_results': 0}
            
            sports_stats[sport]['total'] += 1
            if pred.get('qualifies'):
                sports_stats[sport]['qualified'] += 1
            if pred.get('actual_result'):
                sports_stats[sport]['with_results'] += 1
        
        return jsonify({
            'success': True,
            'period_days': days,
            'total_predictions': total,
            'qualified_predictions': qualified,
            'predictions_with_results': with_results,
            'by_sport': sports_stats
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/accuracy', methods=['GET'])
def get_accuracy():
    """
    Get accuracy statistics for all sources
    Query params:
    - days: number of days to look back (default: 30)
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        # Get accuracy from Supabase manager
        accuracy_data = db.get_all_sources_accuracy(days=days)
        
        return jsonify({
            'success': True,
            'period_days': days,
            'sources': accuracy_data
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/predictions/today', methods=['GET'])
def get_today_predictions():
    """Get predictions for today"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        
        response = db.client.table('predictions').select('*').eq('match_date', today).order('match_time').execute()
        
        return jsonify({
            'success': True,
            'date': today,
            'count': len(response.data),
            'predictions': response.data
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/predictions/upcoming', methods=['GET'])
def get_upcoming_predictions():
    """Get upcoming predictions (next 7 days)"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        next_week = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        
        response = db.client.table('predictions').select('*')\
            .gte('match_date', today)\
            .lte('match_date', next_week)\
            .eq('qualifies', True)\
            .order('match_date')\
            .order('match_time')\
            .execute()
        
        # Group by date
        by_date = {}
        for pred in response.data:
            date = pred['match_date']
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(pred)
        
        return jsonify({
            'success': True,
            'start_date': today,
            'end_date': next_week,
            'total_count': len(response.data),
            'by_date': by_date
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/predictions/<int:prediction_id>', methods=['GET'])
def get_prediction_detail(prediction_id):
    """Get detailed information about a specific prediction"""
    try:
        response = db.client.table('predictions').select('*').eq('id', prediction_id).execute()
        
        if not response.data:
            return jsonify({
                'success': False,
                'error': 'Prediction not found'
            }), 404
        
        return jsonify({
            'success': True,
            'prediction': response.data[0]
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/predictions/<int:prediction_id>/result', methods=['POST'])
def update_prediction_result(prediction_id):
    """
    Update the result of a prediction
    Body: {actual_result: '1'/'X'/'2', home_score: int, away_score: int}
    """
    try:
        data = request.json
        
        success = db.update_match_result(
            match_id=prediction_id,
            actual_result=data.get('actual_result'),
            home_score=data.get('home_score'),
            away_score=data.get('away_score')
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Result updated successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to update result'
            }), 500
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/consensus', methods=['GET'])
def get_consensus_picks():
    """
    Get consensus picks (matches where multiple sources agree)
    Query params:
    - days: number of days to look back (default: 7)
    - min_agreement: minimum sources agreeing (2-4, default: 3)
    """
    try:
        days = request.args.get('days', 7, type=int)
        min_agreement = request.args.get('min_agreement', 3, type=int)
        
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        response = db.client.table('predictions').select('*')\
            .gte('match_date', since_date)\
            .eq('qualifies', True)\
            .execute()
        
        # Calculate consensus for each prediction
        consensus_picks = []
        for pred in response.data:
            agreement_count = 0
            sources_agreeing = []
            
            # Check each source
            if pred.get('livesport_win_rate', 0) >= 60:
                agreement_count += 1
                sources_agreeing.append('LiveSport')
            
            if pred.get('forebet_prediction') == '1':
                agreement_count += 1
                sources_agreeing.append('Forebet')
            
            if pred.get('sofascore_home_win_prob', 0) > pred.get('sofascore_away_win_prob', 0):
                agreement_count += 1
                sources_agreeing.append('SofaScore')
            
            if pred.get('gemini_recommendation') in ['HIGH', 'LOCK']:
                agreement_count += 1
                sources_agreeing.append('Gemini')
            
            if agreement_count >= min_agreement:
                pred['consensus_count'] = agreement_count
                pred['sources_agreeing'] = sources_agreeing
                consensus_picks.append(pred)
        
        # Sort by consensus count (highest first)
        consensus_picks.sort(key=lambda x: x['consensus_count'], reverse=True)
        
        return jsonify({
            'success': True,
            'period_days': days,
            'min_agreement': min_agreement,
            'count': len(consensus_picks),
            'picks': consensus_picks
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/roi', methods=['GET'])
def get_roi_stats():
    """
    Get ROI statistics from ROI Tracker
    Query params:
    - days: number of days to look back (default: 30)
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        # Try to import and use ROI Tracker
        try:
            from roi_tracker import ROITracker
            tracker = ROITracker()
            stats = tracker.get_stats(days)
            
            return jsonify({
                'success': True,
                'period_days': days,
                'stats': stats.to_dict()
            })
        except ImportError:
            # Fallback with demo data
            return jsonify({
                'success': True,
                'period_days': days,
                'stats': {
                    'total_bets': 0,
                    'settled_bets': 0,
                    'wins': 0,
                    'losses': 0,
                    'pending': 0,
                    'total_staked': 0,
                    'total_profit': 0,
                    'roi_percent': 0,
                    'win_rate': 0,
                    'average_odds': 0,
                    'streak_current': 0,
                    'streak_best': 0
                },
                'note': 'ROI Tracker not initialized yet'
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/matches', methods=['GET'])
def get_matches():
    """
    Get matches from local JSON files or database
    Query params:
    - date: date string YYYY-MM-DD (default: today)
    - sport: filter by sport (default: all)
    """
    import json
    
    try:
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        sport = request.args.get('sport', 'all')
        
        matches = []
        stats = {'total': 0, 'qualifying': 0, 'formAdvantage': 0}
        
        # Try to load from local JSON files first
        outputs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'outputs')
        results_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'results')
        
        sports_to_check = ['football', 'basketball', 'volleyball', 'handball', 'hockey', 'tennis']
        if sport != 'all':
            sports_to_check = [sport]
        
        for s in sports_to_check:
            # Check multiple possible file locations
            possible_files = [
                os.path.join(outputs_dir, f'matches_{date}_{s}.json'),
                os.path.join(results_dir, f'matches_{date}_{s}.json'),
                os.path.join(outputs_dir, f'livesport_h2h_{date}_{s}.json')
            ]
            
            for filepath in possible_files:
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            file_matches = data.get('matches', [])
                            for m in file_matches:
                                m['sport'] = s
                            matches.extend(file_matches)
                            break
                    except Exception:
                        pass
        
        # Calculate stats
        stats['total'] = len(matches)
        stats['qualifying'] = sum(1 for m in matches if m.get('qualifies'))
        stats['formAdvantage'] = sum(1 for m in matches if m.get('formAdvantage'))
        
        return jsonify({
            'success': True,
            'date': date,
            'sport': sport,
            'stats': stats,
            'matches': matches
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sports', methods=['GET'])
def get_sports():
    """Get list of sports with match counts"""
    try:
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        sports = [
            {'id': 'all', 'name': 'All Sports', 'icon': 'Activity', 'count': 0},
            {'id': 'football', 'name': 'Football', 'icon': 'Circle', 'count': 0},
            {'id': 'basketball', 'name': 'Basketball', 'icon': 'Disc', 'count': 0},
            {'id': 'volleyball', 'name': 'Volleyball', 'icon': 'Circle', 'count': 0},
            {'id': 'handball', 'name': 'Handball', 'icon': 'Target', 'count': 0},
            {'id': 'hockey', 'name': 'Hockey', 'icon': 'Zap', 'count': 0},
            {'id': 'tennis', 'name': 'Tennis', 'icon': 'Circle', 'count': 0}
        ]
        
        return jsonify(sports)
    
    except Exception as e:
        return jsonify([])


@app.route('/api/sample', methods=['GET'])
def get_sample_data():
    """Get sample data for development/testing"""
    sample_matches = [
        {
            'id': 1,
            'homeTeam': 'Manchester United',
            'awayTeam': 'Liverpool',
            'time': '15:00',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'league': 'Premier League',
            'country': 'England',
            'sport': 'football',
            'qualifies': True,
            'h2h': {'home': 3, 'draw': 1, 'away': 1, 'total': 5, 'winRate': 60},
            'homeForm': ['W', 'W', 'L', 'W', 'D'],
            'awayForm': ['W', 'D', 'W', 'L', 'W'],
            'formAdvantage': True,
            'odds': {'home': 2.10, 'draw': 3.40, 'away': 3.20, 'bookmaker': 'Pinnacle'},
            'forebet': {'prediction': '1', 'probability': 55},
            'sofascore': {'home': 52, 'draw': 24, 'away': 24, 'votes': 1500},
            'focusTeam': 'home'
        },
        {
            'id': 2,
            'homeTeam': 'Real Madrid',
            'awayTeam': 'Barcelona',
            'time': '21:00',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'league': 'La Liga',
            'country': 'Spain',
            'sport': 'football',
            'qualifies': True,
            'h2h': {'home': 4, 'draw': 0, 'away': 1, 'total': 5, 'winRate': 80},
            'homeForm': ['W', 'W', 'W', 'W', 'D'],
            'awayForm': ['L', 'W', 'W', 'L', 'W'],
            'formAdvantage': True,
            'odds': {'home': 1.85, 'draw': 3.60, 'away': 4.20, 'bookmaker': 'Pinnacle'},
            'forebet': {'prediction': '1', 'probability': 65},
            'sofascore': {'home': 58, 'draw': 22, 'away': 20, 'votes': 3200},
            'focusTeam': 'home'
        }
    ]
    
    return jsonify({
        'success': True,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'stats': {'total': 2, 'qualifying': 2, 'formAdvantage': 2},
        'matches': sample_matches
    })


@app.route('/api/live', methods=['GET'])
def get_live_matches():
    """
    Get live/in-progress matches
    Returns matches that are currently being played
    """
    import json
    
    try:
        # Try to get live data from SofaScore API
        live_matches = []
        
        sports = ['football', 'basketball', 'volleyball', 'handball', 'hockey']
        
        for sport in sports:
            try:
                import requests
                sport_slugs = {
                    'football': 'football',
                    'basketball': 'basketball',
                    'volleyball': 'volleyball',
                    'handball': 'handball',
                    'hockey': 'ice-hockey'
                }
                slug = sport_slugs.get(sport, sport)
                url = f"https://api.sofascore.com/api/v1/sport/{slug}/events/live"
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    events = data.get('events', [])[:10]  # Limit per sport
                    
                    for event in events:
                        status = event.get('status', {})
                        home_team = event.get('homeTeam', {}).get('name', '')
                        away_team = event.get('awayTeam', {}).get('name', '')
                        home_score = event.get('homeScore', {}).get('current', 0)
                        away_score = event.get('awayScore', {}).get('current', 0)
                        
                        match_status = 'live'
                        if status.get('type') == 'inprogress':
                            match_status = 'live'
                        elif status.get('code') == 31:  # Halftime
                            match_status = 'halftime'
                        
                        live_matches.append({
                            'id': str(event.get('id', '')),
                            'homeTeam': home_team,
                            'awayTeam': away_team,
                            'homeScore': home_score,
                            'awayScore': away_score,
                            'minute': status.get('description', ''),
                            'status': match_status,
                            'sport': sport,
                            'league': event.get('tournament', {}).get('name', '')
                        })
            except Exception:
                pass
        
        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'count': len(live_matches),
            'matches': live_matches
        })
    
    except Exception as e:
        # Return demo data on error
        demo_live = [
            {
                'id': 'demo_1',
                'homeTeam': 'Team A',
                'awayTeam': 'Team B',
                'homeScore': 1,
                'awayScore': 0,
                'minute': '45',
                'status': 'halftime',
                'sport': 'football',
                'league': 'Demo League'
            }
        ]
        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'count': len(demo_live),
            'matches': demo_live,
            'demo': True
        })


@app.route('/api/results/today', methods=['GET'])
def get_today_results():
    """
    Get finished matches from today with results
    """
    import json
    
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        results = []
        
        # Load from result files
        outputs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey']:
            filepath = os.path.join(outputs_dir, f'results_{today}_{sport}.json')
            
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for r in data.get('results', []):
                            r['sport'] = sport
                            results.append(r)
                except Exception:
                    pass
        
        # Calculate stats
        home_wins = sum(1 for r in results if r.get('result') == '1')
        draws = sum(1 for r in results if r.get('result') == 'X')
        away_wins = sum(1 for r in results if r.get('result') == '2')
        
        return jsonify({
            'success': True,
            'date': today,
            'count': len(results),
            'stats': {
                'home_wins': home_wins,
                'draws': draws,
                'away_wins': away_wins
            },
            'results': results
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/calibration', methods=['GET'])
def get_calibration():
    """Get calibration weights for confidence scoring"""
    try:
        from confidence_calibrator import ConfidenceCalibrator
        
        calibrator = ConfidenceCalibrator()
        
        return jsonify({
            'success': True,
            'weights': calibrator.weights,
            'default_weights': calibrator.DEFAULT_WEIGHTS
        })
    except ImportError:
        return jsonify({
            'success': True,
            'weights': {
                'livesport': 1.0,
                'forebet': 1.2,
                'sofascore': 1.0,
                'gemini': 1.5,
                'consensus': 2.0
            },
            'note': 'Using default weights'
        })


if __name__ == '__main__':
    print("Starting Sports Prediction API Server...")
    print("Dashboard: http://localhost:5000")
    print("API Docs: http://localhost:5000/api/health")
    app.run(debug=True, host='0.0.0.0', port=5000)

