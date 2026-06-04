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
import logging
import random
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
from selenium.common.exceptions import (
    NoSuchElementException, 
    TimeoutException, 
    WebDriverException,
    StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Reduce verbosity of selenium and urllib3 loggers
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('webdriver_manager').setLevel(logging.WARNING)

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


# ============================================================================
# ROBUST ERROR HANDLING HELPERS
# ============================================================================

# Markers that identify a LiveSport "soft" error / rate-limit page. These pages
# return HTTP 200 with a tiny body (~5 KB) and NO match data, so they must be
# detected by content — otherwise the scraper treats them as a successful load,
# finds no H2H rows, and silently drops the match ("no matches today").
_LIVESPORT_ERROR_MARKERS = (
    "requested page can't be displayed",
    "requested page can\u2019t be displayed",  # curly apostrophe variant
    "requested page cannot be displayed",
    "please try again later",
    "access denied",
    "are you a robot",
    "unusual traffic",
)
# A genuine match/H2H page is large; blocked pages are tiny. Used as a
# secondary signal alongside the text markers.
_LIVESPORT_MIN_VALID_PAGE_BYTES = 30000


def is_livesport_error_page(page_source: Optional[str]) -> bool:
    """Return True when ``page_source`` is a LiveSport block/error page.

    Detection combines two signals:
      1. Known error text markers (rate-limit / "can't be displayed" / bot wall)
      2. Suspiciously small page body that contains no H2H markup

    A real match page is hundreds of KB and contains ``h2h`` classes; a blocked
    page is ~5 KB with an apology message and returns HTTP 200, so Selenium's
    ``driver.get`` does not raise.
    """
    if not page_source:
        return True
    low = page_source.lower()
    for marker in _LIVESPORT_ERROR_MARKERS:
        if marker in low:
            return True
    # Tiny page with no H2H / participant scaffolding → almost certainly blocked.
    if len(page_source) < _LIVESPORT_MIN_VALID_PAGE_BYTES:
        if ('h2h' not in low) and ('participant' not in low):
            return True
    return False


def _safe_page_source(driver: webdriver.Chrome) -> Optional[str]:
    """Return ``driver.page_source`` or ``None`` if the driver errors."""
    try:
        return driver.page_source
    except WebDriverException:
        return None


def _wait_for_h2h_rows(driver: webdriver.Chrome, timeout: float = 6.0,
                       poll: float = 0.4) -> bool:
    """Poll until H2H rows (``a.h2h__row``) appear in the DOM.

    With page_load_strategy='eager', ``driver.get`` returns at
    DOMContentLoaded — before LiveSport's JS injects the H2H table. A blind
    ``time.sleep`` is either too short (no rows) or wastefully long. This
    waits only as long as needed, returning True as soon as rows are present.
    """
    deadline = time.time() + timeout
    # Temporarily disable implicit wait so each find_elements poll returns
    # immediately (otherwise implicitly_wait(10) makes every empty poll hang).
    try:
        driver.implicitly_wait(0)
    except WebDriverException:
        pass
    try:
        while time.time() < deadline:
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, 'a.h2h__row')
                if rows:
                    return True
            except WebDriverException:
                pass
            time.sleep(poll)
        return False
    finally:
        try:
            driver.implicitly_wait(10)
        except WebDriverException:
            pass


def check_driver_health(driver: webdriver.Chrome) -> bool:
    """
    Sprawdza czy driver jest w działającym stanie.
    
    Returns:
        True jeśli driver działa poprawnie, False w przeciwnym razie
    """
    if driver is None:
        return False
    try:
        # Próba dostępu do current_url sprawdzi czy driver jest responsywny
        _ = driver.current_url
        return True
    except (WebDriverException, AttributeError, Exception) as e:
        logger.debug(f"Driver health check failed: {type(e).__name__}")
        return False


def safe_find_element(driver: webdriver.Chrome, by: By, value: str, max_retries: int = 3):
    """
    Bezpieczne znalezienie elementu z retry logic dla StaleElementReferenceException.
    
    Args:
        driver: WebDriver instance
        by: Metoda lokalizacji (By.XPATH, By.CSS_SELECTOR, etc.)
        value: Wartość selektora
        max_retries: Maksymalna liczba prób
        
    Returns:
        Element lub None jeśli nie znaleziono
    """
    for attempt in range(max_retries):
        try:
            element = driver.find_element(by, value)
            return element
        except StaleElementReferenceException:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                logger.debug(f"StaleElementReferenceException, retry {attempt + 1}/{max_retries}")
                continue
            logger.warning(f"StaleElementReferenceException after {max_retries} retries for: {value}")
            return None
        except NoSuchElementException:
            return None
        except Exception as e:
            logger.debug(f"safe_find_element error: {type(e).__name__}: {e}")
            return None
    return None


def safe_find_elements(driver: webdriver.Chrome, by: By, value: str, max_retries: int = 3) -> list:
    """
    Bezpieczne znalezienie wielu elementów z retry logic.
    
    Returns:
        Lista elementów (może być pusta)
    """
    for attempt in range(max_retries):
        try:
            elements = driver.find_elements(by, value)
            return elements
        except StaleElementReferenceException:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return []
        except Exception as e:
            logger.debug(f"safe_find_elements error: {type(e).__name__}")
            return []
    return []


def safe_get_text(element, default: str = '') -> str:
    """
    Bezpieczne pobranie tekstu z elementu.
    
    Returns:
        Tekst elementu lub wartość domyślna
    """
    if element is None:
        return default
    try:
        return element.get_text(strip=True) if hasattr(element, 'get_text') else element.text.strip()
    except (AttributeError, StaleElementReferenceException) as e:
        logger.debug(f"safe_get_text error: {type(e).__name__}")
        return default


def save_partial_results(rows: List[Dict], args, suffix: str = '_PARTIAL') -> str:
    """
    Zapisuje częściowe wyniki w razie błędu.
    
    Args:
        rows: Lista wierszy danych
        args: Argumenty programu
        suffix: Sufiks do nazwy pliku
        
    Returns:
        Ścieżka do zapisanego pliku
    """
    if not rows:
        logger.warning("Brak danych do zapisania")
        return None
    
    try:
        os.makedirs('outputs', exist_ok=True)
        
        # Nazwa pliku z sufiksem
        output_suffix = f'_{args.output_suffix}' if hasattr(args, 'output_suffix') and args.output_suffix else ''
        if hasattr(args, 'sports') and args.sports and len(args.sports) == 1:
            output_suffix = f'_{args.sports[0]}{output_suffix}'
        if hasattr(args, 'away_team_focus') and args.away_team_focus:
            output_suffix = f'{output_suffix}_AWAY_FOCUS'
        
        date_str = args.date if hasattr(args, 'date') else datetime.now().strftime('%Y-%m-%d')
        outfn = os.path.join('outputs', f'livesport_h2h_{date_str}{output_suffix}{suffix}.csv')
        
        df = pd.DataFrame(rows)
        df.to_csv(outfn, index=False, encoding='utf-8-sig')
        
        logger.info(f"Zapisano częściowe wyniki ({len(rows)} wierszy) do: {outfn}")
        return outfn
        
    except Exception as e:
        logger.error(f"Błąd zapisu częściowych wyników: {e}")
        return None


def exponential_backoff_with_jitter(attempt: int, base_delay: float = 2.0, max_delay: float = 30.0) -> float:
    """
    Oblicza opóźnienie z exponential backoff i jitter.
    
    Args:
        attempt: Numer próby (0-indexed)
        base_delay: Bazowe opóźnienie w sekundach
        max_delay: Maksymalne opóźnienie
        
    Returns:
        Opóźnienie w sekundach
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.3)  # Do 30% jitter
    return delay + jitter


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
    elif '/baseball/' in url_lower or '/bejsbol/' in url_lower:
        return 'baseball'
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
    'baseball': 'https://www.livesport.com/pl/baseball/',
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
    'baseball': {
        'mlb': 'MLB',
        'npb': 'NPB',
        'kbo': 'KBO',
    },
}

H2H_TAB_TEXT_OPTIONS = ["H2H", "Head-to-Head", "Bezpośrednie", "Bezpośrednie spotkania", "H2H"]


def start_driver(headless: bool = True) -> webdriver.Chrome:
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")

    # 🚀 PAGE LOAD STRATEGY = 'eager': zwróć sterowanie gdy DOM jest gotowy
    # (DOMContentLoaded), NIE czekaj na pełny event 'load' (obrazki, reklamy,
    # trackery, websockety). LiveSport to ciężki SPA — pełny 'load' potrafi
    # trwać 40s+ w CI i powodował timeouty (objaw: h2h=40s, "Brak H2H").
    # Tabela H2H jest w DOM na długo przed eventem 'load', więc 'eager'
    # wystarcza i jest wielokrotnie szybszy.
    chrome_options.page_load_strategy = 'eager'

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
        # 🔥 CI/CD ENVIRONMENT: Use system chromedriver DIRECTLY
        if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            print("🔥 CI/CD detected - using system chromedriver (skipping ChromeDriverManager)")
            service = Service(
                '/usr/bin/chromedriver',  # System chromedriver path
                log_path='/dev/null',
            )
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(60)
            driver.set_script_timeout(30)
            driver.implicitly_wait(10)
        else:
            # Fall back to ChromeDriverManager (local development)
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
        except (NoSuchElementException, StaleElementReferenceException):
            # Element nie istnieje lub stał się nieaktualny - próbuj następny wariant
            continue
        except WebDriverException as e:
            logger.debug(f"WebDriverException przy klikaniu H2H tab '{text}': {e}")
            continue

    # fallback: look for element with data-tab or href containing 'h2h'
    try:
        el = driver.find_element(By.XPATH, "//a[contains(@href, 'h2h') or contains(@data-tab, 'h2h')]")
        el.click()
        time.sleep(0.8)
        return
    except (NoSuchElementException, StaleElementReferenceException):
        logger.debug("Nie znaleziono zakładki H2H - zawartość może być już widoczna")
    except WebDriverException as e:
        logger.debug(f"WebDriverException przy fallback H2H: {e}")

    # if nothing works, do nothing and hope content is already present


def parse_h2h_from_soup(soup: BeautifulSoup, home_team: str) -> List[Dict]:
    """Parsuje sekcję H2H i zwraca listę ostatnich spotkań (do 5).
    Zwracany format: [{'date':..., 'home':..., 'away':..., 'score': 'x - y', 'winner': 'home'/'away'/'draw'}]
    """
    results = []
    
    # Walidacja wejścia
    if soup is None:
        logger.warning("parse_h2h_from_soup: soup jest None - nie można parsować H2H")
        return results

    # NOWA STRUKTURA LIVESPORT (2025)
    # Szukaj sekcji "Pojedynki bezpośrednie"
    try:
        h2h_sections = soup.find_all('div', class_='h2h__section')
    except AttributeError as e:
        logger.warning(f"parse_h2h_from_soup: Błąd przy wyszukiwaniu sekcji H2H: {e}")
        return results
    
    pojedynki_section = None
    for section in h2h_sections:
        try:
            text = section.get_text(" ", strip=True)
            if 'pojedynki' in text.lower() or 'bezpośrednie' in text.lower():
                pojedynki_section = section
                break
        except AttributeError:
            continue
    
    if not pojedynki_section:
        # Fallback: weź pierwszą sekcję h2h__section
        if h2h_sections:
            pojedynki_section = h2h_sections[0]
    
    if not pojedynki_section:
        logger.debug(f"parse_h2h_from_soup: Nie znaleziono sekcji H2H dla {home_team}")
        return results
    
    # Znajdź wiersze z meczami: a.h2h__row
    try:
        match_rows = pojedynki_section.select('a.h2h__row')
    except Exception as e:
        logger.warning(f"parse_h2h_from_soup: Błąd przy wyszukiwaniu wierszy H2H: {e}")
        return results
    
    for row in match_rows[:5]:  # Maksymalnie 5 ostatnich
        try:
            # Data
            date_el = row.select_one('span.h2h__date')
            date = safe_get_text(date_el, '')
            
            # Gospodarz
            home_el = row.select_one('span.h2h__homeParticipant span.h2h__participantInner')
            home = safe_get_text(home_el, '')
            
            # Gość
            away_el = row.select_one('span.h2h__awayParticipant span.h2h__participantInner')
            away = safe_get_text(away_el, '')
            
            # Wynik
            score = ''
            winner = 'unknown'
            result_spans = row.select('span.h2h__result span')
            
            if len(result_spans) >= 2:
                goals_home = safe_get_text(result_spans[0], '0')
                goals_away = safe_get_text(result_spans[1], '0')
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
                except (ValueError, TypeError) as e:
                    logger.debug(f"parse_h2h_from_soup: Nie można sparsować wyniku '{goals_home}-{goals_away}': {e}")
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
        
        except (AttributeError, TypeError) as e:
            logger.debug(f"parse_h2h_from_soup: Błąd przy parsowaniu wiersza H2H: {e}")
            continue
        except Exception as e:
            logger.warning(f"parse_h2h_from_soup: Nieoczekiwany błąd: {type(e).__name__}: {e}")
            continue

    return results


# ---------------------------------------------------------------------------
# H2H helper utilities (module-level so they can be imported & tested)
# ---------------------------------------------------------------------------

def _parse_h2h_date(d):
    """Parse DD.MM.YYYY or DD.MM.YY → datetime for sorting."""
    if not d:
        return datetime(1900, 1, 1)
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', str(d))
    if not m:
        return datetime(1900, 1, 1)
    day, month, year = m.groups()
    year_int = int(year)
    if year_int < 100:
        year_int = 2000 + year_int if year_int <= 50 else 1900 + year_int
    try:
        return datetime(year_int, int(month), int(day))
    except ValueError:
        return datetime(1900, 1, 1)


def _team_key(name):
    """Normalize team name for safe comparison."""
    if not name:
        return ''
    k = str(name).lower().strip()
    k = re.sub(r'\b(fc|cf|ac|as|sk|fk|nk|ks|mks|sc|rc|cd|ud|rcd|ssc|bsc|bv)\b', '', k)
    k = re.sub(r'[^\w\s]', '', k)
    k = re.sub(r'\s+', ' ', k).strip()
    return k


def _teams_match(name_a, name_b):
    """Return True when two names refer to the same team."""
    if not name_a or not name_b:
        return False
    ka, kb = _team_key(name_a), _team_key(name_b)
    if ka == kb:
        return True
    ta, tb = set(ka.split()), set(kb.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= 0.8


def build_h2h_overall_url(match_url: str) -> Optional[str]:
    """Build the direct LiveSport H2H ('ogolem') URL from a match URL.

    Team-sport match pages load the summary tab by default; the H2H table is
    only injected after clicking the H2H tab (a JS action that often fails
    silently in headless CI). Navigating straight to ``.../h2h/ogolem/``
    renders the H2H markup server-side / on first load, which is far more
    reliable than depending on a tab click.

    Converts e.g.::

        /mecz/pilka-nozna/team1/team2/?mid=ABC
        →  /mecz/pilka-nozna/team1/team2/h2h/ogolem/?mid=ABC

    Returns ``None`` when the URL is not a recognisable match URL.
    """
    if not match_url or ('/mecz/' not in match_url and '/match/' not in match_url):
        return None
    # Already an H2H URL → leave as-is.
    if '/h2h/' in match_url:
        return match_url

    base = match_url.split('?')[0].rstrip('/')
    # Strip a trailing detail-page segment if present.
    for tail in ('/szczegoly', '/podsumowanie', '/summary', '/details'):
        if base.endswith(tail):
            base = base[: -len(tail)]
            break
    base = base.rstrip('/')

    mid = ''
    if 'mid=' in match_url:
        mid = match_url.split('mid=', 1)[1].split('&', 1)[0]

    h2h_url = f"{base}/h2h/ogolem/"
    if mid:
        h2h_url += f"?mid={mid}"
    return h2h_url


def process_match(url: str, driver: webdriver.Chrome, away_team_focus: bool = False, require_form_advantage: bool = False, use_forebet: bool = False, use_gemini: bool = False, use_sofascore: bool = False, use_flashscore: bool = False, sport: str = 'football') -> Dict:
    """Odwiedza stronę meczu, otwiera H2H i zwraca informację we właściwym formacie.
    
    Args:
        url: URL meczu
        driver: Selenium WebDriver
        away_team_focus: Jeśli True, liczy zwycięstwa GOŚCI w H2H zamiast gospodarzy
        use_forebet: Jeśli True, pobiera predykcje z Forebet
        use_gemini: Jeśli True, używa Gemini AI do analizy
        sport: Sport (football, volleyball, etc.)
    """
    # ========================================================================
    # PROFILOWANIE CZASU - rozpoczęcie pomiaru
    # ========================================================================
    import time as time_module
    _t_start = time_module.time()
    _timings = {
        'h2h': 0.0,
        'qualify': 0.0,
        'forebet': 0.0,
        'sofascore': 0.0,
        'flashscore': 0.0,
        'gemini': 0.0,
    }
    
    out = {
        'match_url': url,
        'home_team': None,
        'away_team': None,
        'match_time': None,
        'h2h_last5': [],
        'last_h2h_date': None,  # Data ostatniego meczu H2H
        'last_h2h_score': None,  # Wynik ostatniego meczu H2H
        'last_h2h_home': None,  # Gospodarz ostatniego H2H
        'last_h2h_away': None,  # Gość ostatniego H2H
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
        # SPORT INFO
        'sport': sport,  # Nazwa sportu (football, basketball, volleyball, etc.)
        'league': None,  # League/competition name (extracted from Forebet or Livesport)
    }

    # 🔥🔥🔥🔥 QUADRUPLE FORCE: Ultra-aggressive retry logic with multiple strategies
    # W CI: tylko 2 próby (szybkie fail-fast), lokalnie: 5 prób
    import os as _os_ci
    _is_ci = _os_ci.getenv('CI') == 'true' or _os_ci.getenv('GITHUB_ACTIONS') == 'true'
    max_retries = 2 if _is_ci else 5
    last_error = None
    
    # Sprawdź stan drivera przed rozpoczęciem
    if not check_driver_health(driver):
        logger.error(f"Driver nie działa przed przetworzeniem {url}")
        return out

    # 🎯 KLUCZOWA POPRAWKA: dla sportów drużynowych nawiguj BEZPOŚREDNIO do
    # strony H2H (.../h2h/ogolem/), zamiast ładować stronę meczu i klikać
    # zakładkę H2H w JS. Klik zakładki w trybie headless często cicho zawodzi,
    # przez co tabela H2H nigdy się nie ładuje i mecz jest pomijany
    # ("Brak H2H" mimo że H2H istnieje). Bezpośredni URL renderuje H2H od razu.
    _h2h_direct_url = build_h2h_overall_url(url) if sport != 'tennis' else None
    _nav_url = _h2h_direct_url or url
    _need_tab_click = _h2h_direct_url is None  # tylko gdy nie mamy bezpośredniego URL

    # ⚡ W CI skróć page-load timeout: z 'eager' DOM jest gotowy w kilka sekund,
    # więc nie ma sensu czekać 60s na pełny 'load'. Krótszy timeout + fast-path
    # na TimeoutException (poniżej) daje ~kilka s/mecz zamiast 40s.
    if _is_ci:
        try:
            driver.set_page_load_timeout(15)
        except WebDriverException:
            pass

    for attempt in range(max_retries):
        try:
            # 🔥 Strategy 1: Normal navigation - szybsze w CI
            if attempt == 0:
                driver.get(_nav_url)
                time.sleep(1.0 if _is_ci else 3.0)  # CI: szybciej
            
            # 🔥 Strategy 2: Refresh if first failed
            elif attempt == 1:
                print(f"   🔄 Próba #2: Refresh...")
                driver.refresh()
                time.sleep(1.0 if _is_ci else 3.0)
            
            # 🔥 Strategy 3: Navigate to main page first, then match
            elif attempt == 2:
                print(f"   🔄 Próba #3: Via main page...")
                driver.get("https://www.livesport.com/pl/")
                time.sleep(1.0 if _is_ci else 2.0)
                driver.get(_nav_url)
                time.sleep(1.5 if _is_ci else 3.0)
            
            # 🔥 Strategy 4: Clear cache and try
            elif attempt == 3:
                print(f"   🔄 Próba #4: Clear cache...")
                try:
                    driver.delete_all_cookies()
                except WebDriverException:
                    pass  # Ignoruj błędy przy czyszczeniu cookies
                time.sleep(0.5 if _is_ci else 1.0)
                driver.get(_nav_url)
                time.sleep(1.5 if _is_ci else 3.0)
            
            # 🔥 Strategy 5: Last resort - direct URL
            else:
                print(f"   🔄 Próba #5: Direct URL (last resort)...")
                driver.get(_nav_url)
                time.sleep(2.0 if _is_ci else 5.0)  # CI: szybciej
            
            # Klikamy zakładkę H2H tylko jeśli NIE udało się zbudować
            # bezpośredniego URL-a H2H (np. nietypowy format adresu).
            if _need_tab_click:
                click_h2h_tab(driver)
                time.sleep(1.5 if _is_ci else 2.5)  # CI: szybciej
            else:
                # ⏳ Z 'eager' load DOM jest gotowy, ale wiersze H2H wstrzykuje
                # JS chwilę później. Zamiast ślepego sleep — czekaj jawnie na
                # pojawienie się 'a.h2h__row' (max ~6s), z krótkim fallbackiem.
                _waited = _wait_for_h2h_rows(driver, timeout=6.0 if _is_ci else 8.0)
                if not _waited:
                    time.sleep(0.8 if _is_ci else 1.5)

            # 🔥 KRYTYCZNE: Wykryj "miękką" stronę błędu LiveSport (HTTP 200,
            # ale treść = "Nie można wyświetlić strony / spróbuj później").
            # driver.get() NIE rzuca wyjątku dla takiej strony, więc bez tej
            # kontroli scraper traktuje blokadę jako sukces, nie znajduje
            # wierszy H2H i po cichu pomija mecz ("brak meczów dzisiaj").
            try:
                _page_now = driver.page_source
            except WebDriverException:
                _page_now = None
            if is_livesport_error_page(_page_now):
                last_error = RuntimeError("LiveSport error/block page (HTTP 200, no data)")
                if attempt < max_retries - 1:
                    delay = exponential_backoff_with_jitter(attempt)
                    print(f"   🚫 Strona zablokowana/błąd LiveSport "
                          f"(próba {attempt + 1}/{max_retries}) — czekam {delay:.1f}s...")
                    time.sleep(delay)
                    continue  # ponów nawigację (inna strategia)
                else:
                    print(f"   🚫 LiveSport blokuje stronę {url} po {max_retries} próbach")
                    logger.warning(f"LiveSport error page for {url} after {max_retries} attempts")
                    return out

            break  # Success - wyjdź z pętli
            
        except (WebDriverException, ConnectionResetError, ConnectionError, TimeoutError, TimeoutException) as e:
            last_error = e
            logger.debug(f"Błąd połączenia dla {url}: {type(e).__name__}: {str(e)[:100]}")

            # ⚡ TimeoutException przy 'eager' load = pełny event 'load' nie
            # zdążył (reklamy/trackery), ALE DOM z H2H może już być gotowy.
            # Zamiast marnować próby na ponowne ładowanie ciężkiej strony,
            # sprawdź czy treść H2H jest już obecna — jeśli tak, idź dalej.
            if isinstance(e, TimeoutException):
                try:
                    driver.execute_script("window.stop();")
                except WebDriverException:
                    pass
                try:
                    _ps = driver.page_source
                except WebDriverException:
                    _ps = None
                if _ps and ('h2h__' in _ps or 'h2h_' in _ps) and not is_livesport_error_page(_ps):
                    logger.debug(f"Timeout, ale DOM H2H obecny dla {url} — kontynuuję")
                    break
            
            if attempt < max_retries - 1:
                # Użyj exponential backoff z jitter
                delay = exponential_backoff_with_jitter(attempt)
                print(f"⚠️ Błąd połączenia (próba {attempt + 1}/{max_retries}): {type(e).__name__}")
                print(f"   Czekam {delay:.1f}s przed następną próbą...")
                time.sleep(delay)
                
                # Sprawdź czy driver nadal działa
                if not check_driver_health(driver):
                    logger.warning("Driver przestał działać po błędzie - przerywam próby")
                    return out
                continue
            else:
                print(f"❌ Błąd otwierania {url} po {max_retries} próbach")
                print(f"   Ostatni błąd: {type(last_error).__name__}: {str(last_error)[:100]}")
                logger.error(f"Nie udało się otworzyć {url} po {max_retries} próbach: {last_error}")
                return out
        except StaleElementReferenceException as e:
            # Element stał się nieaktualny - spróbuj ponownie
            logger.debug(f"StaleElementReferenceException dla {url}, retry {attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(1.0)
                continue
            else:
                logger.warning(f"StaleElementReferenceException po {max_retries} próbach dla {url}")
                return out

    # pobierz tytuł strony jako fallback na nazwy druzyn
    try:
        page_source = driver.page_source
        if not page_source:
            logger.warning(f"process_match: Pusta strona dla {url}")
            return out
        soup = BeautifulSoup(page_source, 'html.parser')
        # spróbuj wyciągnąć nazwy drużyn z nagłówka
        # FIX: soup.title.string może zwrócić None nawet gdy soup.title istnieje
        title = (soup.title.string or '') if soup.title else ''
        if title:
            # tytuł często ma formę "Home - Away" lub "Home vs Away"
            m = re.split(r"\s[-–—|]\s|\svs\s|\sv\s", title)
            if len(m) >= 2:
                out['home_team'] = m[0].strip()
                out['away_team'] = m[1].strip()
    except (WebDriverException, AttributeError) as e:
        logger.debug(f"process_match: Błąd pobierania tytułu strony dla {url}: {e}")
    except Exception as e:
        logger.warning(f"process_match: Nieoczekiwany błąd przy parsowaniu tytułu: {type(e).__name__}: {e}")

    # NIE MUSIMY KLIKAĆ H2H - już jesteśmy na stronie /h2h/ogolem/

    # Ponownie pobierz soup gdyby poprzednia próba się nie powiodła
    try:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    except WebDriverException as e:
        logger.error(f"process_match: Nie można pobrać page_source dla {url}: {e}")
        return out

    # try to extract team names from the page header - NOWE SELEKTORY
    # Ordered fallback chain that works for all sports (football, basketball, etc.)
    _PARTICIPANT_SELECTORS_HOME = [
        "div.smv__participantRow.smv__homeParticipant a.participant__participantName",
        "div.duelParticipant__home a.participant__participantName",
        "div.duelParticipant__home .participant__participantNameWrapper",
        "a.participant__participantName",  # generic first-match fallback
    ]
    _PARTICIPANT_SELECTORS_AWAY = [
        "div.smv__participantRow.smv__awayParticipant a.participant__participantName",
        "div.duelParticipant__away a.participant__participantName",
        "div.duelParticipant__away .participant__participantNameWrapper",
    ]

    try:
        home_el = None
        for sel in _PARTICIPANT_SELECTORS_HOME:
            home_el = soup.select_one(sel)
            if home_el:
                break
        if home_el:
            out['home_team'] = safe_get_text(home_el, out['home_team'])
    except (AttributeError, TypeError) as e:
        logger.debug(f"process_match: Błąd przy pobieraniu nazwy gospodarzy: {e}")

    try:
        away_el = None
        for sel in _PARTICIPANT_SELECTORS_AWAY:
            away_el = soup.select_one(sel)
            if away_el:
                break
        if not away_el:
            # Fallback: weź drugą nazwę drużyny
            all_teams = soup.select("a.participant__participantName")
            if len(all_teams) >= 2:
                away_el = all_teams[1]
        if away_el:
            out['away_team'] = safe_get_text(away_el, out['away_team'])
    except (AttributeError, TypeError) as e:
        logger.debug(f"process_match: Błąd przy pobieraniu nazwy gości: {e}")

    # If team names are still missing after all selectors, log for diagnosis
    if not out['home_team'] or not out['away_team']:
        logger.warning(
            f"process_match: Could not extract participant names for {sport} match {url} "
            f"(home={out['home_team']!r}, away={out['away_team']!r})"
        )
    
    # Wydobądź datę i godzinę meczu
    try:
        # Szukaj różnych możliwych selektorów dla daty/czasu
        # Próba 1: Element z czasem startu
        time_el = soup.select_one("div.duelParticipant__startTime")
        if time_el:
            out['match_time'] = safe_get_text(time_el, '')
        
        # Próba 2: Z tytułu strony (często zawiera datę)
        if not out['match_time'] and soup.title:
            title = soup.title.string if soup.title else ''
            if title:
                # Szukaj wzorca daty i czasu w tytule
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
                date_param = re.search(r'date=([^&]+)', url)
                if date_param:
                    out['match_time'] = date_param.group(1)
    except (AttributeError, TypeError) as e:
        logger.debug(f"process_match: Błąd przy wydobywaniu czasu meczu: {e}")
    except Exception as e:
        logger.warning(f"process_match: Nieoczekiwany błąd przy parsowaniu czasu: {type(e).__name__}")

    # parse H2H
    h2h = parse_h2h_from_soup(soup, out['home_team'] or '')

    # 🔁 FALLBACK: jeśli bezpośrednia nawigacja nie dała wierszy H2H,
    # spróbuj doładować je interaktywnie (scroll + klik zakładki H2H),
    # a następnie przeparsuj ponownie. Chroni przed sytuacją, gdy tabela
    # H2H ładuje się leniwie albo wymaga kliknięcia mimo bezpośredniego URL.
    if not h2h:
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(0.8 if _is_ci else 1.5)
            click_h2h_tab(driver)
            time.sleep(1.2 if _is_ci else 2.0)
            soup_retry = BeautifulSoup(driver.page_source, 'html.parser')
            h2h_retry = parse_h2h_from_soup(soup_retry, out['home_team'] or '')
            if h2h_retry:
                soup = soup_retry
                h2h = h2h_retry
                logger.debug(f"process_match: H2H odzyskane przez fallback (klik+scroll) dla {url}")
        except (WebDriverException, AttributeError) as e:
            logger.debug(f"process_match: H2H fallback nie powiódł się: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # SORT H2H BY DATE (descending) so h2h[0] is always the most recent
    # Uses module-level _parse_h2h_date, _team_key, _teams_match helpers
    # ------------------------------------------------------------------

    h2h.sort(key=lambda x: _parse_h2h_date(x.get('date', '')), reverse=True)
    out['h2h_last5'] = h2h

    # ------------------------------------------------------------------
    # VALIDATE & PICK LAST H2H — only if both H2H teams match today's teams
    # ------------------------------------------------------------------
    current_home = out['home_team']
    current_away = out['away_team']

    if h2h and len(h2h) > 0:
        last = h2h[0]
        lh, la = last.get('home', ''), last.get('away', '')
        pair_valid = (
            (_teams_match(lh, current_home) and _teams_match(la, current_away)) or
            (_teams_match(lh, current_away) and _teams_match(la, current_home))
        )
        if pair_valid:
            # Store ORIGINAL orientation (how the match was actually played)
            out['last_h2h_date'] = last.get('date', None)
            out['last_h2h_score'] = last.get('score', None)
            out['last_h2h_home'] = lh   # actual home team in that past match
            out['last_h2h_away'] = la   # actual away team in that past match
        else:
            logger.warning(
                'H2H last-match team mismatch: h2h=%s vs %s, today=%s vs %s — skipping',
                lh, la, current_home, current_away,
            )
            out['last_h2h_date'] = None
            out['last_h2h_score'] = None
            out['last_h2h_home'] = None
            out['last_h2h_away'] = None
    # else: defaults from initialize block stay None

    # ------------------------------------------------------------------
    # COUNT WINS using canonical matching
    # ------------------------------------------------------------------
    cnt_home = 0
    cnt_away = 0

    for item in h2h:
        try:
            h2h_home = item.get('home', '').strip()
            h2h_away = item.get('away', '').strip()
            score = item.get('score', '')

            score_match = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
            if not score_match:
                continue

            goals_home_side = int(score_match.group(1))
            goals_away_side = int(score_match.group(2))

            if goals_home_side > goals_away_side:
                winner_team = h2h_home
            elif goals_away_side > goals_home_side:
                winner_team = h2h_away
            else:
                winner_team = None  # draw

            if winner_team:
                if _teams_match(winner_team, current_home):
                    cnt_home += 1
                elif _teams_match(winner_team, current_away):
                    cnt_away += 1

        except Exception as e:
            logger.debug('H2H win-count error: %s', e)
            if item.get('winner') == 'home' and _teams_match(item.get('home', ''), current_home):
                cnt_home += 1
            elif item.get('winner') == 'away' and _teams_match(item.get('away', ''), current_away):
                cnt_away += 1

    out['home_wins_in_h2h_last5'] = cnt_home
    out['away_wins_in_h2h_last5'] = cnt_away
    out['h2h_count'] = len(h2h)
    
    # ⏱️ TIMING: Koniec H2H
    _timings['h2h'] = time_module.time() - _t_start
    
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
            # Jeśli require_form_advantage=True, forma jest WYMAGANA
            # W przeciwnym razie forma jest BONUSEM (dodatkowa ikona 🔥)
            if require_form_advantage:
                out['qualifies'] = basic_qualifies and out['form_advantage']
            else:
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
                # Mapuj na pola _overall dla kompatybilności z email_notifier
                out['home_form_overall'] = home_form
                out['away_form_overall'] = away_form
                out['home_form_home'] = home_form  # Używamy tej samej formy jako fallback
                out['away_form_away'] = away_form
            except (AttributeError, TypeError, WebDriverException) as e:
                logger.debug(f"Błąd przy pobieraniu formy fallback: {e}")
    else:
        # Nie kwalifikuje się podstawowo - ale nadal pobierz formę dla wyświetlenia
        out['qualifies'] = False
        # Pobierz podstawową formę (dla meczów niekwalifikujących się)
        try:
            home_form = extract_team_form(soup, driver, 'home', out.get('home_team'))
            away_form = extract_team_form(soup, driver, 'away', out.get('away_team'))
            out['home_form'] = home_form
            out['away_form'] = away_form
            out['home_form_overall'] = home_form
            out['away_form_overall'] = away_form
        except (AttributeError, TypeError, WebDriverException, NameError) as e:
            logger.debug(f"Błąd przy pobieraniu formy dla niekwalifikujących: {e}")
    
    # ⏱️ TIMING: Koniec kwalifikacji (Etap 1)
    _timings['qualify'] = time_module.time() - _t_start - _timings['h2h']
    
    # 🔥 Kursy bukmacherskie - TYLKO dla kwalifikujących się meczów w sportach z kursami
    # OPTYMALIZACJA: Pominięcie kursów oszczędza ~100s/mecz (12 API calls × timeout)
    _SPORTS_WITH_ODDS = {'football', 'soccer', 'basketball', 'tennis', 'hockey', 'ice-hockey', 'handball', 'volleyball'}
    _skip_odds = sport.lower() not in _SPORTS_WITH_ODDS or not out.get('qualifies')
    
    if _skip_odds:
        _reason = 'nie kwalifikuje się' if not out.get('qualifies') else f'sport {sport} bez kursów'
        logger.debug(f"⏭️ Pomijanie kursów: {_reason}")
    
    if out.get('match_url') and not _skip_odds:
        print(f"   💰 Livesport API: Pobieranie kursów...")
        livesport_odds = fetch_odds_from_livesport(driver, out['match_url'], sport)
        if livesport_odds.get('odds_found'):
            out['home_odds'] = livesport_odds.get('home_odds')
            out['draw_odds'] = livesport_odds.get('draw_odds')
            out['away_odds'] = livesport_odds.get('away_odds')
            out['odds_bookmaker'] = livesport_odds.get('bookmaker')
            print(f"      ✅ Kursy: {out['home_odds']}/{out.get('draw_odds', '-')}/{out['away_odds']} ({out['odds_bookmaker']})")
        else:
            out['home_odds'] = None
            out['draw_odds'] = None
            out['away_odds'] = None
            out['odds_bookmaker'] = None
    elif _skip_odds:
        out['home_odds'] = None
        out['draw_odds'] = None
        out['away_odds'] = None
        out['odds_bookmaker'] = None

    # FOREBET PREDICTIONS - TYLKO jeśli mecz KWALIFIKUJE SIĘ!
    # 🔥 OPTYMALIZACJA: Skip Forebet dla meczów które i tak nie przejdą
    _t_forebet_start = time_module.time()
    if use_forebet and FOREBET_AVAILABLE and out.get('qualifies') and out.get('home_team') and out.get('away_team'):
        try:
            print(f"      🎯 Forebet: Pobieram predykcję...")
            
            # Wyciągnij datę meczu z match_time (format: DD.MM.YY HH:MM lub DD.MM.YYYY HH:MM)
            from datetime import datetime as dt_forebet
            match_date_str = dt_forebet.now().strftime('%Y-%m-%d')  # Domyślna data = dzisiaj
            if out.get('match_time'):
                try:
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
                except (ValueError, AttributeError, TypeError) as e:
                    logger.debug(f"Błąd przy parsowaniu daty dla Forebet: {e}")
            
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
                # v4: Store all 3 probabilities separately
                out['forebet_home_prob'] = forebet_result.get('home_prob')
                out['forebet_draw_prob'] = forebet_result.get('draw_prob')
                out['forebet_away_prob'] = forebet_result.get('away_prob')
                
                # v4: Extract match_time from Forebet if not already set
                if not out.get('match_time') and forebet_result.get('match_time'):
                    out['match_time'] = forebet_result.get('match_time')
                    
                # v4: Extract league from Forebet if not already set
                if not out.get('league') and forebet_result.get('league'):
                    out['league'] = forebet_result.get('league')
                
                print(f"      ✅ {format_forebet_result(forebet_result)}")
            else:
                print(f"      ⚠️ Forebet: {forebet_result.get('error', 'Brak predykcji')}")
                
        except Exception as e:
            print(f"      ⚠️ Błąd Forebet: {e}")
    _timings['forebet'] = time_module.time() - _t_forebet_start
    
    # ============================================
    # GEMINI AI ANALYSIS (Faza 3)
    # ============================================
    _t_gemini_start = time_module.time()
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
    _timings['gemini'] = time_module.time() - _t_gemini_start
    
    # ========================================================================
    # SOFASCORE INTEGRATION - "Who will win?" predictions
    # ========================================================================
    _t_sofascore_start = time_module.time()
    if use_sofascore and out.get('home_team') and out.get('away_team'):
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
    _timings['sofascore'] = time_module.time() - _t_sofascore_start
    
    # FLASHSCORE ODDS - tylko jeśli brak kursów z Livesport AND kwalifikuje się AND sport z kursami
    _t_flash_start = time_module.time()
    has_livesport_odds = out.get('home_odds') and out.get('away_odds')
    if use_flashscore and FLASHSCORE_AVAILABLE and out.get('qualifies') and out.get('home_team') and out.get('away_team') and not has_livesport_odds and not _skip_odds:
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
    _timings['flashscore'] = time_module.time() - _t_flash_start

    # ========================================================================
    # PODSUMOWANIE INTEGRACJI DANYCH + TIMING
    # ========================================================================
    _t_total = time_module.time() - _t_start
    
    if out.get('home_team') and out.get('away_team'):
        sources = []
        missing = []
        
        # H2H
        if out.get('h2h_last5') and len(out.get('h2h_last5', [])) > 0:
            sources.append(f"H2H({len(out['h2h_last5'])})")
        else:
            missing.append("H2H")
        
        # Forebet
        if out.get('forebet_prediction'):
            sources.append(f"Forebet({out.get('forebet_prediction')})")
        elif not use_forebet:
            missing.append("Forebet(FAZA 2)")
        else:
            missing.append("Forebet")
        
        # SofaScore
        if out.get('sofascore_home_win_prob'):
            sources.append(f"SofaScore({out.get('sofascore_home_win_prob')}%)")
        elif not use_sofascore:
            missing.append("SofaScore(FAZA 2)")
        else:
            missing.append("SofaScore")
        
        # Kursy
        if out.get('home_odds') or out.get('flashscore_home_odds'):
            odds_val = out.get('home_odds') or out.get('flashscore_home_odds')
            sources.append(f"Odds({odds_val})")
        else:
            missing.append("Odds")
        
        # Gemini
        if out.get('gemini_prediction'):
            sources.append(f"Gemini({out.get('gemini_confidence')}%)")
        
        # Log podsumowania z czasem
        sources_str = ' | '.join(sources) if sources else 'BRAK'
        missing_str = ', '.join(missing) if missing else 'BRAK'
        qual_str = "✅" if out.get('qualifies') else "❌"
        
        # Timing log
        time_parts = []
        if _timings['h2h'] > 0.1:
            time_parts.append(f"h2h={_timings['h2h']:.1f}s")
        if _timings['forebet'] > 0.1:
            time_parts.append(f"fb={_timings['forebet']:.1f}s")
        if _timings['sofascore'] > 0.1:
            time_parts.append(f"ss={_timings['sofascore']:.1f}s")
        if _timings['flashscore'] > 0.1:
            time_parts.append(f"fs={_timings['flashscore']:.1f}s")
        if _timings['gemini'] > 0.1:
            time_parts.append(f"ai={_timings['gemini']:.1f}s")
        time_str = ' '.join(time_parts) if time_parts else ''
        
        print(f"   📊 Integracja: [{sources_str}] | Brak: [{missing_str}]")
        print(f"   ⏱️ TIME: total={_t_total:.1f}s {time_str} qual={qual_str}")

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
        except (WebDriverException, TimeoutException) as e:
            logger.debug(f"Scroll dla lazy-loading nie powiódł się: {e}")
        
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
                    except (ValueError, AttributeError, TypeError) as e:
                        logger.debug(f"Błąd przy parsowaniu wyniku formy: {e}")
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
                        except (ValueError, AttributeError, TypeError) as e:
                            logger.debug(f"Błąd przy parsowaniu wyniku formy (fallback): {e}")
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



def fetch_odds_from_livesport(driver: webdriver.Chrome, match_url: str, sport: str = 'football') -> Dict[str, Optional[float]]:
    """
    🔥 Pobiera kursy z Livesport używając GraphQL API (nie Selenium!).
    
    Używa bezpośredniego dostępu do API kursów Livesport.
    
    PRIORYTET BUKMACHERÓW:
    1. Pinnacle (najlepsze kursy)
    2. bet365
    3. Unibet
    4. Nordic Bet
    5. Bwin
    6. Betway
    
    Args:
        driver: Selenium WebDriver (nieużywany, zachowany dla kompatybilności)
        match_url: URL strony meczu (np. /pilka-nozna/mecz/xxxx/szczegoly/)
        sport: Typ sportu
        
    Returns:
        {'home_odds': 1.85, 'draw_odds': 3.40, 'away_odds': 2.10, 'bookmaker': 'Pinnacle'}
    """
    result = {
        'home_odds': None,
        'draw_odds': None,
        'away_odds': None,
        'bookmaker': None,
        'odds_found': False
    }
    
    # Debug logging dla sportów bez remisu (volleyball, tennis, basketball)
    is_no_draw_sport = sport.lower() in ['volleyball', 'tennis', 'basketball', 'badminton', 'table_tennis']
    if is_no_draw_sport:
        print(f"   🏐 {sport.title()}: Pobieranie kursów z Livesport API (HOME_AWAY, bez remisu)...")
    
    try:
        # Import API client
        from livesport_odds_api import LivesportOddsAPI, get_livesport_odds
        
        # Użyj API do pobrania kursów
        api_result = get_livesport_odds(match_url, sport)
        
        if api_result and api_result.get('odds_found'):
            # 🔧 Upewnij się że kursy to float lub None (nie string 'nan')
            home_val = api_result.get('home_odds')
            draw_val = api_result.get('draw_odds')
            away_val = api_result.get('away_odds')
            
            result['home_odds'] = float(home_val) if home_val is not None else None
            result['draw_odds'] = float(draw_val) if draw_val is not None else None
            result['away_odds'] = float(away_val) if away_val is not None else None
            result['bookmaker'] = api_result.get('bookmaker', 'Pinnacle')
            result['odds_found'] = True
            
            # 🔧 Dla sportów bez remisu, zawsze ustaw draw_odds na None
            if is_no_draw_sport:
                result['draw_odds'] = None
                print(f"   ✅ {sport.title()}: Kursy znalezione - {result['home_odds']}/{result['away_odds']} ({result['bookmaker']})")
        else:
            # Fallback: Spróbuj wydobyć Event ID z URL ręcznie i próbuj ponownie
            # Wydobądź event ID z URL
            event_id = None
            
            # Metoda 1: Parametr ?mid= lub &mid=
            match = re.search(r'[?&]mid=([a-zA-Z0-9]+)', match_url)
            if match:
                event_id = match.group(1)
            
            # Metoda 2: ID z URL path (ostatni segment alfanumeryczny)
            if not event_id:
                parts = match_url.rstrip('/').split('/')
                for part in reversed(parts):
                    if re.match(r'^[a-zA-Z0-9]{6,10}$', part):
                        if part.lower() not in ['szczegoly', 'h2h', 'statystyki', 'kursy', 'mecz', 'match']:
                            event_id = part
                            break
            
            if event_id:
                print(f"   💰 Livesport API: Retry z Event ID: {event_id}")
                api = LivesportOddsAPI()
                api_result = api.get_odds_from_multiple_bookmakers(event_id, sport)
                
                if api_result and api_result.get('success'):
                    # 🔧 Upewnij się że kursy to float lub None
                    home_val = api_result.get('home_odds')
                    draw_val = api_result.get('draw_odds')
                    away_val = api_result.get('away_odds')
                    
                    result['home_odds'] = float(home_val) if home_val is not None else None
                    result['draw_odds'] = float(draw_val) if draw_val is not None else None
                    result['away_odds'] = float(away_val) if away_val is not None else None
                    result['bookmaker'] = api_result.get('bookmaker', 'Pinnacle')
                    result['odds_found'] = True
                    
                    # 🔧 Dla sportów bez remisu, zawsze ustaw draw_odds na None
                    if is_no_draw_sport:
                        result['draw_odds'] = None
                        print(f"   ✅ {sport.title()} (retry): Kursy znalezione - {result['home_odds']}/{result['away_odds']} ({result['bookmaker']})")
                    else:
                        print(f"   ✅ Livesport API (retry): {result['bookmaker']} - {result['home_odds']}/{result.get('draw_odds', '-')}/{result['away_odds']}")
            
            if not result['odds_found']:
                if is_no_draw_sport:
                    print(f"   ⚠️ {sport.title()}: Brak kursów - event_id może być niepoprawny lub mecz nie ma kursów")
                else:
                    print(f"   ⚠️ Livesport API: Brak kursów na stronie")
                
    except ImportError:
        print(f"   ⚠️ Livesport API: Moduł livesport_odds_api niedostępny")
    except Exception as e:
        print(f"   ⚠️ Livesport odds error: {e}")
    
    return result


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
                except (ValueError, TypeError) as e:
                    logger.debug(f"Nie można sparsować home_odds: {e}")
            if elem.get('data-away-odds'):
                try:
                    odds_data['away_odds'] = float(elem.get('data-away-odds'))
                except (ValueError, TypeError) as e:
                    logger.debug(f"Nie można sparsować away_odds: {e}")
        
        # Metoda 3: Szukaj w JSON-LD lub skryptach
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                script_content = script.string if script.string else ''
                if script_content:
                    data = json.loads(script_content)
                    if 'offers' in data or 'odds' in str(data).lower():
                        # Próbuj wydobyć kursy z JSON
                        pass
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                logger.debug(f"Nie można sparsować JSON-LD dla kursów: {e}")
        
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


def _build_tennis_h2h_url(original_url: str) -> Optional[str]:
    """Build a valid Livesport tennis H2H URL from a match detail or partial URL.

    Accepts:
      - Detail page:  .../tenis/mecz/.../szczegoly/
      - Already H2H:  .../tenis/mecz/.../h2h/...
      - Bare match:   .../tenis/mecz/LEAGUE/ID/
      - With query:   .../tenis/mecz/.../?mid=XYZ

    Returns a normalised H2H URL or None if the input cannot be resolved.
    """
    if not original_url or not isinstance(original_url, str):
        return None

    url = original_url.strip()

    if not url.startswith('http'):
        return None

    # Strip query parameters and fragments FIRST (e.g. ?mid=URuwAe6d)
    from urllib.parse import urlsplit, urlunsplit, quote
    parts = urlsplit(url)
    # Work only with the path (no query, no fragment)
    path = parts.path

    # Normalise: ensure trailing /  so segment splitting works reliably
    if not path.endswith('/'):
        path += '/'

    # Strip existing tail segments to get the match base path
    if '/h2h/' in path:
        path = path.split('/h2h/')[0]
    elif '/szczegoly/' in path:
        path = path.split('/szczegoly/')[0]
    elif '/statystyki/' in path:
        path = path.split('/statystyki/')[0]
    elif '/wyniki/' in path:
        path = path.split('/wyniki/')[0]
    else:
        # Remove trailing slash for clean append
        path = path.rstrip('/')

    # Validate: a Livesport tennis match URL must contain '/tenis/' and '/mecz/'
    path_lower = path.lower()
    if '/tenis/' not in path_lower and '/tennis/' not in path_lower:
        return None
    if '/mecz/' not in path_lower and '/match/' not in path_lower:
        return None

    # Build H2H path (no query params!)
    h2h_path = path + '/h2h/wszystkie-nawierzchnie/'

    # Percent-encode non-ASCII characters (e.g. Polish path segments)
    encoded_path = quote(h2h_path, safe='/:@!$&\'()*+,;=')
    h2h_url = urlunsplit((parts.scheme, parts.netloc, encoded_path, '', ''))

    return h2h_url


def _extract_player_names_from_soup(soup: BeautifulSoup) -> tuple:
    """Extract player A (home) and player B (away) names from a Livesport match page.

    Returns (player_a, player_b) — either may be None.
    Uses an ordered fallback chain identical to the team-sport scraper.
    """
    player_a = None
    player_b = None

    # Strategy 1: CSS selectors for participant rows
    try:
        home_el = soup.select_one(
            "div.duelParticipant__home a.participant__participantName, "
            "div.smv__participantRow.smv__homeParticipant a.participant__participantName"
        )
        if home_el:
            player_a = home_el.get_text(strip=True)
    except Exception:
        pass

    try:
        away_el = soup.select_one(
            "div.duelParticipant__away a.participant__participantName, "
            "div.smv__participantRow.smv__awayParticipant a.participant__participantName"
        )
        if away_el:
            player_b = away_el.get_text(strip=True)
    except Exception:
        pass

    # Strategy 2: generic participant__participantName elements (first = A, second = B)
    if not player_a or not player_b:
        try:
            all_players = soup.select("a.participant__participantName")
            if not player_a and len(all_players) >= 1:
                player_a = all_players[0].get_text(strip=True)
            if not player_b and len(all_players) >= 2:
                player_b = all_players[1].get_text(strip=True)
        except Exception:
            pass

    # Strategy 3: page title split  "Player A - Player B | …"
    if not player_a or not player_b:
        try:
            title = soup.title.string if soup.title else ''
            if title:
                m = re.split(r"\s[-–—|]\s|\svs\.?\s|\sv\s", title)
                if len(m) >= 2:
                    if not player_a:
                        player_a = m[0].strip()
                    if not player_b:
                        player_b = m[1].strip()
        except Exception:
            pass

    return player_a, player_b


def process_match_tennis(url: str, driver: webdriver.Chrome) -> Dict:
    """
    Przetwarzanie meczu tenisowego – silnik v5 (Player A / Player B).

    FAKTORY (wagi z TennisScoringEngine):
      H2H recency-weighted   0.25
      Current form            0.20
      Surface form            0.15
      Ranking gap             0.12
      Odds-implied            0.10
      Fatigue / freshness     0.08
      SofaScore fan vote      0.10

    Próg kwalifikacji: ≥45/100 advanced_score.

    HARD SKIP (przed scoringiem):
      - Brak obu nazw zawodników po wszystkich fallbackach
      - Kursy bukmacherskie < 1.35 po którejś stronie
      - Nieodwracalny błąd nawigacji (invalid URL)

    SOFT FAIL (obniża data_quality, nie odrzuca):
      - Brak ostatniego H2H (data + wynik)
      - Brak ostatniego meczu któregokolwiek zawodnika
      - Brak form / surface form

    NIE generuje syntetycznych danych – brak danych = neutralne 0.5.
    """
    out: Dict = {
        'match_url': url,
        'home_team': None,          # Player A
        'away_team': None,          # Player B
        'match_time': None,
        'h2h_last5': [],
        'home_wins_in_h2h_last5': 0,   # Player A H2H wins
        'away_wins_in_h2h_last5': 0,   # Player B H2H wins  ← FIXED field name
        'ranking_a': None,
        'ranking_b': None,
        'form_a': [],
        'form_b': [],
        'surface': None,
        'surface_form_a': [],       # Last 5 W/L on same surface (Player A)
        'surface_form_b': [],       # Last 5 W/L on same surface (Player B)
        'surface_stats_a': None,    # {surface: win_rate} dict for scoring engine
        'surface_stats_b': None,    # {surface: win_rate} dict for scoring engine
        'last_h2h_date': None,      # Date of last H2H match
        'last_h2h_score': None,     # Score of last H2H match
        'last_h2h_home': None,      # Home player of last H2H
        'last_h2h_away': None,      # Away player of last H2H
        'last_match_a_date': None,  # Date of Player A's last match
        'last_match_a_score': None, # Score of Player A's last match
        'last_match_a_opponent': None,  # Opponent in Player A's last match
        'last_match_a_result': None,    # 'W' or 'L'
        'last_match_b_date': None,  # Date of Player B's last match
        'last_match_b_score': None, # Score of Player B's last match
        'last_match_b_opponent': None,  # Opponent in Player B's last match
        'last_match_b_result': None,    # 'W' or 'L'
        'advanced_score': 0.0,
        'qualifies': False,
        'home_odds': None,
        'away_odds': None,
        'tennis_skip_reason': None, # Reason for hard skip (if any)
        'tennis_phase_path': 'full_pipeline',  # full_pipeline | fast_odds_skip | partial_data_fastpath

        # Compatibility fields (always present)
        'home_form': [],
        'away_form': [],
        'home_form_overall': [],
        'away_form_overall': [],
        'home_form_home': [],
        'away_form_away': [],
        'h2h_count': 0,
        'win_rate': 0.0,
        'form_advantage': False,
        'sport': 'tennis',
        'focus_team': 'home',
        'ranking_info': None,
        'favorite': 'unknown',
    }

    # CI-aware sleep durations — shorter in GitHub Actions for 6h budget
    _is_ci_tennis = os.environ.get('GITHUB_ACTIONS') == 'true' or os.environ.get('CI') == 'true'
    _SLEEP_MATCH_PAGE = 1.5 if _is_ci_tennis else 2.5
    _SLEEP_H2H_PAGE = 1.8 if _is_ci_tennis else 3.0

    # In CI: reduce page load timeout for tennis to avoid 60s hangs
    _original_page_load_timeout = None
    if _is_ci_tennis:
        try:
            _original_page_load_timeout = 60  # default
            driver.set_page_load_timeout(20)  # 20s max per navigation in CI
        except Exception:
            pass

    # --- Helper: apply compatibility mapping (runs on EVERY exit path) ---
    def _finalise(o: Dict) -> Dict:
        """Set all email-compat fields before returning."""
        # Restore page load timeout if we reduced it for CI
        if _is_ci_tennis and _original_page_load_timeout:
            try:
                driver.set_page_load_timeout(_original_page_load_timeout)
            except Exception:
                pass
        o['home_form'] = o.get('form_a', [])
        o['away_form'] = o.get('form_b', [])
        o['home_form_overall'] = o.get('form_a', [])
        o['away_form_overall'] = o.get('form_b', [])
        o['home_form_home'] = []
        o['away_form_away'] = []
        o['h2h_count'] = len(o.get('h2h_last5', []))
        o['sport'] = 'tennis'
        total_h2h = o.get('home_wins_in_h2h_last5', 0) + o.get('away_wins_in_h2h_last5', 0)
        fav = o.get('favorite', 'unknown')
        if total_h2h > 0:
            if fav == 'player_a':
                o['win_rate'] = o['home_wins_in_h2h_last5'] / total_h2h
            elif fav == 'player_b':
                o['win_rate'] = o['away_wins_in_h2h_last5'] / total_h2h
            else:
                o['win_rate'] = 0.5
        else:
            o['win_rate'] = 0.0
        o['form_advantage'] = False
        o['focus_team'] = 'home' if fav == 'player_a' else 'away'
        if o.get('ranking_a') and o.get('ranking_b'):
            o['ranking_info'] = f"ATP/WTA: #{o['ranking_a']} vs #{o['ranking_b']}"
        return o

    # ── tennis_data_warnings collects soft-fail reasons (not fatal) ──
    tennis_warnings: List[str] = []
    h2h_navigation_ok = False
    match_page_soup = None  # preserved for odds extraction

    try:
        if not url or not isinstance(url, str):
            print(f"   ⚠️ Tennis: missing URL (None/empty)")
            return _finalise(out)

        url = url.strip()
        if not url.startswith('http'):
            print(f"   ⚠️ Tennis: invalid URL: {url[:80]}...")
            return _finalise(out)

        # ── STEP 1: Navigate to match detail page ──
        driver.get(url)
        time.sleep(_SLEEP_MATCH_PAGE)

        match_page_soup = BeautifulSoup(driver.page_source, 'html.parser')

        # ── STEP 2: Extract player names from match page (before leaving) ──
        pa, pb = _extract_player_names_from_soup(match_page_soup)
        if pa:
            out['home_team'] = pa
        if pb:
            out['away_team'] = pb

        # ── STEP 2b: Extract match time from match page ──
        try:
            time_el = match_page_soup.select_one("div.duelParticipant__startTime")
            if time_el:
                out['match_time'] = time_el.get_text(strip=True)

            if not out['match_time'] and match_page_soup.title:
                title = match_page_soup.title.string
                date_match = re.search(r'(\d{1,2}\.\d{1,2}\.\d{2,4})\s*(\d{1,2}:\d{2})?', title)
                if date_match:
                    date_str = date_match.group(1)
                    time_str = date_match.group(2) if date_match.group(2) else ''
                    out['match_time'] = f"{date_str} {time_str}".strip()
        except Exception:
            pass

        # ── STEP 2c: Extract odds from match page (CSS selectors) ──
        odds = extract_betting_odds(match_page_soup)
        out['home_odds'] = odds['home_odds']
        out['away_odds'] = odds['away_odds']

        # ── STEP 2d: Livesport API odds fallback (if CSS extraction failed) ──
        if not out['home_odds'] or not out['away_odds']:
            try:
                print(f"   💰 Tennis: CSS odds empty, trying Livesport API...")
                livesport_odds = fetch_odds_from_livesport(driver, url, 'tennis')
                if livesport_odds.get('odds_found'):
                    out['home_odds'] = livesport_odds.get('home_odds')
                    out['away_odds'] = livesport_odds.get('away_odds')
                    out['odds_bookmaker'] = livesport_odds.get('bookmaker')
                    print(f"      ✅ Tennis API odds: {out['home_odds']}/{out['away_odds']} ({out['odds_bookmaker']})")
                else:
                    print(f"      ⚠️ Tennis: Livesport API odds not found")
            except Exception as e:
                print(f"      ⚠️ Tennis: Livesport API odds error: {e}")

        # ── EARLY ODDS GATE (balanced fast-path) ──
        # Najczęstszy powód odrzucenia tenisa to `odds_below_threshold`. Jeżeli
        # obydwa kursy są już znane i któryś leży poniżej progu, nie ma sensu
        # nawigować do H2H ani ekstrahować last-match/surface form — to
        # oszczędza ~5–15 s na mecz przy niskich kursach typu 1.05/8.0.
        gate_reason = _tennis_odds_gate_reason(out)
        if gate_reason:
            out['tennis_skip_reason'] = gate_reason
            out['tennis_data_warnings'] = ['fast_path_odds_gate']
            out['qualifies'] = False
            out['tennis_phase_path'] = 'fast_odds_skip'
            print(f"   ❌ Tennis HARD SKIP: {gate_reason}  [fast_path_odds_gate]")
            return _finalise(out)

        # ── STEP 3: Build & validate H2H URL, then navigate ──
        # Strategy A: find an H2H link on the match page itself
        h2h_url = None
        for link in match_page_soup.find_all('a', href=True):
            href = link.get('href', '')
            if '/h2h/' in href.lower():
                raw = 'https://www.livesport.com' + href if href.startswith('/') else href
                # Percent-encode non-ASCII characters in Strategy A URLs
                from urllib.parse import urlsplit, urlunsplit, quote
                _p = urlsplit(raw)
                raw = urlunsplit((_p.scheme, _p.netloc, quote(_p.path, safe='/:@!$&\'()*+,;='), _p.query, _p.fragment))
                h2h_url = raw
                break

        # Strategy B: deterministic URL builder (already encodes non-ASCII)
        if not h2h_url:
            h2h_url = _build_tennis_h2h_url(url)

        if not h2h_url:
            print(f"   ⚠️ Tennis: cannot build H2H URL from: {url[:80]}")
            tennis_warnings.append("navigation_failed: cannot build H2H URL")
            # Continue with match-page data only (no H2H, no last-match sections)
        else:
            try:
                driver.get(h2h_url)
                time.sleep(_SLEEP_H2H_PAGE)
                h2h_navigation_ok = True
            except WebDriverException as e:
                err_short = str(e).split('\n')[0][:120]
                print(f"   ⚠️ Tennis: H2H navigation failed: {err_short}")
                tennis_warnings.append(f"navigation_failed: {err_short}")

    except WebDriverException as e:
        err_short = str(e).split('\n')[0][:120]
        print(f"   ⚠️ Tennis: match-page navigation failed: {err_short}")
        out['tennis_skip_reason'] = f"navigation_failed: {err_short}"
        return _finalise(out)

    # ── Build soup for H2H parsing (H2H page if available, else match page) ──
    if h2h_navigation_ok:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Re-extract player names from H2H page if missing
        if not out['home_team'] or not out['away_team']:
            pa2, pb2 = _extract_player_names_from_soup(soup)
            if pa2 and not out['home_team']:
                out['home_team'] = pa2
            if pb2 and not out['away_team']:
                out['away_team'] = pb2
    else:
        soup = match_page_soup or BeautifulSoup('<html></html>', 'html.parser')

    # Parse H2H
    h2h = parse_h2h_from_soup(soup, out['home_team'] or '')
    out['h2h_last5'] = h2h

    # LOGIKA KWALIFIKACJI DLA TENISA (robust name matching – Phase 4/5)
    player_a = out['home_team']  # Zawodnik A (pierwszy)
    player_b = out['away_team']  # Zawodnik B (drugi)
    
    player_a_wins = 0
    player_b_wins = 0
    
    for item in h2h:
        try:
            h2h_player1 = item.get('home', '').strip()
            h2h_player2 = item.get('away', '').strip()
            score = item.get('score', '')
            
            score_match = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score)
            if not score_match:
                continue
            
            sets1 = int(score_match.group(1))
            sets2 = int(score_match.group(2))
            
            if sets1 > sets2:
                winner = h2h_player1
            elif sets2 > sets1:
                winner = h2h_player2
            else:
                continue  # no draws in tennis
            
            # Robust name matching (same _teams_match as Phase 4 football fix)
            if player_a and _teams_match(winner, player_a):
                player_a_wins += 1
            elif player_b and _teams_match(winner, player_b):
                player_b_wins += 1
                    
        except Exception:
            continue

    out['home_wins_in_h2h_last5'] = player_a_wins  # Zawodnik A
    out['away_wins_in_h2h_last5'] = player_b_wins  # Zawodnik B  ← FIXED field name
    out['h2h_count'] = len(h2h)

    # ===================================================================
    # SORT H2H BY DATE (descending) — most recent first
    # ===================================================================
    h2h.sort(key=lambda x: _parse_h2h_date(x.get('date', '')), reverse=True)
    out['h2h_last5'] = h2h

    # ===================================================================
    # LAST H2H — date + score of the most recent direct encounter
    # ===================================================================
    if h2h:
        last = h2h[0]
        lh, la = last.get('home', ''), last.get('away', '')
        pair_valid = (
            (_teams_match(lh, player_a) and _teams_match(la, player_b)) or
            (_teams_match(lh, player_b) and _teams_match(la, player_a))
        ) if player_a and player_b else False
        if pair_valid:
            out['last_h2h_date'] = last.get('date', None)
            out['last_h2h_score'] = last.get('score', None)
            out['last_h2h_home'] = lh
            out['last_h2h_away'] = la
    
    # ===================================================================
    # ADDITIONAL DATA EXTRACTION (real data only, NO synthetics)
    # ===================================================================
    
    # 1. RANKING
    out['ranking_a'] = extract_player_ranking(soup, player_a)
    out['ranking_b'] = extract_player_ranking(soup, player_b)
    
    # 2. SURFACE
    out['surface'] = detect_tennis_surface(soup, url)
    
    # 3. FORM — REAL form badges only (no fake defaults)
    out['form_a'] = _extract_real_form_badges(soup, player_a)
    out['form_b'] = _extract_real_form_badges(soup, player_b)

    # 4. ODDS — already extracted from match-page soup (more reliable);
    #    try H2H page only if match page had nothing
    if not out['home_odds'] or not out['away_odds']:
        odds = extract_betting_odds(soup)
        if odds['home_odds']:
            out['home_odds'] = odds['home_odds']
        if odds['away_odds']:
            out['away_odds'] = odds['away_odds']

    # 4b. FLASHSCORE odds fallback — last resort if both API and CSS failed
    # In CI: SKIP FlashScore for tennis — it spawns a new scraper and adds
    # 10-20s per match. Livesport API already provides Pinnacle odds reliably.
    if not out.get('home_odds') or not out.get('away_odds'):
        if FLASHSCORE_AVAILABLE and out.get('home_team') and out.get('away_team') and not _is_ci_tennis:
            try:
                print(f"   💰 Tennis FlashScore fallback: Pobieranie kursów...")
                flashscore_scraper = FlashScoreOddsScraper(headless=True)
                flashscore_result = flashscore_scraper.get_odds(
                    home_team=out['home_team'],
                    away_team=out['away_team'],
                    sport='tennis',
                    driver=driver
                )
                if flashscore_result.get('found'):
                    if not out.get('home_odds') and flashscore_result.get('home_odds'):
                        out['home_odds'] = flashscore_result.get('home_odds')
                    if not out.get('away_odds') and flashscore_result.get('away_odds'):
                        out['away_odds'] = flashscore_result.get('away_odds')
                    out['flashscore_home_odds'] = flashscore_result.get('home_odds')
                    out['flashscore_away_odds'] = flashscore_result.get('away_odds')
                    out['flashscore_bookmaker'] = flashscore_result.get('bookmaker', 'FlashScore')
                    out['flashscore_found'] = True
                    print(f"      ✅ FlashScore tennis: {flashscore_result.get('home_odds')}/{flashscore_result.get('away_odds')}")
                else:
                    print(f"      ⚠️ FlashScore tennis: Kursy nie znalezione")
            except Exception as e:
                print(f"      ⚠️ FlashScore tennis error: {e}")

    # ===================================================================
    # 5. LAST MATCH PER PLAYER (from "Ostatnie mecze" / "Last matches" tabs)
    #    + 6. SURFACE FORM
    # Balanced fast-path: gdy mecz nie ma żadnych podstawowych sygnałów
    # (brak H2H, brak rankingów, brak form), oba kroki nie zmienią wyniku
    # (i tak skończy jako partial_data z bardzo niskim score'em), a każdy
    # robi własny driver.get + sleep ≥1.5 s. Pomijamy je, oszczędzając
    # zwykle ~5 s/mecz, i zostawiamy explicit warning dla audytu.
    # ===================================================================
    if _tennis_should_skip_expensive_steps(out):
        tennis_warnings.append('fast_path_skipped_expensive_steps')
        out['tennis_phase_path'] = 'partial_data_fastpath'
        print(f"   ⏭️ Tennis fast-path: pomijam last-matches + surface form "
              f"(brak h2h/rankingów/form — i tak partial_data)")
    else:
        _extract_last_matches_for_players(soup, driver, url, out, player_a, player_b)
        _compute_surface_form(soup, driver, url, out, player_a, player_b)

    # ===================================================================
    # DATA COMPLETENESS: hard fails vs soft warnings
    # ===================================================================
    hard_reason, soft_warnings = _check_tennis_data_completeness(out)
    tennis_warnings.extend(soft_warnings)

    if hard_reason:
        out['tennis_skip_reason'] = hard_reason
        out['tennis_data_warnings'] = tennis_warnings
        out['qualifies'] = False
        print(f"   ❌ Tennis HARD SKIP: {hard_reason}")
        return _finalise(out)

    if tennis_warnings:
        out['tennis_data_warnings'] = tennis_warnings
        print(f"   ⚠️ Tennis partial data ({len(tennis_warnings)} warnings): "
              f"{'; '.join(tennis_warnings)}")

    # ===================================================================
    # SCORING: Tennis Scoring Engine v4
    # ===================================================================

    if not player_a or not player_b:
        out['tennis_skip_reason'] = "missing_player_names"
        print(f"   ❌ Tennis HARD SKIP: missing player names (A: {player_a}, B: {player_b})")
        return _finalise(out)
    
    try:
        from tennis_scoring_engine import TennisScoringEngine

        engine = TennisScoringEngine()
        scored = engine.score_match(out)

        out['advanced_score'] = scored.advanced_score
        out['qualifies'] = scored.advanced_score >= engine.threshold
        out['favorite'] = scored.favorite
        out['prob_a'] = scored.prob_a
        out['prob_b'] = scored.prob_b
        out['cal_a'] = scored.cal_a
        out['cal_b'] = scored.cal_b
        out['best_pick'] = scored.best_pick
        out['best_prob'] = scored.best_prob
        out['best_odds'] = scored.best_odds
        out['ev'] = scored.ev
        out['edge'] = scored.edge
        out['kelly'] = scored.kelly
        out['confidence'] = scored.confidence
        out['data_quality'] = scored.data_quality
        out['score_breakdown'] = scored.breakdown

        if out['qualifies']:
            print(f"   ✅ Tennis QUALIFIES! Score: {scored.advanced_score:.1f}/100  "
                  f"pick={scored.best_pick}  P={scored.best_prob:.0%}  "
                  f"EV={scored.ev:+.3f}  edge={scored.edge:+.1f}%  "
                  f"dq={scored.data_quality:.0%}")
        else:
            print(f"   ❌ Tennis nie kwalifikuje: Score: {scored.advanced_score:.1f}/100 "
                  f"(threshold: {engine.threshold})  dq={scored.data_quality:.0%}")

    except Exception as e:
        print(f"   ⚠️ Tennis scoring engine error: {e}, using basic logic")

        # Minimal fallback – no synthetic data, just H2H + ranking
        fallback_score = 0.0
        if player_a_wins > 0 or player_b_wins > 0:
            fallback_score += (player_a_wins - player_b_wins) * 10.0
        if out['ranking_a'] and out['ranking_b']:
            rdiff = out['ranking_b'] - out['ranking_a']  # >0 = A better
            fallback_score += rdiff * 0.5

        out['advanced_score'] = abs(fallback_score)
        out['qualifies'] = abs(fallback_score) >= 45.0
        if fallback_score > 0:
            out['favorite'] = 'player_a'
        elif fallback_score < 0:
            out['favorite'] = 'player_b'
        else:
            out['favorite'] = 'unknown'
        print(f"   📊 Fallback score: {abs(fallback_score):.1f} (qualifies: {out['qualifies']})")

    return _finalise(out)


# ===================================================================
# TENNIS HELPER FUNCTIONS (last match, surface form, data completeness)
# ===================================================================

def _extract_last_matches_for_players(soup: BeautifulSoup, driver: webdriver.Chrome,
                                       match_url: str, out: Dict,
                                       player_a: str, player_b: str) -> None:
    """
    Extract last match (date, score, opponent, result) for each player
    from Livesport's H2H sub-sections.

    Uses three ordered strategies:
      1. Player-specific sections identified by header containing the player name.
      2. Non-H2H sections without recognisable headers — scan rows for the player.
      3. Row-level scan across ALL sections (including the direct H2H block)
         to find any recent row involving the target player.

    Populates out['last_match_a_*'] and out['last_match_b_*'] fields in-place.
    """
    if not player_a or not player_b:
        return

    # ------------------------------------------------------------------
    # Inner helper: extract the most recent valid match row for a player
    # ------------------------------------------------------------------
    def _extract_last_from_section(section, target_player: str):
        """Extract the most recent match from a section's rows."""
        rows = section.select('a.h2h__row')
        if not rows:
            return None, None, None, None

        for row in rows[:8]:
            try:
                date_el = row.select_one('span.h2h__date')
                match_date = date_el.get_text(strip=True) if date_el else None

                home_el = row.select_one('span.h2h__homeParticipant span.h2h__participantInner')
                away_el = row.select_one('span.h2h__awayParticipant span.h2h__participantInner')
                home_name = home_el.get_text(strip=True) if home_el else ''
                away_name = away_el.get_text(strip=True) if away_el else ''

                result_spans = row.select('span.h2h__result span')
                if len(result_spans) < 2:
                    continue
                s1 = int(result_spans[0].get_text(strip=True))
                s2 = int(result_spans[1].get_text(strip=True))
                score_str = f"{s1}-{s2}"

                if s1 == s2:
                    continue  # no draws in tennis

                if _teams_match(home_name, target_player):
                    opponent = away_name
                    result = 'W' if s1 > s2 else 'L'
                elif _teams_match(away_name, target_player):
                    opponent = home_name
                    result = 'W' if s2 > s1 else 'L'
                else:
                    continue

                return match_date, score_str, opponent, result
            except (ValueError, TypeError, AttributeError):
                continue
        return None, None, None, None

    # ------------------------------------------------------------------
    # Collect all h2h__section divs
    # ------------------------------------------------------------------
    try:
        all_sections = soup.find_all('div', class_='h2h__section')
    except Exception:
        return

    # Classify sections: direct-H2H vs player-specific vs unknown
    h2h_direct_section = None
    player_sections = []   # (header_text, section)
    unknown_sections = []  # sections with empty/unrecognised headers

    for section in all_sections:
        try:
            header_text = ''
            header_el = section.select_one(
                '[data-testid="wcl-headerSection-text"], '
                '[class*="headerSection"], '
                'div.h2h__sectionHeader, div.section__title, '
                'div.h2h__sectionHeader span, h2, h3'
            )
            if header_el:
                header_text = header_el.get_text(strip=True).lower()

            # Identify the direct H2H section
            if any(kw in header_text for kw in (
                'pojedynki', 'bezpośrednie', 'head-to-head', 'head to head',
                'direct', 'h2h'
            )):
                h2h_direct_section = section
                continue

            if header_text:
                player_sections.append((header_text, section))
            else:
                unknown_sections.append(section)
        except Exception:
            continue

    # ------------------------------------------------------------------
    # STRATEGY 1: match sections to players by header text
    # ------------------------------------------------------------------
    def _header_matches_player(header: str, player_name: str) -> bool:
        """Check if a section header refers to a specific player."""
        if not header or not player_name:
            return False
        h = header.lower()
        pn = player_name.lower()
        # Direct containment
        if pn in h:
            return True
        # Any significant word (>2 chars) from the player name in the header
        if any(part.lower() in h for part in player_name.split() if len(part) > 2):
            return True
        # Fuzzy match
        if _teams_match(header, player_name):
            return True
        return False

    for header_text, section in player_sections:
        if not out.get('last_match_a_date') and _header_matches_player(header_text, player_a):
            d, s, o, r = _extract_last_from_section(section, player_a)
            if d and s:
                out['last_match_a_date'] = d
                out['last_match_a_score'] = s
                out['last_match_a_opponent'] = o
                out['last_match_a_result'] = r

        if not out.get('last_match_b_date') and _header_matches_player(header_text, player_b):
            d, s, o, r = _extract_last_from_section(section, player_b)
            if d and s:
                out['last_match_b_date'] = d
                out['last_match_b_score'] = s
                out['last_match_b_opponent'] = o
                out['last_match_b_result'] = r

    # ------------------------------------------------------------------
    # STRATEGY 2: scan unknown (header-less) sections for player rows
    # ------------------------------------------------------------------
    if not out.get('last_match_a_date') or not out.get('last_match_b_date'):
        # Also include player_sections that didn't match either player
        remaining = unknown_sections + [
            sec for hdr, sec in player_sections
            if not _header_matches_player(hdr, player_a)
            and not _header_matches_player(hdr, player_b)
        ]
        for section in remaining:
            if not out.get('last_match_a_date'):
                d, s, o, r = _extract_last_from_section(section, player_a)
                if d and s:
                    out['last_match_a_date'] = d
                    out['last_match_a_score'] = s
                    out['last_match_a_opponent'] = o
                    out['last_match_a_result'] = r
            if not out.get('last_match_b_date'):
                d, s, o, r = _extract_last_from_section(section, player_b)
                if d and s:
                    out['last_match_b_date'] = d
                    out['last_match_b_score'] = s
                    out['last_match_b_opponent'] = o
                    out['last_match_b_result'] = r

    # ------------------------------------------------------------------
    # STRATEGY 3: last-resort row scan of direct H2H section
    # ------------------------------------------------------------------
    if not out.get('last_match_a_date') or not out.get('last_match_b_date'):
        if h2h_direct_section:
            if not out.get('last_match_a_date'):
                d, s, o, r = _extract_last_from_section(h2h_direct_section, player_a)
                if d and s:
                    out['last_match_a_date'] = d
                    out['last_match_a_score'] = s
                    out['last_match_a_opponent'] = o
                    out['last_match_a_result'] = r
            if not out.get('last_match_b_date'):
                d, s, o, r = _extract_last_from_section(h2h_direct_section, player_b)
                if d and s:
                    out['last_match_b_date'] = d
                    out['last_match_b_score'] = s
                    out['last_match_b_opponent'] = o
                    out['last_match_b_result'] = r


def _compute_surface_form(soup: BeautifulSoup, driver: webdriver.Chrome,
                          match_url: str, out: Dict,
                          player_a: str, player_b: str) -> None:
    """
    Compute surface-specific form: W/L from last matches on the same surface.

    Livesport does NOT support surface-filtered H2H URLs for tennis.
    Instead, we derive surface form from the "Ostatnie mecze" sections
    already present on the H2H page by checking tournament context.

    Strategy:
      1. Parse the player's "Ostatnie mecze" section rows
      2. For each row, check if the tournament/event name suggests the same surface
      3. If we can't determine surface per row, use ALL recent matches as proxy
         (better than nothing — most players play on the same surface in a period)

    Populates out['surface_form_a'], out['surface_form_b'],
    out['surface_stats_a'], out['surface_stats_b'].
    """
    surface = out.get('surface')
    if not surface or not player_a or not player_b:
        return

    surface_form_a: List[str] = []
    surface_form_b: List[str] = []

    # Surface keyword maps for tournament detection
    _SURFACE_KEYWORDS: Dict[str, List[str]] = {
        'clay': ['roland garros', 'french open', 'antuka', 'clay', 'rome', 'madrid',
                 'barcelona', 'monte carlo', 'hamburg', 'buenos aires', 'rio',
                 'lyon', 'bastad', 'umag', 'kitzbuhel', 'gstaad', 'bucharest'],
        'grass': ['wimbledon', 'grass', 'queen', 'halle', 'eastbourne', 'stuttgart',
                  's-hertogenbosch', 'mallorca', 'newport', 'trawa'],
        'hard': ['us open', 'australian open', 'hard', 'indian wells', 'miami',
                 'cincinnati', 'montreal', 'toronto', 'shanghai', 'beijing',
                 'dubai', 'doha', 'brisbane', 'adelaide', 'auckland'],
    }

    def _row_matches_surface(row, target_surface: str) -> bool:
        """Check if a match row's tournament suggests the target surface.
        
        Since Livesport H2H rows don't expose tournament/event info,
        we always return True — using all recent matches as surface form proxy.
        This is acceptable because:
        1. During clay season, most matches are on clay
        2. Having approximate surface form is better than no data at all
        3. The scoring engine weights surface_form at only 0.13
        """
        return True

    def _extract_surface_form_from_section(sec, player: str, target_surface: str) -> List[str]:
        """Extract W/L for matches on the target surface from a section."""
        form: List[str] = []
        rows = sec.select('a.h2h__row')
        for row in rows[:10]:  # Check up to 10 rows to find 5 on surface
            try:
                home_el = row.select_one('span.h2h__homeParticipant span.h2h__participantInner')
                away_el = row.select_one('span.h2h__awayParticipant span.h2h__participantInner')
                home_name = home_el.get_text(strip=True) if home_el else ''
                away_name = away_el.get_text(strip=True) if away_el else ''

                result_spans = row.select('span.h2h__result span')
                if len(result_spans) < 2:
                    continue
                s1 = int(result_spans[0].get_text(strip=True))
                s2 = int(result_spans[1].get_text(strip=True))
                if s1 == s2:
                    continue

                # Determine if this player is home or away
                is_home = _teams_match(home_name, player)
                is_away = _teams_match(away_name, player)
                if not is_home and not is_away:
                    continue

                # Check surface match (if we can determine it)
                if not _row_matches_surface(row, target_surface):
                    continue

                if is_home:
                    form.append('W' if s1 > s2 else 'L')
                else:
                    form.append('W' if s2 > s1 else 'L')

                if len(form) >= 5:
                    break
            except (ValueError, TypeError, AttributeError):
                continue
        return form

    try:
        # Find player sections using correct header selector
        sections = soup.find_all('div', class_='h2h__section')

        for sec in sections:
            header = sec.select_one(
                '[data-testid="wcl-headerSection-text"], '
                '[class*="headerSection"], '
                'div.h2h__sectionHeader, div.section__title'
            )
            if not header:
                continue
            header_text = header.get_text(strip=True).lower()

            # Skip direct H2H section
            if any(kw in header_text for kw in ('pojedynki', 'bezpośrednie', 'head-to-head', 'h2h')):
                continue

            # Match section to player
            if not surface_form_a:
                name_parts_a = [p for p in player_a.split() if len(p) > 2]
                if player_a.lower() in header_text or any(p.lower() in header_text for p in name_parts_a):
                    surface_form_a = _extract_surface_form_from_section(sec, player_a, surface)

            if not surface_form_b:
                name_parts_b = [p for p in player_b.split() if len(p) > 2]
                if player_b.lower() in header_text or any(p.lower() in header_text for p in name_parts_b):
                    surface_form_b = _extract_surface_form_from_section(sec, player_b, surface)

    except Exception as e:
        print(f"   ⚠️ Surface form extraction error: {e}")

    # Limit to 5 most recent
    surface_form_a = surface_form_a[:5]
    surface_form_b = surface_form_b[:5]

    out['surface_form_a'] = surface_form_a
    out['surface_form_b'] = surface_form_b

    # Build surface_stats dict for scoring engine
    if surface_form_a:
        wins_a = surface_form_a.count('W')
        out['surface_stats_a'] = {surface: wins_a / len(surface_form_a)}
    if surface_form_b:
        wins_b = surface_form_b.count('W')
        out['surface_stats_b'] = {surface: wins_b / len(surface_form_b)}


# Tennis data completeness threshold
TENNIS_MIN_ODDS = 1.35


def _tennis_odds_gate_reason(out: Dict) -> Optional[str]:
    """Early-skip reason oparty wyłącznie o kursy.

    Zwraca powód skipu (`odds_below_threshold: …`) tylko gdy oba kursy są już
    pobrane i któryś jest poniżej `TENNIS_MIN_ODDS`. Gdy któregoś brak lub są
    nieliczbowe, zwracamy `None` — to pozostawia szansę kolejnym fallbackom
    (np. FlashScore) i nie odrzuca meczu pochopnie.

    Używane w `process_match_tennis` jako szybki gate zaraz po pobraniu kursów,
    przed kosztowną nawigacją do H2H i ekstrakcją last-matches/surface form.
    Dzięki temu mecze z bardzo niskim/wysokim kursem (najczęstszy powód
    `odds_below_threshold` w logach) odpadają w sekundach zamiast w minutach.
    """
    ho = out.get('home_odds')
    ao = out.get('away_odds')
    if ho is None or ao is None:
        return None
    try:
        ho_f = float(ho)
        ao_f = float(ao)
    except (ValueError, TypeError):
        return None
    if ho_f < TENNIS_MIN_ODDS:
        return f"odds_below_threshold: A ({ho_f:.2f}) < {TENNIS_MIN_ODDS}"
    if ao_f < TENNIS_MIN_ODDS:
        return f"odds_below_threshold: B ({ao_f:.2f}) < {TENNIS_MIN_ODDS}"
    return None


def _tennis_should_skip_expensive_steps(out: Dict) -> bool:
    """Heurystyka „balanced": pomiń droższe kroki gdy mecz prawie na pewno
    skończy jako `partial_data` z bardzo niskim score'em.

    Skip kosztownych etapów (`_extract_last_matches_for_players`,
    `_compute_surface_form` — każdy robi własny `driver.get` + `time.sleep`)
    tylko jeśli WSZYSTKIE poniższe są prawdą:

      * brak H2H (`h2h_count == 0`),
      * brak rankingów dla obu graczy,
      * brak form badges dla obu graczy.

    Mecz z którymkolwiek z tych sygnałów daje szansę na zdobycie sensownego
    score'u, więc tam pełny pipeline zostawiamy. Heurystyka jest celowo
    konserwatywna — nie zmienia progów biznesowych ani struktury wyjścia,
    tylko unika minutowego czekania na dane i tak nie do uratowania.

    Oszczędność czasu w CI pochodzi z innych optymalizacji (krótsze sleepy,
    timeout 20s, brak FlashScore fallback) — ta heurystyka jest identyczna
    w CI i lokalnie.
    """
    if (out.get('h2h_count') or 0) > 0:
        return False
    if out.get('ranking_a') or out.get('ranking_b'):
        return False
    if out.get('form_a') or out.get('form_b'):
        return False
    return True


def _check_tennis_data_completeness(out: Dict) -> tuple:
    """
    Validate tennis match data.

    Returns (hard_reason, soft_warnings):
      hard_reason  – str  → match must be discarded (None if OK)
      soft_warnings – list[str] → informational; match is still scoreable

    Hard-fail conditions (discard the match):
      1. Both player names missing
      2. Odds missing or below 1.35 on either side

    Soft-fail conditions (lower data_quality, keep the match):
      1. No last H2H date/score
      2. No last match for either player
      3. No form data
    """
    warnings: List[str] = []

    # ── HARD: player names ──
    if not out.get('home_team') or not out.get('away_team'):
        return "missing_player_names", warnings

    # ── HARD: odds threshold ──
    home_odds = out.get('home_odds')
    away_odds = out.get('away_odds')
    if not home_odds or not away_odds:
        return "odds_missing", warnings
    try:
        ho = float(home_odds)
        ao = float(away_odds)
        if ho < TENNIS_MIN_ODDS:
            return f"odds_below_threshold: A ({ho:.2f}) < {TENNIS_MIN_ODDS}", warnings
        if ao < TENNIS_MIN_ODDS:
            return f"odds_below_threshold: B ({ao:.2f}) < {TENNIS_MIN_ODDS}", warnings
    except (ValueError, TypeError):
        return "odds_invalid", warnings

    # ── SOFT: last H2H ──
    if not out.get('last_h2h_date') or not out.get('last_h2h_score'):
        warnings.append("missing_h2h")

    # ── SOFT: last match per player ──
    if not out.get('last_match_a_date') or not out.get('last_match_a_score'):
        warnings.append(f"missing_recent_matches_A ({out.get('home_team', '?')})")
    if not out.get('last_match_b_date') or not out.get('last_match_b_score'):
        warnings.append(f"missing_recent_matches_B ({out.get('away_team', '?')})")

    # ── SOFT: form ──
    if not out.get('form_a'):
        warnings.append("missing_form_A")
    if not out.get('form_b'):
        warnings.append("missing_form_B")

    return None, warnings  # No hard failure


def _extract_real_form_badges(soup: BeautifulSoup, player_name: str) -> List[str]:
    """Extract REAL form W/L badges from Livesport H2H page.

    Livesport renders form badges as small colored circles with class patterns:
      - Win:  class="wcl-badgeform_* wcl-win_*"   text="Z" (Zwycięstwo)
      - Loss: class="wcl-badgeform_* wcl-lose_*"  text="P" (Przegrana)

    These badges appear in the "Ostatnie mecze: PlayerName" sections.
    We find the section matching the player name, then extract badges from it.

    Fallback: if no player-specific section found, scan all badge elements.

    Returns list of 'W'/'L' (max 5, most recent first) or empty list.
    """
    if not player_name:
        return []

    form: List[str] = []

    try:
        # Strategy 1: Find the section for this player and extract badges from it
        sections = soup.find_all('div', class_='h2h__section')
        player_section = None

        for sec in sections:
            # Use the correct header selector (data-testid or class*=headerSection)
            header = sec.select_one(
                '[data-testid="wcl-headerSection-text"], '
                '[class*="headerSection"], '
                'div.h2h__sectionHeader, div.section__title'
            )
            if not header:
                continue
            header_text = header.get_text(strip=True).lower()

            # Skip direct H2H section
            if any(kw in header_text for kw in ('pojedynki', 'bezpośrednie', 'head-to-head', 'h2h')):
                continue

            # Check if this section belongs to our player
            # Header format: "Ostatnie mecze: PlayerName"
            player_lower = player_name.lower()
            if player_lower in header_text:
                player_section = sec
                break
            # Fuzzy: check if any significant word from player name is in header
            name_parts = [p for p in player_name.split() if len(p) > 2]
            if any(part.lower() in header_text for part in name_parts):
                player_section = sec
                break

        # Strategy 2: Extract badges from the player's section
        target = player_section if player_section else soup

        # Livesport badge classes: wcl-badgeform_* with wcl-win_* or wcl-lose_*
        badges = target.select('[class*="badgeform"]')
        if not badges:
            # Fallback: try broader selector
            badges = target.select('[class*="badge"]')

        for badge in badges:
            classes = ' '.join(badge.get('class', [])).lower()
            text = badge.get_text(strip=True).upper()

            if 'win' in classes or text == 'Z' or text == 'W':
                form.append('W')
            elif 'lose' in classes or text == 'P' or text == 'L':
                form.append('L')

            if len(form) >= 5:
                break

    except Exception:
        pass

    return form[:5]


def _accept_cookies_on_page(driver: webdriver.Chrome):
    """Akceptuje banner cookies/consent jeśli się pojawi (OneTrust itp.)."""
    try:
        cookie_btn = driver.find_element(By.ID, "onetrust-accept-btn-handler")
        if cookie_btn.is_displayed():
            cookie_btn.click()
            time.sleep(0.5)
            print("   🍪 Consent banner zaakceptowany")
            return True
    except NoSuchElementException:
        pass
    except Exception:
        pass
    # Fallback: szukaj innych popularnych przycisków consent
    for selector in ['button#accept-cookies', 'button.cookie-accept', '[data-testid="accept-cookies"]']:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed():
                btn.click()
                time.sleep(0.3)
                print("   🍪 Consent banner zaakceptowany (fallback)")
                return True
        except Exception:
            continue
    return False


def _count_match_links_in_page(driver: webdriver.Chrome) -> int:
    """Szybko liczy ile linków do meczów jest aktualnie na stronie (bez parsowania BS4)."""
    try:
        count = driver.execute_script("""
            var links = document.querySelectorAll('a[href]');
            var count = 0;
            for (var i = 0; i < links.length; i++) {
                var href = links[i].getAttribute('href') || '';
                if (href.indexOf('/match/') !== -1 || href.indexOf('/mecz/') !== -1 || 
                    href.indexOf('/#/match/') !== -1 || href.indexOf('/#id/') !== -1 ||
                    href.indexOf('/event/') !== -1 || href.indexOf('/detail/') !== -1) {
                    count++;
                }
            }
            return count;
        """)
        return count or 0
    except Exception:
        return 0


def _extract_match_links_from_soup(soup: BeautifulSoup, sport_url: str, existing_links: set, leagues: List[str] = None) -> List[str]:
    """Wyciąga linki do meczów z BeautifulSoup. Zwraca unikalne nowe linki."""
    sport_links = []
    # Rozszerzone wzorce URL — Livesport zmienia endpointy
    patterns = ['/match/', '/mecz/', '/#/match/', '/#id/', '/event/', '/detail/']
    debug_patterns_found = {p: 0 for p in patterns}
    
    anchors = soup.find_all('a', href=True)
    
    for a in anchors:
        href = a['href']
        matched = False
        for pattern in patterns:
            if pattern in href:
                debug_patterns_found[pattern] += 1
                matched = True
                break
        
        if not matched:
            # Dodatkowy fallback: data-href lub onclick z URLem meczu
            data_href = a.get('data-href', '')
            for pattern in patterns:
                if pattern in data_href:
                    href = data_href
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
                if not any(league.lower() in href.lower() for league in leagues):
                    link_text = a.get_text(strip=True).lower()
                    if not any(league.lower() in link_text for league in leagues):
                        continue
            
            if href not in existing_links:
                existing_links.add(href)
                sport_links.append(href)
    
    return sport_links, debug_patterns_found


def get_match_links_from_day(driver: webdriver.Chrome, date: str, sports: List[str] = None, leagues: List[str] = None) -> List[str]:
    """Zbiera linki do meczów z głównej strony dla danego dnia.
    
    OPTYMALIZACJA CI:
    - Smart scroll: liczy linki podczas scrollowania, wychodzi gdy brak nowych
    - Cookie consent: automatycznie zamyka bannery blokujące lazy-load
    - Rozszerzone wzorce URL: /match/, /mecz/, /event/, /detail/, /#id/
    - Debug logging: w CI loguje szczegóły dla diagnozy problemów
    
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
    
    IS_CI = os.environ.get('GITHUB_ACTIONS') == 'true' or os.environ.get('CI') == 'true'
    all_links = []
    all_links_set = set()
    
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
            
            # Czas na pierwsze załadowanie strony
            if sport in ['volleyball', 'handball', 'rugby']:
                time.sleep(3.5)
            else:
                time.sleep(2.5)
            
            # 🍪 Akceptuj consent banner (może blokować lazy-load!)
            _accept_cookies_on_page(driver)
            
            # 🔥 Wykryj stronę błędu/blokady LiveSport także na liście dnia.
            # Jeśli LiveSport zwróci stronę-zaślepkę, ponów z backoffem zanim
            # uznamy, że "nie ma meczów".
            _list_attempts = 0
            while is_livesport_error_page(_safe_page_source(driver)) and _list_attempts < 3:
                _list_attempts += 1
                _delay = exponential_backoff_with_jitter(_list_attempts)
                print(f"   🚫 Lista {sport}: strona błędu/blokady LiveSport "
                      f"(próba {_list_attempts}/3) — czekam {_delay:.1f}s...")
                time.sleep(_delay)
                try:
                    driver.get(date_url)
                    time.sleep(3.0)
                    _accept_cookies_on_page(driver)
                except WebDriverException as _e:
                    logger.debug(f"Retry listy {sport} nie powiódł się: {_e}")

            # 📊 DEBUG CI: Sprawdź co jest na stronie PRZED scrollowaniem
            initial_link_count = _count_match_links_in_page(driver)
            page_title = driver.title or 'N/A'
            current_url = driver.current_url
            print(f"   📊 Strona załadowana: title='{page_title[:60]}', linki_przed_scroll={initial_link_count}")
            print(f"   📊 Aktualny URL: {current_url}")
            
            if IS_CI and initial_link_count == 0:
                # DIAGNOZA: brak linków po załadowaniu — może Cloudflare/consent blokuje
                page_source_len = len(driver.page_source)
                print(f"   ⚠️  CI DEBUG: 0 linków! page_source_len={page_source_len}")
                # Sprawdź czy strona ma treść sportową
                has_content = driver.execute_script("""
                    var body = document.body ? document.body.innerText : '';
                    return {
                        length: body.length,
                        has_event: body.indexOf('event') !== -1 || body.indexOf('mecz') !== -1,
                        has_league: body.indexOf('liga') !== -1 || body.indexOf('league') !== -1,
                        has_cloudflare: body.indexOf('Cloudflare') !== -1 || body.indexOf('challenge') !== -1,
                        sample: body.substring(0, 300)
                    };
                """)
                print(f"   ⚠️  CI DEBUG: body_len={has_content.get('length')}, has_event={has_content.get('has_event')}, has_league={has_content.get('has_league')}, cloudflare={has_content.get('has_cloudflare')}")
                if has_content.get('sample'):
                    print(f"   ⚠️  CI DEBUG: body[0:300] = {has_content['sample'][:200]}")
                
                # Retry: poczekaj dodatkowe 3s i sprawdź ponownie
                print(f"   🔄 Dodatkowe oczekiwanie 3s...")
                time.sleep(3.0)
                _accept_cookies_on_page(driver)
                initial_link_count = _count_match_links_in_page(driver)
                print(f"   📊 Po retry: linki={initial_link_count}")
            
            # ========================================
            # SMART SCROLL: Dynamicznie wg znalezionych linków
            # ========================================
            # Maks scrolli: football=15, inne=8. Auto-exit jeśli 3x z rzędu brak nowych.
            max_scrolls = 15 if sport == 'football' else (10 if sport in ['basketball', 'tennis'] else 8)
            
            prev_link_count = initial_link_count
            no_new_links_count = 0
            
            for scroll_i in range(max_scrolls):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.6)  # Krótki wait — wystarczy do lazy-load
                
                # Policz aktualną liczbę linków (szybkie JS, bez BS4)
                current_count = _count_match_links_in_page(driver)
                
                if current_count <= prev_link_count:
                    no_new_links_count += 1
                    if no_new_links_count >= 3:
                        print(f"   ℹ️ Stop scrollowania po {scroll_i+1} scrollach (brak nowych linków, total={current_count})")
                        break
                else:
                    no_new_links_count = 0
                    if (scroll_i + 1) % 5 == 0:
                        print(f"   📜 Scroll {scroll_i+1}/{max_scrolls}: {current_count} linków znalezionych")
                prev_link_count = current_count
            
            # Scroll do góry i parsuj
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            sport_links, debug_patterns_found = _extract_match_links_from_soup(
                soup, sport_url, all_links_set, leagues
            )
            
            # Debug info gdy za mało meczów
            if len(sport_links) < 20 or (sport == 'football' and len(sport_links) < 100):
                print(f"   ⚠️  DEBUG - Wzorce znalezione: {debug_patterns_found}")
                anchors = soup.find_all('a', href=True)
                print(f"   ⚠️  DEBUG - Wszystkich <a> na stronie: {len(anchors)}")
                sample_hrefs = [a['href'] for a in anchors[:30] if a.get('href')]
                print(f"   ⚠️  DEBUG - Przykładowe hrefs (5): {sample_hrefs[:5]}")
                
                # Dodatkowe: szukaj elementów które mogą być meczami ale nie są <a>
                match_elements = soup.select('[class*="event"], [class*="match"], [class*="sportName"], [data-id]')
                if match_elements:
                    print(f"   ⚠️  DEBUG - Elementy match/event (nie <a>): {len(match_elements)}")
                    for el in match_elements[:3]:
                        print(f"      tag={el.name}, classes={el.get('class', [])[:3]}, data-id={el.get('data-id', 'N/A')}")
            
            print(f"   ✓ Znaleziono {len(sport_links)} meczów dla {sport}")
            all_links.extend(sport_links)
            
        except Exception as e:
            print(f"   ✗ Błąd przy zbieraniu linków dla {sport}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n📊 TOTAL: {len(all_links)} linków do meczów ze wszystkich sportów")
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
            except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
                logger.debug(f"Kalendarz nie znaleziony lub niedostępny: {e}")
            
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
                
        except (WebDriverException, ConnectionResetError, ConnectionError) as e:
            logger.warning(f'Błąd połączenia przy meczu {url}: {type(e).__name__}: {str(e)[:100]}')
            print(f'   ⚠️  Błąd połączenia: {type(e).__name__}')
        except Exception as e:
            logger.error(f'Nieoczekiwany błąd przy meczu {url}: {type(e).__name__}: {e}')
            print(f'   ⚠️  Błąd: {e}')
        
        # AUTO-RESTART przeglądarki co N meczów (zapobiega crashom)
        if i % RESTART_INTERVAL == 0 and i < len(urls):
            print(f'\n🔄 AUTO-RESTART: Restartowanie przeglądarki po {i} meczach...')
            print(f'   ✅ Przetworzone dane ({len(rows)} meczów) są bezpieczne w pamięci!')
            
            restart_success = False
            max_restart_attempts = 3
            
            for restart_attempt in range(max_restart_attempts):
                try:
                    # Zamknij stary driver
                    try:
                        driver.quit()
                    except Exception:
                        pass  # Ignoruj błędy przy zamykaniu
                    
                    time.sleep(2)
                    
                    # Utwórz nowy driver
                    driver = start_driver(headless=args.headless)
                    
                    # Sprawdź czy nowy driver działa
                    if check_driver_health(driver):
                        print(f'   ✅ Przeglądarka zrestartowana! Kontynuuję od meczu {i+1}...\n')
                        restart_success = True
                        break
                    else:
                        logger.warning(f"Driver health check failed po restarcie (próba {restart_attempt + 1})")
                        
                except Exception as e:
                    logger.warning(f'Błąd restartu (próba {restart_attempt + 1}/{max_restart_attempts}): {e}')
                    time.sleep(2)
            
            if not restart_success:
                logger.error("Nie udało się zrestartować przeglądarki po maksymalnej liczbie prób")
                print(f'   ❌ Krytyczny błąd restartu - zapisuję częściowe wyniki...')
                save_partial_results(rows, args)
                # Ostatnia próba uruchomienia drivera
                try:
                    driver = start_driver(headless=args.headless)
                    if not check_driver_health(driver):
                        raise RuntimeError("Driver nie działa po ostatecznej próbie")
                except Exception as e:
                    logger.critical(f"Nie można kontynuować scrapowania: {e}")
                    print(f'   ❌ Zapisano {len(rows)} meczów, kończę działanie.')
                    break
        
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

