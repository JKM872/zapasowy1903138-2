"""
Auto Result Updater - Automatyczne aktualizowanie wyników
==========================================================

Monitoruje zakończone mecze i automatycznie aktualizuje wyniki w bazie danych.
Może działać w tle lub być uruchamiany przez scheduler.

Użycie:
    python auto_result_updater.py --check
    python auto_result_updater.py --update
    python auto_result_updater.py --daemon
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import threading

# Local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from supabase_manager import SupabaseManager
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


class AutoResultUpdater:
    """
    Automatycznie pobiera i aktualizuje wyniki meczów.
    Używa SofaScore API lub ESPN jako źródła.
    """
    
    def __init__(self, check_interval: int = 300):
        """
        Args:
            check_interval: Interwał sprawdzania w sekundach (default: 5 min)
        """
        self.check_interval = check_interval
        self.running = False
        self.last_check = None
        self.stats = {
            'checked': 0,
            'updated': 0,
            'errors': 0
        }
    
    def get_pending_predictions(self, date: str = None) -> List[Dict]:
        """Pobiera predykcje bez wyników"""
        if not SUPABASE_AVAILABLE:
            return self._get_pending_from_files(date)
        
        try:
            db = SupabaseManager()
            if date is None:
                date = datetime.now().strftime('%Y-%m-%d')
            
            # Pobierz predykcje bez actual_result
            response = db.client.table('predictions').select('*')\
                .eq('match_date', date)\
                .is_('actual_result', 'null')\
                .execute()
            
            return response.data
        except Exception as e:
            print(f"Blad pobierania predykcji: {e}")
            return []
    
    def _get_pending_from_files(self, date: str = None) -> List[Dict]:
        """Fallback - pobiera z plików JSON"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        matches = []
        outputs_dir = os.path.join(os.path.dirname(__file__), 'outputs')
        
        for sport in ['football', 'basketball', 'volleyball', 'handball', 'hockey']:
            filepath = os.path.join(outputs_dir, f'matches_{date}_{sport}.json')
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for m in data.get('matches', []):
                            if not m.get('actual_result'):
                                m['sport'] = sport
                                matches.append(m)
                except Exception:
                    pass
        
        return matches
    
    def fetch_result_from_api(self, match: Dict) -> Optional[Dict]:
        """Pobiera wynik meczu z API"""
        if not REQUESTS_AVAILABLE:
            return None
        
        # Próbuj SofaScore API
        result = self._fetch_from_sofascore(match)
        if result:
            return result
        
        # Fallback: ESPN API
        result = self._fetch_from_espn(match)
        return result
    
    def _fetch_from_sofascore(self, match: Dict) -> Optional[Dict]:
        """Pobiera wynik z SofaScore"""
        try:
            sport = match.get('sport', 'football')
            sport_slugs = {
                'football': 'football',
                'basketball': 'basketball',
                'volleyball': 'volleyball',
                'handball': 'handball',
                'hockey': 'ice-hockey'
            }
            slug = sport_slugs.get(sport, 'football')
            
            # Szukaj po nazwie drużyny
            home_team = match.get('homeTeam', match.get('home_team', ''))
            
            # Search API
            url = f"https://api.sofascore.com/api/v1/search/events/{home_team}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code != 200:
                return None
            
            events = response.json().get('events', [])
            for event in events:
                status = event.get('status', {}).get('type', '')
                if status == 'finished':
                    return {
                        'home_score': event.get('homeScore', {}).get('current', 0),
                        'away_score': event.get('awayScore', {}).get('current', 0),
                        'result': self._determine_result(
                            event.get('homeScore', {}).get('current', 0),
                            event.get('awayScore', {}).get('current', 0)
                        ),
                        'source': 'sofascore'
                    }
            
            return None
        except Exception as e:
            return None
    
    def _fetch_from_espn(self, match: Dict) -> Optional[Dict]:
        """Pobiera wynik z ESPN"""
        try:
            from espn_api_client import ESPNAPIClient
            
            client = ESPNAPIClient()
            sport = match.get('sport', 'football')
            
            scores = client.get_live_scores(sport)
            
            home_team = match.get('homeTeam', match.get('home_team', '')).lower()
            
            for score in scores:
                if home_team in score.home_team.lower() and score.status == 'finished':
                    return {
                        'home_score': score.home_score,
                        'away_score': score.away_score,
                        'result': self._determine_result(score.home_score, score.away_score),
                        'source': 'espn'
                    }
            
            return None
        except Exception:
            return None
    
    def _determine_result(self, home: int, away: int) -> str:
        """Określa wynik: 1, X, 2"""
        if home > away:
            return '1'
        elif away > home:
            return '2'
        else:
            return 'X'
    
    def update_prediction(self, prediction_id: int, result: Dict) -> bool:
        """Aktualizuje predykcję z wynikiem"""
        if not SUPABASE_AVAILABLE:
            print(f"Supabase niedostepny - wynik: {result}")
            return True
        
        try:
            db = SupabaseManager()
            success = db.update_match_result(
                match_id=prediction_id,
                actual_result=result['result'],
                home_score=result['home_score'],
                away_score=result['away_score']
            )
            return success
        except Exception as e:
            print(f"Blad aktualizacji: {e}")
            return False
    
    def check_and_update(self, date: str = None) -> Dict:
        """Sprawdza i aktualizuje wyniki"""
        pending = self.get_pending_predictions(date)
        
        results = {
            'checked': len(pending),
            'updated': 0,
            'not_finished': 0,
            'errors': 0
        }
        
        for prediction in pending:
            self.stats['checked'] += 1
            
            result = self.fetch_result_from_api(prediction)
            
            if result:
                pred_id = prediction.get('id', prediction.get('match_id'))
                if self.update_prediction(pred_id, result):
                    results['updated'] += 1
                    self.stats['updated'] += 1
                    print(f"Zaktualizowano: {prediction.get('homeTeam', prediction.get('home_team'))} - {result['result']}")
                else:
                    results['errors'] += 1
                    self.stats['errors'] += 1
            else:
                results['not_finished'] += 1
        
        self.last_check = datetime.now()
        return results
    
    def run_daemon(self):
        """Uruchamia demon w tle"""
        self.running = True
        print(f"Auto Result Updater uruchomiony (interval: {self.check_interval}s)")
        
        while self.running:
            try:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Sprawdzam wyniki...")
                results = self.check_and_update()
                print(f"  Sprawdzono: {results['checked']}, Zaktualizowano: {results['updated']}")
            except Exception as e:
                print(f"Blad: {e}")
            
            time.sleep(self.check_interval)
    
    def stop(self):
        """Zatrzymuje demona"""
        self.running = False
        print("Zatrzymywanie...")
    
    def print_stats(self):
        """Wyświetla statystyki"""
        print("\n" + "="*40)
        print("AUTO RESULT UPDATER - STATS")
        print("="*40)
        print(f"Sprawdzono: {self.stats['checked']}")
        print(f"Zaktualizowano: {self.stats['updated']}")
        print(f"Bledy: {self.stats['errors']}")
        if self.last_check:
            print(f"Ostatnie sprawdzenie: {self.last_check.strftime('%H:%M:%S')}")
        print("="*40)


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Auto Result Updater')
    parser.add_argument('--check', action='store_true', help='Sprawdz i zaktualizuj raz')
    parser.add_argument('--daemon', action='store_true', help='Uruchom jako demon')
    parser.add_argument('--interval', type=int, default=300, help='Interwal w sekundach')
    parser.add_argument('--date', type=str, help='Data (YYYY-MM-DD lub "yesterday")')
    parser.add_argument('--mode', type=str, choices=['check', 'update', 'daemon'], help='Tryb działania')
    parser.add_argument('--stats', action='store_true', help='Pokaz statystyki')
    
    args = parser.parse_args()
    
    # Obsługa --date yesterday
    target_date = args.date
    if target_date == 'yesterday':
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        print(f"📅 Weryfikacja predykcji z dnia: {target_date}")
    
    updater = AutoResultUpdater(check_interval=args.interval)
    
    # --mode ma priorytet nad --check/--daemon
    mode = args.mode
    if not mode:
        if args.check:
            mode = 'check'
        elif args.daemon:
            mode = 'daemon'
    
    if mode == 'check':
        print(f"🔍 Sprawdzam wyniki dla: {target_date or 'dzisiaj'}...")
        results = updater.check_and_update(target_date)
        print(f"\n✅ Wyniki weryfikacji:")
        print(f"   Sprawdzono: {results['checked']}")
        print(f"   Zaktualizowano: {results['updated']}")
        print(f"   Niezakończone: {results['not_finished']}")
        print(f"   Błędy: {results['errors']}")
        
        # Oblicz accuracy jeśli mamy dane
        if results['updated'] > 0:
            accuracy = (results['updated'] / results['checked']) * 100 if results['checked'] > 0 else 0
            print(f"\n📊 Wskaźnik aktualizacji: {accuracy:.1f}%")
            
    elif mode == 'update':
        results = updater.check_and_update(target_date)
        print(f"\nWyniki: {results}")
        
    elif mode == 'daemon':
        try:
            updater.run_daemon()
        except KeyboardInterrupt:
            updater.stop()
            updater.print_stats()
            
    elif args.stats:
        updater.print_stats()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

