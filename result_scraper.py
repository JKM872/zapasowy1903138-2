"""
Result Scraper - Automatyczne pobieranie wyników meczów
========================================================

Scrapuje wyniki zakończonych meczów i aktualizuje bazę danych.
Obsługuje: Livesport, FlashScore jako źródła wyników.

Użycie:
    python result_scraper.py --date 2025-12-15
    python result_scraper.py --yesterday
    python result_scraper.py --test
"""

import os
import sys
import json
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Requests for API
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# Local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from supabase_manager import SupabaseManager
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


@dataclass
class MatchResult:
    """Reprezentuje wynik meczu"""
    match_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    result: str  # '1', 'X', '2'
    sport: str
    date: str
    status: str = "finished"  # finished, postponed, cancelled
    
    @property
    def winner(self) -> str:
        if self.home_score > self.away_score:
            return "1"
        elif self.home_score < self.away_score:
            return "2"
        else:
            return "X"
    
    def to_dict(self) -> Dict:
        return {
            "match_id": self.match_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "result": self.result,
            "sport": self.sport,
            "date": self.date,
            "status": self.status
        }


class ResultScraper:
    """
    Główna klasa do scrapowania wyników meczów.
    Obsługuje wiele źródeł danych.
    """
    
    SPORT_URLS = {
        'football': 'https://www.livesport.com/pl/pilka-nozna/',
        'basketball': 'https://www.livesport.com/pl/koszykowka/',
        'volleyball': 'https://www.livesport.com/pl/siatkowka/',
        'handball': 'https://www.livesport.com/pl/pilka-reczna/',
        'hockey': 'https://www.livesport.com/pl/hokej/',
        'tennis': 'https://www.livesport.com/pl/tenis/'
    }
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        self.results: List[MatchResult] = []
    
    def _init_driver(self):
        """Inicjalizuje WebDriver"""
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium nie jest zainstalowany")
        
        options = Options()
        if self.headless:
            options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(30)
    
    def _close_driver(self):
        """Zamyka WebDriver"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
    
    def scrape_results_for_date(self, date: str, sports: List[str] = None) -> List[MatchResult]:
        """
        Scrapuje wyniki dla podanej daty.
        
        Args:
            date: Data w formacie YYYY-MM-DD
            sports: Lista sportów (domyślnie wszystkie)
            
        Returns:
            Lista MatchResult
        """
        if sports is None:
            sports = list(self.SPORT_URLS.keys())
        
        all_results = []
        
        try:
            self._init_driver()
            
            for sport in sports:
                print(f"\n{'='*50}")
                print(f"Scrapuję wyniki: {sport.upper()} - {date}")
                print('='*50)
                
                sport_results = self._scrape_sport_results(sport, date)
                all_results.extend(sport_results)
                print(f"Znaleziono {len(sport_results)} wyników dla {sport}")
                
                time.sleep(1)  # Rate limiting
        
        finally:
            self._close_driver()
        
        self.results = all_results
        return all_results
    
    def _scrape_sport_results(self, sport: str, date: str) -> List[MatchResult]:
        """Scrapuje wyniki dla konkretnego sportu"""
        results = []
        
        base_url = self.SPORT_URLS.get(sport)
        if not base_url:
            print(f"Nieobsługiwany sport: {sport}")
            return results
        
        # Format daty dla URL
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        url = f"{base_url}wyniki/?d={date}"
        
        try:
            self.driver.get(url)
            time.sleep(3)
            
            # Akceptuj cookies jeśli pojawi się popup
            self._accept_cookies()
            
            # Poczekaj na załadowanie meczów
            time.sleep(2)
            
            # Znajdź wszystkie zakończone mecze
            page_source = self.driver.page_source
            
            # Parsuj zakończone mecze z HTML
            results = self._parse_finished_matches(page_source, sport, date)
            
        except TimeoutException:
            print(f"Timeout podczas ładowania {url}")
        except Exception as e:
            print(f"Błąd scrapowania {sport}: {e}")
        
        return results
    
    def _accept_cookies(self):
        """Akceptuje cookies popup"""
        try:
            cookie_btn = self.driver.find_element(By.ID, "onetrust-accept-btn-handler")
            if cookie_btn.is_displayed():
                cookie_btn.click()
                time.sleep(0.5)
        except NoSuchElementException:
            pass
        except Exception:
            pass
    
    def _parse_finished_matches(self, html: str, sport: str, date: str) -> List[MatchResult]:
        """Parsuje zakończone mecze z HTML"""
        results = []
        
        # Regex patterns dla wyników
        # Szukamy wzorców typu: "Team A 2 - 1 Team B" lub podobnych
        
        # Pattern dla zakończonych meczów (FT, AET, etc.)
        score_pattern = r'(\d+)\s*[-:]\s*(\d+)'
        
        # Znajdź wszystkie elementy z wynikami
        # Livesport używa klas jak "event__match" dla meczów
        
        match_blocks = re.findall(
            r'event__match[^>]*>.*?event__scores.*?<span[^>]*>(\d+)</span>.*?<span[^>]*>(\d+)</span>.*?'
            r'event__participant.*?>(.*?)</.*?event__participant.*?>(.*?)</.*?',
            html, re.DOTALL | re.IGNORECASE
        )
        
        # Alternatywny prosty parsing
        if not match_blocks:
            # Szukaj prostszych wzorców
            simple_pattern = r'([A-Za-z\s\.\-]+)\s+(\d+)\s*[-:]\s*(\d+)\s+([A-Za-z\s\.\-]+)'
            simple_matches = re.findall(simple_pattern, html)
            
            for i, (home, h_score, a_score, away) in enumerate(simple_matches[:20]):  # Limit
                home = home.strip()
                away = away.strip()
                
                if len(home) > 3 and len(away) > 3:  # Filtruj śmieci
                    try:
                        result = MatchResult(
                            match_id=f"{sport}_{date}_{i}",
                            home_team=home,
                            away_team=away,
                            home_score=int(h_score),
                            away_score=int(a_score),
                            result=self._determine_result(int(h_score), int(a_score), sport),
                            sport=sport,
                            date=date
                        )
                        results.append(result)
                    except (ValueError, Exception):
                        continue
        
        return results
    
    def _determine_result(self, home_score: int, away_score: int, sport: str) -> str:
        """Określa wynik meczu"""
        if home_score > away_score:
            return "1"
        elif home_score < away_score:
            return "2"
        else:
            # Dla sportów bez remisów
            if sport in ['basketball', 'volleyball', 'tennis']:
                return "1" if home_score > away_score else "2"
            return "X"
    
    def match_with_predictions(self, results: List[MatchResult], predictions: List[Dict]) -> List[Dict]:
        """
        Dopasowuje wyniki do predykcji.
        
        Args:
            results: Lista wyników
            predictions: Lista predykcji z bazy
            
        Returns:
            Lista matched updates
        """
        matched = []
        
        for result in results:
            for pred in predictions:
                # Dopasowanie po nazwach drużyn
                pred_home = pred.get('home_team', '').lower()
                pred_away = pred.get('away_team', '').lower()
                res_home = result.home_team.lower()
                res_away = result.away_team.lower()
                
                # Sprawdź podobieństwo
                if (self._teams_similar(pred_home, res_home) and 
                    self._teams_similar(pred_away, res_away)):
                    
                    matched.append({
                        'prediction_id': pred.get('id'),
                        'actual_result': result.result,
                        'home_score': result.home_score,
                        'away_score': result.away_score,
                        'status': result.status
                    })
                    break
        
        return matched
    
    def _teams_similar(self, name1: str, name2: str, threshold: float = 0.6) -> bool:
        """Sprawdza podobieństwo nazw drużyn"""
        from difflib import SequenceMatcher
        
        # Normalizacja
        n1 = re.sub(r'[^a-z0-9]', '', name1.lower())
        n2 = re.sub(r'[^a-z0-9]', '', name2.lower())
        
        return SequenceMatcher(None, n1, n2).ratio() >= threshold
    
    def update_database(self, matched_results: List[Dict]) -> Tuple[int, int]:
        """
        Aktualizuje bazę danych z wynikami.
        
        Returns:
            Tuple (updated_count, error_count)
        """
        if not SUPABASE_AVAILABLE:
            print("Supabase niedostępny")
            return 0, len(matched_results)
        
        db = SupabaseManager()
        updated = 0
        errors = 0
        
        for match in matched_results:
            try:
                success = db.update_match_result(
                    match_id=match['prediction_id'],
                    actual_result=match['actual_result'],
                    home_score=match['home_score'],
                    away_score=match['away_score']
                )
                if success:
                    updated += 1
                else:
                    errors += 1
            except Exception as e:
                print(f"Błąd aktualizacji: {e}")
                errors += 1
        
        return updated, errors
    
    def save_results_to_file(self, results: List[MatchResult], filename: str = None):
        """Zapisuje wyniki do pliku JSON"""
        if filename is None:
            date = results[0].date if results else datetime.now().strftime('%Y-%m-%d')
            filename = f"outputs/results_{date}.json"
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        data = {
            'date': results[0].date if results else None,
            'scraped_at': datetime.now().isoformat(),
            'count': len(results),
            'results': [r.to_dict() for r in results]
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Zapisano {len(results)} wyników do {filename}")
    
    def print_summary(self, results: List[MatchResult]):
        """Wyświetla podsumowanie wyników"""
        print("\n" + "="*60)
        print("PODSUMOWANIE WYNIKÓW")
        print("="*60)
        
        # Grupuj po sportach
        by_sport = {}
        for r in results:
            if r.sport not in by_sport:
                by_sport[r.sport] = []
            by_sport[r.sport].append(r)
        
        for sport, sport_results in by_sport.items():
            print(f"\n{sport.upper()}: {len(sport_results)} meczów")
            home_wins = sum(1 for r in sport_results if r.result == '1')
            draws = sum(1 for r in sport_results if r.result == 'X')
            away_wins = sum(1 for r in sport_results if r.result == '2')
            print(f"   1: {home_wins} | X: {draws} | 2: {away_wins}")
        
        print("\n" + "="*60)


def scrape_results_via_api(date: str, sport: str = 'football') -> List[MatchResult]:
    """
    Alternatywna metoda - pobieranie wyników przez API.
    Używa SofaScore API jako źródła.
    """
    if not REQUESTS_AVAILABLE:
        return []
    
    results = []
    
    sport_slugs = {
        'football': 'football',
        'basketball': 'basketball',
        'volleyball': 'volleyball',
        'handball': 'handball',
        'hockey': 'ice-hockey',
        'tennis': 'tennis'
    }
    
    slug = sport_slugs.get(sport, sport)
    url = f"https://api.sofascore.com/api/v1/sport/{slug}/scheduled-events/{date}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            events = data.get('events', [])
            
            for event in events:
                # Tylko zakończone mecze
                status = event.get('status', {}).get('type', '')
                if status != 'finished':
                    continue
                
                home = event.get('homeTeam', {}).get('name', '')
                away = event.get('awayTeam', {}).get('name', '')
                home_score = event.get('homeScore', {}).get('current', 0)
                away_score = event.get('awayScore', {}).get('current', 0)
                
                result = MatchResult(
                    match_id=str(event.get('id', '')),
                    home_team=home,
                    away_team=away,
                    home_score=home_score,
                    away_score=away_score,
                    result='1' if home_score > away_score else '2' if away_score > home_score else 'X',
                    sport=sport,
                    date=date
                )
                results.append(result)
    
    except Exception as e:
        print(f"Błąd API: {e}")
    
    return results


def main():
    """Główna funkcja CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Result Scraper dla BigOne')
    parser.add_argument('--date', type=str, help='Data (YYYY-MM-DD)')
    parser.add_argument('--yesterday', action='store_true', help='Wczorajsze wyniki')
    parser.add_argument('--sports', nargs='+', help='Lista sportów')
    parser.add_argument('--test', action='store_true', help='Tryb testowy')
    parser.add_argument('--api', action='store_true', help='Użyj API zamiast scrapingu')
    parser.add_argument('--save', action='store_true', help='Zapisz do pliku')
    
    args = parser.parse_args()
    
    # Określ datę
    if args.yesterday:
        date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    elif args.date:
        date = args.date
    else:
        date = datetime.now().strftime('%Y-%m-%d')
    
    sports = args.sports or ['football', 'basketball']
    
    print(f"\nPobieranie wyników dla: {date}")
    print(f"Sporty: {sports}")
    
    if args.api:
        # Użyj API
        all_results = []
        for sport in sports:
            results = scrape_results_via_api(date, sport)
            all_results.extend(results)
            print(f"{sport}: {len(results)} wyników")
        
        if all_results:
            scraper = ResultScraper()
            scraper.print_summary(all_results)
            if args.save:
                scraper.save_results_to_file(all_results)
    else:
        # Użyj Selenium
        scraper = ResultScraper(headless=True)
        results = scraper.scrape_results_for_date(date, sports)
        
        scraper.print_summary(results)
        
        if args.save:
            scraper.save_results_to_file(results)
    
    if args.test:
        print("\n[TEST MODE] Nie aktualizuję bazy danych")
    

if __name__ == '__main__':
    main()
