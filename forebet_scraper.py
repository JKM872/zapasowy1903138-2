"""
Forebet.com Scraper
===================
Pobiera predykcje meczów z Forebet.com:
- Prediction (1/X/2) - kto wygra
- Probability (%) - prawdopodobieństwo wyniku
- Over/Under - przewidywana liczba goli
- BTTS (Both Teams To Score) - czy obie drużyny strzelą

🔥 ULTRA POWER CLOUDFLARE BYPASS 🔥
Używa wielu metod aby ominąć Cloudflare w CI/CD

Autor: AI Assistant
Data: 2025-11-17
"""

import time
import random
import os
from typing import Dict, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
import undetected_chromedriver as uc

# 🔥 Import Cloudflare Bypass
try:
    from cloudflare_bypass import fetch_forebet_with_bypass, CloudflareBypass, print_available_methods
    CLOUDFLARE_BYPASS_AVAILABLE = True
    print("🔥 Cloudflare Bypass module loaded!")
except ImportError:
    CLOUDFLARE_BYPASS_AVAILABLE = False
    print("⚠️ cloudflare_bypass not available, using standard methods")

try:
    from selenium_stealth import stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("⚠️ selenium_stealth not available, skipping...")

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    print("⚠️ cloudscraper not available, skipping...")

# Sprawdź czy jesteśmy w CI/CD
IS_CI_CD = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'
if IS_CI_CD:
    print("🔥 CI/CD environment detected - using Ultra Power Cloudflare Bypass!")

# Cache dla wyników (żeby nie scrape'ować dwa razy tego samego)
_forebet_cache = {}


def normalize_team_name(name: str) -> str:
    """
    Normalizuje nazwę drużyny do porównania.
    Usuwa znaki specjalne, lowercase, trim.
    """
    if not name:
        return ""
    
    # Lowercase i trim
    normalized = name.lower().strip()
    
    # Usuń typowe sufiksy/prefixy
    suffixes_to_remove = [' fc', ' afc', ' cf', ' united', ' city', ' town', 
                          ' wanderers', ' rovers', ' athletic', ' sports',
                          ' k', ' w', ' kobiety', ' kobiet']
    
    for suffix in suffixes_to_remove:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
    
    # Usuń znaki specjalne (zostaw tylko litery i spacje)
    normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
    
    return normalized


def similarity_score(name1: str, name2: str) -> float:
    """
    Oblicza similarity score między dwoma nazwami drużyn (0.0 - 1.0).
    Używa SequenceMatcher z difflib.
    """
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    
    if not norm1 or not norm2:
        return 0.0
    
    return SequenceMatcher(None, norm1, norm2).ratio()


def find_best_match(target_team: str, available_teams: list) -> Tuple[Optional[str], float]:
    """
    Znajduje najlepsze dopasowanie drużyny z listy dostępnych.
    
    Returns:
        (best_match, score) - najlepsza nazwa i score similarity
    """
    if not target_team or not available_teams:
        return None, 0.0
    
    best_match = None
    best_score = 0.0
    
    for team in available_teams:
        score = similarity_score(target_team, team)
        if score > best_score:
            best_score = score
            best_match = team
    
    return best_match, best_score


def search_forebet_prediction(
    home_team: str,
    away_team: str,
    match_date: str,
    driver: webdriver.Chrome = None,
    min_similarity: float = 0.7,
    timeout: int = 10,
    headless: bool = False,
    sport: str = 'football',
    use_xvfb: bool = None  # Auto-detect CI/CD environment
) -> Dict[str, any]:
    """
    Wyszukuje predykcję meczu na Forebet.com.
    
    Args:
        home_team: Nazwa drużyny gospodarzy
        away_team: Nazwa drużyny gości
        match_date: Data meczu w formacie YYYY-MM-DD
        driver: Opcjonalny WebDriver (jeśli None, tworzy nowy)
        min_similarity: Minimalny threshold similarity (0.0-1.0)
        timeout: Timeout w sekundach
    
    Returns:
        Dict z kluczami:
        - success (bool): Czy znaleziono predykcję
        - prediction (str): '1', 'X', '2' lub None
        - probability (float): Prawdopodobieństwo 0-100 lub None
        - over_under (str): 'Over 2.5', 'Under 2.5' lub None
        - btts (str): 'Yes', 'No' lub None
        - avg_goals (float): Przewidywana średnia liczba goli
        - error (str): Komunikat błędu jeśli wystąpił
    """
    
    # Auto-detect CI/CD environment (GitHub Actions, GitLab CI, etc.)
    if use_xvfb is None:
        import os
        use_xvfb = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'
    
    # Xvfb (Virtual Display) - dla CI/CD bez GUI
    xvfb_display = None
    if use_xvfb:
        try:
            from xvfbwrapper import Xvfb
            xvfb_display = Xvfb(width=1920, height=1080)
            xvfb_display.start()
            print(f"      🖥️ Xvfb virtual display started (CI/CD mode)")
        except ImportError:
            print(f"      ⚠️ xvfbwrapper not available, using headless mode")
            headless = True
        except Exception as e:
            print(f"      ⚠️ Xvfb failed: {e}, using headless mode")
            headless = True
    
    # Sprawdź cache
    cache_key = f"{home_team}_{away_team}_{match_date}"
    if cache_key in _forebet_cache:
        print(f"      📋 Forebet (cache): {_forebet_cache[cache_key]}")
        if xvfb_display:
            xvfb_display.stop()
        return _forebet_cache[cache_key]
    
    result = {
        'success': False,
        'prediction': None,
        'probability': None,
        'over_under': None,
        'btts': None,
        'avg_goals': None,
        'error': None
    }
    
    own_driver = False
    html_content = None
    
    # 🔥 ULTRA POWER: Używaj Cloudflare Bypass (włącznie z FlareSolverr w CI/CD!)
    if CLOUDFLARE_BYPASS_AVAILABLE:
        print(f"      🔥 Używam Ultra Power Cloudflare Bypass!")
        
        sport_urls = {
            'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today',
            'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today',
            'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
            'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
            'handball': 'https://www.forebet.com/en/handball/predictions-today',
            'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
            'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
            'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
        }
        
        url = sport_urls.get(sport.lower(), sport_urls['football'])
        print(f"      🌐 Forebet ({sport}): {url}")
        
        try:
            html_content = fetch_forebet_with_bypass(url, debug=True)
            
            if html_content:
                print(f"      🔥 Cloudflare Bypass SUCCESS! ({len(html_content)} znaków)")
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Przejdź do parsowania meczów (poniżej)
            else:
                print(f"      ⚠️ Cloudflare Bypass nie zadziałał, próbuję standardową metodę...")
                html_content = None
        except Exception as e:
            print(f"      ⚠️ Cloudflare Bypass error: {e}")
            html_content = None
    
    try:
        # Jeśli mamy już HTML z bypass, parsuj go
        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
        else:
            # Utwórz driver jeśli nie podano - UNDETECTED CHROMEDRIVER
            if driver is None:
                print(f"      🚀 Tworzenie undetected ChromeDriver...")
            
            # METODA 1: undetected-chromedriver (najlepsza do Cloudflare)
            options = uc.ChromeOptions()
            
            # HEADLESS MODE - opcjonalny (Cloudflare często blokuje headless)
            if headless:
                print(f"      ⚠️ Uwaga: Headless mode może być blokowany przez Cloudflare")
                options.add_argument('--headless=new')
            else:
                print(f"      👀 Tryb widoczny (lepiej omija Cloudflare)")
            
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--start-maximized')
            
            # Random user agent
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            ]
            options.add_argument(f'user-agent={random.choice(user_agents)}')
            
            try:
                driver = uc.Chrome(options=options, version_main=None)
                print(f"      ✅ Undetected ChromeDriver utworzony")
            except Exception as e:
                print(f"      ⚠️ Fallback do standardowego Chrome: {e}")
                # Fallback do zwykłego Chrome z stealth
                from selenium.webdriver.chrome.options import Options
                options = Options()
                options.add_argument('--headless=new')
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                driver = webdriver.Chrome(options=options)
            
            # METODA 2: Selenium Stealth (dodatkowa warstwa)
            if STEALTH_AVAILABLE:
                try:
                    stealth(driver,
                        languages=["en-US", "en"],
                        vendor="Google Inc.",
                        platform="Win32",
                        webgl_vendor="Intel Inc.",
                        renderer="Intel Iris OpenGL Engine",
                        fix_hairline=True,
                    )
                    print(f"      ✅ Selenium Stealth applied")
                except Exception as e:
                    print(f"      ⚠️ Stealth warning: {e}")
            else:
                print(f"      ⚠️ Selenium Stealth not available")
            
            own_driver = True
        
        # Forebet URL - różne sporty (poprawne URLe z menu)
        sport_urls = {
            'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today',
            'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today',
            'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
            'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
            'handball': 'https://www.forebet.com/en/handball/predictions-today',
            'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
            'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
            'rugby': 'https://www.forebet.com/en/rugby/predictions-today',
            'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
            'baseball': 'https://www.forebet.com/en/baseball/predictions-today',
        }
        
        url = sport_urls.get(sport.lower(), sport_urls['football'])
        print(f"      🌐 Forebet ({sport}): Ładuję {url}")
        
        driver.get(url)
        
        # STRATEGIA ANTY-CLOUDFLARE: Symulacja ludzkiego zachowania
        print(f"      ⏳ Czekam na Cloudflare check...")
        time.sleep(random.uniform(3, 5))  # Random delay 3-5s
        
        # Sprawdź czy Cloudflare challenge
        page_title = driver.title.lower()
        if 'cloudflare' in page_title or 'checking' in page_title:
            print(f"      ⚠️ Wykryto Cloudflare challenge - czekam dłużej...")
            time.sleep(8)  # Dodatkowe 8s na challenge
        
        # Symulacja ludzkiego przewijania (kilka razy)
        print(f"      🖱️ Symulacja scrollowania...")
        for _ in range(3):
            scroll_amount = random.randint(200, 500)
            driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            time.sleep(random.uniform(0.3, 0.8))
        
        # Przewiń na środek strony
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1)
        
        # Sprawdź czy są mecze (czekaj max 10s)
        print(f"      ⏳ Czekam na załadowanie meczów...")
        start_wait = time.time()
        while time.time() - start_wait < 10:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            if soup.find_all('div', class_='tr') or soup.find_all('tr') or soup.find('table'):
                print(f"      ✅ Mecze załadowane!")
                break
            time.sleep(1)
        else:
            print(f"      ⚠️ Timeout czekania na mecze")
        
        # Pobierz finalny HTML
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # DEBUG: Zapisz HTML do pliku
        with open('forebet_debug.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"      💾 Debug: Zapisano HTML do forebet_debug.html")
        
        # Sprawdź czy to nie jest strona błędu Cloudflare
        body_text = soup.get_text().lower()
        if 'cloudflare' in body_text and 'checking your browser' in body_text:
            result['error'] = 'Cloudflare blocked - nie udało się ominąć'
            print(f"      ❌ Cloudflare zablokował dostęp")
            return result
        
        # Znajdź wszystkie mecze na stronie - MULTI-WARIANT
        match_rows = []
        
        # Wariant 1: div.rcnt
        match_rows = soup.find_all('div', class_='rcnt')
        print(f"      🔍 Wariant 1 (div.rcnt): {len(match_rows)} elementów")
        
        # Wariant 2: tr z klasami tr_0 i tr_1
        if not match_rows:
            match_rows = soup.find_all('tr', class_=['tr_0', 'tr_1'])
            print(f"      🔍 Wariant 2 (tr.tr_0/1): {len(match_rows)} elementów")
        
        # Wariant 3: div.tr (nowsza struktura)
        if not match_rows:
            match_rows = soup.find_all('div', class_='tr')
            print(f"      🔍 Wariant 3 (div.tr): {len(match_rows)} elementów")
        
        # Wariant 4: Wszystkie tr w tabeli
        if not match_rows:
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                match_rows.extend(rows)
            print(f"      🔍 Wariant 4 (table>tr): {len(match_rows)} elementów")
        
        # Wariant 5: div.schema > div
        if not match_rows:
            schemas = soup.find_all('div', class_='schema')
            for schema in schemas:
                divs = schema.find_all('div', recursive=False)
                match_rows.extend(divs)
            print(f"      🔍 Wariant 5 (div.schema>div): {len(match_rows)} elementów")
        
        # Wariant 6: Wszystkie linki z '/predictions/'
        if not match_rows:
            links = soup.find_all('a', href=True)
            pred_links = [l for l in links if '/predictions/' in l.get('href', '')]
            # Wróć do parent elementów
            match_rows = [l.find_parent() for l in pred_links if l.find_parent()]
            print(f"      🔍 Wariant 6 (linki /predictions/): {len(match_rows)} elementów")
        
        if not match_rows:
            result['error'] = 'Nie znaleziono meczów na stronie Forebet'
            print(f"      ❌ Debug: Żaden wariant nie znalazł meczów")
            # Debug: Wypisz klasy występujące na stronie
            all_classes = set()
            for elem in soup.find_all(class_=True):
                classes = elem.get('class', [])
                if isinstance(classes, list):
                    all_classes.update(classes)
            print(f"      📋 Znalezione klasy CSS: {list(all_classes)[:20]}")
            return result
        
        print(f"      🔍 Znaleziono {len(match_rows)} meczów na Forebet")
        
        # Szukaj naszego meczu
        for row in match_rows:
            try:
                # Wyciągnij nazwy drużyn - WIELE WARIANTÓW
                home_elem = None
                away_elem = None
                
                # Wariant 1: span.homeTeam / span.awayTeam
                home_elem = row.find('span', class_='homeTeam')
                away_elem = row.find('span', class_='awayTeam')
                
                # Wariant 2: td.lscr_td > spans
                if not home_elem or not away_elem:
                    teams_td = row.find('td', class_='lscr_td')
                    if teams_td:
                        spans = teams_td.find_all('span')
                        if len(spans) >= 2:
                            home_elem = spans[0]
                            away_elem = spans[1]
                
                # Wariant 3: div.homeTeam / div.awayTeam
                if not home_elem or not away_elem:
                    home_elem = row.find('div', class_='homeTeam')
                    away_elem = row.find('div', class_='awayTeam')
                
                # Wariant 4: Szukaj <a> z href zawierającym '/predictions/'
                if not home_elem or not away_elem:
                    links = row.find_all('a', href=True)
                    for link in links:
                        if '/predictions/' in link['href']:
                            # Link wygląda jak: /predictions/home-vs-away
                            teams_in_url = link['href'].split('/')[-1]
                            if '-vs-' in teams_in_url:
                                parts = teams_in_url.split('-vs-')
                                # Symuluj elementy
                                class FakeElement:
                                    def __init__(self, text):
                                        self.text = text
                                    def get_text(self, strip=False):
                                        return self.text.strip() if strip else self.text
                                
                                home_elem = FakeElement(parts[0].replace('-', ' ').title())
                                away_elem = FakeElement(parts[1].replace('-', ' ').title())
                                break
                
                if not home_elem or not away_elem:
                    continue
                
                forebet_home = home_elem.get_text(strip=True)
                forebet_away = away_elem.get_text(strip=True)
                
                # Sprawdź similarity
                home_score = similarity_score(home_team, forebet_home)
                away_score = similarity_score(away_team, forebet_away)
                
                if home_score >= min_similarity and away_score >= min_similarity:
                    print(f"      ✅ Znaleziono mecz na Forebet: {forebet_home} vs {forebet_away}")
                    print(f"         Similarity: Home={home_score:.2f}, Away={away_score:.2f}")
                    
                    # Wyciągnij predykcję - POPRAWIONA STRUKTURA
                    
                    # 1. Prawdopodobieństwa (div.fprc > spans)
                    fprc_div = row.find('div', class_='fprc')
                    if fprc_div:
                        spans = fprc_div.find_all('span')
                        if len(spans) >= 3:
                            try:
                                home_prob = int(spans[0].get_text(strip=True))
                                draw_prob = int(spans[1].get_text(strip=True))
                                away_prob = int(spans[2].get_text(strip=True))
                                
                                # Najwyższe prawdopodobieństwo to predykcja
                                max_prob = max(home_prob, draw_prob, away_prob)
                                result['probability'] = float(max_prob)
                                
                                if max_prob == home_prob:
                                    result['prediction'] = '1'  # Home win
                                elif max_prob == draw_prob:
                                    result['prediction'] = 'X'  # Draw
                                else:
                                    result['prediction'] = '2'  # Away win
                            except (ValueError, IndexError):
                                pass
                    
                    # 2. Predykcja tekstowa (div.predict > span.forepr)
                    forepr_elem = row.find('span', class_='forepr')
                    if forepr_elem and not result.get('prediction'):
                        pred_text = forepr_elem.get_text(strip=True)
                        if pred_text in ['1', 'X', '2']:
                            result['prediction'] = pred_text
                    
                    # 3. Dokładny wynik (div.ex_sc)
                    ex_sc_elem = row.find('div', class_='ex_sc')
                    if ex_sc_elem:
                        result['exact_score'] = ex_sc_elem.get_text(strip=True)
                    
                    # 4. Average Goals (div.avg_sc)
                    avg_sc_elem = row.find('div', class_='avg_sc')
                    if avg_sc_elem:
                        avg_text = avg_sc_elem.get_text(strip=True)
                        try:
                            result['avg_goals'] = float(avg_text)
                            # Określ Over/Under 2.5
                            if result['avg_goals'] > 2.5:
                                result['over_under'] = 'Over 2.5'
                            else:
                                result['over_under'] = 'Under 2.5'
                        except ValueError:
                            pass
                    
                    # 5. BTTS - sprawdź czy oba zespoły strzelą
                    # Jeśli dokładny wynik to np. "1-3", oba strzelą
                    if result.get('exact_score'):
                        score_parts = result['exact_score'].split('-')
                        if len(score_parts) == 2:
                            try:
                                home_goals = int(score_parts[0].strip())
                                away_goals = int(score_parts[1].strip())
                                if home_goals > 0 and away_goals > 0:
                                    result['btts'] = 'Yes'
                                else:
                                    result['btts'] = 'No'
                            except ValueError:
                                pass
                    
                    result['success'] = True
                    break
                    
            except Exception as e:
                print(f"      ⚠️ Błąd parsowania wiersza Forebet: {e}")
                continue
        
        if not result['success']:
            result['error'] = f'Nie znaleziono meczu {home_team} vs {away_team} na Forebet (similarity < {min_similarity})'
    
    except TimeoutException:
        result['error'] = 'Timeout podczas ładowania Forebet.com'
        print(f"      ⚠️ Forebet timeout")
    
    except Exception as e:
        result['error'] = f'Błąd Forebet: {str(e)}'
        print(f"      ⚠️ Forebet error: {e}")
    
    finally:
        # Zamknij driver jeśli utworzyliśmy własny
        if own_driver and driver:
            try:
                driver.quit()
            except:
                pass
        
        # Zamknij Xvfb jeśli był użyty
        if xvfb_display:
            try:
                xvfb_display.stop()
                print(f"      🖥️ Xvfb virtual display stopped")
            except:
                pass
    
    # Zapisz do cache
    _forebet_cache[cache_key] = result
    
    return result


def format_forebet_result(result: Dict[str, any]) -> str:
    """
    Formatuje wynik Forebet do czytelnego stringa.
    
    Returns:
        String np: "🎯 Forebet: Goście (50%) | Wynik: 1-3 | O/U: Over 2.5 | BTTS: Yes"
    """
    if not result.get('success'):
        return "🎯 Forebet: Brak danych"
    
    parts = []
    
    # Prediction + Probability
    if result.get('prediction'):
        pred_map = {'1': 'Gospodarze', 'X': 'Remis', '2': 'Goście'}
        pred_text = pred_map.get(result['prediction'], result['prediction'])
        if result.get('probability'):
            parts.append(f"{pred_text} ({result['probability']:.0f}%)")
        else:
            parts.append(pred_text)
    
    # Exact Score
    if result.get('exact_score'):
        parts.append(f"Wynik: {result['exact_score']}")
    
    # Over/Under
    if result.get('over_under'):
        parts.append(f"O/U: {result['over_under']}")
    
    # BTTS
    if result.get('btts'):
        parts.append(f"BTTS: {result['btts']}")
    
    # Average goals (jeśli nie ma O/U)
    if result.get('avg_goals') and not result.get('over_under'):
        parts.append(f"Avg: {result['avg_goals']:.1f} goli")
    
    return "🎯 Forebet: " + " | ".join(parts) if parts else "🎯 Forebet: Brak szczegółów"


# Test standalone
if __name__ == '__main__':
    import sys
    
    # Sprawdź argumenty - możliwość testowania różnych sportów
    test_sport = sys.argv[1] if len(sys.argv) > 1 else 'football'
    
    print('🎯 Forebet Scraper - Test')
    print('='*70)
    print(f'🏅 Sport: {test_sport.upper()}')
    print('='*70)
    
    if test_sport.lower() == 'volleyball':
        # Test volleyball - pobierz pierwszy mecz z listy
        print(f'\n🔍 Testuję volleyball - pobieram listę meczów...\n')
        
        # Pobierz listę meczów
        result_test = {
            'success': False,
            'prediction': None,
            'probability': None,
            'over_under': None,
            'btts': None,
            'avg_goals': None,
            'error': None
        }
        
        try:
            import undetected_chromedriver as uc
            options = uc.ChromeOptions()
            driver = uc.Chrome(options=options)
            driver.get('https://www.forebet.com/en/volleyball-tips-and-predictions-for-today')
            time.sleep(5)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all('div', class_='rcnt')
            
            print(f'✅ Znaleziono {len(rows)} meczów volleyball na Forebet\n')
            
            if rows:
                # Wyświetl pierwsze 5 meczów
                print('Pierwsze 5 meczów:')
                print('-'*70)
                for i, row in enumerate(rows[:5], 1):
                    home_elem = row.find('span', class_='homeTeam')
                    away_elem = row.find('span', class_='awayTeam')
                    if home_elem and away_elem:
                        print(f'{i}. {home_elem.get_text(strip=True)} vs {away_elem.get_text(strip=True)}')
                
                # Testuj pierwszy mecz
                first_row = rows[0]
                home_elem = first_row.find('span', class_='homeTeam')
                away_elem = first_row.find('span', class_='awayTeam')
                
                if home_elem and away_elem:
                    test_home = home_elem.get_text(strip=True)
                    test_away = away_elem.get_text(strip=True)
                    test_date = '2025-11-17'
                    
                    print(f'\n🔍 Testuję parsowanie dla: {test_home} vs {test_away}')
                    driver.quit()
                    
                    result = search_forebet_prediction(test_home, test_away, test_date, sport='volleyball')
                    
                    print('\n📊 WYNIK:')
                    print('='*70)
                    
                    if result['success']:
                        print(f"✅ Znaleziono predykcję!")
                        print(format_forebet_result(result))
                        print(f"\nSzczegóły:")
                        print(f"  Prediction: {result.get('prediction')}")
                        print(f"  Probability: {result.get('probability')}%")
                        print(f"  Exact Score: {result.get('exact_score')}")
                        print(f"  Over/Under: {result.get('over_under')}")
                        print(f"  Avg Goals: {result.get('avg_goals')}")
                    else:
                        print(f"❌ Nie znaleziono predykcji")
                        print(f"Error: {result.get('error')}")
                else:
                    print('❌ Nie udało się wyciągnąć nazw drużyn')
                    driver.quit()
            else:
                print('❌ Brak meczów volleyball na Forebet')
                driver.quit()
                
        except Exception as e:
            print(f'❌ Error: {e}')
            import traceback
            traceback.print_exc()
    
    else:
        # Test football (domyślny)
        test_home = 'Dinamo Minsk II'
        test_away = 'Niva Dolbizno'
        test_date = '2025-11-17'
        
        print(f'\n🔍 Szukam predykcji dla: {test_home} vs {test_away}')
        print(f'📅 Data: {test_date}\n')
        
        result = search_forebet_prediction(test_home, test_away, test_date, sport='football')
        
        print('\n📊 WYNIK:')
        print('='*70)
        
        if result['success']:
            print(f"✅ Znaleziono predykcję!")
            print(format_forebet_result(result))
            print(f"\nSzczegóły:")
            print(f"  Prediction: {result.get('prediction')}")
            print(f"  Probability: {result.get('probability')}%")
            print(f"  Exact Score: {result.get('exact_score')}")
            print(f"  Over/Under: {result.get('over_under')}")
            print(f"  BTTS: {result.get('btts')}")
            print(f"  Avg Goals: {result.get('avg_goals')}")
        else:
            print(f"❌ Nie znaleziono predykcji")
            print(f"Error: {result.get('error')}")
    
    print('\n' + '='*70)
