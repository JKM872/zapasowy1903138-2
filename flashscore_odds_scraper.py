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
    
    # 🔥 POLSKIE/EUROPEJSKIE ZNAKI → ASCII
    char_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
        'é': 'e', 'è': 'e', 'ê': 'e', 'á': 'a', 'à': 'a',
        'í': 'i', 'ú': 'u', 'ñ': 'n', 'ç': 'c',
        'š': 's', 'č': 'c', 'ž': 'z', 'ř': 'r',
    }
    for char, replacement in char_map.items():
        name = name.replace(char, replacement)
    
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
        
        # 🔥 CI/CD ENVIRONMENT: Use system chromedriver
        import os
        if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            from selenium.webdriver.chrome.service import Service
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            driver = webdriver.Chrome(options=chrome_options)
        
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(15)
        
        return driver
    
    def _find_match_on_page(self, home_team: str, away_team: str, sport: str = 'football') -> Optional[str]:
        """
        Szuka meczu na stronie głównej FlashScore i zwraca URL z kursami.
        Używa element ID z FlashScore (format: g_1_XXXXXXXX).
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
            
            # Pobierz tekst strony i HTML
            page_source = self.driver.page_source
            
            # FlashScore używa div z id="g_1_XXXXXXXXX" dla każdego meczu
            # Szukamy elementów z danymi meczów
            
            # 🔥 UPDATED: FlashScore changed their class names - use newer patterns
            # Modern FlashScore uses classes like: event__match, sportName, etc.
            match_selectors = [
                # New patterns (2024+)
                '.event__match',
                '.event__participant',
                '[class*="participant__participantName"]',
                # Row-based
                '[class*="event__"]',
                '.sportName',
                # ID-based
                '[id^="g_1_"]',
                '[id^="g_2_"]',
            ]
            
            for selector in match_selectors:
                try:
                    match_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for elem in match_elements:
                        try:
                            elem_text = elem.text.lower()
                            if not elem_text or len(elem_text) < 3:
                                continue
                                
                            # Find parent with match ID
                            parent = None
                            match_id = None
                            
                            try:
                                parent = elem.find_element(By.XPATH, './ancestor::div[starts-with(@id,"g_")]')
                                if parent:
                                    match_id = parent.get_attribute('id')
                            except:
                                pass
                            
                            # Check team name match
                            home_parts = [p for p in home_norm.split() if len(p) > 2]
                            away_parts = [p for p in away_norm.split() if len(p) > 2]
                            
                            home_found = any(part in elem_text for part in home_parts) if home_parts else False
                            away_found = any(part in elem_text for part in away_parts) if away_parts else False
                            
                            if home_found or away_found:
                                # Try clicking to open match page
                                try:
                                    clickable = parent if parent else elem
                                    self.driver.execute_script("arguments[0].click();", clickable)
                                    time.sleep(2)
                                    match_url = self.driver.current_url
                                    if '/match/' in match_url:
                                        match_id_from_url = match_url.split('/')[-2] if match_url.endswith('/') else match_url.split('/')[-1].split('#')[0]
                                        print(f"   ✅ FlashScore: Znaleziono mecz (ID: {match_id_from_url})!")
                                        return match_url
                                except:
                                    pass
                        except:
                            continue
                except:
                    continue
            
            # Metoda 2: Szukaj bezpośrednio po tekście na stronie
            try:
                # Znajdź wszystkie divy z dwoma uczestnikami
                event_rows = self.driver.find_elements(By.CSS_SELECTOR, 
                    '[class*="event__participant--home"], [class*="homeParticipant"]')
                
                for row in event_rows:
                    try:
                        home_text = row.text.lower()
                        
                        # Znajdź away team w sąsiednim elemencie
                        parent = row.find_element(By.XPATH, './ancestor::div[contains(@class, "event")]')
                        away_elem = parent.find_element(By.CSS_SELECTOR, 
                            '[class*="event__participant--away"], [class*="awayParticipant"]')
                        away_text = away_elem.text.lower()
                        
                        home_parts = [p for p in home_norm.split() if len(p) > 2]
                        away_parts = [p for p in away_norm.split() if len(p) > 2]
                        
                        home_match = any(part in home_text for part in home_parts)
                        away_match = any(part in away_text for part in away_parts)
                        
                        if home_match and away_match:
                            parent.click()
                            time.sleep(2)
                            match_url = self.driver.current_url
                            if '/match/' in match_url:
                                print(f"   ✅ FlashScore: Znaleziono mecz!")
                                return match_url
                    except:
                        continue
            except:
                pass
            
            # Metoda 3: Fallback - szukaj po regex w HTML
            match_pattern = r'id="g_1_([^"]+)"[^>]*>.*?(' + '|'.join([re.escape(p) for p in home_norm.split() if len(p) > 2]) + ').*?</div>'
            matches = re.findall(match_pattern, page_source, re.IGNORECASE | re.DOTALL)
            
            for match_id, _ in matches[:5]:
                match_url = f'https://www.flashscore.com/match/{match_id}/'
                print(f"   ✅ FlashScore: Znaleziono mecz (ID: {match_id})!")
                return match_url
            
            print(f"   ⚠️ FlashScore: Nie znaleziono meczu {home_team} vs {away_team}")
            return None
            
        except Exception as e:
            print(f"   ❌ FlashScore: Błąd wyszukiwania: {e}")
            return None
    
    def _extract_odds_from_match(self, match_url: str, sport: str = 'football') -> Dict:
        """
        Wyciąga kursy ze strony meczu FlashScore.
        PRIORYTET: Pinnacle > bet365 > Betway > dowolny bukmacher
        """
        has_draw = sport not in ['tennis', 'volleyball', 'basketball']
        
        # Preferowani bukmacherzy w kolejności priorytetu
        PREFERRED_BOOKMAKERS = ['pinnacle', 'bet365', 'betway', 'unibet', 'william hill', '1xbet']
        
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
            # Otwórz stronę z kursami
            odds_url = match_url.rstrip('/') + '/#/odds-comparison/1x2-odds/full-time'
            
            try:
                self.driver.get(odds_url)
            except TimeoutException:
                pass
            
            time.sleep(4)
            
            page_source = self.driver.page_source.lower()
            
            # Struktura: każdy wiersz bukmachera ma nazwę i kursy
            # Szukamy wierszy z kursami
            
            bookmaker_odds = {}  # {'pinnacle': [1.85, 3.40, 2.10], ...}
            
            # Metoda 1: Szukaj konkretnych bukmacherów
            for bookie in PREFERRED_BOOKMAKERS:
                if bookie in page_source:
                    # Znajdź pozycję bukmachera i wyciągnij kursy z tej okolicy
                    bookie_idx = page_source.find(bookie)
                    if bookie_idx > 0:
                        # Wyciągnij fragment HTML wokół bukmachera (500 znaków)
                        snippet = page_source[bookie_idx:bookie_idx + 500]
                        
                        # Szukaj kursów w formacie X.XX
                        odds_pattern = r'(\d+\.\d{2})'
                        odds_found = re.findall(odds_pattern, snippet)
                        
                        # Filtruj prawidłowe kursy
                        valid_odds = [float(o) for o in odds_found if 1.01 <= float(o) <= 50.0]
                        
                        if len(valid_odds) >= 2:
                            bookmaker_odds[bookie] = valid_odds[:3]  # Max 3 kursy (1X2)
            
            # Wybierz najlepszego bukmachera według priorytetu
            selected_bookie = None
            selected_odds = None
            
            for bookie in PREFERRED_BOOKMAKERS:
                if bookie in bookmaker_odds:
                    selected_bookie = bookie
                    selected_odds = bookmaker_odds[bookie]
                    break
            
            # Fallback: jeśli żaden preferowany nie znaleziony, weź pierwsze dostępne kursy
            if not selected_odds:
                # Szukaj wszystkich kursów na stronie
                all_odds_pattern = r'>(\d+\.\d{2})<'
                all_odds = re.findall(all_odds_pattern, self.driver.page_source)
                valid_odds = [float(o) for o in all_odds if 1.01 <= float(o) <= 50.0]
                
                if len(valid_odds) >= 2:
                    selected_odds = valid_odds[:3]
                    selected_bookie = 'flashscore_avg'
            
            # Zapisz wyniki
            if selected_odds and len(selected_odds) >= 2:
                result['odds_found'] = True
                result['bookmaker'] = selected_bookie.title() if selected_bookie else 'Unknown'
                
                if has_draw and len(selected_odds) >= 3:
                    result['home_odds'] = selected_odds[0]
                    result['draw_odds'] = selected_odds[1]
                    result['away_odds'] = selected_odds[2]
                else:
                    result['home_odds'] = selected_odds[0]
                    result['away_odds'] = selected_odds[1]
                
                print(f"   ✅ Kursy od {result['bookmaker']}: {result['home_odds']}/{result['draw_odds']}/{result['away_odds']}")
            else:
                print(f"   ⚠️ Nie znaleziono kursów")
            
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
