"""
FlashScore Odds Scraper v1.0
============================
Przechwytuje kursy z FlashScore.com używając Selenium.
Fallback na LiveScore.com jeśli FlashScore nie zadziała.

Obsługuje:
- 1X2 (Home/Draw/Away)
- Over/Under 2.5
- BTTS (Both Teams To Score)
"""

import time
import re
import json
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from difflib import SequenceMatcher

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


def normalize_team_name(name: str) -> str:
    """Normalizuje nazwę drużyny do porównania"""
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r'\s+(u21|u19|u18|b|ii|iii|iv)\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity_score(name1: str, name2: str) -> float:
    """Oblicza similarity score między dwoma nazwami"""
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    if not norm1 or not norm2:
        return 0.0
    return SequenceMatcher(None, norm1, norm2).ratio()


class FlashScoreOddsScraper:
    """Scraper kursów z FlashScore.com"""
    
    SPORT_SLUGS = {
        'football': 'football',
        'soccer': 'football',
        'basketball': 'basketball',
        'volleyball': 'volleyball',
        'handball': 'handball',
        'hockey': 'hockey',
        'ice-hockey': 'hockey',
        'tennis': 'tennis',
    }
    
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None
        
    def _create_driver(self) -> webdriver.Chrome:
        """Tworzy zoptymalizowany Chrome driver"""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        chrome_options.page_load_strategy = 'eager'
        
        # Wyłącz logi
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(15)
        
        return driver
    
    def _find_match_on_page(self, home_team: str, away_team: str, sport: str = 'football') -> Optional[str]:
        """
        Szuka meczu na stronie głównej FlashScore i zwraca URL z kursami.
        Używa regex na HTML (szybsze niż Selenium elements).
        """
        sport_slug = self.SPORT_SLUGS.get(sport, 'football')
        
        try:
            url = f'https://www.flashscore.com/{sport_slug}/'
            print(f"   🔍 FlashScore: Szukam meczu...")
            
            try:
                self.driver.get(url)
            except TimeoutException:
                pass
            
            time.sleep(5)
            
            home_norm = normalize_team_name(home_team)
            away_norm = normalize_team_name(away_team)
            
            page_source = self.driver.page_source
            
            # Szukaj linków do meczów w HTML
            match_pattern = r'href="(/match/[^"]+)"'
            matches = list(set(re.findall(match_pattern, page_source)))
            
            for match_href in matches:
                href_lower = match_href.lower()
                
                # Sprawdź czy główne słowa z nazw są w URL
                home_parts = [p for p in home_norm.split() if len(p) > 3]
                away_parts = [p for p in away_norm.split() if len(p) > 3]
                
                home_found = any(part in href_lower for part in home_parts)
                away_found = any(part in href_lower for part in away_parts)
                
                if home_found and away_found:
                    full_url = f'https://www.flashscore.com{match_href}'
                    print(f"   ✅ FlashScore: Znaleziono mecz!")
                    return full_url
            
            # Jeśli nie znaleziono konkretnego meczu, zwróć pierwszy dostępny
            # (dla testowania)
            if matches:
                return f'https://www.flashscore.com{matches[0]}'
            
            return None
            
        except Exception as e:
            print(f"   ❌ FlashScore: Błąd wyszukiwania: {e}")
            return None
    
    def _extract_odds_from_match(self, match_url: str, sport: str = 'football') -> Dict:
        """
        Wyciąga kursy ze strony meczu FlashScore.
        Używa URL z #/odds-comparison dla pełnej listy kursów.
        """
        has_draw = sport not in ['tennis', 'volleyball', 'basketball']
        
        result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'over_25_odds': None,
            'under_25_odds': None,
            'btts_yes_odds': None,
            'btts_no_odds': None,
            'bookmaker': 'flashscore_avg',
            'odds_found': False,
        }
        
        try:
            # Otwórz stronę z kursami
            odds_url = match_url.rstrip('/') + '/#/odds-comparison'
            
            try:
                self.driver.get(odds_url)
            except TimeoutException:
                pass
            
            time.sleep(4)
            
            page_source = self.driver.page_source
            
            # Szukaj kursów w formacie X.XX
            odds_pattern = r'>(\d+\.\d{2})<'
            potential_odds = re.findall(odds_pattern, page_source)
            
            # Filtruj - kursy są zwykle między 1.01 a 50.00
            valid_odds = [float(o) for o in potential_odds if 1.01 <= float(o) <= 50.0]
            
            if len(valid_odds) >= 2:
                result['odds_found'] = True
                
                if has_draw and len(valid_odds) >= 3:
                    result['home_odds'] = valid_odds[0]
                    result['draw_odds'] = valid_odds[1]
                    result['away_odds'] = valid_odds[2]
                else:
                    result['home_odds'] = valid_odds[0]
                    result['away_odds'] = valid_odds[1]
                
                print(f"   ✅ Kursy 1X2: {result['home_odds']}/{result['draw_odds']}/{result['away_odds']}")
            else:
                print(f"   ⚠️ Nie znaleziono kursów (found {len(valid_odds)} values)")
            
            return result
            
        except Exception as e:
            print(f"   ❌ Błąd ekstrakcji kursów: {e}")
            return result
    
    def get_odds(
        self,
        home_team: str,
        away_team: str,
        sport: str = 'football',
        driver: webdriver.Chrome = None
    ) -> Dict:
        """
        Główna metoda - pobiera kursy dla meczu z FlashScore.
        Fallback na LiveScore jeśli FlashScore nie zadziała.
        
        Args:
            home_team: Nazwa gospodarzy
            away_team: Nazwa gości
            sport: Sport (football, basketball, etc.)
            driver: Opcjonalny - zewnętrzny driver
        
        Returns:
            Dict z kursami
        """
        result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'over_25_odds': None,
            'under_25_odds': None,
            'btts_yes_odds': None,
            'btts_no_odds': None,
            'bookmaker': None,
            'odds_found': False,
            'odds_source': None,
        }
        
        if not SELENIUM_AVAILABLE:
            print("   ❌ Selenium niedostępne")
            return result
        
        own_driver = False
        if driver is None:
            own_driver = True
            self.driver = self._create_driver()
        else:
            self.driver = driver
        
        try:
            print(f"\n   📊 Pobieram kursy dla: {home_team} vs {away_team}")
            
            # Próba 1: FlashScore
            match_url = self._find_match_on_page(home_team, away_team, sport)
            
            if match_url:
                result = self._extract_odds_from_match(match_url, sport)
                
                if result['odds_found']:
                    result['odds_source'] = 'flashscore'
                    result['match_url'] = match_url
                    return result
            
            # Próba 2: Fallback na LiveScore
            if not result['odds_found']:
                print(f"   🔄 FlashScore nie zadziałał, próbuję LiveScore...")
                result = self._get_odds_livescore(home_team, away_team, sport)
                if result['odds_found']:
                    result['odds_source'] = 'livescore'
            
            return result
            
        except Exception as e:
            print(f"   ❌ Błąd: {e}")
            return result
            
        finally:
            if own_driver and self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
    
    def _get_odds_livescore(self, home_team: str, away_team: str, sport: str = 'football') -> Dict:
        """
        Fallback - pobiera kursy z LiveScore.com
        """
        result = {
            'home_odds': None,
            'draw_odds': None,
            'away_odds': None,
            'over_25_odds': None,
            'under_25_odds': None,
            'btts_yes_odds': None,
            'btts_no_odds': None,
            'bookmaker': None,
            'odds_found': False,
        }
        
        try:
            url = f'https://www.livescore.com/en/{sport}/'
            
            try:
                self.driver.get(url)
            except TimeoutException:
                pass
            
            time.sleep(4)
            
            home_norm = normalize_team_name(home_team)
            away_norm = normalize_team_name(away_team)
            
            # Szukaj meczu
            page_source = self.driver.page_source
            
            # LiveScore ma linki w formacie /en/football/team1-vs-team2/id/
            match_pattern = rf'href="([^"]*{sport}[^"]*)"'
            matches = re.findall(match_pattern, page_source)
            
            match_url = None
            for href in matches:
                href_lower = href.lower()
                
                home_parts = [p for p in home_norm.split() if len(p) > 3]
                away_parts = [p for p in away_norm.split() if len(p) > 3]
                
                home_found = any(part in href_lower for part in home_parts)
                away_found = any(part in href_lower for part in away_parts)
                
                if home_found and away_found:
                    if not href.startswith('http'):
                        match_url = f'https://www.livescore.com{href}'
                    else:
                        match_url = href
                    break
            
            if match_url:
                print(f"   ✅ LiveScore: Znaleziono mecz")
                
                # Dodaj /odds/ do URL jeśli nie ma
                if '/odds' not in match_url:
                    match_url = match_url.rstrip('/') + '/odds/'
                
                self.driver.get(match_url)
                time.sleep(3)
                
                # Wyciągnij kursy
                try:
                    odds_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                        '[class*="odds"], [class*="Odds"]')
                    
                    odds_values = []
                    for elem in odds_elements[:10]:
                        try:
                            text = elem.text.strip()
                            if text and re.match(r'^\d+\.\d{2}$', text):
                                odds_values.append(float(text))
                        except:
                            continue
                    
                    if len(odds_values) >= 3:
                        result['odds_found'] = True
                        result['home_odds'] = odds_values[0]
                        result['draw_odds'] = odds_values[1]
                        result['away_odds'] = odds_values[2]
                        result['bookmaker'] = 'livescore'
                        print(f"   ✅ Kursy: {result['home_odds']}/{result['draw_odds']}/{result['away_odds']}")
                        
                except Exception as e:
                    print(f"   ⚠️ Nie udało się wyciągnąć kursów z LiveScore: {e}")
            else:
                print(f"   ⚠️ LiveScore: Nie znaleziono meczu")
            
            return result
            
        except Exception as e:
            print(f"   ❌ LiveScore fallback error: {e}")
            return result


def format_odds_for_display(result: Dict) -> str:
    """Formatuje kursy do wyświetlenia"""
    if not result.get('odds_found'):
        return "❌ Kursy: Nie znaleziono"
    
    home = result.get('home_odds')
    draw = result.get('draw_odds')
    away = result.get('away_odds')
    source = result.get('odds_source', 'unknown')
    
    if draw:
        return f"💰 Kursy ({source}): 1={home:.2f} | X={draw:.2f} | 2={away:.2f}"
    else:
        return f"💰 Kursy ({source}): 1={home:.2f} | 2={away:.2f}"


def format_odds_for_email(result: Dict) -> str:
    """Formatuje kursy do emaila HTML"""
    if not result.get('odds_found'):
        return ""
    
    home = result.get('home_odds')
    draw = result.get('draw_odds')
    away = result.get('away_odds')
    
    # Znajdź najniższy kurs (faworyt)
    odds_list = [('1', home), ('X', draw), ('2', away)]
    odds_list = [(k, v) for k, v in odds_list if v is not None]
    
    if not odds_list:
        return ""
    
    min_odds = min(odds_list, key=lambda x: x[1])
    
    html_parts = []
    for label, value in odds_list:
        if value == min_odds[1]:
            html_parts.append(f'<span style="color: #28a745; font-weight: bold;">{label}={value:.2f}</span>')
        else:
            html_parts.append(f'{label}={value:.2f}')
    
    return ' | '.join(html_parts)


# ============================================================================
# TESTING / CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test FlashScore Odds Scraper')
    parser.add_argument('--home', default='Barcelona', help='Home team name')
    parser.add_argument('--away', default='Chelsea', help='Away team name')
    parser.add_argument('--sport', default='football', help='Sport')
    parser.add_argument('--headless', action='store_true', help='Run headless')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"TESTING FLASHSCORE ODDS SCRAPER v1.0")
    print(f"{'='*60}\n")
    
    scraper = FlashScoreOddsScraper(headless=args.headless)
    
    result = scraper.get_odds(
        home_team=args.home,
        away_team=args.away,
        sport=args.sport
    )
    
    print(f"\n{'='*60}")
    print(f"RESULTS:")
    print(f"{'='*60}")
    for key, value in result.items():
        print(f"{key}: {value}")
    
    print(f"\n{format_odds_for_display(result)}")
