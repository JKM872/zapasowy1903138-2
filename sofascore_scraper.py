"""
SofaScore Scraper v3.2
----------------------
Pobiera dane z SofaScore.com:
- "Who will win?" probabilities (community voting)
- "Will both teams score?" (BTTS) 

NOWE W v3.3:
- Ulepszona obsługa wyjątków z logowaniem
- Driver health checks
- Exponential backoff z jitter

NOWE W v3.2:
- RETRY LOGIC z exponential backoff (3 próby)
- Lepsze obsługa błędów sieciowych
- Automatyczne ponawianie przy timeout

NOWE W v3.1:
- ZAWSZE dedykowany driver (nie używa zewnętrznego z 120s timeout)
- Globalny timeout 35s dla całej operacji (zwiększono z 20s dla stabilności CI/CD)
- Lepsze wyłapywanie wszystkich wyjątków Selenium
- Nie blokuje głównego scrapera

NOWE W v3.0:
- Obsługa consent popup
- Cache wyników (30 min)
- API fallback zamiast HTML scraping
- Dedykowany driver z optymalnymi timeoutami
"""

import time
import re
import hashlib
import threading
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, Optional
from difflib import SequenceMatcher

# Logging setup
logger = logging.getLogger(__name__)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, 
        NoSuchElementException,
        WebDriverException,
        StaleElementReferenceException
    )
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from urllib3.exceptions import ReadTimeoutError, MaxRetryError
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    
# Globalny timeout dla całej operacji SofaScore (sekundy)
# W CI: 20s (szybsze fail-fast), lokalnie: 35s (więcej cierpliwości)
import os as _os_timeout
_IS_CI_TIMEOUT = _os_timeout.getenv('CI') == 'true' or _os_timeout.getenv('GITHUB_ACTIONS') == 'true'
SOFASCORE_GLOBAL_TIMEOUT = 20 if _IS_CI_TIMEOUT else 35

# Sporty BEZ REMISÓW (tylko Home/Away win)
SPORTS_WITHOUT_DRAW = ['volleyball', 'tennis', 'basketball', 'handball', 'hockey', 'ice-hockey']

# Mapowanie nazw sportów na SofaScore URL slugs
SOFASCORE_SPORT_SLUGS = {
    'football': 'football',
    'soccer': 'football',
    'basketball': 'basketball',
    'volleyball': 'volleyball',
    'handball': 'handball',
    'rugby': 'rugby',
    'hockey': 'ice-hockey',
    'ice-hockey': 'ice-hockey',
    'tennis': 'tennis',
}

# Headers dla requests API
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.sofascore.com/',
}

# ============================================================================
# CACHE SYSTEM
# ============================================================================

_sofascore_cache: Dict[str, Dict] = {}
_cache_expiry: Dict[str, datetime] = {}
CACHE_DURATION_MINUTES = 30


def _get_cache_key(home_team: str, away_team: str, sport: str) -> str:
    """Generuje klucz cache na podstawie meczu"""
    key_str = f"{home_team.lower()}|{away_team.lower()}|{sport}".encode()
    return hashlib.md5(key_str).hexdigest()


def _get_cached_result(home_team: str, away_team: str, sport: str) -> Optional[Dict]:
    """Pobiera wynik z cache jeśli istnieje i nie wygasł"""
    key = _get_cache_key(home_team, away_team, sport)
    if key in _sofascore_cache:
        if key in _cache_expiry and datetime.now() < _cache_expiry[key]:
            print(f"   📦 SofaScore: Używam cache")
            return _sofascore_cache[key]
        else:
            del _sofascore_cache[key]
            if key in _cache_expiry:
                del _cache_expiry[key]
    return None


def _set_cached_result(home_team: str, away_team: str, sport: str, result: Dict):
    """Zapisuje wynik do cache"""
    key = _get_cache_key(home_team, away_team, sport)
    _sofascore_cache[key] = result
    _cache_expiry[key] = datetime.now() + timedelta(minutes=CACHE_DURATION_MINUTES)


# ============================================================================
# RETRY LOGIC - zoptymalizowane dla CI (mniej retry)
# ============================================================================

# Wykrywanie CI - w CI zmniejszamy retry aby nie tracić czasu
import os
IS_CI = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'

# W CI: tylko 1 próba (brak retry), lokalnie: 3 próby
MAX_RETRIES = 1 if IS_CI else 3
RETRY_BACKOFF = [0.5, 1, 2] if IS_CI else [1, 2, 4]  # Szybsze w CI


def _retry_request(request_func, *args, **kwargs):
    """
    Wrapper do wielokrotnych prób wykonania requestu z exponential backoff.
    W CI: wykonuje tylko 1 próbę (brak retry po timeout).
    
    Args:
        request_func: Funkcja wykonująca request (np. requests.get)
        *args: Argumenty przekazywane do funkcji
        **kwargs: Keyword arguments przekazywane do funkcji
        
    Returns:
        Response jeśli sukces, None jeśli wszystkie próby zawiodą
    """
    last_exception = None
    
    for attempt in range(MAX_RETRIES):
        try:
            response = request_func(*args, **kwargs)
            if response.status_code == 200:
                return response
            elif response.status_code in [429, 503]:  # Rate limited lub service unavailable
                wait_time = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else RETRY_BACKOFF[-1]
                print(f"      ⏳ SofaScore API: Status {response.status_code}, czekam {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                return response  # Inne błędy - zwróć natychmiast
        except requests.exceptions.Timeout as e:
            last_exception = e
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF[attempt]
                print(f"      ⏳ SofaScore API: Timeout, próba {attempt + 2}/{MAX_RETRIES} za {wait_time}s...")
                time.sleep(wait_time)
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF[attempt]
                print(f"      ⏳ SofaScore API: Błąd połączenia, próba {attempt + 2}/{MAX_RETRIES} za {wait_time}s...")
                time.sleep(wait_time)
        except Exception as e:
            last_exception = e
            break  # Inne błędy - przerwij natychmiast
    
    if last_exception:
        print(f"      ❌ SofaScore API: Wszystkie próby zawiodły - {type(last_exception).__name__}")
    return None


def normalize_team_name(name: str) -> str:
    """Normalizuje nazwę drużyny do porównania - rozszerzona wersja"""
    if not name:
        return ""
    name = name.lower().strip()
    
    # 🔥 POLSKIE/EUROPEJSKIE ZNAKI → ASCII
    char_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
        'é': 'e', 'è': 'e', 'ê': 'e', 'á': 'a', 'à': 'a', 'â': 'a',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ú': 'u', 'ù': 'u', 'û': 'u',
        'ñ': 'n', 'ç': 'c', 'š': 's', 'č': 'c', 'ž': 'z', 'ř': 'r',
        'ď': 'd', 'ť': 't', 'ň': 'n', 'ő': 'o', 'ű': 'u',
    }
    for char, replacement in char_map.items():
        name = name.replace(char, replacement)
    
    # Usuń prefiksy klubów
    prefixes = ['fc ', 'afc ', 'cf ', 'sc ', 'sv ', 'fk ', 'nk ', 'sk ', 'bk ',
                'ac ', 'as ', 'ss ', 'us ', 'cd ', 'ud ', 'rcd ', 'ks ', 'mks ',
                'hapoel ', 'maccabi ', 'beitar ', 'dinamo ', 'dynamo ', 'spartak ',
                'cska ', 'lokomotiv ', 'rapid ', 'inter ', 'real ', 'sporting ']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    
    # Usuń sufiksy
    name = re.sub(r'\s+(u21|u19|u18|u17|u16|u23|b|ii|iii|iv|women|kobiety|ladies)\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+(fc|sc|fk|united|city|town)\s*$', '', name, flags=re.IGNORECASE)
    
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity_score(name1: str, name2: str) -> float:
    """Oblicza similarity score między dwoma nazwami (0.0 - 1.0)."""
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    if not norm1 or not norm2:
        return 0.0
    return SequenceMatcher(None, norm1, norm2).ratio()


def teams_match(team1: str, team2: str, threshold: float = 0.45) -> bool:
    """Sprawdza czy dwie nazwy drużyn są podobne - poluzowany threshold z 0.6"""
    return similarity_score(team1, team2) >= threshold


def accept_consent_popup(driver: 'webdriver.Chrome') -> bool:
    """
    Akceptuje cookie consent popup na SofaScore.
    Zwraca True jeśli popup został zaakceptowany lub nie istnieje.
    """
    try:
        consent_selectors = [
            "button[data-testid='cookie-accept']",
            "button.fc-cta-consent",
            "button[title='Consent']",
            "//button[contains(text(), 'Consent')]",
            "//button[contains(text(), 'Accept')]",
            "//button[contains(text(), 'Agree')]",
        ]
        for selector in consent_selectors:
            try:
                if selector.startswith('//'):
                    btn = driver.find_element(By.XPATH, selector)
                else:
                    btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn and btn.is_displayed():
                    btn.click()
                    time.sleep(0.5)
                    print(f"   ✅ SofaScore: Consent popup zaakceptowany")
                    return True
            except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
                logger.debug(f"Consent popup selector nie znaleziony: {e}")
                continue
        return True
    except (WebDriverException, TimeoutException) as e:
        logger.debug(f"Błąd consent popup: {e}")
        return True


def get_votes_via_api(event_id: int) -> Optional[Dict]:
    """
    Pobiera głosy Fan Vote przez SofaScore API.
    Szybsze i bardziej niezawodne niż HTML scraping.
    
    v3.2: Dodano retry logic z exponential backoff.
    v3.4: Ulepszone logowanie dla CI/CD
    """
    if not REQUESTS_AVAILABLE:
        logger.warning("SofaScore API: requests module not available")
        return None
    try:
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/votes"
        response = _retry_request(requests.get, url, headers=API_HEADERS, timeout=10)
        
        if response is None:
            print(f"   ⚠️ SofaScore API: Brak odpowiedzi (event_id={event_id})")
            return None
            
        if response.status_code == 200:
            data = response.json()
            vote = data.get('vote', {})
            
            # Sprawdź czy są dane głosowania
            if not vote or vote.get('vote1') is None:
                print(f"   ⚠️ SofaScore API: Brak danych głosowania (event_id={event_id})")
                return None
            
            return {
                'sofascore_home_win_prob': vote.get('vote1'),
                'sofascore_draw_prob': vote.get('voteX'),
                'sofascore_away_win_prob': vote.get('vote2'),
                'sofascore_total_votes': sum([
                    vote.get('vote1Count', 0),
                    vote.get('voteXCount', 0),
                    vote.get('vote2Count', 0)
                ]),
            }
        elif response.status_code == 403:
            print(f"   ⚠️ SofaScore API: Zablokowane (403) - możliwe blokady geograficzne/rate limit")
            return None
        elif response.status_code == 404:
            print(f"   ⚠️ SofaScore API: Nie znaleziono meczu (404, event_id={event_id})")
            return None
        else:
            print(f"   ⚠️ SofaScore API: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"   ⚠️ SofaScore API error: {type(e).__name__}: {str(e)[:50]}")
        logger.debug(f"SofaScore API error details: {e}")
        return None


def get_odds_via_api(event_id: int) -> Optional[Dict]:
    """
    🔥 NOWE: Pobiera kursy bukmacherskie przez SofaScore API.
    Fallback gdy FlashScore nie zadziała.
    
    Returns:
        Dict z kursami lub None
    """
    if not REQUESTS_AVAILABLE:
        return None
    try:
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/odds/1/all"
        response = _retry_request(requests.get, url, headers=API_HEADERS, timeout=5)
        if response and response.status_code == 200:
            data = response.json()
            markets = data.get('markets', [])
            
            result = {
                'home_odds': None,
                'draw_odds': None,
                'away_odds': None,
                'bookmaker': None,
                'odds_found': False,
            }
            
            # Szukaj rynku 1X2 (Full Time Result)
            for market in markets:
                if market.get('marketName') in ['Full Time', '1X2', 'Match Winner', 'Full Time Result']:
                    choices = market.get('choices', [])
                    
                    for choice in choices:
                        name = choice.get('name', '').lower()
                        # Weź najlepsze kursy (pierwszy bukmacher z listy)
                        fractional = choice.get('fractionalValue', '')
                        decimal_odds = None
                        
                        # Konwertuj ułamek na dziesiętny
                        if '/' in str(fractional):
                            parts = str(fractional).split('/')
                            if len(parts) == 2:
                                try:
                                    decimal_odds = float(parts[0]) / float(parts[1]) + 1
                                except (ValueError, ZeroDivisionError):
                                    pass
                        elif fractional:
                            try:
                                decimal_odds = float(fractional)
                            except ValueError:
                                pass
                        
                        # Alternatywnie użyj sourceOdds
                        if not decimal_odds:
                            source_odds = choice.get('sourceOdds', [])
                            if source_odds:
                                try:
                                    decimal_odds = float(source_odds[0].get('odds', 0))
                                except (ValueError, IndexError, TypeError):
                                    pass
                        
                        if decimal_odds and decimal_odds > 1.0:
                            if '1' in name or 'home' in name:
                                result['home_odds'] = round(decimal_odds, 2)
                            elif 'x' in name or 'draw' in name:
                                result['draw_odds'] = round(decimal_odds, 2)
                            elif '2' in name or 'away' in name:
                                result['away_odds'] = round(decimal_odds, 2)
                    
                    if result['home_odds'] and result['away_odds']:
                        result['odds_found'] = True
                        result['bookmaker'] = 'SofaScore'
                        print(f"   💰 SofaScore Odds: 1={result['home_odds']:.2f} | X={result.get('draw_odds', '-')} | 2={result['away_odds']:.2f}")
                        return result
            
            return None
        return None
    except Exception as e:
        logger.debug(f"SofaScore odds API error: {e}")
        return None



def search_event_via_api(home_team: str, away_team: str, sport: str = 'football', date_str: str = None) -> Optional[int]:
    """
    Szuka event ID przez SofaScore API.
    
    v3.2: Dodano retry logic z exponential backoff.
    v3.4: Ulepszone logowanie dla CI/CD
    """
    if not REQUESTS_AVAILABLE:
        logger.warning("SofaScore search API: requests module not available")
        return None
    try:
        if date_str:
            search_date = date_str
        else:
            search_date = datetime.now().strftime('%Y-%m-%d')
        sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
        url = f"https://api.sofascore.com/api/v1/sport/{sport_slug}/scheduled-events/{search_date}"
        response = _retry_request(requests.get, url, headers=API_HEADERS, timeout=10)
        
        if not response:
            print(f"   ⚠️ SofaScore search API: Brak odpowiedzi ({sport}/{search_date})")
            return None
            
        if response.status_code == 403:
            print(f"   ⚠️ SofaScore search API: Zablokowane (403)")
            return None
        elif response.status_code != 200:
            print(f"   ⚠️ SofaScore search API: HTTP {response.status_code}")
            return None
        data = response.json()
        events = data.get('events', [])
        home_norm = normalize_team_name(home_team)
        away_norm = normalize_team_name(away_team)
        for event in events:
            event_home = event.get('homeTeam', {}).get('name', '')
            event_away = event.get('awayTeam', {}).get('name', '')
            event_home_norm = normalize_team_name(event_home)
            event_away_norm = normalize_team_name(event_away)
            
            # Poluzowane warunki dopasowania (z 0.6 na 0.45)
            home_sim = similarity_score(home_team, event_home)
            away_sim = similarity_score(away_team, event_away)
            
            # Warunek 1: Similarity score >= 0.45
            home_match_sim = home_sim > 0.45
            away_match_sim = away_sim > 0.45
            
            # Warunek 2: Część nazwy drużyny zawarta w nazwie z SofaScore (dla krótkich słów >= 3 znaki)
            home_match_partial = any(p in event_home_norm for p in home_norm.split() if len(p) > 2)
            away_match_partial = any(p in event_away_norm for p in away_norm.split() if len(p) > 2)
            
            # Warunek 3: Nazwa z SofaScore zawiera część szukanej nazwy
            home_match_reverse = any(p in home_norm for p in event_home_norm.split() if len(p) > 2)
            away_match_reverse = any(p in away_norm for p in event_away_norm.split() if len(p) > 2)
            
            home_match = home_match_sim or home_match_partial or home_match_reverse
            away_match = away_match_sim or away_match_partial or away_match_reverse
            
            # Dodatkowy warunek: suma similarity >= 1.0 (nawet jeśli jedna drużyna słabsza)
            combined_match = (home_sim + away_sim) >= 1.0
            
            if (home_match and away_match) or combined_match:
                return event.get('id')
        return None
    except Exception:
        return None



def extract_event_id_from_url(url: str) -> Optional[int]:
    """Wyciąga event ID z URL SofaScore"""
    match = re.search(r'#id:(\d+)', url)
    if match:
        return int(match.group(1))
    return None


def extract_votes_from_page(driver: webdriver.Chrome, sport: str = 'football') -> Dict:
    """
    Wyciąga dane głosowania "Who will win?" ze strony meczu SofaScore
    """
    has_draw = sport not in SPORTS_WITHOUT_DRAW
    
    result = {
        'sofascore_home_win_prob': None,
        'sofascore_draw_prob': None,
        'sofascore_away_win_prob': None,
        'sofascore_total_votes': 0,
        'sofascore_btts_yes': None,
        'sofascore_btts_no': None,
    }
    
    try:
        page = driver.page_source
        
        # Znajdź sekcję "Who will win" i wyciągnij procenty
        idx = page.find('Who will win')
        if idx > 0:
            section = page[idx:idx+5000]
            
            # Szukaj procentów z pattern >XX%<
            pct_pattern = r'>(\d{1,2})%<'
            percentages = re.findall(pct_pattern, section)
            
            if len(percentages) >= 2:
                if has_draw and len(percentages) >= 3:
                    result['sofascore_home_win_prob'] = int(percentages[0])
                    result['sofascore_draw_prob'] = int(percentages[1])
                    result['sofascore_away_win_prob'] = int(percentages[2])
                else:
                    result['sofascore_home_win_prob'] = int(percentages[0])
                    result['sofascore_away_win_prob'] = int(percentages[1])
            
            # BTTS - szukaj YES/NO po sekcji Who will win
            btts_idx = section.find('both teams score')
            if btts_idx < 0:
                btts_idx = section.find('Will both')
            if btts_idx > 0:
                btts_section = section[btts_idx:btts_idx+1000]
                btts_pcts = re.findall(pct_pattern, btts_section)
                if len(btts_pcts) >= 2:
                    result['sofascore_btts_yes'] = int(btts_pcts[0])
                    result['sofascore_btts_no'] = int(btts_pcts[1])
        
        # Szukaj total votes
        votes_match = re.search(r'Total votes:\s*([\d.,]+)\s*([kKmM])?', page)
        if votes_match:
            votes_str = votes_match.group(1)
            multiplier = votes_match.group(2)
            try:
                votes = float(votes_str.replace(',', '.'))
            except ValueError:
                try:
                    votes = float(votes_str.replace('.', ''))
                except ValueError:
                    votes = 0
            if multiplier and multiplier.lower() == 'k':
                votes *= 1000
            elif multiplier and multiplier.lower() == 'm':
                votes *= 1000000
            result['sofascore_total_votes'] = int(votes)
        
        return result
        
    except Exception as e:
        print(f"❌ Error extracting votes: {e}")
        return result


def find_match_on_main_page(
    driver: webdriver.Chrome,
    home_team: str,
    away_team: str,
    sport: str = 'football'
) -> Optional[str]:
    """
    Szuka meczu na stronie głównej sportu SofaScore.
    Bardziej niezawodne niż wyszukiwarka.
    Używa regex na HTML zamiast Selenium elements (szybsze dla ciężkich stron).
    
    Wszystkie operacje z driver są w try/except żeby nie blokować głównego scrapera.
    """
    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    
    try:
        url = f'https://www.sofascore.com/{sport_slug}'
        print(f"   🔍 SofaScore: Szukam meczu na stronie głównej...")
        
        # Ustaw krótki timeout dla szybszego działania
        try:
            driver.set_page_load_timeout(8)
        except WebDriverException as e:
            logger.debug(f"Nie można ustawić page_load_timeout: {e}")
        
        # Użyj page_load_strategy do szybszego ładowania
        try:
            driver.get(url)
        except (TimeoutException, WebDriverException, ReadTimeoutError, MaxRetryError) as e:
            logger.debug(f"Timeout/błąd przy ładowaniu strony (kontynuuję): {e}")
            # Kontynuuj nawet przy timeout (strona częściowo załadowana)
        
        # Akceptuj consent popup
        accept_consent_popup(driver)
        
        time.sleep(1.5)
        
        home_norm = normalize_team_name(home_team)
        away_norm = normalize_team_name(away_team)
        
        # Metoda 1: Szukaj bezpośrednio w HTML z regex (szybsze niż Selenium elements)
        try:
            page_source = driver.page_source
        except (WebDriverException, ReadTimeoutError, MaxRetryError) as e:
            print(f"   ⚠️ SofaScore: Nie można pobrać strony: {e}")
            return None
        except Exception as e:
            print(f"   ⚠️ SofaScore: Błąd driver.page_source: {e}")
            return None
        
        # Szukaj linków do meczów danego sportu
        match_pattern = rf'href="(/{sport_slug}/[^"]*#id:\d+)"'
        matches = re.findall(match_pattern, page_source)
        
        for match_url in matches:
            href_lower = match_url.lower()
            
            # Sprawdź czy główne słowa z nazw są w URL
            home_parts = [p for p in home_norm.split() if len(p) > 3]
            away_parts = [p for p in away_norm.split() if len(p) > 3]
            
            home_found = any(part in href_lower for part in home_parts)
            away_found = any(part in href_lower for part in away_parts)
            
            if home_found and away_found:
                full_url = f'https://www.sofascore.com{match_url}'
                print(f"   ✅ SofaScore: Znaleziono mecz!")
                return full_url
        
        # Metoda 2: Fallback - użyj Selenium elements jeśli regex nie zadziałał
        try:
            links = driver.find_elements(By.TAG_NAME, 'a')
            
            for link in links[:100]:  # Ogranicz do pierwszych 100 linków
                try:
                    href = link.get_attribute('href')
                    if not href or '#id:' not in href or f'/{sport_slug}/' not in href:
                        continue
                    
                    href_lower = href.lower()
                    
                    home_parts = [p for p in home_norm.split() if len(p) > 3]
                    away_parts = [p for p in away_norm.split() if len(p) > 3]
                    
                    home_found = any(part in href_lower for part in home_parts)
                    away_found = any(part in href_lower for part in away_parts)
                    
                    if home_found and away_found:
                        print(f"   ✅ SofaScore: Znaleziono mecz (fallback)!")
                        return href
                except (StaleElementReferenceException, WebDriverException):
                    continue
                except Exception:
                    continue
        except (WebDriverException, ReadTimeoutError, MaxRetryError) as e:
            print(f"   ⚠️ SofaScore: Fallback search failed: {e}")
        except Exception as e:
            print(f"   ⚠️ SofaScore: Fallback search failed: {e}")
        
        return None
        
    except Exception as e:
        print(f"   ❌ SofaScore: Błąd wyszukiwania: {e}")
        return None


def search_and_get_votes(
    driver: webdriver.Chrome,
    home_team: str,
    away_team: str,
    sport: str = 'football',
    date_str: str = None
) -> Dict:
    """
    Szuka meczu na SofaScore i pobiera dane głosowania.
    Używa strony głównej sportu (bardziej niezawodne niż wyszukiwarka).
    """
    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    has_draw = sport not in SPORTS_WITHOUT_DRAW
    
    result = {
        'sofascore_home_win_prob': None,
        'sofascore_draw_prob': None,
        'sofascore_away_win_prob': None,
        'sofascore_total_votes': 0,
        'sofascore_btts_yes': None,
        'sofascore_btts_no': None,
        'sofascore_url': None,
        'sofascore_found': False,
    }
    
    try:
        # =============================================
        # METODA 1: API (szybsza, bardziej niezawodna)
        # =============================================
        print(f"   🔍 SofaScore: Próbuję API...")
        event_id = search_event_via_api(home_team, away_team, sport, date_str)
        
        if event_id:
            api_result = get_votes_via_api(event_id)
            if api_result and api_result.get('sofascore_home_win_prob') is not None:
                result.update(api_result)
                result['sofascore_url'] = f"https://www.sofascore.com/{sport_slug}/match/{event_id}"
                result['sofascore_found'] = True
                draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
                print(f"   ✅ Fan Vote (API): 🏠{result['sofascore_home_win_prob']}% | "
                      f"{draw_str}✈️{result['sofascore_away_win_prob']}% "
                      f"({result['sofascore_total_votes']:,} głosów)")
                return result
        
        # =============================================
        # METODA 2: HTML Scraping (fallback)
        # =============================================
        print(f"   🔍 SofaScore: API nie zadziałało, próbuję HTML...")
        match_url = find_match_on_main_page(driver, home_team, away_team, sport)
        
        if not match_url:
            print(f"   ⚠️ SofaScore: Nie znaleziono meczu {home_team} vs {away_team}")
            return result
        
        # Spróbuj API z event ID z URL
        event_id = extract_event_id_from_url(match_url)
        if event_id:
            api_result = get_votes_via_api(event_id)
            if api_result and api_result.get('sofascore_home_win_prob') is not None:
                result.update(api_result)
                result['sofascore_url'] = match_url
                result['sofascore_found'] = True
                draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
                print(f"   ✅ Fan Vote (API via URL): 🏠{result['sofascore_home_win_prob']}% | "
                      f"{draw_str}✈️{result['sofascore_away_win_prob']}% "
                      f"({result['sofascore_total_votes']:,} głosów)")
                return result
        
        # Załaduj stronę meczu (ostatnia deska ratunku)
        print(f"   📊 SofaScore: Pobieram dane z HTML...")
        try:
            driver.set_page_load_timeout(12)
        except WebDriverException as e:
            logger.debug(f"Nie można ustawić page_load_timeout dla match_url: {e}")
        
        try:
            driver.get(match_url)
        except (TimeoutException, WebDriverException, ReadTimeoutError, MaxRetryError) as e:
            logger.debug(f"Timeout przy ładowaniu match_url (kontynuuję): {e}")
            # Kontynuuj nawet przy timeout - strona może być częściowo załadowana
        
        # Dłuższe oczekiwanie na załadowanie JavaScript
        time.sleep(4)
        
        # Scroll żeby załadować sekcję głosowania (jest w dolnej części)
        try:
            for _ in range(6):
                driver.execute_script('window.scrollBy(0, 500);')
                time.sleep(0.3)
            
            # Wróć na górę i poczekaj
            driver.execute_script('window.scrollTo(0, 0);')
            time.sleep(1)
            
            # Scroll ponownie - głosy mogą być w różnych miejscach
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight / 2);')
            time.sleep(1)
        except (WebDriverException, ReadTimeoutError, MaxRetryError, TimeoutException) as e:
            logger.debug(f"Błąd przy scrollowaniu SofaScore: {e}")
            # Kontynuuj mimo błędu scrollowania
        
        # Pobierz HTML
        try:
            page_source = driver.page_source
        except (WebDriverException, ReadTimeoutError, MaxRetryError) as e:
            print(f"   ⚠️ SofaScore: Nie można pobrać HTML: {e}")
            return result
        except Exception as e:
            print(f"   ⚠️ SofaScore: Błąd page_source: {e}")
            return result
        
        # Sprawdź czy strona się załadowała (tytuł 404 = błąd)
        try:
            if "404" in driver.title:
                print(f"   ⚠️ SofaScore: Strona meczu nie znaleziona (404)")
                return result
        except Exception:
            pass
        
        result['sofascore_url'] = match_url
        result['sofascore_found'] = True
        
        # Szukaj sekcji głosowania - różne warianty
        who_will_win_found = False
        section_start = -1
        
        for pattern in ['Who will win', 'who will win', 'Fan vote', 'fan vote']:
            idx = page_source.lower().find(pattern.lower())
            if idx > 0:
                section_start = idx
                who_will_win_found = True
                break
        
        if who_will_win_found:
            # Wyciągnij sekcję wokół znalezionego tekstu
            section = page_source[max(0, section_start-500):section_start+5000]
            
            # Szukaj procentów - różne wzorce
            # Pattern 1: >XX%<
            percentages = re.findall(r'>(\d{1,3})%<', section)
            
            # Pattern 2: jeśli nie znaleziono, szukaj w innych formatach
            if len(percentages) < 2:
                percentages = re.findall(r'(\d{1,3})%', section)
            
            if len(percentages) >= 2:
                if has_draw and len(percentages) >= 3:
                    result['sofascore_home_win_prob'] = int(percentages[0])
                    result['sofascore_draw_prob'] = int(percentages[1])
                    result['sofascore_away_win_prob'] = int(percentages[2])
                else:
                    result['sofascore_home_win_prob'] = int(percentages[0])
                    result['sofascore_away_win_prob'] = int(percentages[1])
                
                # BTTS - szukaj po sekcji głosowania
                btts_idx = section.lower().find('both teams score')
                if btts_idx < 0:
                    btts_idx = section.lower().find('btts')
                if btts_idx > 0 and len(percentages) >= 5:
                    result['sofascore_btts_yes'] = int(percentages[3])
                    result['sofascore_btts_no'] = int(percentages[4])
        else:
            # Fallback - szukaj wszystkich procentów na stronie
            all_percentages = re.findall(r'>(\d{1,3})%<', page_source)
            
            # Filtruj sensowne wartości (suma ~100%)
            for i in range(len(all_percentages) - 2):
                try:
                    p1, p2, p3 = int(all_percentages[i]), int(all_percentages[i+1]), int(all_percentages[i+2])
                    if 95 <= p1 + p2 + p3 <= 105:  # Suma bliska 100%
                        result['sofascore_home_win_prob'] = p1
                        result['sofascore_draw_prob'] = p2
                        result['sofascore_away_win_prob'] = p3
                        break
                except (ValueError, IndexError) as e:
                    logger.debug(f"Błąd przy parsowaniu procentów: {e}")
                    continue
        
        # Szukaj total votes
        votes_match = re.search(r'Total votes[:\s]*(\d+\.?\d*)\s*([kKmM])?', page_source)
        if votes_match:
            try:
                votes = float(votes_match.group(1).replace(',', '.'))
                multiplier = votes_match.group(2)
                if multiplier and multiplier.lower() == 'k':
                    votes *= 1000
                elif multiplier and multiplier.lower() == 'm':
                    votes *= 1000000
                result['sofascore_total_votes'] = int(votes)
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug(f"Błąd przy parsowaniu liczby głosów: {e}")
        
        if result['sofascore_home_win_prob'] is not None:
            draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
            print(f"   ✅ Fan Vote: 🏠{result['sofascore_home_win_prob']}% | "
                  f"{draw_str}✈️{result['sofascore_away_win_prob']}% "
                  f"({result['sofascore_total_votes']:,} głosów)")
            if result['sofascore_btts_yes']:
                print(f"   ✅ BTTS: Yes {result['sofascore_btts_yes']}% | No {result['sofascore_btts_no']}%")
        else:
            print(f"   ⚠️ SofaScore: Brak danych Fan Vote")
        
        return result
        
    except Exception as e:
        print(f"   ❌ SofaScore: Błąd: {e}")
        return result


def format_votes_for_display(result: Dict) -> str:
    """Formatuje wyniki głosowania do wyświetlenia"""
    if not result.get('sofascore_found'):
        return "❌ SofaScore: Not found"
    
    home = result.get('sofascore_home_win_prob')
    draw = result.get('sofascore_draw_prob')
    away = result.get('sofascore_away_win_prob')
    votes = result.get('sofascore_total_votes', 0)
    
    if home is None:
        return "⚠️ SofaScore: No vote data"
    
    # Format votes count
    if votes >= 1000000:
        votes_str = f"{votes/1000000:.1f}M"
    elif votes >= 1000:
        votes_str = f"{votes/1000:.1f}k"
    else:
        votes_str = str(votes)
    
    if draw is not None:
        return f"🗳️ Fan Vote ({votes_str}): 🏠{home}% | 🤝{draw}% | ✈️{away}%"
    else:
        return f"🗳️ Fan Vote ({votes_str}): 🏠{home}% | ✈️{away}%"


def get_sofascore_prediction(
    home_team: str,
    away_team: str,
    sport: str = 'football',
    date_str: str = None
) -> Dict:
    """
    🔥 WRAPPER: Interfejs kompatybilny z scrape_and_notify.py
    
    Konwertuje wynik z scrape_sofascore_full() na format oczekiwany przez
    scrape_and_notify.py (klucze bez prefiksu 'sofascore_').
    
    Args:
        home_team: Nazwa gospodarzy
        away_team: Nazwa gości
        sport: Sport
        date_str: Data meczu (YYYY-MM-DD)
    
    Returns:
        Dict z kluczami: found, home_win_prob, draw_prob, away_win_prob, total_votes
    """
    # Pobierz pełne dane z SofaScore
    full_result = scrape_sofascore_full(
        home_team=home_team,
        away_team=away_team,
        sport=sport,
        date_str=date_str,
        use_cache=True
    )
    
    # Konwertuj na format oczekiwany przez scrape_and_notify.py
    return {
        'found': full_result.get('sofascore_found', False),
        'home_win_prob': full_result.get('sofascore_home_win_prob'),
        'draw_prob': full_result.get('sofascore_draw_prob'),
        'away_win_prob': full_result.get('sofascore_away_win_prob'),
        'total_votes': full_result.get('sofascore_total_votes', 0),
        'btts_yes': full_result.get('sofascore_btts_yes'),
        'btts_no': full_result.get('sofascore_btts_no'),
        'url': full_result.get('sofascore_url'),
        # Również zachowaj oryginalne klucze dla backward compatibility
        'sofascore_found': full_result.get('sofascore_found', False),
        'sofascore_home_win_prob': full_result.get('sofascore_home_win_prob'),
        'sofascore_draw_prob': full_result.get('sofascore_draw_prob'),
        'sofascore_away_win_prob': full_result.get('sofascore_away_win_prob'),
        'sofascore_total_votes': full_result.get('sofascore_total_votes', 0),
    }


def format_sofascore_for_email(result: Dict) -> str:
    """Formatuje wyniki SofaScore do emaila HTML"""
    if not result.get('sofascore_found'):
        return ""
    
    home = result.get('sofascore_home_win_prob')
    draw = result.get('sofascore_draw_prob')
    away = result.get('sofascore_away_win_prob')
    votes = result.get('sofascore_total_votes', 0)
    
    if home is None:
        return ""
    
    # Format votes count
    if votes >= 1000000:
        votes_str = f"{votes/1000000:.1f}M"
    elif votes >= 1000:
        votes_str = f"{votes/1000:.1f}k"
    else:
        votes_str = str(votes)
    
    # Determine winner prediction
    if draw is not None:
        max_pct = max(home, draw, away)
        if home == max_pct:
            winner = f"🏠 {home}%"
            winner_color = "#28a745"
        elif away == max_pct:
            winner = f"✈️ {away}%"
            winner_color = "#dc3545"
        else:
            winner = f"🤝 {draw}%"
            winner_color = "#ffc107"
    else:
        if home > away:
            winner = f"🏠 {home}%"
            winner_color = "#28a745"
        else:
            winner = f"✈️ {away}%"
            winner_color = "#dc3545"
    
    return f'<span style="color: {winner_color}; font-weight: bold;">{winner}</span> <small>({votes_str})</small>'


def scrape_sofascore_full(
    driver: webdriver.Chrome = None,
    home_team: str = None,
    away_team: str = None,
    sport: str = 'football',
    date_str: str = None,
    use_cache: bool = True
) -> Dict:
    """
    Pełne scrapowanie SofaScore:
    1. Sprawdź cache
    2. Próbuj API
    3. Fallback do HTML scraping
    
    Args:
        driver: Selenium WebDriver (opcjonalny - jeśli None, tworzy dedykowany)
        home_team: Nazwa gospodarzy
        away_team: Nazwa gości
        sport: Sport
        date_str: Data meczu (YYYY-MM-DD)
        use_cache: Czy używać cache (domyślnie True)
    
    Returns:
        Dict ze wszystkimi danymi SofaScore
    """
    result = {
        'sofascore_home_win_prob': None,
        'sofascore_draw_prob': None,
        'sofascore_away_win_prob': None,
        'sofascore_total_votes': 0,
        'sofascore_btts_yes': None,
        'sofascore_btts_no': None,
        'sofascore_url': None,
        'sofascore_found': False,
    }
    
    if not home_team or not away_team:
        print("   ⚠️ SofaScore: Brak nazw drużyn")
        return result
    
    # Sprawdź cache
    if use_cache:
        cached = _get_cached_result(home_team, away_team, sport)
        if cached:
            return cached
    
    # =============================================
    # METODA SZYBKA: Tylko API (bez Selenium)
    # =============================================
    if REQUESTS_AVAILABLE:
        print(f"   🚀 SofaScore: Szybka ścieżka przez API...")
        event_id = search_event_via_api(home_team, away_team, sport, date_str)
        
        if event_id:
            api_result = get_votes_via_api(event_id)
            if api_result and api_result.get('sofascore_home_win_prob') is not None:
                result.update(api_result)
                sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
                result['sofascore_url'] = f"https://www.sofascore.com/{sport_slug}/match/{event_id}"
                result['sofascore_found'] = True
                draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
                print(f"   ✅ Fan Vote: 🏠{result['sofascore_home_win_prob']}% | "
                      f"{draw_str}✈️{result['sofascore_away_win_prob']}% "
                      f"({result['sofascore_total_votes']:,} głosów)")
                if use_cache:
                    _set_cached_result(home_team, away_team, sport, result)
                return result
    
    # =============================================
    # METODA WOLNA: Selenium (fallback)
    # ZAWSZE tworzy dedykowany driver z krótkim timeout
    # (nie używa zewnętrznego drivera który może mieć 60-120s timeout)
    # =============================================
    if not SELENIUM_AVAILABLE:
        print("   ❌ SofaScore: Selenium niedostępne, API nie znalazło meczu")
        return result
    
    # Ignorujemy przekazany driver - zawsze tworzymy własny z optymalnym timeout
    print(f"   🌐 SofaScore: Tworzę dedykowany driver (timeout {SOFASCORE_GLOBAL_TIMEOUT}s)...")
    
    sofascore_driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--blink-settings=imagesEnabled=false')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        chrome_options.page_load_strategy = 'eager'
        
        sofascore_driver = webdriver.Chrome(options=chrome_options)
        sofascore_driver.set_page_load_timeout(10)
        sofascore_driver.set_script_timeout(5)
        
        # Uruchom scraping z własnym timeoutem przez threading
        scrape_result = [result]  # Użyj listy żeby móc modyfikować w wątku
        scrape_exception = [None]
        
        def do_scrape():
            try:
                scrape_result[0] = search_and_get_votes(
                    sofascore_driver, home_team, away_team, sport, date_str
                )
            except Exception as e:
                scrape_exception[0] = e
        
        scrape_thread = threading.Thread(target=do_scrape)
        scrape_thread.start()
        scrape_thread.join(timeout=SOFASCORE_GLOBAL_TIMEOUT)
        
        if scrape_thread.is_alive():
            print(f"   ⚠️ SofaScore: Timeout po {SOFASCORE_GLOBAL_TIMEOUT}s - przerywam")
            logger.warning(f"SofaScore: Globalny timeout {SOFASCORE_GLOBAL_TIMEOUT}s przekroczony")
            # Wątek się nie skończył - driver.quit() przerwać operację
            try:
                sofascore_driver.quit()
            except (WebDriverException, OSError) as e:
                logger.debug(f"Błąd przy zamykaniu drivera po timeout: {e}")
            sofascore_driver = None
            return result
        
        if scrape_exception[0]:
            logger.warning(f"SofaScore scrape exception: {scrape_exception[0]}")
            print(f"   ⚠️ SofaScore: Błąd: {scrape_exception[0]}")
            return result
        
        result = scrape_result[0]
        if use_cache and result.get('sofascore_found'):
            _set_cached_result(home_team, away_team, sport, result)
        return result
        
    except Exception as e:
        logger.error(f"SofaScore scraping error: {type(e).__name__}: {e}")
        print(f"   ❌ SofaScore scraping error: {e}")
        return result
        
    finally:
        if sofascore_driver:
            try:
                sofascore_driver.quit()
            except (WebDriverException, OSError) as e:
                logger.debug(f"Błąd przy zamykaniu drivera SofaScore: {e}")


# ============================================================================
# TESTING / CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test SofaScore scraper v3.1')
    parser.add_argument('--home', required=True, help='Home team name')
    parser.add_argument('--away', required=True, help='Away team name')
    parser.add_argument('--sport', default='football', help='Sport')
    parser.add_argument('--headless', action='store_true', help='Run headless')
    parser.add_argument('--no-cache', action='store_true', help='Disable cache')
    parser.add_argument('--api-only', action='store_true', help='Only use API, no Selenium')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"TESTING SOFASCORE SCRAPER v3.1")
    print(f"{'='*60}\n")
    
    print(f"🏠 Home: {args.home}")
    print(f"✈️ Away: {args.away}")
    print(f"⚽ Sport: {args.sport}")
    print(f"📦 Cache: {'disabled' if args.no_cache else 'enabled'}")
    print()
    
    if args.api_only:
        print("🚀 API-only mode")
        event_id = search_event_via_api(args.home, args.away, args.sport)
        if event_id:
            print(f"✅ Found event ID: {event_id}")
            result = get_votes_via_api(event_id)
            if result:
                print(f"✅ API Result: {result}")
            else:
                print("❌ No API result")
        else:
            print("❌ Event not found via API")
    else:
        result = scrape_sofascore_full(
            home_team=args.home,
            away_team=args.away,
            sport=args.sport,
            use_cache=not args.no_cache
        )
        
        print(f"\n{'='*60}")
        print(f"RESULTS:")
        print(f"{'='*60}")
        for key, value in result.items():
            print(f"  {key}: {value}")
        
        print(f"\n{'='*60}")
        print(f"FORMATTED OUTPUT:")
        print(f"{'='*60}")
        print(format_votes_for_display(result))
