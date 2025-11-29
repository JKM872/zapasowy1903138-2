"""
🌐 FLASHSCORE API SERVER v2.0
==============================
REST API do scrapowania i pobierania danych o meczach

✨ NOWOŚCI v2.0:
- ✅ Wsparcie dla TENISA (advanced scoring ≥50/100)
- ✅ Filtrowanie meczów bez kursów bukmacherskich
- ✅ Szczegółowe dane: forma, kursy, ranking (tenis)
- ✅ Endpoint dla pojedynczego meczu

Użycie:
    python api_server.py

API będzie dostępne pod: http://localhost:5000

Endpointy:
    GET  /api/health              - Status API
    GET  /api/matches             - Lista kwalifikujących się meczów (z filtrowaniem)
    GET  /api/match/<id>          - Pojedynczy mecz ze szczegółami
    POST /api/scrape              - Uruchom scraping
    GET  /api/scrape/status       - Status aktualnego scrapingu
    GET  /api/sports              - Dostępne sporty (football, basketball, tennis, etc.)
    GET  /api/history             - Historia poprzednich scrapingów
    GET  /api/download/<date>     - Pobierz plik CSV
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pandas as pd
import os
from datetime import datetime, timedelta
import threading
import time
from typing import Dict, List, Optional
import glob

# Import z naszego scrapera
from livesport_h2h_scraper import start_driver, get_match_links_from_day, process_match, process_match_tennis, detect_sport_from_url

app = Flask(__name__)
CORS(app)  # Pozwala na requesty z innych domen (ważne dla web/mobile app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Globalne zmienne do śledzenia statusu scrapingu
scraping_status = {
    'is_running': False,
    'progress': 0,
    'total': 0,
    'current_match': '',
    'start_time': None,
    'qualifying_count': 0,
    'error': None
}


# ============================================
# 1. HEALTH CHECK
# ============================================

@app.route('/api/health', methods=['GET'])
def health():
    """
    Sprawdź czy API działa
    
    Przykład:
        GET /api/health
    """
    return jsonify({
        'status': 'OK',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0',
        'features': [
            'Tennis support (advanced scoring)',
            'Betting odds filtering',
            'Form analysis (3 sources)',
            'Single match details',
            'Multi-sport scraping'
        ],
        'endpoints': {
            'health': '/api/health',
            'matches': '/api/matches',
            'single_match': '/api/match/<id>',
            'scrape': '/api/scrape',
            'status': '/api/scrape/status',
            'sports': '/api/sports',
            'history': '/api/history',
            'download': '/api/download/<date>'
        }
    }), 200


# ============================================
# 2. POBIERZ MECZE
# ============================================

@app.route('/api/matches', methods=['GET'])
def get_matches():
    """
    Pobierz kwalifikujące się mecze
    
    Query params:
        date - Data (YYYY-MM-DD), domyślnie dzisiaj
        sport - Sport (football, basketball, etc.), domyślnie wszystkie
        min_wins - Minimum wygranych (default: 2)
        limit - Limit wyników (default: wszystkie)
        sort - Sortowanie: time/wins/team (default: time)
    
    Przykłady:
        GET /api/matches
        GET /api/matches?date=2025-10-05
        GET /api/matches?date=2025-10-05&sport=football
        GET /api/matches?date=2025-10-05&sport=football&min_wins=3
        GET /api/matches?date=2025-10-05&limit=10&sort=wins
    """
    
    # Parametry
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    sport_filter = request.args.get('sport', None)
    min_wins = int(request.args.get('min_wins', 2))
    limit = request.args.get('limit', None)
    sort_by = request.args.get('sort', 'time')
    
    # Znajdź najnowszy plik CSV dla tej daty
    csv_files = glob.glob(f'outputs/livesport_h2h_{date}*.csv')
    
    if not csv_files:
        return jsonify({
            'error': 'Brak danych dla tej daty',
            'date': date,
            'suggestion': f'Uruchom scraping: POST /api/scrape z body: {{"date": "{date}"}}'
        }), 404
    
    # Weź najnowszy plik
    latest_csv = max(csv_files, key=os.path.getmtime)
    
    try:
        # Wczytaj dane
        df = pd.read_csv(latest_csv)
        
        # Filtruj kwalifikujące się mecze
        qualified = df[df['qualifies'] == True].copy()
        
        # Filtruj po sporcie (jeśli podano)
        if sport_filter:
            qualified = qualified[qualified['match_url'].str.contains(sport_filter, na=False)]
        
        # Filtruj po minimum wygranych (tylko dla sportów drużynowych, nie tenisa)
        # Tennis ma advanced_score zamiast prostego liczenia wygranych
        if min_wins > 0:
            qualified = qualified[qualified['home_wins_in_h2h_last5'] >= min_wins]
        
        # Sortowanie
        if sort_by == 'time':
            # Sortuj po match_time
            qualified = qualified.sort_values('match_time', na_position='last')
        elif sort_by == 'wins':
            qualified = qualified.sort_values('home_wins_in_h2h_last5', ascending=False)
        elif sort_by == 'team':
            qualified = qualified.sort_values('home_team')
        
        # Limit
        if limit:
            qualified = qualified.head(int(limit))
        
        # Konwertuj do listy słowników
        matches = []
        for _, row in qualified.iterrows():
            # Wykryj czy to tenis (ma kolumnę 'favorite' lub 'advanced_score')
            is_tennis = pd.notna(row.get('favorite')) or pd.notna(row.get('advanced_score'))
            
            match = {
                'id': row.get('match_url', '').split('/')[-1],
                'home_team': row.get('home_team', ''),
                'away_team': row.get('away_team', ''),
                'match_time': row.get('match_time', ''),
                'home_wins': int(row.get('home_wins_in_h2h_last5', 0)),
                'h2h_count': int(row.get('h2h_count', 0)),
                'match_url': row.get('match_url', ''),
                'qualifies': bool(row.get('qualifies', False)),
                'is_tennis': is_tennis
            }
            
            # Kursy bukmacherskie
            if pd.notna(row.get('home_odds')):
                match['home_odds'] = float(row['home_odds'])
            if pd.notna(row.get('away_odds')):
                match['away_odds'] = float(row['away_odds'])
            
            # Tennis-specific data
            if is_tennis:
                if pd.notna(row.get('advanced_score')):
                    match['advanced_score'] = float(row['advanced_score'])
                if pd.notna(row.get('favorite')):
                    match['favorite'] = row['favorite']
                if pd.notna(row.get('ranking_a')):
                    match['ranking_a'] = int(row['ranking_a'])
                if pd.notna(row.get('ranking_b')):
                    match['ranking_b'] = int(row['ranking_b'])
                if pd.notna(row.get('surface')):
                    match['surface'] = row['surface']
            
            # Forma drużyn/zawodników (dla wszystkich sportów)
            if pd.notna(row.get('home_form_overall')):
                try:
                    import ast
                    match['home_form_overall'] = ast.literal_eval(row['home_form_overall'])
                except:
                    pass
            if pd.notna(row.get('away_form_overall')):
                try:
                    import ast
                    match['away_form_overall'] = ast.literal_eval(row['away_form_overall'])
                except:
                    pass
            
            # Dodatkowe dane formy dla sportów drużynowych
            if pd.notna(row.get('home_form_home')):
                try:
                    import ast
                    match['home_form_home'] = ast.literal_eval(row['home_form_home'])
                except:
                    pass
            if pd.notna(row.get('away_form_away')):
                try:
                    import ast
                    match['away_form_away'] = ast.literal_eval(row['away_form_away'])
                except:
                    pass
            
            # Przewaga formy
            if pd.notna(row.get('form_advantage')):
                match['form_advantage'] = bool(row['form_advantage'])
            
            # Win rate
            if pd.notna(row.get('win_rate')):
                match['win_rate'] = float(row['win_rate'])
            
            # Dodaj szczegóły H2H jeśli dostępne
            if pd.notna(row.get('h2h_last5')):
                try:
                    import ast
                    match['h2h_details'] = ast.literal_eval(row['h2h_last5'])
                except:
                    match['h2h_details'] = []
            
            matches.append(match)
        
        return jsonify({
            'date': date,
            'total_matches': len(df),
            'qualified_count': len(matches),
            'filters': {
                'sport': sport_filter,
                'min_wins': min_wins,
                'limit': limit,
                'sort': sort_by
            },
            'matches': matches,
            'file': os.path.basename(latest_csv)
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'file': latest_csv
        }), 500


# ============================================
# 3. URUCHOM SCRAPING
# ============================================

def run_scraping_task(date: str, sports: List[str], max_matches: Optional[int] = None):
    """Funkcja do uruchamiania scrapingu w osobnym wątku"""
    # Modyfikujemy słownik globalny (bez global statement bo nie przypisujemy nowej wartości)
    try:
        scraping_status['is_running'] = True
        scraping_status['start_time'] = datetime.now().isoformat()
        scraping_status['error'] = None
        scraping_status['progress'] = 0
        scraping_status['qualifying_count'] = 0
        
        socketio.emit('scraping_status', scraping_status)

        # Start driver
        driver = start_driver(headless=True)
        
        # Zbierz linki
        scraping_status['current_match'] = 'Zbieranie linków...'
        socketio.emit('scraping_status', scraping_status)
        
        all_urls = []
        for sport in sports:
            urls = get_match_links_from_day(driver, date, sports=[sport])
            all_urls.extend(urls)
        
        scraping_status['total'] = len(all_urls)
        
        # Limit
        if max_matches and max_matches < len(all_urls):
            all_urls = all_urls[:max_matches]
            scraping_status['total'] = max_matches
        
        socketio.emit('scraping_status', scraping_status)

        # Scrapuj mecze
        rows = []
        RESTART_INTERVAL = 200
        
        for i, url in enumerate(all_urls, 1):
            scraping_status['progress'] = i
            scraping_status['current_match'] = url[:80]
            socketio.emit('scraping_status', scraping_status)
            
            try:
                # Wykryj sport z URL (tennis ma '/tenis/' w URLu)
                is_tennis = '/tenis/' in url.lower() or 'tennis' in url.lower()
                
                if is_tennis:
                    # Użyj dedykowanej funkcji dla tenisa (ADVANCED)
                    info = process_match_tennis(url, driver)
                else:
                    # Sporty drużynowe (bez Forebet w API - wymaga widocznej przeglądarki)
                    current_sport = detect_sport_from_url(url)
                    info = process_match(url, driver, away_team_focus=False, use_forebet=False, sport=current_sport)
                
                rows.append(info)
                
                if info['qualifies']:
                    scraping_status['qualifying_count'] += 1
                    
            except Exception as e:
                print(f'Błąd przy meczu {url}: {e}')
            
            # Auto-restart
            if i % RESTART_INTERVAL == 0 and i < len(all_urls):
                try:
                    driver.quit()
                    time.sleep(2)
                    driver = start_driver(headless=True)
                except Exception as e:
                    print(f'Błąd restartu: {e}')
                    driver = start_driver(headless=True)
            
            time.sleep(1.5)
        
        # Zapisz wyniki
        df = pd.DataFrame(rows)
        sports_str = '_'.join(sports)
        output_file = f'outputs/livesport_h2h_{date}_{sports_str}_API.csv'
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        scraping_status['output_file'] = output_file
        scraping_status['is_running'] = False
        scraping_status['current_match'] = 'Zakończono!'
        socketio.emit('scraping_status', scraping_status)
        
        driver.quit()
        
    except Exception as e:
        scraping_status['is_running'] = False
        scraping_status['error'] = str(e)
        scraping_status['current_match'] = 'Błąd!'
        socketio.emit('scraping_status', scraping_status)


@app.route('/api/scrape', methods=['POST'])
def start_scraping():
    """
    Uruchom scraping
    
    Body (JSON):
        date - Data (YYYY-MM-DD), wymagane
        sports - Lista sportów, domyślnie wszystkie
        max_matches - Limit meczów (opcjonalne)
    
    Przykłady:
        POST /api/scrape
        Body: {"date": "2025-10-05"}
        
        POST /api/scrape
        Body: {"date": "2025-10-05", "sports": ["football", "basketball"]}
        
        POST /api/scrape
        Body: {"date": "2025-10-05", "sports": ["football"], "max_matches": 100}
    """
    # Czytamy słownik globalny (bez global statement bo tylko czytamy)
    if scraping_status['is_running']:
        return jsonify({
            'error': 'Scraping już trwa',
            'status': scraping_status
        }), 409
    
    data = request.get_json()
    
    if not data or 'date' not in data:
        return jsonify({
            'error': 'Brak parametru "date" w body',
            'example': {
                'date': '2025-10-05',
                'sports': ['football', 'basketball'],
                'max_matches': 100
            }
        }), 400
    
    date = data['date']
    sports = data.get('sports', ['football', 'basketball', 'volleyball', 'handball', 'rugby', 'hockey'])
    max_matches = data.get('max_matches', None)
    
    # Walidacja daty
    try:
        datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return jsonify({
            'error': 'Nieprawidłowy format daty. Użyj YYYY-MM-DD',
            'example': '2025-10-05'
        }), 400
    
    # Uruchom w osobnym wątku
    socketio.start_background_task(run_scraping_task, date, sports, max_matches)
    
    return jsonify({
        'message': 'Scraping rozpoczęty',
        'date': date,
        'sports': sports,
        'max_matches': max_matches,
        'status_url': '/api/scrape/status'
    }), 202


@app.route('/api/scrape/status', methods=['GET'])
def get_scraping_status():
    """
    Sprawdź status aktualnego scrapingu
    
    Przykład:
        GET /api/scrape/status
    """
    # Czytamy słownik globalny (bez global statement bo tylko czytamy)
    status_copy = scraping_status.copy()
    
    # Dodaj procent postępu
    if status_copy['total'] > 0:
        status_copy['percent'] = round((status_copy['progress'] / status_copy['total']) * 100, 1)
    else:
        status_copy['percent'] = 0
    
    # Oszacuj czas pozostały
    if status_copy['is_running'] and status_copy['start_time'] and status_copy['progress'] > 0:
        start = datetime.fromisoformat(status_copy['start_time'])
        elapsed = (datetime.now() - start).total_seconds()
        avg_time_per_match = elapsed / status_copy['progress']
        remaining_matches = status_copy['total'] - status_copy['progress']
        estimated_seconds = remaining_matches * avg_time_per_match
        status_copy['estimated_time_remaining'] = f"{int(estimated_seconds // 60)}m {int(estimated_seconds % 60)}s"
    
    return jsonify(status_copy), 200


# ============================================
# 4. DOSTĘPNE SPORTY
# ============================================

@app.route('/api/sports', methods=['GET'])
def get_sports():
    """
    Lista dostępnych sportów
    
    Przykład:
        GET /api/sports
    """
    sports = [
        {'id': 'football', 'name': 'Piłka nożna', 'icon': '⚽', 'type': 'team'},
        {'id': 'basketball', 'name': 'Koszykówka', 'icon': '🏀', 'type': 'team'},
        {'id': 'volleyball', 'name': 'Siatkówka', 'icon': '🏐', 'type': 'team'},
        {'id': 'handball', 'name': 'Piłka ręczna', 'icon': '🤾', 'type': 'team'},
        {'id': 'rugby', 'name': 'Rugby', 'icon': '🏉', 'type': 'team'},
        {'id': 'hockey', 'name': 'Hokej', 'icon': '🏒', 'type': 'team'},
        {'id': 'tennis', 'name': 'Tenis', 'icon': '🎾', 'type': 'individual', 'scoring': 'advanced'}
    ]
    
    return jsonify({
        'sports': sports,
        'count': len(sports),
        'info': {
            'team_sports': 'Wymagają ≥60% H2H + dobrej formy',
            'tennis': 'Advanced scoring ≥50/100 (H2H + ranking + forma + powierzchnia)'
        }
    }), 200


# ============================================
# 5. HISTORIA
# ============================================

@app.route('/api/history', methods=['GET'])
def get_history():
    """
    Historia poprzednich scrapingów
    
    Query params:
        limit - Limit wyników (default: 10)
    
    Przykład:
        GET /api/history
        GET /api/history?limit=5
    """
    limit = int(request.args.get('limit', 10))
    
    # Znajdź wszystkie pliki CSV
    csv_files = glob.glob('outputs/livesport_h2h_*.csv')
    
    if not csv_files:
        return jsonify({
            'history': [],
            'count': 0
        }), 200
    
    # Sortuj po dacie modyfikacji (najnowsze pierwsze)
    csv_files.sort(key=os.path.getmtime, reverse=True)
    csv_files = csv_files[:limit]
    
    history = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            qualified = df[df['qualifies'] == True]
            
            # Wyciągnij datę z nazwy pliku
            filename = os.path.basename(csv_file)
            date_part = filename.split('_')[2]  # livesport_h2h_2025-10-05_...
            
            history.append({
                'date': date_part,
                'file': filename,
                'total_matches': len(df),
                'qualified_count': len(qualified),
                'modified': datetime.fromtimestamp(os.path.getmtime(csv_file)).isoformat(),
                'size_kb': round(os.path.getsize(csv_file) / 1024, 2)
            })
        except Exception as e:
            print(f'Błąd przy przetwarzaniu {csv_file}: {e}')
    
    return jsonify({
        'history': history,
        'count': len(history)
    }), 200


# ============================================
# 6. POBIERZ POJEDYNCZY MECZ
# ============================================

@app.route('/api/match/<match_id>', methods=['GET'])
def get_single_match(match_id):
    """
    Pobierz szczegóły pojedynczego meczu
    
    Query params:
        date - Data (YYYY-MM-DD), domyślnie dzisiaj
    
    Przykład:
        GET /api/match/abc123?date=2025-10-05
    """
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    # Znajdź pliki CSV dla tej daty
    csv_files = glob.glob(f'outputs/livesport_h2h_{date}*.csv')
    
    if not csv_files:
        return jsonify({
            'error': f'Brak danych dla daty {date}',
            'match_id': match_id
        }), 404
    
    # Szukaj w wszystkich plikach dla tej daty
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            
            # Znajdź mecz po ID (ostatnia część URL)
            match_row = df[df['match_url'].str.contains(match_id, na=False)]
            
            if len(match_row) > 0:
                row = match_row.iloc[0]
                
                # Wykryj czy to tenis
                is_tennis = pd.notna(row.get('favorite')) or pd.notna(row.get('advanced_score'))
                
                # Zbuduj pełny obiekt meczu
                match = {
                    'id': match_id,
                    'home_team': row.get('home_team', ''),
                    'away_team': row.get('away_team', ''),
                    'match_time': row.get('match_time', ''),
                    'match_url': row.get('match_url', ''),
                    'qualifies': bool(row.get('qualifies', False)),
                    'is_tennis': is_tennis,
                    'h2h_count': int(row.get('h2h_count', 0)),
                    'home_wins': int(row.get('home_wins_in_h2h_last5', 0)),
                }
                
                # Kursy
                if pd.notna(row.get('home_odds')):
                    match['home_odds'] = float(row['home_odds'])
                if pd.notna(row.get('away_odds')):
                    match['away_odds'] = float(row['away_odds'])
                
                # Tennis-specific
                if is_tennis:
                    if pd.notna(row.get('advanced_score')):
                        match['advanced_score'] = float(row['advanced_score'])
                    if pd.notna(row.get('favorite')):
                        match['favorite'] = row['favorite']
                    if pd.notna(row.get('ranking_a')):
                        match['ranking_a'] = int(row['ranking_a'])
                    if pd.notna(row.get('ranking_b')):
                        match['ranking_b'] = int(row['ranking_b'])
                    if pd.notna(row.get('surface')):
                        match['surface'] = row['surface']
                    
                    # Forma zawodników
                    if pd.notna(row.get('form_a')):
                        try:
                            import ast
                            match['form_a'] = ast.literal_eval(row['form_a'])
                        except:
                            pass
                    if pd.notna(row.get('form_b')):
                        try:
                            import ast
                            match['form_b'] = ast.literal_eval(row['form_b'])
                        except:
                            pass
                
                # Forma drużyn
                if pd.notna(row.get('home_form_overall')):
                    try:
                        import ast
                        match['home_form_overall'] = ast.literal_eval(row['home_form_overall'])
                    except:
                        pass
                if pd.notna(row.get('away_form_overall')):
                    try:
                        import ast
                        match['away_form_overall'] = ast.literal_eval(row['away_form_overall'])
                    except:
                        pass
                if pd.notna(row.get('home_form_home')):
                    try:
                        import ast
                        match['home_form_home'] = ast.literal_eval(row['home_form_home'])
                    except:
                        pass
                if pd.notna(row.get('away_form_away')):
                    try:
                        import ast
                        match['away_form_away'] = ast.literal_eval(row['away_form_away'])
                    except:
                        pass
                
                # Przewaga formy i win rate
                if pd.notna(row.get('form_advantage')):
                    match['form_advantage'] = bool(row['form_advantage'])
                if pd.notna(row.get('win_rate')):
                    match['win_rate'] = float(row['win_rate'])
                
                # H2H details
                if pd.notna(row.get('h2h_last5')):
                    try:
                        import ast
                        match['h2h_details'] = ast.literal_eval(row['h2h_last5'])
                    except:
                        match['h2h_details'] = []
                
                return jsonify({
                    'match': match,
                    'found_in': os.path.basename(csv_file)
                }), 200
        
        except Exception as e:
            continue
    
    # Nie znaleziono
    return jsonify({
        'error': f'Nie znaleziono meczu {match_id} dla daty {date}',
        'match_id': match_id,
        'date': date
    }), 404


# ============================================
# 7. POBIERZ PLIK CSV
# ============================================

@app.route('/api/download/<date>', methods=['GET'])
def download_csv(date):
    """
    Pobierz plik CSV dla danej daty
    
    Przykład:
        GET /api/download/2025-10-05
    """
    csv_files = glob.glob(f'outputs/livesport_h2h_{date}*.csv')
    
    if not csv_files:
        return jsonify({
            'error': f'Brak pliku dla daty {date}'
        }), 404
    
    latest_csv = max(csv_files, key=os.path.getmtime)
    
    return send_file(
        latest_csv,
        mimetype='text/csv',
        as_attachment=True,
        download_name=os.path.basename(latest_csv)
    )


# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    print('='*60)
    print('🌐 FLASHSCORE API SERVER')
    print('='*60)
    print()
    print('🚀 Server uruchomiony!')
    print('📍 URL: http://localhost:5000')
    print()
    print('📖 Dokumentacja:')
    print('   GET  /api/health           - Status API')
    print('   GET  /api/matches          - Lista meczów (z filtrowaniem)')
    print('   GET  /api/match/<id>       - Pojedynczy mecz (szczegóły)')
    print('   POST /api/scrape           - Uruchom scraping')
    print('   GET  /api/scrape/status    - Status scrapingu')
    print('   GET  /api/sports           - Dostępne sporty')
    print('   GET  /api/history          - Historia scrapingów')
    print('   GET  /api/download/<date>  - Pobierz CSV')
    print()
    print('💡 Przykłady użycia: Zobacz API_EXAMPLES.md')
    print('='*60)
    print()
    
    # Utwórz folder outputs jeśli nie istnieje
    os.makedirs('outputs', exist_ok=True)
    
    # Uruchom server
    socketio.run(
        app,
        host='0.0.0.0',  # Dostępne z innych urządzeń w sieci
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True
    )


