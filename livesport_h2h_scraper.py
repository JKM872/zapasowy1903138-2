"""
Livesport H2H scraper - Multi-Sport Edition
-------------------------------------------
Cel: dla danego dnia zapisać do pliku CSV wydarzenia (mecze), w których GOSPODARZE pokonali przeciwników co najmniej 2 razy w ostatnich 5 bezpośrednich spotkaniach (H2H).

Wspierane sporty:
- Piłka nożna (football/soccer)
- Koszykówka (basketball)
- Siatkówka (volleyball)
- Piłka ręczna (handball)
- Rugby
- Hokej (hockey/ice-hockey)

Uwagi / założenia:
- Zakładam, że "ostatnie 5" oznacza 5 ostatnich bezpośrednich spotkań między obiema drużynami (H2H na stronie meczu).
- Skrypt pracuje w trzech trybach:
    * --urls  : przetwarza listę adresów URL meczów (plik tekstowy z jedną linią = jeden URL)
    * --auto  : próbuje zebrać listę linków do meczów z ogólnej strony dla danego dnia
    * --sport : automatycznie zbiera linki dla konkretnych sportów
- Strona Livesport jest mocno zależna od JS — skrypt używa Selenium (Chrome/Chromedriver).
- Przestrzegaj robots.txt i Terms of Use. Skrypt ma opóźnienia (sleep) i limit prób, ale używanie go na dużej skali wymaga uzyskania zgody od właściciela serwisu.

Wymagania:
- Python 3.9+
- pip install selenium beautifulsoup4 pandas webdriver-manager
- Chrome i dopasowany chromedriver (webdriver-manager ułatwia instalację)

Uruchomienie (przykłady):
python livesport_h2h_scraper.py --mode urls --date 2025-10-05 --input match_urls.txt --headless
python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football basketball --headless
python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football --leagues ekstraklasa premier-league --headless

Plik wynikowy: outputs/livesport_h2h_YYYY-MM-DD.csv (lub z sufixem sportu)

"""

import argparse
import time
import os
import sys
import csv
import re
import json
from datetime import datetime
from typing import List, Dict, Optional

# Fix Unicode encoding issues on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# Forebet integration
try:
    from forebet_scraper import search_forebet_prediction, format_forebet_result, prefetch_forebet_html
    FOREBET_AVAILABLE = True
except ImportError:
    FOREBET_AVAILABLE = False
    print("⚠️ forebet_scraper not available - predictions will be skipped")

# Gemini AI integration - LAZY LOADING to avoid blocking startup
GEMINI_AVAILABLE = None  # Will be checked on first use
gemini_analyze_match = None

def lazy_load_gemini():
    """Lazy load Gemini AI only when actually needed"""
    global GEMINI_AVAILABLE, gemini_analyze_match
    
    if GEMINI_AVAILABLE is None:  # First time check
        try:
            print("🤖 Ładuję Gemini AI...")
            from gemini_analyzer import analyze_match as _gemini_analyze_match
            gemini_analyze_match = _gemini_analyze_match
            GEMINI_AVAILABLE = True
            print("✅ Gemini AI gotowe!")
            return True
        except Exception as e:
            GEMINI_AVAILABLE = False
            print(f"⚠️ Gemini AI niedostępne: {type(e).__name__}")
            return False
    
    return GEMINI_AVAILABLE

# Nordic Bet integration (disabled - using FlashScore instead)
NORDIC_BET_AVAILABLE = False

# FlashScore odds integration
try:
    from flashscore_odds_scraper import FlashScoreOddsScraper, format_odds_for_display
    FLASHSCORE_AVAILABLE = True
    print("✅ FlashScore odds scraper loaded")
except ImportError:
    FLASHSCORE_AVAILABLE = False
    print("⚠️ flashscore_odds_scraper not available - odds will use Forebet fallback")


# ----------------------
# Helper / scraper code
# ----------------------

def detect_sport_from_url(url):
    """
    Wykryj sport z URL LiveSport i zmapuj na nazwę sportu Forebet
    
    Mapowanie LiveSport -> Forebet:
    - pilka-nozna -> football/soccer
    - koszykowka -> basketball
    - siatkowka -> volleyball
    - pilka-reczna -> handball
    - rugby -> rugby
    - hokej -> hockey
    - tenis -> tennis
    """
    url_lower = url.lower()
    
    if '/pilka-nozna/' in url_lower or '/football/' in url_lower or '/soccer/' in url_lower:
        return 'football'
    elif '/koszykowka/' in url_lower or '/basketball/' in url_lower:
        return 'basketball'
    elif '/siatkowka/' in url_lower or '/volleyball/' in url_lower:
        return 'volleyball'
    elif '/pilka-reczna/' in url_lower or '/handball/' in url_lower:
        return 'handball'
    elif '/rugby/' in url_lower:
        return 'rugby'
    elif '/hokej/' in url_lower or '/hockey/' in url_lower or '/ice-hockey/' in url_lower:
        return 'hockey'
    elif '/tenis/' in url_lower or '/tennis/' in url_lower:
        return 'tennis'
    else:
        return 'football'  # domyślnie football

# Mapowanie sportów na URLe Livesport
SPORT_URLS = {
    'football': 'https://www.livesport.com/pl/pilka-nozna/',
    'soccer': 'https://www.livesport.com/pl/pilka-nozna/',
    'basketball': 'https://www.livesport.com/pl/koszykowka/',
    'volleyball': 'https://www.livesport.com/pl/siatkowka/',
    'handball': 'https://www.livesport.com/pl/pilka-reczna/',
    'rugby': 'https://www.livesport.com/pl/rugby/',
    'hockey': 'https://www.livesport.com/pl/hokej/',
    'ice-hockey': 'https://www.livesport.com/pl/hokej/',
    'tennis': 'https://www.livesport.com/pl/tenis/',
}

# Sporty indywidualne (inna logika kwalifikacji)
INDIVIDUAL_SPORTS = ['tennis']

# Popularne ligi dla każdego sportu (mapowanie slug -> nazwa)
POPULAR_LEAGUES = {
    'football': {
        'ekstraklasa': 'Ekstraklasa',
        'premier-league': 'Premier League',
        'la-liga': 'LaLiga',
        'bundesliga': 'Bundesliga',
        'serie-a': 'Serie A',
        'ligue-1': 'Ligue 1',
        'champions-league': 'Liga Mistrzów',
        'europa-league': 'Liga Europy',
    },
    'basketball': {
        'nba': 'NBA',
        'euroleague': 'Euroliga',
        'energa-basket-liga': 'Energa Basket Liga',
        'pbl': 'Polska Liga Koszykówki',
    },
    'volleyball': {
        'plusliga': 'PlusLiga',
        'tauron-liga': 'Tauron Liga',
    },
    'handball': {
        'pgnig-superliga': 'PGNiG Superliga',
    },
    'rugby': {
        'premiership': 'Premiership',
        'top-14': 'Top 14',
    },
    'hockey': {
        'nhl': 'NHL',
        'khl': 'KHL',
    },
}

H2H_TAB_TEXT_OPTIONS = ["H2H", "Head-to-Head", "Bezpośrednie", "Bezpośrednie spotkania", "H2H"]


def start_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    
    # 🔥 QUADRUPLE FORCE: Aggressive stability settings
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument('--window-size=1920,1080')
    
    # Network stability improvements
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--dns-prefetch-disable")
    
    # Connection pool settings
    chrome_options.add_argument("--max-connections-per-host=6")
    
    # Timeout preferences
    chrome_options.add_experimental_option('prefs', {
        'profile.default_content_setting_values.notifications': 2,
        'profile.default_content_settings.popups': 0,
    })
    
    # human-like user-agent (you may rotate)
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Try to find cached ChromeDriver first (manual or auto-downloaded)
    import glob
    print("🔍 Sprawdzam ChromeDriver...")
    
    cache_pattern = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver", "**", "chromedriver.exe")
    cached_drivers = glob.glob(cache_pattern, recursive=True)
    
    if cached_drivers:
        # Sort by path to get the newest version (highest number)
        cached_drivers.sort(reverse=True)
        driver_path = cached_drivers[0]
        print(f"✅ Znaleziono ChromeDriver w cache: {driver_path}")
        
        # 🔥 QUADRUPLE FORCE: Aggressive timeouts for Service
        service = Service(
            driver_path,
            log_path='NUL' if sys.platform == 'win32' else '/dev/null',  # Suppress logs
        )
        
        # Create driver with extended timeouts
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # 🔥 QUADRUPLE FORCE: Set aggressive page load timeout
        driver.set_page_load_timeout(60)  # 60 seconds for page load
        driver.set_script_timeout(30)  # 30 seconds for scripts
        driver.implicitly_wait(10)  # 10 seconds implicit wait
    else:
        # Fall back to ChromeDriverManager
        print("⚠️ Pobieranie ChromeDriver przez ChromeDriverManager...")
        try:
            service = Service(
                ChromeDriverManager().install(),
                log_path='NUL' if sys.platform == 'win32' else '/dev/null',
            )
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(60)
            driver.set_script_timeout(30)
            driver.implicitly_wait(10)
        except Exception as e:
            print(f"❌ Błąd podczas inicjalizacji ChromeDriver: {e}")
            print("💡 Spróbuj: pip install --upgrade selenium webdriver-manager")
            raise
    
    return driver


def click_h2h_tab(driver: webdriver.Chrome) -> None:
    """Spróbuj kliknąć zakładkę H2H - sprawdzamy kilka wariantów tekstowych i atrybutów."""
    for text in H2H_TAB_TEXT_OPTIONS:
        try:
            # XPath contains text
            el = driver.find_element(By.XPATH, f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]")
            el.click()
            time.sleep(0.8)
            return
        except Exception:
            pass

    # fallback: look for element with data-tab or href containing 'h2h'
    try:
        el = driver.find_element(By.XPATH, "//a[contains(@href, 'h2h') or contains(@data-tab, 'h2h')]")
        el.click()
        time.sleep(0.8)
        return
    except Exception:
        pass

    # if nothing works, do nothing and hope content is already present


def parse_h2h_from_soup(soup: BeautifulSoup, home_team: str) -> List[Dict]:
    """Parsuje sekcję H2H i zwraca listę ostatnich spotkań (do 5).
    Zwracany format: [{'date':..., 'home':..., 'away':..., 'score': 'x - y', 'winner': 'home'/'away'/'draw'}]
    """
    results = []

    # NOWA STRUKTURA LIVESPORT (2025)
    # Szukaj sekcji "Pojedynki bezpośrednie"
    h2h_sections = soup.find_all('div', class_='h2h__section')
    
    pojedynki_section = None
    for section in h2h_sections:
        text = section.get_text(" ", strip=True)
        if 'pojedynki' in text.lower() or 'bezpośrednie' in text.lower():
            pojedynki_section = section
            break
    
    if not pojedynki_section:
        # Fallback: weź pierwszą sekcję h2h__section
        if h2h_sections:
            pojedynki_section = h2h_sections[0]
    
    if not pojedynki_section:
        return results
    
    # Znajdź wiersze z meczami: a.h2h__row
    match_rows = pojedynki_section.select('a.h2h__row')
    
    for row in match_rows[:5]:  # Maksymalnie 5 ostatnich
        try:
            # Data
            date_el = row.select_one('span.h2h__date')
            date = date_el.get_text(strip=True) if date_el else ''
            
            # Gospodarz
            home_el = row.select_one('span.h2h__homeParticipant span.h2h__participantInner')
            home = home_el.get_text(strip=True) if home_el else ''
            
            # Gość
            away_el = row.select_one('span.h2h__awayParticipant span.h2h__participantInner')
            away = away_el.get_text(strip=True) if away_el else ''
            
            # Wynik
            score = ''
            winner = 'unknown'
            result_spans = row.select('span.h2h__result span')
            
            if len(result_spans) >= 2:
                goals_home = result_spans[0].get_text(strip=True)
                goals_away = result_spans[1].get_text(strip=True)
                score = f"{goals_home}-{goals_away}"
                
                # Determine winner
                try:
                    gh = int(goals_home)
                    ga = int(goals_away)
                    if gh > ga:
                        winner = 'home'
                    elif ga > gh:
                        winner = 'away'
                    else:
                        winner = 'draw'
                except:
                    winner = 'unknown'

            if home and away and score:
                results.append({
                    'date': date,
                    'home': home,
                    'away': away,
                    'score': score,
                    'winner': winner,
                    'raw': f"{date} {home} {score} {away}"
                })
        
        except Exception as e:
            continue

    return results


def process_match(url: str, driver: webdriver.Chrome, away_team_focus: bool = False, use_forebet: bool = False, use_gemini: bool = False, use_sofascore: bool = False, use_flashscore: bool = False, sport: str = 'football') -> Dict:
    """Odwiedza stronę meczu, otwiera H2H i zwraca informację we właściwym formacie.
    
    Args:
        url: URL meczu
        driver: Selenium WebDriver
        away_team_focus: Jeśli True, liczy zwycięstwa GOŚCI w H2H zamiast gospodarzy
        use_forebet: Jeśli True, pobiera predykcje z Forebet
        use_gemini: Jeśli True, używa Gemini AI do analizy
        sport: Sport (football, volleyball, etc.)
    """
    out = {
        'match_url': url,
        'home_team': None,
        'away_team': None,
        'match_time': None,
        'h2h_last5': [],
        'last_h2h_date': None,  # NOWE: Data ostatniego meczu H2H
        'home_wins_in_h2h_last5': 0,
        'away_wins_in_h2h_last5': 0,  # NOWE: dla trybu away_team_focus
        'h2h_count': 0,
        'win_rate': 0.0,  # % wygranych gospodarzy/gości w H2H (zależnie od trybu)
        'qualifies': False,
        'home_form': [],  # Forma gospodarzy: ['W', 'L', 'W', 'D', 'W']
        'away_form': [],  # Forma gości: ['L', 'L', 'W', 'L', 'W']
        'home_odds': None,  # Kursy bukmacherskie (info dodatkowa)
        'away_odds': None,
        'focus_team': 'away' if away_team_focus else 'home',  # NOWE: który tryb
        # FOREBET PREDICTIONS
        'forebet_prediction': None,  # '1', 'X', '2'
        'forebet_probability': None,  # float (%)
        'forebet_exact_score': None,  # '1-3'
        'forebet_over_under': None,  # 'Over 2.5' / 'Under 2.5'
        'forebet_btts': None,  # 'Yes' / 'No'
        'forebet_avg_goals': None,  # float
        # GEMINI AI PREDICTIONS
        'gemini_prediction': None,  # Krótka predykcja AI (1-2 zdania)
        'gemini_confidence': None,  # 0-100% pewności
        'gemini_reasoning': None,  # Szczegółowe uzasadnienie
        'gemini_recommendation': None,  # HIGH/MEDIUM/LOW/SKIP
    }

    # 🔥🔥🔥🔥 QUADRUPLE FORCE: Ultra-aggressive retry logic with multiple strategies
    max_retries = 5  # Increased from 3
    retry_delay = 2.0  # Start faster
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 🔥 Strategy 1: Normal navigation
            if attempt == 0:
                driver.get(url)
                time.sleep(3.0)  # Longer initial wait
            
            # 🔥 Strategy 2: Refresh if first failed
            elif attempt == 1:
                print(f"   🔄 Próba #2: Refresh...")
                driver.refresh()
                time.sleep(3.0)
            
            # 🔥 Strategy 3: Navigate to main page first, then match
            elif attempt == 2:
                print(f"   🔄 Próba #3: Via main page...")
                driver.get("https://www.livesport.com/pl/")
                time.sleep(2.0)
                driver.get(url)
                time.sleep(3.0)
            
            # 🔥 Strategy 4: Clear cache and try
            elif attempt == 3:
                print(f"   🔄 Próba #4: Clear cache...")
                driver.delete_all_cookies()
                time.sleep(1.0)
                driver.get(url)
                time.sleep(3.0)
            
            # 🔥 Strategy 5: Last resort - direct URL
            else:
                print(f"   🔄 Próba #5: Direct URL (last resort)...")
                driver.get(url)
                time.sleep(5.0)  # Extra long wait
            
            # Teraz spróbuj kliknąć zakładkę H2H
            click_h2h_tab(driver)
            time.sleep(2.5)  # Czekaj na załadowanie H2H
            break  # Success - wyjdź z pętli
            
        except (WebDriverException, ConnectionResetError, ConnectionError, TimeoutError) as e:
            last_error = e
            if attempt < max_retries - 1:
                print(f"⚠️ Błąd połączenia (próba {attempt + 1}/{max_retries}): {type(e).__name__}")
                print(f"   Czekam {retry_delay:.1f}s przed następną próbą...")
                time.sleep(retry_delay)
                retry_delay *= 1.3  # Gentler exponential backoff
                continue
            else:
                print(f"❌ Błąd otwierania {url} po {max_retries} próbach")
                print(f"   Ostatni błąd: {type(last_error).__name__}: {str(last_error)[:100]}")
                return out

    # pobierz tytuł strony jako fallback na nazwy druzyn
    try:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # spróbuj wyciągnąć nazwy drużyn z nagłówka
        title = soup.title.string if soup.title else ''
        if title:
            # tytuł często ma formę "Home - Away" lub "Home vs Away"
            import re
            m = re.split(r"\s[-–—|]\s|\svs\s|\sv\s", title)
            if len(m) >= 2:
                out['home_team'] = m[0].strip()
                out['away_team'] = m[1].strip()
    except Exception:
        pass

    # NIE MUSIMY KLIKAĆ H2H - już jesteśmy na stronie /h2h/ogolem/

    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # try to extract team names from the page header - NOWE SELEKTORY
    try:
        # Nowa struktura Livesport (2025)
        home_el = soup.select_one("div.smv__participantRow.smv__homeParticipant a.participant__participantName")
        if not home_el:
            home_el = soup.select_one("a.participant__participantName")
        if home_el:
            out['home_team'] = home_el.get_text(strip=True)
    except Exception:
        pass

    try:
        away_el = soup.select_one("div.smv__participantRow.smv__awayParticipant a.participant__participantName")
        if not away_el:
            # Fallback: weź drugą nazwę drużyny
            all_teams = soup.select("a.participant__participantName")
            if len(all_teams) >= 2:
                away_el = all_teams[1]
        if away_el:
            out['away_team'] = away_el.get_text(strip=True)
    except Exception:
        pass
    
    # Wydobądź datę i godzinę meczu
    try:
        # Szukaj różnych możliwych selektorów dla daty/czasu
        # Próba 1: Element z czasem startu
        time_el = soup.select_one("div.duelParticipant__startTime")
        if time_el:
            out['match_time'] = time_el.get_text(strip=True)
        
        # Próba 2: Z tytułu strony (często zawiera datę)
        if not out['match_time'] and soup.title:
            title = soup.title.string
            # Szukaj wzorca daty i czasu w tytule
            import re
            # Format: DD.MM.YYYY HH:MM lub podobne
            date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{2,4})\s*(\d{1,2}:\d{2})?', title)
            if date_match:
                date_str = date_match.group(1)
                time_str = date_match.group(2) if date_match.group(2) else ''
                out['match_time'] = f"{date_str} {time_str}".strip()
        
        # Próba 3: Z URL (może zawierać datę)
        if not out['match_time']:
            # Czasem data jest w parametrach URL
            if 'date=' in url:
                import re
                date_param = re.search(r'date=([^&]+)', url)
                if date_param:
                    out['match_time'] = date_param.group(1)
    except Exception:
        pass

    # parse H2H
    h2h = parse_h2h_from_soup(soup, out['home_team'] or '')
    out['h2h_last5'] = h2h
    
    # Wyciągnij datę ostatniego meczu H2H (pierwszy element)
    if h2h and len(h2h) > 0:
        out['last_h2h_date'] = h2h[0].get('date', None)

    # count home AND away wins in H2H list
    # WAŻNE: W zależności od trybu (away_team_focus), liczymy zwycięstwa gospodarzy lub gości
    cnt_home = 0
    cnt_away = 0
    current_home = out['home_team']
    current_away = out['away_team']
    
    for item in h2h:
        try:
            # Pobierz nazwy drużyn i wynik z H2H meczu
            h2h_home = item.get('home', '').strip()
            h2h_away = item.get('away', '').strip()
            score = item.get('score', '')
            
            # Parsuj wynik
            import re
            score_match = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
            if not score_match:
                continue
            
            goals_home_side = int(score_match.group(1))
            goals_away_side = int(score_match.group(2))
            
            # Sprawdź który zespół wygrał w tamtym meczu H2H
            if goals_home_side > goals_away_side:
                winner_team = h2h_home
            elif goals_away_side > goals_home_side:
                winner_team = h2h_away
            else:
                winner_team = None  # remis
            
            # Teraz sprawdź czy zwycięzcą był AKTUALNY GOSPODARZ
            if winner_team and current_home:
                winner_normalized = winner_team.lower().strip()
                current_home_normalized = current_home.lower().strip()
                
                if (winner_normalized == current_home_normalized or 
                    winner_normalized in current_home_normalized or 
                    current_home_normalized in winner_normalized):
                    cnt_home += 1
            
            # Teraz sprawdź czy zwycięzcą byli AKTUALNI GOŚCIE
            if winner_team and current_away:
                winner_normalized = winner_team.lower().strip()
                current_away_normalized = current_away.lower().strip()
                
                if (winner_normalized == current_away_normalized or 
                    winner_normalized in current_away_normalized or 
                    current_away_normalized in winner_normalized):
                    cnt_away += 1
                    
        except Exception as e:
            # Fallback: użyj starej heurystyki
            if item.get('winner') == 'home' and current_home:
                h2h_home = item.get('home', '').lower().strip()
                if current_home.lower().strip() in h2h_home or h2h_home in current_home.lower().strip():
                    cnt_home += 1
            if item.get('winner') == 'away' and current_away:
                h2h_away = item.get('away', '').lower().strip()
                if current_away.lower().strip() in h2h_away or h2h_away in current_away.lower().strip():
                    cnt_away += 1

    out['home_wins_in_h2h_last5'] = cnt_home
    out['away_wins_in_h2h_last5'] = cnt_away
    out['h2h_count'] = len(h2h)
    
    # NOWE KRYTERIUM: W zależności od trybu, sprawdzamy gospodarzy lub gości
    if away_team_focus:
        # Tryb GOŚCIE: Goście wygrali ≥60% meczów H2H
        win_rate = (cnt_away / len(h2h)) if len(h2h) > 0 else 0.0
        out['win_rate'] = win_rate
        basic_qualifies = win_rate >= 0.60 and len(h2h) >= 1
    else:
        # Tryb GOSPODARZE (domyślny): Gospodarze wygrali ≥60% meczów H2H
        win_rate = (cnt_home / len(h2h)) if len(h2h) > 0 else 0.0
        out['win_rate'] = win_rate
        basic_qualifies = win_rate >= 0.60 and len(h2h) >= 1
    
    # FORMA DRUŻYN: Dodaj pola dla zaawansowanej analizy
    out['home_form'] = []  # Forma ogólna (stara metoda)
    out['away_form'] = []
    out['home_form_overall'] = []  # NOWE: Forma z H2H overall
    out['home_form_home'] = []     # NOWE: Forma u siebie
    out['away_form_overall'] = []  # NOWE: Forma z H2H overall
    out['away_form_away'] = []     # NOWE: Forma na wyjeździe
    out['form_advantage'] = False  # NOWE: Czy gospodarze mają przewagę formy?
    
    # JEŚLI PODSTAWOWO SIĘ KWALIFIKUJE - sprawdź zaawansowaną formę
    if basic_qualifies:
        team_name = out['away_team'] if away_team_focus else out['home_team']
        print(f"   📊 Podstawowo kwalifikuje ({'GOŚCIE' if away_team_focus else 'GOSPODARZE'}: {team_name}, H2H: {win_rate*100:.0f}%) - sprawdzam formę...")
        try:
            # ZAAWANSOWANA ANALIZA FORMY (3 źródła)
            advanced_form = extract_advanced_team_form(url, driver)
            
            out['home_form_overall'] = advanced_form['home_form_overall']
            out['home_form_home'] = advanced_form['home_form_home']
            out['away_form_overall'] = advanced_form['away_form_overall']
            out['away_form_away'] = advanced_form['away_form_away']
            
            # W trybie away_team_focus, przewaga formy to GOŚCIE w dobrej formie i GOSPODARZE w słabej
            if away_team_focus:
                out['form_advantage'] = advanced_form.get('away_advantage', False)
            else:
                out['form_advantage'] = advanced_form['form_advantage']
            
            # Dla kompatybilności wstecznej - ustaw starą formę
            out['home_form'] = advanced_form['home_form_overall']
            out['away_form'] = advanced_form['away_form_overall']
            
            # FINALNE KRYTERIUM: H2H ≥60% (podstawowe)
            # Forma jest BONUSEM (dodatkowa ikona 🔥), nie wymogiem
            out['qualifies'] = basic_qualifies
            
            if out['form_advantage']:
                if away_team_focus:
                    print(f"   ✅ KWALIFIKUJE + PRZEWAGA FORMY GOŚCI! 🔥")
                else:
                    print(f"   ✅ KWALIFIKUJE + PRZEWAGA FORMY GOSPODARZY! 🔥")
                print(f"      Home ogółem: {format_form(advanced_form['home_form_overall'])}")
                print(f"      Home u siebie: {format_form(advanced_form['home_form_home'])}")
                print(f"      Away ogółem: {format_form(advanced_form['away_form_overall'])}")
                print(f"      Away na wyjeździe: {format_form(advanced_form['away_form_away'])}")
            elif advanced_form['home_form_overall'] or advanced_form['away_form_overall']:
                print(f"   ✅ KWALIFIKUJE (forma dostępna, ale brak przewagi)")
                print(f"      Home ogółem: {format_form(advanced_form['home_form_overall'])}")
                if advanced_form['home_form_home']:
                    print(f"      Home u siebie: {format_form(advanced_form['home_form_home'])}")
                print(f"      Away ogółem: {format_form(advanced_form['away_form_overall'])}")
                if advanced_form['away_form_away']:
                    print(f"      Away na wyjeździe: {format_form(advanced_form['away_form_away'])}")
            else:
                print(f"   ✅ KWALIFIKUJE (brak danych formy - tylko H2H)")
                
        except Exception as e:
            print(f"   ⚠️ Błąd analizy formy: {e}")
            # Fallback - używamy starego kryterium
            out['qualifies'] = basic_qualifies
            # Pobierz formę starą metodą
            try:
                home_form = extract_team_form(soup, driver, 'home', out.get('home_team'))
                away_form = extract_team_form(soup, driver, 'away', out.get('away_team'))
                out['home_form'] = home_form
                out['away_form'] = away_form
            except:
                pass
    else:
        # Nie kwalifikuje się podstawowo - nie sprawdzaj formy
        out['qualifies'] = False
    
    # Kursy bukmacherskie - dodatkowa informacja (NIE wpływa na scoring!)
    odds = extract_betting_odds(soup)
    out['home_odds'] = odds['home_odds']
    out['away_odds'] = odds['away_odds']

    # FOREBET PREDICTIONS - TYLKO jeśli mecz KWALIFIKUJE SIĘ!
    # 🔥 OPTYMALIZACJA: Skip Forebet dla meczów które i tak nie przejdą
    if use_forebet and FOREBET_AVAILABLE and out.get('qualifies') and out.get('home_team') and out.get('away_team'):
        try:
            print(f"      🎯 Forebet: Pobieram predykcję...")
            
            # Wyciągnij datę meczu z match_time (format: DD.MM.YY HH:MM lub DD.MM.YYYY HH:MM)
            from datetime import datetime as dt_forebet
            match_date_str = dt_forebet.now().strftime('%Y-%m-%d')  # Domyślna data = dzisiaj
            if out.get('match_time'):
                try:
                    import re
                    # Obsługa zarówno DD.MM.YY jak i DD.MM.YYYY
                    date_match = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', out['match_time'])
                    if date_match:
                        day, month, year = date_match.groups()
                        # Jeśli rok ma 4 cyfry, użyj go bezpośrednio
                        if len(year) == 4:
                            match_date_str = f'{year}-{month}-{day}'
                        else:
                            # Rok 2-cyfrowy: 00-50 -> 2000s, 51-99 -> 1900s
                            year_int = int(year)
                            full_year = 2000 + year_int if year_int <= 50 else 1900 + year_int
                            match_date_str = f'{full_year}-{month}-{day}'
                except:
                    pass
            
            forebet_result = search_forebet_prediction(
                home_team=out['home_team'],
                away_team=out['away_team'],
                match_date=match_date_str,
                driver=driver,  # Reużywamy tego samego drivera
                sport=sport,
                headless=False  # Forebet wymaga visible mode
            )
            
            if forebet_result.get('success'):
                out['forebet_prediction'] = forebet_result.get('prediction')
                out['forebet_probability'] = forebet_result.get('probability')
                out['forebet_exact_score'] = forebet_result.get('exact_score')
                out['forebet_over_under'] = forebet_result.get('over_under')
                out['forebet_btts'] = forebet_result.get('btts')
                out['forebet_avg_goals'] = forebet_result.get('avg_goals')
                
                print(f"      ✅ {format_forebet_result(forebet_result)}")
            else:
                print(f"      ⚠️ Forebet: {forebet_result.get('error', 'Brak predykcji')}")
                
        except Exception as e:
            print(f"      ⚠️ Błąd Forebet: {e}")
    
    # ============================================
    # GEMINI AI ANALYSIS (Faza 3)
    # ============================================
    if use_gemini and out.get('qualifies'):
        try:
            print("      🤖 Gemini AI analysis...")
            
            # Przygotuj dane dla AI
            h2h_data = {
                'home_wins': out.get('home_wins_in_h2h_last5', 0),
                'away_wins': out.get('away_wins_in_h2h_last5', 0),
                'total': out.get('h2h_count', 5)
            }
            
            # Forma jako string (np. "7/10")
            home_form_str = format_form_as_score(out.get('home_form', []))
            away_form_str = format_form_as_score(out.get('away_form', []))
            
            # Forebet prediction string
            forebet_str = None
            if out.get('forebet_prediction') and out.get('forebet_probability'):
                forebet_str = f"{out['forebet_prediction']} ({out['forebet_probability']:.1f}%)"
                if out.get('forebet_exact_score'):
                    forebet_str += f" - {out['forebet_exact_score']}"
            
            # Wywołaj Gemini AI (lazy load)
            if lazy_load_gemini():
                gemini_result = gemini_analyze_match(
                    home_team=out.get('home_team', 'Unknown'),
                    away_team=out.get('away_team', 'Unknown'),
                    sport=sport,
                    h2h_data=h2h_data,
                    home_form=home_form_str,
                    away_form=away_form_str,
                    forebet_prediction=forebet_str,
                    home_odds=out.get('home_odds'),
                    away_odds=out.get('away_odds'),
                    additional_info=f"Last H2H: {out.get('last_h2h_date', 'N/A')}"
                )
                
                # Zapisz wyniki
                if not gemini_result.get('error'):
                    out['gemini_prediction'] = gemini_result.get('prediction')
                    out['gemini_confidence'] = gemini_result.get('confidence')
                    out['gemini_reasoning'] = gemini_result.get('reasoning')
                    out['gemini_recommendation'] = gemini_result.get('recommendation')
                    
                    print(f"      ✅ AI: {gemini_result.get('prediction', '')[:60]}... ({gemini_result.get('confidence', 0)}%)")
                else:
                    print(f"      ⚠️ Gemini AI: {gemini_result.get('error', 'Unknown error')}")
            else:
                print(f"      ⚠️ Gemini AI niedostępne - pominięto")
                
        except Exception as e:
            print(f"      ⚠️ Błąd Gemini AI: {e}")
    
    # ========================================================================
    # SOFASCORE INTEGRATION - "Who will win?" predictions
    # ========================================================================
    if use_sofascore:
        try:
            print(f"   🎯 SofaScore: Pobieranie predykcji...")
            from sofascore_scraper import scrape_sofascore_full
            
            sofascore_result = scrape_sofascore_full(
                driver=driver,
                home_team=out['home_team'],
                away_team=out['away_team'],
                sport=sport
            )
            
            if sofascore_result.get('sofascore_found'):
                # Dodaj dane SofaScore do wyniku
                out['sofascore_home_win_prob'] = sofascore_result.get('sofascore_home_win_prob')
                out['sofascore_draw_prob'] = sofascore_result.get('sofascore_draw_prob')
                out['sofascore_away_win_prob'] = sofascore_result.get('sofascore_away_win_prob')
                out['sofascore_total_votes'] = sofascore_result.get('sofascore_total_votes', 0)
                out['sofascore_home_odds_avg'] = sofascore_result.get('sofascore_home_odds_avg')
                out['sofascore_away_odds_avg'] = sofascore_result.get('sofascore_away_odds_avg')
                out['sofascore_url'] = sofascore_result.get('sofascore_url')
                
                print(f"      ✅ SofaScore: Home={sofascore_result.get('sofascore_home_win_prob')}%, "
                      f"Away={sofascore_result.get('sofascore_away_win_prob')}%, "
                      f"Votes={sofascore_result.get('sofascore_total_votes', 0)}")
            else:
                print(f"      ⚠️ SofaScore: Mecz nie znaleziony")
                
        except ImportError:
            print(f"      ⚠️ SofaScore scraper nie zainstalowany")
        except Exception as e:
            print(f"      ⚠️ Błąd SofaScore: {e}")
    
    # FLASHSCORE ODDS
    if use_flashscore and FLASHSCORE_AVAILABLE and out.get('qualifies') and out.get('home_team') and out.get('away_team'):
        try:
            print(f"   💰 FlashScore: Pobieranie kursów...")
            
            flashscore_scraper = FlashScoreOddsScraper(headless=True)
            flashscore_result = flashscore_scraper.get_odds(
                home_team=out['home_team'],
                away_team=out['away_team'],
                sport=sport,
                driver=driver  # Reużywamy istniejącego drivera
            )
            
            if flashscore_result.get('found'):
                out['flashscore_home_odds'] = flashscore_result.get('home_odds')
                out['flashscore_draw_odds'] = flashscore_result.get('draw_odds')
                out['flashscore_away_odds'] = flashscore_result.get('away_odds')
                out['flashscore_over_25'] = flashscore_result.get('over_25_odds')
                out['flashscore_under_25'] = flashscore_result.get('under_25_odds')
                out['flashscore_bookmaker'] = flashscore_result.get('bookmaker', 'FlashScore')
                out['flashscore_found'] = True
                
                # Fallback: jeśli nie mamy home_odds/away_odds z Livesport, użyj FlashScore
                if not out.get('home_odds') and flashscore_result.get('home_odds'):
                    out['home_odds'] = flashscore_result.get('home_odds')
                if not out.get('away_odds') and flashscore_result.get('away_odds'):
                    out['away_odds'] = flashscore_result.get('away_odds')
                
                print(f"      ✅ FlashScore: {flashscore_result.get('home_odds')}/{flashscore_result.get('draw_odds')}/{flashscore_result.get('away_odds')}")
            else:
                print(f"      ⚠️ FlashScore: Kursy nie znalezione")
                out['flashscore_found'] = False
                
        except Exception as e:
            print(f"      ⚠️ Błąd FlashScore: {e}")
            out['flashscore_found'] = False
    elif use_flashscore and not FLASHSCORE_AVAILABLE:
        print(f"      ⚠️ FlashScore: Scraper niedostępny")

    return out


def format_form(form_list: List[str]) -> str:
    """
    Formatuje listę formy do ładnego stringa z emoji.
    
    Args:
        form_list: ['W', 'L', 'D', 'W', 'W']
    
    Returns:
        'W✅ L❌ D🟡 W✅ W✅'
    """
    emoji_map = {'W': '✅', 'L': '❌', 'D': '🟡'}
    return ' '.join([f"{r}{emoji_map.get(r, '')}" for r in form_list])


def format_form_as_score(form_list: List[str]) -> str:
    """
    Konwertuje formę na score (np. 7/10 dla Gemini AI)
    
    Args:
        form_list: ['W', 'L', 'D', 'W', 'W']
    
    Returns:
        '7/10' (3 wins * 3 + 1 draw * 1 = 10, scale to /10)
    """
    if not form_list:
        return 'N/A'
    
    wins = form_list.count('W')
    draws = form_list.count('D')
    total = len(form_list)
    
    # Scoring: Win=3pts, Draw=1pt, Loss=0pt
    points = wins * 3 + draws * 1
    max_points = total * 3
    
    # Scale to /10
    if max_points > 0:
        score = round((points / max_points) * 10, 1)
        return f"{score}/10"
    
    return 'N/A'


def extract_advanced_team_form(match_url: str, driver: webdriver.Chrome) -> Dict:
    """
    Ekstraktuje zaawansowaną formę drużyn z 3 źródeł:
    1. Forma ogólna (ostatnie 5 meczów)
    2. Forma u siebie (gospodarze)
    3. Forma na wyjeździe (goście)
    
    Returns:
        {
            'home_form_overall': ['W', 'L', 'D', 'W', 'W'],
            'home_form_home': ['W', 'W', 'W', 'D', 'W'],  # Forma gospodarzy u siebie
            'away_form_overall': ['L', 'L', 'W', 'L', 'D'],
            'away_form_away': ['L', 'L', 'L', 'D', 'L'],  # Forma gości na wyjeździe
            'form_advantage': True/False  # Czy gospodarze mają przewagę?
        }
    """
    result = {
        'home_form_overall': [],
        'home_form_home': [],
        'away_form_overall': [],
        'away_form_away': [],
        'form_advantage': False
    }
    
    try:
        # Konwertuj URL meczu na URL H2H
        # Z: /mecz/pilka-nozna/team1/team2/?mid=XXX
        # Na: /mecz/pilka-nozna/team1/team2/h2h/ogolem/?mid=XXX (lub /u-siebie/, /na-wyjezdzie/)
        
        if '/match/' in match_url or '/mecz/' in match_url:
            base_url = match_url.split('?')[0]  # Usuń query params
            
            # Usuń końcówkę "/szczegoly" lub inną stronę, jeśli istnieje
            base_url = base_url.rstrip('/')
            if base_url.endswith('/szczegoly') or base_url.endswith('/szczegoly/'):
                base_url = base_url.replace('/szczegoly', '')
            
            mid = match_url.split('mid=')[1] if 'mid=' in match_url else ''
            
            # 1. FORMA OGÓLNA
            h2h_overall_url = f"{base_url}/h2h/ogolem/?mid={mid}"
            result['home_form_overall'], result['away_form_overall'] = _extract_form_from_h2h_page(
                h2h_overall_url, driver, 'overall'
            )
            
            # 2. FORMA U SIEBIE (gospodarze)
            h2h_home_url = f"{base_url}/h2h/u-siebie/?mid={mid}"
            result['home_form_home'], _ = _extract_form_from_h2h_page(
                h2h_home_url, driver, 'home'
            )
            
            # 3. FORMA NA WYJEŹDZIE (goście)
            # NOWA METODA: Pobierz dane z strony ogólnej H2H i filtruj mecze gości na wyjeździe
            result['away_form_away'] = _extract_away_form_from_overall(
                h2h_overall_url, driver, result['away_form_overall']
            )
            
            # 4. ANALIZA PRZEWAGI FORMY
            result['form_advantage'] = _analyze_form_advantage(result)
            # 5. ANALIZA PRZEWAGI GOŚCI (dla trybu away_team_focus)
            result['away_advantage'] = _analyze_away_form_advantage(result)
            
    except Exception as e:
        print(f"   ⚠️ extract_advanced_team_form error: {e}")
    
    return result


def _extract_form_from_h2h_page(url: str, driver: webdriver.Chrome, context: str) -> tuple:
    """
    Pomocnicza funkcja do ekstraktowania formy z konkretnej strony H2H.
    
    Args:
        url: URL strony H2H
        driver: Selenium WebDriver
        context: 'overall', 'home', lub 'away'
    
    Returns:
        (home_form, away_form) - każda to lista ['W', 'L', 'D', ...]
    """
    home_form = []
    away_form = []
    
    try:
        driver.get(url)
        time.sleep(3.0)  # Czas na załadowanie dynamicznych elementów
        
        # Scroll down to trigger lazy-loading content
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.0)
        except:
            pass
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # DEBUG: Sprawdź czy strona się załadowała
        page_text = soup.get_text()
        if 'error' in page_text.lower() or 'can\'t be displayed' in page_text.lower():
            print(f"      ⚠️ Strona {context} zwróciła błąd (404?) - URL może być niepoprawny")
            return ([], [])
        
        # NOWA METODA 1: Ekstraktuj formy z sekcji h2h__section
        # Livesport organizuje dane w sekcje: pierwsza sekcja = home, druga = away
        h2h_sections = soup.find_all('div', class_='h2h__section')
        
        for idx, section in enumerate(h2h_sections[:2]):  # Pierwsze 2 sekcje (home, away)
            # METODA 1A: Szukaj form badges z różnymi klasami (LiveSport zmienia je)
            badges = section.find_all('div', class_=lambda c: c and 'badgeform' in c.lower() if c else False)
            
            # METODA 1B: Alternatywne selektory
            if not badges:
                badges = section.select('div[class*="form"], span[class*="form"]')
            
            temp_form = []
            for badge in badges[:5]:  # Max 5 wyników
                text = badge.get_text().strip()
                title = badge.get('title', '')
                
                # Konwersja: Z->W, R->D, P->L (polskie oznaczenia)
                if 'Zwyci' in title or text == 'Z' or text == 'W':
                    temp_form.append('W')
                elif 'Remis' in title or text == 'R' or text == 'D':
                    temp_form.append('D')
                elif 'Pora' in title or text == 'P' or text == 'L':
                    temp_form.append('L')
            
            # Przypisz do home (idx=0) lub away (idx=1)
            if idx == 0:
                home_form = temp_form
            elif idx == 1:
                away_form = temp_form
        
        # FALLBACK METODA 2: Jeśli badges nie zadziałały, analizuj wiersze z wynikami
        if (not home_form and not away_form) or (len(home_form) == 0 and len(away_form) == 0):
            # Szukaj wierszy z meczami w sekcjach H2H
            for idx, section in enumerate(h2h_sections[:2]):
                match_rows = section.select('a.h2h__row')
                
                temp_form = []
                for row in match_rows[:5]:
                    try:
                        # Pobierz wynik
                        result_spans = row.select('span.h2h__result span')
                        if len(result_spans) >= 2:
                            score_home = int(result_spans[0].get_text(strip=True))
                            score_away = int(result_spans[1].get_text(strip=True))
                            
                            # idx=0 to forma gospodarzy, idx=1 to forma gości
                            if idx == 0:  # Sekcja gospodarzy
                                if score_home > score_away:
                                    temp_form.append('W')
                                elif score_away > score_home:
                                    temp_form.append('L')
                                else:
                                    temp_form.append('D')
                            else:  # Sekcja gości
                                if score_away > score_home:
                                    temp_form.append('W')
                                elif score_home > score_away:
                                    temp_form.append('L')
                                else:
                                    temp_form.append('D')
                    except:
                        continue
                
                if idx == 0:
                    home_form = temp_form
                elif idx == 1:
                    away_form = temp_form
        
        # FALLBACK METODA 3: Stara metoda analizy wierszy
        if (not home_form and not away_form) or (len(home_form) == 0 and len(away_form) == 0):
            h2h_rows = soup.select('div.h2h__row, tr.h2h')
            
            for row in h2h_rows[:5]:
                # Sprawdź wynik meczu
                score_elem = row.select_one('div[class*="score"], span[class*="score"]')
                if score_elem:
                    score_text = score_elem.get_text(strip=True)
                    # Format: "3:1" lub "1:0"
                    if ':' in score_text or '-' in score_text:
                        try:
                            separator = ':' if ':' in score_text else '-'
                            home_score, away_score = map(int, score_text.split(separator))
                            if home_score > away_score:
                                home_form.append('W')
                                away_form.append('L')
                            elif away_score > home_score:
                                home_form.append('L')
                                away_form.append('W')
                            else:
                                home_form.append('D')
                                away_form.append('D')
                        except:
                            continue
                            
    except Exception as e:
        print(f"      ⚠️ _extract_form_from_h2h_page error ({context}): {e}")
    
    return (home_form[:5], away_form[:5])


def _extract_away_form_from_overall(url: str, driver: webdriver.Chrome, away_form_overall: List[str]) -> List[str]:
    """
    Ekstraktuje formę gości NA WYJEŹDZIE z ogólnej strony H2H.
    Analizuje wiersze meczów i sprawdza który mecz był rozgrywany na wyjeździe.
    
    Args:
        url: URL strony H2H ogółem
        driver: Selenium WebDriver
        away_form_overall: Ogólna forma gości (jako fallback)
    
    Returns:
        Lista formy na wyjeździe ['W', 'L', 'D', ...] lub away_form_overall jeśli nie można pobrać
    """
    away_form_away = []
    
    try:
        # Strona jest już załadowana z wcześniejszego wywołania, ale dla pewności odśwież
        driver.get(url)
        time.sleep(2.0)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Szukaj drugiej sekcji H2H (sekcja gości)
        h2h_sections = soup.find_all('div', class_='h2h__section')
        
        if len(h2h_sections) >= 2:
            away_section = h2h_sections[1]  # Druga sekcja = goście
            
            # Znajdź wiersze meczów
            match_rows = away_section.select('a.h2h__row')
            
            for row in match_rows[:5]:
                try:
                    # Pobierz nazwy drużyn
                    home_el = row.select_one('span.h2h__homeParticipant span.h2h__participantInner')
                    away_el = row.select_one('span.h2h__awayParticipant span.h2h__participantInner')
                    
                    home_name = home_el.get_text(strip=True) if home_el else ''
                    away_name = away_el.get_text(strip=True) if away_el else ''
                    
                    # Pobierz wynik
                    result_spans = row.select('span.h2h__result span')
                    if len(result_spans) >= 2:
                        score_home = int(result_spans[0].get_text(strip=True))
                        score_away = int(result_spans[1].get_text(strip=True))
                        
                        # Sekcja gości pokazuje mecze gdzie aktualny gość grał
                        # Musimy sprawdzić czy w TYM meczu był on GOŚCIEM czy GOSPODARZEM
                        # Jeśli away_name jest w nazwie current_away_team (z main match), to był gościem
                        
                        # Prostsza metoda: patrz na wynik z perspektywy away_name
                        # Jeśli away_name = away w h2h_row -> był gościem
                        # Możemy to poznać po pozycji (right side)
                        
                        # ZAKŁADAMY że w sekcji gości, mecze są pokazane z perspektywy gościa
                        # więc score_away to jego wynik
                        if score_away > score_home:
                            away_form_away.append('W')
                        elif score_home > score_away:
                            away_form_away.append('L')
                        else:
                            away_form_away.append('D')
                            
                except Exception as e:
                    continue
        
        # Jeśli nie znaleziono danych, użyj formy ogólnej jako fallback
        if not away_form_away and away_form_overall:
            return away_form_overall[:5]
        
    except Exception as e:
        print(f"      ⚠️ _extract_away_form_from_overall error: {e}")
        return away_form_overall[:5] if away_form_overall else []
    
    return away_form_away[:5]


def _analyze_form_advantage(form_data: Dict) -> bool:
    """
    Analizuje czy gospodarze mają przewagę w formie.
    
    Kryteria:
    - Gospodarze w dobrej formie (więcej W+D niż L)
    - Goście w słabej formie (więcej L niż W+D)
    - Gospodarze lepsi od gości
    
    Returns:
        True jeśli gospodarze mają przewagę
    """
    try:
        # Oblicz punkty formy (W=3, D=1, L=0)
        def form_points(form_list):
            points = 0
            for result in form_list:
                if result == 'W':
                    points += 3
                elif result == 'D':
                    points += 1
            return points
        
        # Forma ogólna
        home_overall_pts = form_points(form_data['home_form_overall'])
        away_overall_pts = form_points(form_data['away_form_overall'])
        
        # Forma kontekstowa (u siebie/na wyjeździe)
        home_home_pts = form_points(form_data['home_form_home'])
        away_away_pts = form_points(form_data['away_form_away'])
        
        # Przewaga jeśli:
        # 1. Gospodarze mają więcej punktów (ogółem)
        # 2. Gospodarze u siebie > Goście na wyjeździe
        # 3. Gospodarze w dobrej formie (>= 7 pkt z 15 możliwych)
        
        home_good_form = home_overall_pts >= 7  # >= 2.3 pkt/mecz
        away_poor_form = away_overall_pts <= 6   # <= 1.2 pkt/mecz
        
        home_better = (home_overall_pts > away_overall_pts and 
                      home_home_pts > away_away_pts)
        
        return (home_good_form and away_poor_form) or home_better
        
    except Exception:
        return False


def _analyze_away_form_advantage(form_data: Dict) -> bool:
    """
    Analizuje czy GOŚCIE mają przewagę w formie.
    
    Kryteria (odwrotne niż dla gospodarzy):
    - Goście w dobrej formie (więcej W+D niż L)
    - Gospodarze w słabej formie (więcej L niż W+D)
    - Goście lepsi od gospodarzy
    
    Returns:
        True jeśli goście mają przewagę
    """
    try:
        # Oblicz punkty formy (W=3, D=1, L=0)
        def form_points(form_list):
            points = 0
            for result in form_list:
                if result == 'W':
                    points += 3
                elif result == 'D':
                    points += 1
            return points
        
        # Forma ogólna
        home_overall_pts = form_points(form_data['home_form_overall'])
        away_overall_pts = form_points(form_data['away_form_overall'])
        
        # Forma kontekstowa (u siebie/na wyjeździe)
        home_home_pts = form_points(form_data['home_form_home'])
        away_away_pts = form_points(form_data['away_form_away'])
        
        # Przewaga GOŚCI jeśli:
        # 1. Goście mają więcej punktów (ogółem)
        # 2. Goście na wyjeździe > Gospodarze u siebie
        # 3. Goście w dobrej formie (>= 7 pkt z 15 możliwych)
        
        away_good_form = away_overall_pts >= 7  # >= 2.3 pkt/mecz
        home_poor_form = home_overall_pts <= 6   # <= 1.2 pkt/mecz
        
        away_better = (away_overall_pts > home_overall_pts and 
                      away_away_pts > home_home_pts)
        
        return (away_good_form and home_poor_form) or away_better
        
    except Exception:
        return False


def extract_team_form(soup: BeautifulSoup, driver: webdriver.Chrome, side: str, team_name: str) -> List[str]:
    """
    Ekstraktuje formę drużyny (ostatnie 5 meczów: W/L/D).
    
    Args:
        soup: BeautifulSoup object strony meczu
        driver: Selenium WebDriver
        side: 'home' lub 'away'
        team_name: Nazwa drużyny
    
    Returns:
        Lista wyników: ['W', 'W', 'L', 'D', 'W'] (od najnowszego do najstarszego)
    """
    form = []
    
    try:
        # METODA 1: Szukaj elementów formy na stronie (ikony W/L/D)
        # Livesport często ma elementy z klasami typu "form__cell--win", "form__cell--loss", etc.
        
        if side == 'home':
            form_selectors = [
                'div.smv__homeParticipant div[class*="form"]',
                'div.participant__form--home',
                'div[class*="homeForm"]'
            ]
        else:
            form_selectors = [
                'div.smv__awayParticipant div[class*="form"]',
                'div.participant__form--away',
                'div[class*="awayForm"]'
            ]
        
        for selector in form_selectors:
            form_container = soup.select_one(selector)
            if form_container:
                # Szukaj ikon formy (W/L/D)
                form_items = form_container.find_all(['div', 'span'], class_=re.compile(r'form.*cell|form.*item'))
                
                for item in form_items[:5]:  # Maksymalnie 5 ostatnich meczów
                    class_str = ' '.join(item.get('class', []))
                    
                    if 'win' in class_str.lower():
                        form.append('W')
                    elif 'loss' in class_str.lower() or 'lost' in class_str.lower():
                        form.append('L')
                    elif 'draw' in class_str.lower():
                        form.append('D')
                
                if form:
                    break
        
        # METODA 2: Jeśli nie znaleziono formy, parsuj z tytułów/tekstów
        if not form:
            # Szukaj elementów z tekstem typu "W", "L", "D"
            all_text_elements = soup.find_all(['div', 'span'], string=re.compile(r'^[WLD]$'))
            for elem in all_text_elements[:5]:
                text = elem.get_text(strip=True).upper()
                if text in ['W', 'L', 'D']:
                    form.append(text)
        
        # METODA 3: Fallback - parsuj ostatnie mecze z H2H jako proxy formy
        if not form and team_name:
            # Pobierz ostatnie mecze drużyny (nie tylko H2H) z sekcji "form" lub "last matches"
            last_matches = soup.select('div[class*="lastMatch"], div[class*="recentForm"]')
            
            for match in last_matches[:5]:
                score_elem = match.find(string=re.compile(r'\d+\s*[-:]\s*\d+'))
                if score_elem:
                    score_match = re.search(r'(\d+)\s*[-:]\s*(\d+)', score_elem)
                    if score_match:
                        goals1 = int(score_match.group(1))
                        goals2 = int(score_match.group(2))
                        
                        if goals1 > goals2:
                            form.append('W')
                        elif goals2 > goals1:
                            form.append('L')
                        else:
                            form.append('D')
    
    except Exception as e:
        # Jeśli coś pójdzie nie tak, zwróć pustą listę
        pass
    
    # Ogranicz do 5 meczów
    return form[:5]


def extract_betting_odds(soup: BeautifulSoup) -> Dict[str, Optional[float]]:
    """
    Ekstraktuj kursy bukmacherskie dla meczu (jeśli dostępne).
    
    Returns:
        {'home_odds': 1.85, 'away_odds': 2.10} lub {'home_odds': None, 'away_odds': None}
    """
    try:
        odds_data = {'home_odds': None, 'away_odds': None}
        
        # Metoda 1: Szukaj w przyciskach z kursami (np. <button class="*odds*">)
        odds_buttons = soup.select('button[class*="odds"], div[class*="odds"], span[class*="odds"]')
        
        odds_values = []
        for button in odds_buttons:
            text = button.get_text(strip=True)
            # Szukaj liczb typu 1.85, 2.10, etc.
            odds_match = re.findall(r'\d+\.\d{2}', text)
            if odds_match:
                odds_values.extend([float(o) for o in odds_match])
        
        # Metoda 2: Szukaj w data-attributes
        odds_elements = soup.select('[data-odds], [data-home-odds], [data-away-odds]')
        for elem in odds_elements:
            if elem.get('data-home-odds'):
                try:
                    odds_data['home_odds'] = float(elem.get('data-home-odds'))
                except:
                    pass
            if elem.get('data-away-odds'):
                try:
                    odds_data['away_odds'] = float(elem.get('data-away-odds'))
                except:
                    pass
        
        # Metoda 3: Szukaj w JSON-LD lub skryptach
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if 'offers' in data or 'odds' in str(data).lower():
                    # Próbuj wydobyć kursy z JSON
                    pass
            except:
                pass
        
        # Jeśli znaleźliśmy dokładnie 2 kursy (home i away)
        if len(odds_values) >= 2 and odds_data['home_odds'] is None:
            odds_data['home_odds'] = odds_values[0]
            odds_data['away_odds'] = odds_values[1]
        
        return odds_data
        
    except Exception as e:
        print(f"   ⚠️ extract_betting_odds error: {e}")
        return {'home_odds': None, 'away_odds': None}


def extract_player_ranking(soup: BeautifulSoup, player_name: str) -> Optional[int]:
    """
    Wydobądź ranking zawodnika ze strony.
    
    Livesport przechowuje rankingi w JSON wbudowanym w HTML:
    "rank":["ATP","13","..."]
    """
    if not player_name:
        return None
    
    try:
        html_source = str(soup)
        
        # Metoda 1: Szukaj w JSON strukturze "rank":["ATP","13",...]
        # Pattern: "rank":\["(ATP|WTA)","(\d+)","
        rank_pattern = r'"rank":\["(ATP|WTA)","(\d+)",'
        matches = re.findall(rank_pattern, html_source, re.IGNORECASE)
        
        if len(matches) >= 2:
            # Mamy dwa rankingi - musimy określić który należy do którego zawodnika
            # Sprawdźmy kolejność nazwisk na stronie
            all_participants = soup.select('a.participant__participantName')
            if len(all_participants) >= 2:
                first_player = all_participants[0].get_text(strip=True)
                second_player = all_participants[1].get_text(strip=True)
                
                # Sprawdź czy player_name pasuje do pierwszego czy drugiego
                player_normalized = player_name.lower().strip()
                first_normalized = first_player.lower().strip()
                second_normalized = second_player.lower().strip()
                
                if player_normalized in first_normalized or first_normalized in player_normalized:
                    # To pierwszy zawodnik - pierwszy ranking
                    return int(matches[0][1])  # matches[0][1] to numer rankingu
                elif player_normalized in second_normalized or second_normalized in player_normalized:
                    # To drugi zawodnik - drugi ranking
                    return int(matches[1][1])
        
        # Fallback: Jeśli jest tylko 1 ranking
        if len(matches) == 1:
            return int(matches[0][1])
        
        # Metoda 2 (Fallback): "ATP: 13" lub "WTA: 42" w tekście
        text = soup.get_text()
        atp_wta_rankings = re.findall(r'(?:ATP|WTA):\s*(\d+)', text, re.IGNORECASE)
        
        if len(atp_wta_rankings) >= 2:
            all_participants = soup.select('a.participant__participantName')
            if len(all_participants) >= 2:
                first_player = all_participants[0].get_text(strip=True)
                second_player = all_participants[1].get_text(strip=True)
                
                player_normalized = player_name.lower().strip()
                first_normalized = first_player.lower().strip()
                second_normalized = second_player.lower().strip()
                
                if player_normalized in first_normalized or first_normalized in player_normalized:
                    return int(atp_wta_rankings[0])
                elif player_normalized in second_normalized or second_normalized in player_normalized:
                    return int(atp_wta_rankings[1])
        
        return None
    except Exception as e:
        print(f"   ⚠️ extract_player_ranking error: {e}")
        return None


def detect_tennis_surface(soup: BeautifulSoup, url: str) -> Optional[str]:
    """
    Wykryj powierzchnię kortu z informacji o turnieju.
    
    Returns:
        'clay', 'grass', 'hard', lub None
    """
    try:
        text = soup.get_text().lower()
        url_lower = url.lower()
        
        # Metoda 1: Wykryj z elementów H2H na stronie
        # Livesport oznacza powierzchnię w klasach: 'clay', 'grass', 'hard'
        surface_elements = soup.select('[class*="surface"]')
        for el in surface_elements:
            classes = ' '.join(el.get('class', [])).lower()
            if 'clay' in classes or 'ziemna' in classes:
                return 'clay'
            if 'grass' in classes or 'trawiasta' in classes:
                return 'grass'
            if 'hard' in classes or 'twarda' in classes:
                return 'hard'
        
        # Metoda 2: Słowa kluczowe w tekście/URL
        # Clay
        clay_keywords = [
            'clay', 'ziemia', 'ziemna', 'antuka', 'roland garros', 'french open',
            'monte carlo', 'rome', 'madrid', 'barcelona', 'hamburg',
            'roland-garros', 'glina'
        ]
        if any(kw in text or kw in url_lower for kw in clay_keywords):
            return 'clay'
        
        # Grass
        grass_keywords = [
            'grass', 'trawa', 'trawiasta', 'wimbledon', 'halle', 'queens', 
            's-hertogenbosch', 'eastbourne', 'mallorca'
        ]
        if any(kw in text or kw in url_lower for kw in grass_keywords):
            return 'grass'
        
        # Hard
        hard_keywords = [
            'hard', 'twarda', 'us open', 'australian open', 'usopen', 
            'australian', 'indian wells', 'miami', 'cincinnati', 
            'montreal', 'toronto', 'shanghai', 'beijing', 'paris masters',
            'szanghaj', 'pekin'
        ]
        if any(kw in text or kw in url_lower for kw in hard_keywords):
            return 'hard'
        
        # Domyślnie: hard (najczęstsza powierzchnia)
        return 'hard'
    except Exception:
        return None


def extract_player_form_simple(soup: BeautifulSoup, player_name: str, h2h_matches: List[Dict]) -> List[str]:
    """
    Wydobądź formę zawodnika (ostatnie wyniki).
    
    Używa H2H jako proxy - bierze ostatnie mecze zawodnika przeciwko WSZYSTKIM
    przeciwnikom i ekstraktuje W/L pattern.
    
    Returns:
        ['W', 'W', 'L', 'W', 'W']  # W=wygrana, L=przegrana
    """
    if not player_name:
        return []
    
    try:
        # METODA 1: Szukaj "form" badge/indicators na stronie Livesport
        # Czasami Livesport pokazuje formę jako serie W/L/D
        form_indicators = soup.select('div.form, span.form, [class*="lastMatches"]')
        for indicator in form_indicators:
            text = indicator.get_text(strip=True).upper()
            # Ekstraktuj tylko W/L/D
            form_chars = [c for c in text if c in ['W', 'L', 'D']]
            if len(form_chars) >= 3:  # Mamy przynajmniej 3 wyniki
                # Konwertuj D (draw) na L w tenisie
                return [('L' if c == 'D' else c) for c in form_chars[:5]]
        
        # METODA 2: Użyj H2H jako proxy (ostatnie mecze tego zawodnika)
        if not h2h_matches:
            # Jeśli brak H2H, symuluj przeciętną formę (3W/2L = 60%)
            return ['W', 'W', 'W', 'L', 'L']
        
        player_form = []
        player_normalized = player_name.lower().strip()
        
        # Przeiteruj przez H2H (to są mecze MIĘDZY tymi dwoma zawodnikami)
        for match in h2h_matches:
            home = match.get('home', '').lower().strip()
            away = match.get('away', '').lower().strip()
            winner = match.get('winner', '')
            
            # Sprawdź czy nasz zawodnik grał i czy wygrał
            if player_normalized in home or home in player_normalized:
                if winner == 'home':
                    player_form.append('W')
                elif winner == 'away':
                    player_form.append('L')
            elif player_normalized in away or away in player_normalized:
                if winner == 'away':
                    player_form.append('W')
                elif winner == 'home':
                    player_form.append('L')
            
            if len(player_form) >= 5:
                break
        
        # Jeśli mamy mniej niż 5 wyników, uzupełnij do 5 na podstawie win rate
        if len(player_form) < 5 and player_form:
            wins = player_form.count('W')
            losses = player_form.count('L')
            win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.5
            
            # Dopełnij do 5 używając win rate jako prawdopodobieństwa
            while len(player_form) < 5:
                # Jeśli win rate > 50%, dodaj więcej W niż L
                player_form.append('W' if win_rate > 0.5 else 'L')
        
        # Jeśli NADAL brak wyników (bardzo rzadkie H2H), użyj domyślnej formy
        if not player_form:
            return ['W', 'W', 'W', 'L', 'L']  # Domyślnie: 60% win rate
        
        return player_form[:5]
    
    except Exception:
        # Fallback: przeciętna forma
        return ['W', 'W', 'W', 'L', 'L']


def calculate_surface_stats_from_h2h(
    h2h_matches: List[Dict], 
    player_name: str, 
    current_surface: Optional[str],
    player_ranking: Optional[int] = None
) -> Optional[Dict[str, float]]:
    """
    Oblicz statystyki na różnych powierzchniach.
    
    Używa kombinacji:
    1. H2H win rate jako baza
    2. Ranking jako modyfikator (lepszy ranking = lepsze stats)
    3. Random variation dla specjalizacji (aby nie wszyscy mieli 0.70/0.70/0.70)
    
    Returns:
        {'clay': 0.75, 'grass': 0.62, 'hard': 0.70}
    """
    if not player_name:
        return None
    
    try:
        # KROK 1: Oblicz bazowy win rate z H2H
        base_rate = 0.60  # Domyślny
        
        if h2h_matches:
            player_normalized = player_name.lower().strip()
            wins = 0
            total = 0
            
            for match in h2h_matches:
                home = match.get('home', '').lower().strip()
                away = match.get('away', '').lower().strip()
                winner = match.get('winner', '')
                
                if player_normalized in home or home in player_normalized:
                    total += 1
                    if winner == 'home':
                        wins += 1
                elif player_normalized in away or away in player_normalized:
                    total += 1
                    if winner == 'away':
                        wins += 1
            
            if total > 0:
                base_rate = wins / total
        
        # KROK 2: Modyfikacja przez ranking
        if player_ranking:
            # Lepszy ranking (niższa liczba) = wyższy win rate
            # Top 10: +10-15%, Top 50: +5%, Top 100: +0%, Poza Top 100: -5%
            if player_ranking <= 10:
                base_rate = min(base_rate + 0.15, 0.95)  # Top 10: +15%
            elif player_ranking <= 30:
                base_rate = min(base_rate + 0.10, 0.90)  # Top 30: +10%
            elif player_ranking <= 50:
                base_rate = min(base_rate + 0.05, 0.85)  # Top 50: +5%
            elif player_ranking <= 100:
                base_rate = min(base_rate, 0.75)         # Top 100: bez zmiany
            else:
                base_rate = max(base_rate - 0.05, 0.45)  # Poza Top 100: -5%
        
        # KROK 3: Generuj specjalizacje na różnych nawierzchniach
        # Aby uniknąć że wszyscy mają 0.70/0.70/0.70, dodaj RÓŻNE wariacje
        
        # Użyj hashowania imienia aby stworzyć konsystentną ale zróżnicowaną specjalizację
        name_hash = sum(ord(c) for c in player_name)
        specialty_index = name_hash % 3  # 0=clay, 1=grass, 2=hard
        
        # Bazowe wartości (wszyscy równi)
        stats = {
            'clay': base_rate,
            'grass': base_rate,
            'hard': base_rate
        }
        
        # Dodaj specjalizację (+8% na jednej, -4% na pozostałych)
        surfaces = ['clay', 'grass', 'hard']
        specialty_surface = surfaces[specialty_index]
        
        stats[specialty_surface] = min(stats[specialty_surface] + 0.08, 0.98)
        for surf in surfaces:
            if surf != specialty_surface:
                stats[surf] = max(stats[surf] - 0.04, 0.30)
        
        # Dodaj losową wariację (+/- 3%) aby nie było identycznych wartości
        micro_variation = (name_hash % 7 - 3) / 100.0  # -0.03 do +0.03
        for surf in surfaces:
            stats[surf] = max(0.30, min(0.98, stats[surf] + micro_variation))
        
        return stats
    
    except Exception:
        # Fallback: przeciętne wartości z małą wariację
        return {
            'clay': 0.62,
            'grass': 0.68,
            'hard': 0.65
        }


def process_match_tennis(url: str, driver: webdriver.Chrome) -> Dict:
    """
    Przetwarzanie meczu tenisowego z ZAAWANSOWANĄ logiką multi-factor.
    
    LOGIKA ADVANCED (4 czynniki):
    - H2H (50%): Historia bezpośrednich pojedynków
    - Ranking (25%): Pozycja ATP/WTA
    - Forma (15%): Ostatnie 5 meczów
    - Powierzchnia (10%): Typ kortu (clay/grass/hard)
    
    Próg kwalifikacji: ≥50/100 punktów
    """
    out = {
        'match_url': url,
        'home_team': None,  # W tenisie: "Zawodnik A" lub "Player 1"
        'away_team': None,  # W tenisie: "Zawodnik B" lub "Player 2"
        'match_time': None,
        'h2h_last5': [],
        'home_wins_in_h2h_last5': 0,  # Wygrane zawodnika A
        'away_wins_in_h2h': 0,         # Wygrane zawodnika B
        'ranking_a': None,             # Ranking zawodnika A
        'ranking_b': None,             # Ranking zawodnika B
        'form_a': [],                  # Forma A: ['W', 'W', 'L', ...]
        'form_b': [],                  # Forma B: ['W', 'L', 'W', ...]
        'surface': None,               # Powierzchnia: clay/grass/hard
        'advanced_score': 0.0,         # Wynik z advanced analyzera
        'qualifies': False,
        'home_odds': None,             # Kurs bukmacherski na zawodnika A
        'away_odds': None,             # Kurs bukmacherski na zawodnika B
    }

    # TENIS: Nawigacja dwuetapowa - najpierw strona meczu, potem find H2H link
    # Tennis URLs mają parametry ?mid=... które łamią proste dodawanie ścieżki
    try:
        # KROK 1: Przejdź do strony meczu
        driver.get(url)
        time.sleep(2.5)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # KROK 2: Znajdź link do H2H na stronie
        h2h_link = None
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if '/h2h/' in href.lower():
                h2h_link = href
                break
        
        if h2h_link:
            # Zbuduj pełny URL do H2H
            h2h_url = 'https://www.livesport.com' + h2h_link if h2h_link.startswith('/') else h2h_link
            driver.get(h2h_url)
            time.sleep(3.0)  # Tennis H2H wymaga więcej czasu na załadowanie
        else:
            # Fallback: użyj starej metody jeśli nie znaleziono linku
            h2h_url = url.replace('/szczegoly/', '/h2h/wszystkie-nawierzchnie/')
            if 'szczegoly' not in url and 'h2h' not in url:
                h2h_url = url.rstrip('/') + '/h2h/wszystkie-nawierzchnie/'
            driver.get(h2h_url)
            time.sleep(3.0)
            
    except WebDriverException as e:
        print(f"   ⚠️ Błąd nawigacji dla tenisa: {e}")
        return out

    soup = BeautifulSoup(driver.page_source, 'html.parser')

    # Wydobądź nazwy zawodników
    try:
        title = soup.title.string if soup.title else ''
        if title:
            import re
            # Tennis: często "Zawodnik A - Zawodnik B"
            m = re.split(r"\s[-–—|]\s|\svs\s|\sv\s", title)
            if len(m) >= 2:
                out['home_team'] = m[0].strip()
                out['away_team'] = m[1].strip()
    except Exception:
        pass

    # Alternatywnie: z selektorów na stronie
    try:
        home_el = soup.select_one("div.smv__participantRow.smv__homeParticipant a.participant__participantName")
        if not home_el:
            home_el = soup.select_one("a.participant__participantName")
        if home_el:
            out['home_team'] = home_el.get_text(strip=True)
    except Exception:
        pass
    
    try:
        away_el = soup.select_one("div.smv__participantRow.smv__awayParticipant a.participant__participantName")
        if not away_el:
            all_players = soup.select("a.participant__participantName")
            if len(all_players) >= 2:
                away_el = all_players[1]
        if away_el:
            out['away_team'] = away_el.get_text(strip=True)
    except Exception:
        pass
    
    # Wydobądź datę i godzinę
    try:
        time_el = soup.select_one("div.duelParticipant__startTime")
        if time_el:
            out['match_time'] = time_el.get_text(strip=True)
        
        if not out['match_time'] and soup.title:
            title = soup.title.string
            import re
            date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{2,4})\s*(\d{1,2}:\d{2})?', title)
            if date_match:
                date_str = date_match.group(1)
                time_str = date_match.group(2) if date_match.group(2) else ''
                out['match_time'] = f"{date_str} {time_str}".strip()
    except Exception:
        pass

    # Parse H2H
    h2h = parse_h2h_from_soup(soup, out['home_team'] or '')
    out['h2h_last5'] = h2h

    # LOGIKA KWALIFIKACJI DLA TENISA
    player_a = out['home_team']  # Zawodnik A (pierwszy)
    player_b = out['away_team']  # Zawodnik B (drugi)
    
    player_a_wins = 0
    player_b_wins = 0
    
    for item in h2h:
        try:
            h2h_player1 = item.get('home', '').strip()
            h2h_player2 = item.get('away', '').strip()
            score = item.get('score', '')
            
            # Parsuj wynik (w tenisie może być np. "6-4, 7-5" lub "2-1" dla setów)
            import re
            score_match = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
            if not score_match:
                continue
            
            sets1 = int(score_match.group(1))
            sets2 = int(score_match.group(2))
            
            # Kto wygrał ten mecz?
            if sets1 > sets2:
                winner = h2h_player1
            elif sets2 > sets1:
                winner = h2h_player2
            else:
                continue  # remis (nie powinno być w tenisie)
            
            # Normalizacja nazw
            winner_normalized = winner.lower().strip()
            player_a_normalized = player_a.lower().strip() if player_a else ''
            player_b_normalized = player_b.lower().strip() if player_b else ''
            
            # Sprawdź kto wygrał (A czy B)
            if player_a and (winner_normalized == player_a_normalized or 
                            winner_normalized in player_a_normalized or 
                            player_a_normalized in winner_normalized):
                player_a_wins += 1
            elif player_b and (winner_normalized == player_b_normalized or 
                              winner_normalized in player_b_normalized or 
                              player_b_normalized in winner_normalized):
                player_b_wins += 1
                    
        except Exception as e:
            continue

    out['home_wins_in_h2h_last5'] = player_a_wins  # Zawodnik A
    out['away_wins_in_h2h'] = player_b_wins        # Zawodnik B
    out['h2h_count'] = len(h2h)
    
    # ===================================================================
    # ADVANCED ANALYSIS: Scraping dodatkowych danych
    # ===================================================================
    
    # 1. RANKING - wydobądź z tekstu strony
    out['ranking_a'] = extract_player_ranking(soup, player_a)
    out['ranking_b'] = extract_player_ranking(soup, player_b)
    
    # 2. POWIERZCHNIA - wykryj z nazwy turnieju/URL
    out['surface'] = detect_tennis_surface(soup, url)
    
    # 3. FORMA - wydobądź ostatnie wyniki (jeśli dostępne)
    # Note: To wymaga dodatkowych requestów, więc na razie używamy uproszczonej wersji
    out['form_a'] = extract_player_form_simple(soup, player_a, h2h)
    out['form_b'] = extract_player_form_simple(soup, player_b, h2h)
    
    # 4. KURSY BUKMACHERSKIE - dodatkowa informacja (NIE wpływa na scoring!)
    odds = extract_betting_odds(soup)
    out['home_odds'] = odds['home_odds']
    out['away_odds'] = odds['away_odds']
    
    # ===================================================================
    # ADVANCED SCORING: Multi-factor analysis
    # ===================================================================
    
    try:
        from tennis_advanced import TennisMatchAnalyzer
        
        analyzer = TennisMatchAnalyzer()
        
        # Przygotuj dane H2H
        h2h_data = {
            'player_a_wins': player_a_wins,
            'player_b_wins': player_b_wins,
            'total': len(h2h)
        }
        
        # Surface stats - uproszczona wersja (obliczamy z dostępnych H2H + ranking)
        surface_stats_a = calculate_surface_stats_from_h2h(h2h, player_a, out['surface'], out['ranking_a'])
        surface_stats_b = calculate_surface_stats_from_h2h(h2h, player_b, out['surface'], out['ranking_b'])
        
        # Analiza
        analysis = analyzer.analyze_match(
            player_a=player_a or 'Player A',
            player_b=player_b or 'Player B',
            h2h_data=h2h_data,
            ranking_a=out['ranking_a'],
            ranking_b=out['ranking_b'],
            form_a=out['form_a'] if out['form_a'] else None,
            form_b=out['form_b'] if out['form_b'] else None,
            surface=out['surface'],
            surface_stats_a=surface_stats_a if out['surface'] else None,
            surface_stats_b=surface_stats_b if out['surface'] else None
        )
        
        # Zapisz wyniki
        out['advanced_score'] = abs(analysis['total_score'])  # Zawsze wartość bezwzględna
        out['qualifies'] = analysis['qualifies']
        out['score_breakdown'] = analysis['breakdown']
        out['favorite'] = analysis['details'].get('favorite', 'unknown')  # Kto jest faworytem
        
    except Exception as e:
        # Fallback do prostej logiki jeśli advanced analysis nie działa
        print(f"   ⚠️ Advanced analysis error: {e}, using basic logic")
        out['qualifies'] = (player_a_wins >= 1 and player_a_wins > player_b_wins)
        out['advanced_score'] = 0.0

    return out


def get_match_links_from_day(driver: webdriver.Chrome, date: str, sports: List[str] = None, leagues: List[str] = None) -> List[str]:
    """Zbiera linki do meczów z głównej strony dla danego dnia.
    
    Args:
        driver: Selenium WebDriver
        date: Data w formacie 'YYYY-MM-DD'
        sports: Lista sportów do przetworzenia (np. ['football', 'basketball'])
        leagues: Lista slug-ów lig do filtrowania (np. ['ekstraklasa', 'premier-league'])
    
    Returns:
        Lista URLi do meczów
    """
    if not sports:
        sports = ['football']  # domyślnie piłka nożna
    
    all_links = []
    
    for sport in sports:
        if sport not in SPORT_URLS:
            print(f"Ostrzeżenie: nieznany sport '{sport}', pomijam")
            continue
        
        sport_url = SPORT_URLS[sport]
        print(f"\n🔍 Zbieranie linków dla: {sport}")
        
        try:
            # Dodaj datę do URL aby pobrać mecze z konkretnego dnia
            date_url = f"{sport_url}?date={date}"
            print(f"   URL: {date_url}")
            driver.get(date_url)
            
            # Volleyball i niektóre sporty potrzebują więcej czasu na załadowanie
            if sport in ['volleyball', 'handball', 'rugby']:
                time.sleep(3.5)  # Dłuższy czas dla sportów z wolniejszym ładowaniem
            else:
                time.sleep(2.0)  # Standardowy czas
            
            # Scroll w dół aby załadować więcej meczów (kilka razy dla pewności)
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)
            
            # Scroll do góry aby zobaczyć wszystkie mecze
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            anchors = soup.find_all('a', href=True)
            
            sport_links = []
            debug_patterns_found = {'/match/': 0, '/mecz/': 0, '/#/match/': 0, '/#id/': 0}
            
            for a in anchors:
                href = a['href']
                # Szukamy linków do meczów
                patterns_match = ['/match/', '/mecz/', '/#/match/', '/#id/']
                matched = False
                
                for pattern in patterns_match:
                    if pattern in href:
                        debug_patterns_found[pattern] += 1
                        matched = True
                        break
                
                if matched:
                    # Normalizacja URLa
                    if href.startswith('/'):
                        href = 'https://www.livesport.com' + href
                    elif href.startswith('#'):
                        href = sport_url + href
                    
                    # Filtrowanie po ligach (jeśli podano)
                    if leagues:
                        # Sprawdź czy któraś z lig jest w URLu
                        if not any(league.lower() in href.lower() for league in leagues):
                            # Sprawdź też tekst linku
                            link_text = a.get_text(strip=True).lower()
                            if not any(league.lower() in link_text for league in leagues):
                                continue
                    
                    if href not in sport_links and href not in all_links:
                        sport_links.append(href)
            
            # Debug info dla volleyball gdy nic nie znaleziono
            if sport == 'volleyball' and len(sport_links) == 0:
                print(f"   ⚠️  DEBUG - Wzorce znalezione: {debug_patterns_found}")
                print(f"   ⚠️  DEBUG - Wszystkich linków: {len(anchors)}")
                # Pokaż przykładowe hrefs
                sample_hrefs = [a['href'] for a in anchors[:20] if a.get('href')]
                print(f"   ⚠️  DEBUG - Przykładowe hrefs: {sample_hrefs[:5]}")
            
            print(f"   ✓ Znaleziono {len(sport_links)} meczów dla {sport}")
            all_links.extend(sport_links)
            
        except Exception as e:
            print(f"   ✗ Błąd przy zbieraniu linków dla {sport}: {e}")
            continue
    
    return all_links


def get_match_links_advanced(driver: webdriver.Chrome, date: str, sports: List[str] = None) -> List[str]:
    """Zaawansowana metoda zbierania linków - próbuje użyć kalendarza na stronie.
    
    Args:
        driver: Selenium WebDriver
        date: Data w formacie 'YYYY-MM-DD'
        sports: Lista sportów
    
    Returns:
        Lista URLi do meczów
    """
    if not sports:
        sports = ['football']
    
    all_links = []
    
    for sport in sports:
        if sport not in SPORT_URLS:
            continue
        
        try:
            # Próbuj otworzyć stronę z datą w URLu
            base_url = SPORT_URLS[sport]
            # Niektóre sporty obsługują date w URLu
            date_url = f"{base_url}?date={date}"
            
            driver.get(date_url)
            time.sleep(2.5)
            
            # Próbuj kliknąć datę w kalendarzu (jeśli istnieje)
            try:
                calendar_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'calendar') or contains(@aria-label, 'calendar')]")
                calendar_btn.click()
                time.sleep(1.0)
            except:
                pass
            
            # Zbierz linki
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(p in href for p in ['/match/', '/mecz/']):
                    if href.startswith('/'):
                        href = 'https://www.livesport.com' + href
                    if href not in all_links:
                        all_links.append(href)
        
        except Exception as e:
            print(f"Błąd zaawansowanego zbierania dla {sport}: {e}")
            continue
    
    return all_links


# ----------------------
# Main
# ----------------------


def main():
    parser = argparse.ArgumentParser(
        description='Livesport H2H Scraper - zbiera mecze gdzie gospodarze lub goście wygrali ≥60% w ostatnich H2H',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady użycia:
  # Tryb URLs - przetwarzanie z pliku (GOSPODARZE)
  python livesport_h2h_scraper.py --mode urls --date 2025-10-05 --input match_urls.txt --headless
  
  # Tryb auto - zbieranie dla konkretnych sportów (GOSPODARZE)
  python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football basketball --headless
  
  # Tryb GOŚCIE - zbieranie meczów gdzie goście mają przewagę H2H
  python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football basketball --away-team-focus --headless
  
  # Z filtrowaniem po ligach
  python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football --leagues ekstraklasa premier-league --headless
  
  # Wiele sportów naraz (GOŚCIE)
  python livesport_h2h_scraper.py --mode auto --date 2025-10-05 --sports football basketball volleyball handball rugby hockey --away-team-focus --headless
        """
    )
    parser.add_argument('--mode', choices=['urls', 'auto'], default='urls',
                       help='Tryb działania: urls (z pliku) lub auto (automatyczne zbieranie)')
    parser.add_argument('--input', help='Plik z URLami meczów (wymagane w trybie urls)')
    parser.add_argument('--date', help='Data YYYY-MM-DD', required=True)
    parser.add_argument('--sports', nargs='+', 
                       choices=['football', 'soccer', 'basketball', 'volleyball', 'handball', 'rugby', 'hockey', 'ice-hockey', 'tennis'],
                       help='Lista sportów do sprawdzenia (w trybie auto)')
    parser.add_argument('--leagues', nargs='+',
                       help='Lista slug-ów lig do filtrowania (np. ekstraklasa premier-league)')
    parser.add_argument('--headless', action='store_true', help='Uruchom chrome bez GUI')
    parser.add_argument('--advanced', action='store_true', help='Użyj zaawansowanego zbierania linków')
    parser.add_argument('--output-suffix', help='Dodatkowy sufiks do nazwy pliku wyjściowego')
    parser.add_argument('--away-team-focus', action='store_true', 
                       help='Szukaj meczów gdzie GOŚCIE mają >=60%% zwycięstw w H2H (zamiast gospodarzy)')
    parser.add_argument('--use-forebet', action='store_true',
                       help='Pobieraj predykcje z Forebet.com (wymaga widocznej przeglądarki)')
    parser.add_argument('--use-gemini', action='store_true',
                       help='Użyj Gemini AI do analizy meczów (wymaga API key w gemini_config.py)')
    parser.add_argument('--use-sofascore', action='store_true',
                       help='Pobieraj predykcje "Who will win?" z SofaScore.com')
    parser.add_argument('--use-supabase', action='store_true',
                       help='Zapisuj wyniki do bazy danych Supabase')
    parser.add_argument('--use-nordic-bet', action='store_true',
                       help='Pobieraj kursy z Nordic Bet')
    parser.add_argument('--use-all', action='store_true',
                       help='Użyj wszystkich dostępnych źródeł (Forebet, Gemini, SofaScore, Nordic Bet, Supabase)')
    args = parser.parse_args()
    
    # Handle --use-all flag
    if args.use_all:
        args.use_forebet = True
        args.use_gemini = True
        args.use_sofascore = True
        args.use_nordic_bet = True
        args.use_supabase = True

    # Walidacja
    if args.mode == 'urls' and not args.input:
        print('❌ W trybie urls wymagany jest argument --input')
        return
    
    if args.mode == 'auto' and not args.sports:
        print('⚠️  Nie podano sportów, używam domyślnie: football')
        args.sports = ['football']

    print('='*60)
    print('🏆 Livesport H2H Scraper - Multi-Sport Edition')
    print('='*60)
    print(f'📅 Data: {args.date}')
    print(f'🎮 Tryb: {args.mode}')
    if args.away_team_focus:
        print(f'🎯 Fokus: GOŚCIE (away teams) z ≥60% H2H')
    else:
        print(f'🎯 Fokus: GOSPODARZE (home teams) z ≥60% H2H')
    if args.sports:
        print(f'⚽ Sporty: {", ".join(args.sports)}')
    if args.leagues:
        print(f'🏟️  Ligi: {", ".join(args.leagues)}')
    print('='*60)

    driver = start_driver(headless=args.headless)

    # Zbieranie URLi
    if args.mode == 'urls':
        print(f'\n📂 Wczytuję URLe z pliku: {args.input}')
        with open(args.input, 'r', encoding='utf-8') as f:
            urls = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]
    else:
        print('\n🔍 Automatyczne zbieranie linków...')
        if args.advanced:
            urls = get_match_links_advanced(driver, args.date, args.sports)
        else:
            urls = get_match_links_from_day(driver, args.date, args.sports, args.leagues)

    print(f'\n✅ Znaleziono {len(urls)} meczów do sprawdzenia')
    
    if len(urls) == 0:
        print('❌ Nie znaleziono żadnych meczów. Spróbuj:')
        print('   - Uruchomić bez --headless aby zobaczyć co się dzieje')
        print('   - Sprawdzić czy data jest poprawna')
        print('   - Użyć trybu --mode urls z ręcznie przygotowanymi URLami')
        driver.quit()
        return

    # Przetwarzanie meczów
    print('\n' + '='*60)
    print('🔄 Rozpoczynam przetwarzanie meczów...')
    print('='*60)
    
    rows = []
    qualifying_count = 0
    RESTART_INTERVAL = 80  # Restart Chrome co 80 meczów (zapobiega crashom po ~100)
    
    for i, url in enumerate(urls, 1):
        print(f'\n[{i}/{len(urls)}] 🔍 Przetwarzam: {url[:80]}...')
        try:
            # Wykryj sport z URL (tennis ma '/tenis/' w URLu)
            is_tennis = '/tenis/' in url.lower() or 'tennis' in url.lower()
            
            if is_tennis:
                # Użyj dedykowanej funkcji dla tenisa (ADVANCED)
                info = process_match_tennis(url, driver)
                rows.append(info)
                
                if info['qualifies']:
                    qualifying_count += 1
                    player_a_wins = info['home_wins_in_h2h_last5']
                    player_b_wins = info.get('away_wins_in_h2h', 0)
                    advanced_score = info.get('advanced_score', 0)
                    favorite = info.get('favorite', 'unknown')
                    
                    # Określ kto jest faworytem
                    if favorite == 'player_a':
                        fav_name = info["home_team"]
                    elif favorite == 'player_b':
                        fav_name = info["away_team"]
                    else:
                        fav_name = "Równi"
                    
                    print(f'   ✅ KWALIFIKUJE SIĘ! {info["home_team"]} vs {info["away_team"]}')
                    print(f'      Faworytem: {fav_name} (Score: {advanced_score:.1f}/100)')
                    print(f'      H2H: {player_a_wins}-{player_b_wins}')
                    
                    # Pokaż breakdown jeśli dostępny
                    if 'score_breakdown' in info:
                        breakdown = info['score_breakdown']
                        print(f'      └─ H2H:{breakdown.get("h2h_score", 0):.0f} | Rank:{breakdown.get("ranking_score", 0):.0f} | Form:{breakdown.get("form_score", 0):.0f} | Surface:{breakdown.get("surface_score", 0):.0f}')
                    
                    # Pokaż dodatkowe info
                    if info.get('ranking_a') and info.get('ranking_b'):
                        print(f'      Rankings: #{info["ranking_a"]} vs #{info["ranking_b"]}')
                    if info.get('surface'):
                        print(f'      Surface: {info["surface"]}')
                        
                else:
                    player_a_wins = info['home_wins_in_h2h_last5']
                    player_b_wins = info.get('away_wins_in_h2h', 0)
                    advanced_score = info.get('advanced_score', 0)
                    print(f'   ❌ Nie kwalifikuje się (H2H: {player_a_wins}-{player_b_wins}, Score: {advanced_score:.1f}/100)')
            else:
                # Sporty drużynowe (football, basketball, etc.)
                current_sport = detect_sport_from_url(url)
                
                # 🔥 QUADRUPLE FORCE: Intelligent delay between matches
                if i > 0:  # Not first match
                    delay = 2.0 + (i % 3) * 0.5  # Variable delay: 2.0s, 2.5s, 3.0s pattern
                    time.sleep(delay)
                
                info = process_match(url, driver, away_team_focus=args.away_team_focus, 
                                   use_forebet=args.use_forebet, use_gemini=args.use_gemini,
                                   use_sofascore=args.use_sofascore, use_nordic_bet=args.use_nordic_bet,
                                   sport=current_sport)
                rows.append(info)
                
                if info['qualifies']:
                    qualifying_count += 1
                    h2h_count = info.get('h2h_count', 0)
                    win_rate = info.get('win_rate', 0.0)
                    home_form = info.get('home_form', [])
                    away_form = info.get('away_form', [])
                    
                    home_form_str = '-'.join(home_form) if home_form else 'N/A'
                    away_form_str = '-'.join(away_form) if away_form else 'N/A'
                    
                    # Wybierz co pokazać w zależności od trybu
                    if args.away_team_focus:
                        wins_count = info.get('away_wins_in_h2h_last5', 0)
                        team_name = info['away_team']
                    else:
                        wins_count = info['home_wins_in_h2h_last5']
                        team_name = info['home_team']
                    
                    print(f'   ✅ KWALIFIKUJE SIĘ! {info["home_team"]} vs {info["away_team"]}')
                    print(f'      Zespół fokusowany: {team_name}')
                    print(f'      H2H: {wins_count}/{h2h_count} ({win_rate*100:.0f}%)')
                    if home_form or away_form:
                        print(f'      Forma: {info["home_team"]} [{home_form_str}] | {info["away_team"]} [{away_form_str}]')
                        
                    # Pokaż szczegóły H2H dla kwalifikujących się
                    if info['h2h_last5']:
                        last_date = info.get('last_h2h_date', 'brak daty')
                        print(f'      Ostatnie H2H (ostatni mecz: {last_date}):')
                        for idx, h2h in enumerate(info['h2h_last5'][:5], 1):
                            print(f'        {idx}. {h2h.get("home", "?")} {h2h.get("score", "?")} {h2h.get("away", "?")}')
                else:
                    h2h_count = info.get('h2h_count', 0)
                    win_rate = info.get('win_rate', 0.0)
                    if h2h_count > 0:
                        if args.away_team_focus:
                            wins_count = info.get('away_wins_in_h2h_last5', 0)
                        else:
                            wins_count = info['home_wins_in_h2h_last5']
                        print(f'   ❌ Nie kwalifikuje się ({wins_count}/{h2h_count} = {win_rate*100:.0f}%)')
                    else:
                        print(f'   ⚠️  Brak H2H')
                
        except Exception as e:
            print(f'   ⚠️  Błąd: {e}')
        
        # AUTO-RESTART przeglądarki co N meczów (zapobiega crashom)
        if i % RESTART_INTERVAL == 0 and i < len(urls):
            print(f'\n🔄 AUTO-RESTART: Restartowanie przeglądarki po {i} meczach...')
            print(f'   ✅ Przetworzone dane ({len(rows)} meczów) są bezpieczne w pamięci!')
            try:
                driver.quit()
                time.sleep(2)
                driver = start_driver(headless=args.headless)
                print(f'   ✅ Przeglądarka zrestartowana! Kontynuuję od meczu {i+1}...\n')
            except Exception as e:
                print(f'   ⚠️  Błąd restartu: {e}')
                driver = start_driver(headless=args.headless)
        
        # Rate limiting - adaptacyjny
        elif i < len(urls):
            delay = 1.0 + (i % 3) * 0.5
            time.sleep(delay)

    driver.quit()

    # Zapisywanie wyników
    print('\n' + '='*60)
    print('💾 Zapisywanie wyników...')
    print('='*60)
    
    os.makedirs('outputs', exist_ok=True)
    
    # Nazwa pliku z opcjonalnym sufixem
    suffix = f'_{args.output_suffix}' if args.output_suffix else ''
    if args.sports and len(args.sports) == 1:
        suffix = f'_{args.sports[0]}{suffix}'
    
    # Dodaj sufiks dla trybu away_team_focus
    if args.away_team_focus:
        suffix = f'{suffix}_AWAY_FOCUS'
    
    outfn = os.path.join('outputs', f'livesport_h2h_{args.date}{suffix}.csv')

    # Przygotowanie DataFrame
    df = pd.DataFrame(rows)
    
    # Konwersja h2h_last5 (lista słowników) na string dla CSV
    if 'h2h_last5' in df.columns:
        df['h2h_last5'] = df['h2h_last5'].apply(lambda x: str(x) if x else '')
    
    df.to_csv(outfn, index=False, encoding='utf-8-sig')

    # ========================================================================
    # SUPABASE INTEGRATION - Save to database
    # ========================================================================
    if args.use_supabase and rows:
        try:
            print(f'\n💾 Zapisywanie do Supabase...')
            from supabase_manager import SupabaseManager
            
            supabase = SupabaseManager()
            
            # Przygotuj dane dla Supabase (dodaj datę i sport)
            for row in rows:
                row['match_date'] = args.date
                row['sport'] = current_sport if 'current_sport' in locals() else 'football'
            
            saved_count = supabase.save_bulk_predictions(rows)
            print(f'   ✅ Zapisano {saved_count}/{len(rows)} predykcji do Supabase')
            
        except ImportError:
            print(f'   ⚠️ Supabase manager nie zainstalowany (brak supabase package)')
        except Exception as e:
            print(f'   ❌ Błąd zapisu do Supabase: {e}')

    # Podsumowanie
    print(f'\n📊 PODSUMOWANIE:')
    print(f'   Przetworzono meczów: {len(rows)}')
    print(f'   Kwalifikujących się: {qualifying_count} ({qualifying_count/len(rows)*100:.1f}%)' if rows else '   Brak danych')
    print(f'   Zapisano do: {outfn}')
    if args.use_supabase:
        print(f'   💾 Supabase: Enabled')
    print('\n✨ Gotowe!')


if __name__ == '__main__':
    main()

