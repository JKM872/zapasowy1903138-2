"""
FOREBET-FIRST SCRAPER v1.0
==========================
Nowy flow: Zaczyna od Forebet, potem szuka H2H na Livesport.

FLOW:
1. FOREBET → Pobierz WSZYSTKIE mecze z predykcjami (z Load More)
2. LIVESPORT → Szukaj H2H dla każdego meczu
3. SOFASCORE → Fan Votes
4. FLASHSCORE → Pinnacle Odds
5. FILTR → Tylko mecze z H2H ≥60%

Autor: AI Assistant
Data: 2025-12-06
"""

import os
import sys
import time
import re
import atexit
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher
from bs4 import BeautifulSoup

# Patch for undetected_chromedriver WinError 6 on Windows
# This must be done BEFORE importing undetected_chromedriver
if sys.platform == 'win32':
    import warnings
    # Suppress OSError in threading cleanup
    _original_excepthook = sys.excepthook
    def _patched_excepthook(exc_type, exc_val, exc_tb):
        if exc_type is OSError and 'WinError 6' in str(exc_val):
            pass  # Suppress WinError 6 "Invalid handle"
        else:
            _original_excepthook(exc_type, exc_val, exc_tb)
    sys.excepthook = _patched_excepthook

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

# Cloudflare Bypass
try:
    from cloudflare_bypass import fetch_forebet_with_bypass, CloudflareBypass
    CLOUDFLARE_BYPASS_AVAILABLE = True
except ImportError:
    CLOUDFLARE_BYPASS_AVAILABLE = False

# Existing scrapers
try:
    from sofascore_scraper import search_and_get_sofascore_votes
    SOFASCORE_AVAILABLE = True
except ImportError:
    SOFASCORE_AVAILABLE = False

try:
    from flashscore_odds_scraper import FlashScoreOddsScraper
    FLASHSCORE_AVAILABLE = True
except ImportError:
    FLASHSCORE_AVAILABLE = False


# ============================================================================
# FOREBET MATCH EXTRACTION
# ============================================================================

FOREBET_SPORT_URLS = {
    'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
    'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
    'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
    'handball': 'https://www.forebet.com/en/handball/predictions-today',
    'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
    'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
}


def normalize_team_name(name: str) -> str:
    """Normalizuje nazwę drużyny do porównania"""
    if not name:
        return ""
    name = name.lower().strip()
    
    # Polskie/europejskie znaki
    char_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
        'é': 'e', 'è': 'e', 'á': 'a', 'à': 'a',
        'í': 'i', 'ú': 'u', 'ñ': 'n', 'ç': 'c',
        'š': 's', 'č': 'c', 'ž': 'z', 'ř': 'r',
    }
    for char, replacement in char_map.items():
        name = name.replace(char, replacement)
    
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity_score(name1: str, name2: str) -> float:
    """Oblicza similarity między nazwami drużyn"""
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    if not norm1 or not norm2:
        return 0.0
    return SequenceMatcher(None, norm1, norm2).ratio()


def get_all_forebet_matches(
    sport: str,
    date: str = None,
    max_load_more_clicks: int = 20
) -> List[Dict]:
    """
    Pobiera WSZYSTKIE mecze z Forebet dla danego sportu.
    
    Args:
        sport: Sport (football, basketball, etc.)
        date: Data YYYY-MM-DD (domyślnie dzisiaj)
        max_load_more_clicks: Max kliknięć Load More (zabezpieczenie)
    
    Returns:
        Lista meczów: [{home, away, prediction, probability, ...}, ...]
    """
    sport_lower = sport.lower()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    base_url = FOREBET_SPORT_URLS.get(sport_lower, FOREBET_SPORT_URLS['football'])
    today = datetime.now().strftime('%Y-%m-%d')
    
    if date != today:
        url = f"{base_url}?date={date}"
    else:
        url = base_url
    
    print(f"\n{'='*60}")
    print(f"🔥 FOREBET: Pobieranie wszystkich meczów ({sport})")
    print(f"📅 Data: {date}")
    print(f"🌐 URL: {url}")
    print(f"{'='*60}")
    
    # Metoda 1: FlareSolverr (dla CI/CD)
    html_content = None
    driver = None
    
    if CLOUDFLARE_BYPASS_AVAILABLE:
        print("   🔥 Próbuję FlareSolverr bypass...")
        try:
            html_content = fetch_forebet_with_bypass(url, debug=True, sport=sport_lower)
        except Exception as e:
            print(f"   ⚠️ FlareSolverr error: {e}")
    
    # Metoda 2: Selenium z Load More (dla lokalnie i gdy FlareSolverr nie zadziałał)
    # Use flexible matching - check for any Forebet indicator
    html_has_forebet_content = html_content and (
        'rcnt' in html_content or 
        'homeTeam' in html_content or 
        'forepr' in html_content or
        'tr_0' in html_content
    )
    
    if not html_has_forebet_content:
        if SELENIUM_AVAILABLE:
            print("   🌐 Używam Selenium z Load More...")
            try:
                html_content = _fetch_forebet_with_selenium(url, sport_lower, max_load_more_clicks)
            except Exception as e:
                print(f"   ❌ Selenium error: {e}")
    
    if not html_content:
        print("   ❌ Nie udało się pobrać strony Forebet")
        return []
    
    # Parsuj mecze
    matches = _parse_forebet_matches(html_content, sport_lower)
    print(f"   ✅ Znaleziono {len(matches)} meczów na Forebet")
    
    return matches


def _fetch_forebet_with_selenium(
    url: str,
    sport: str,
    max_clicks: int = 20
) -> Optional[str]:
    """
    Pobiera Forebet z Selenium, klikając Load More aż załadują się wszystkie mecze.
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.page_load_strategy = 'eager'
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(60)
    
    try:
        print(f"   📄 Ładuję stronę...")
        driver.get(url)
        time.sleep(5)
        
        # Klikaj Load More dopóki jest dostępny
        load_more_selectors = [
            'button.load-more',
            'a.load-more',
            '.load-more-button',
            'button[class*="load"]',
            'a[class*="more"]',
            '#loadMore',
            '.loadMoreBtn',
        ]
        
        click_count = 0
        while click_count < max_clicks:
            found_button = False
            
            for selector in load_more_selectors:
                try:
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in buttons:
                        if btn.is_displayed() and btn.is_enabled():
                            print(f"   🔄 Klikam Load More ({click_count + 1})...")
                            driver.execute_script("arguments[0].scrollIntoView();", btn)
                            time.sleep(0.5)
                            btn.click()
                            time.sleep(3)  # Czekaj na załadowanie
                            click_count += 1
                            found_button = True
                            break
                    if found_button:
                        break
                except:
                    continue
            
            if not found_button:
                # Spróbuj scrollowania na dół (lazy loading)
                last_height = driver.execute_script("return document.body.scrollHeight")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                
                if new_height == last_height:
                    print(f"   ✅ Wszystkie mecze załadowane (po {click_count} kliknięciach)")
                    break
        
        return driver.page_source
        
    except Exception as e:
        print(f"   ❌ Selenium error: {e}")
        return None
    finally:
        driver.quit()


def _parse_forebet_matches(html: str, sport: str) -> List[Dict]:
    """
    Parsuje mecze z HTML Forebet.
    """
    soup = BeautifulSoup(html, 'html.parser')
    matches = []
    
    # Znajdź wszystkie wiersze meczów
    match_rows = soup.find_all('div', class_='rcnt')
    if not match_rows:
        match_rows = soup.find_all('tr', class_=['tr_0', 'tr_1'])
    
    print(f"   📋 Parsowanie {len(match_rows)} wierszy...")
    
    for row in match_rows:
        try:
            match_data = _parse_single_match(row, sport)
            if match_data:
                matches.append(match_data)
        except Exception as e:
            continue
    
    return matches


def _parse_single_match(row, sport: str) -> Optional[Dict]:
    """
    Parsuje pojedynczy mecz z wiersza HTML.
    """
    # Wyciągnij nazwy drużyn
    home_span = row.find('span', class_='homeTeam')
    away_span = row.find('span', class_='awayTeam')
    
    if not home_span or not away_span:
        return None
    
    # Szukaj zagnieżdżonego span z itemprop="name"
    home_inner = home_span.find('span', itemprop='name')
    away_inner = away_span.find('span', itemprop='name')
    
    if home_inner and away_inner:
        home_team = home_inner.get_text(strip=True)
        away_team = away_inner.get_text(strip=True)
    else:
        home_team = home_span.get_text(strip=True)
        away_team = away_span.get_text(strip=True)
    
    if not home_team or not away_team:
        return None
    
    # Wyciągnij predykcję (1, X, 2 lub Home, Away dla basketball)
    prediction = None
    probability = None
    
    # Szukaj predykcji w różnych formatach
    # Basketball używa 'forepr', football używa 'fprc'
    pred_spans = row.find_all('span', class_=re.compile(r'(fprc|forepr|foremark|pred)'))
    for span in pred_spans:
        text = span.get_text(strip=True)
        if text in ['1', 'X', '2', '1X', 'X2', '12']:
            prediction = text
            break
        elif text in ['Home', 'Away', 'H', 'A']:
            prediction = '1' if text in ['Home', 'H'] else '2'
            break
    
    # Szukaj prawdopodobieństwa
    # Basketball używa 'fpr', football używa 'fprc'
    prob_spans = row.find_all('span', class_=re.compile(r'(prob|fpr|fprc)'))
    for span in prob_spans:
        text = span.get_text(strip=True).replace('%', '')
        try:
            probability = float(text)
            break
        except:
            continue
    
    # Szukaj Over/Under
    over_under = None
    ou_spans = row.find_all('span', class_=re.compile(r'(ou_|over|under)'))
    for span in ou_spans:
        text = span.get_text(strip=True)
        if 'over' in text.lower() or 'under' in text.lower() or re.match(r'[0-9.]+', text):
            over_under = text
            break
    
    # Szukaj BTTS
    btts = None
    btts_spans = row.find_all('span', class_=re.compile(r'(btts|both)'))
    for span in btts_spans:
        text = span.get_text(strip=True).lower()
        if 'yes' in text:
            btts = 'Yes'
        elif 'no' in text:
            btts = 'No'
    
    return {
        'home_team': home_team,
        'away_team': away_team,
        'prediction': prediction,
        'probability': probability,
        'over_under': over_under,
        'btts': btts,
        'sport': sport,
        'source': 'forebet',
    }


# ============================================================================
# LIVESPORT H2H SEARCH
# ============================================================================

def search_h2h_on_livesport(
    home_team: str,
    away_team: str,
    sport: str,
    driver: webdriver.Chrome = None,
    date: str = None
) -> Optional[Dict]:
    """
    Szuka meczu na Livesport po nazwach drużyn i pobiera H2H.
    
    Args:
        home_team: Nazwa drużyny gospodarzy
        away_team: Nazwa drużyny gości
        sport: Sport (basketball, football, etc.)
        driver: Selenium WebDriver (opcjonalny)
        date: Data meczu YYYY-MM-DD (opcjonalny, domyślnie dziś)
    
    Returns:
        Dict z H2H danymi lub None jeśli nie znaleziono
    """
    # Import livesport scraper
    try:
        from livesport_h2h_scraper import (
            start_driver,
            get_match_links_from_day,
            process_match,
            extract_advanced_team_form,
            parse_h2h_from_soup,
            format_form,
        )
    except ImportError as e:
        print(f"   ⚠️ livesport_h2h_scraper not available: {e}")
        return None
    
    print(f"   🔍 Szukam H2H: {home_team} vs {away_team}...")
    
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    own_driver = False
    try:
        # Utwórz driver jeśli nie podano
        if driver is None:
            driver = start_driver(headless=True)
            own_driver = True
        
        # Pobierz listę meczów z danego dnia
        urls = get_match_links_from_day(driver, date, sports=[sport], leagues=None)
        
        if not urls:
            print(f"   ⚠️ Nie znaleziono meczów {sport} na Livesport dla {date}")
            return None
        
        # Szukaj meczu po nazwach drużyn
        home_norm = normalize_team_name(home_team)
        away_norm = normalize_team_name(away_team)
        
        best_match_url = None
        best_score = 0.0
        
        for url in urls[:50]:  # Ogranicz do pierwszych 50 meczów dla wydajności
            # URL zawiera nazwy drużyn, np. /mecz/team1-team2/
            url_lower = url.lower()
            
            # Sprawdź czy główne słowa z nazw są w URL
            home_words = [w for w in home_norm.split() if len(w) > 3]
            away_words = [w for w in away_norm.split() if len(w) > 3]
            
            home_in_url = sum(1 for w in home_words if w in url_lower)
            away_in_url = sum(1 for w in away_words if w in url_lower)
            
            # Score: ile słów pasuje
            score = home_in_url + away_in_url
            
            if score > best_score and home_in_url > 0 and away_in_url > 0:
                best_score = score
                best_match_url = url
        
        if not best_match_url:
            print(f"   ⚠️ Nie znaleziono meczu {home_team} vs {away_team} na Livesport")
            return None
        
        print(f"   ✅ Znaleziono mecz na Livesport!")
        
        # Pobierz dane H2H dla znalezionego meczu
        match_data = process_match(best_match_url, driver, away_team_focus=False, sport=sport)
        
        # Pobierz zaawansowane dane formy
        advanced_form = {}
        try:
            advanced_form = extract_advanced_team_form(best_match_url, driver)
        except Exception as e:
            print(f"   ⚠️ Nie udało się pobrać zaawansowanej formy: {e}")
        
        # Pobierz H2H historię (mecze bezpośrednie)
        h2h_matches = []
        last_meeting_date = None
        if match_data:
            h2h_matches = match_data.get('h2h_matches', [])
            if h2h_matches and len(h2h_matches) > 0:
                last_meeting_date = h2h_matches[0].get('date')
        
        if match_data:
            h2h_percent = match_data.get('win_rate', 0) * 100
            h2h_count = match_data.get('h2h_count', 0)
            
            result = {
                # H2H stats
                'h2h_wins': match_data.get('home_wins_in_h2h_last5', 0),
                'h2h_total': h2h_count or 5,
                'h2h_percent': h2h_percent,
                'focus_team': home_team,
                
                # Basic form (from process_match)
                'home_form': match_data.get('home_form', []),
                'away_form': match_data.get('away_form', []),
                
                # Advanced form (home at home, away on road)
                'home_form_overall': advanced_form.get('home_form_overall', match_data.get('home_form', [])),
                'home_form_home': advanced_form.get('home_form_home', []),
                'away_form_overall': advanced_form.get('away_form_overall', match_data.get('away_form', [])),
                'away_form_away': advanced_form.get('away_form_away', []),
                'form_advantage': advanced_form.get('form_advantage', False),
                
                # H2H matches with dates
                'h2h_matches': h2h_matches[:5],  # Last 5 meetings
                'last_meeting_date': last_meeting_date,
            }
            
            return result
        else:
            return None
    
    except Exception as e:
        print(f"   ❌ Livesport search error: {e}")
        return None
    
    finally:
        if own_driver and driver:
            try:
                driver.quit()
            except:
                pass


# ============================================================================
# MAIN FLOW
# ============================================================================

def scrape_forebet_first(
    sport: str,
    date: str = None,
    min_h2h_percent: float = 60.0,
    use_sofascore: bool = True,
    use_odds: bool = True,
    headless: bool = True
) -> List[Dict]:
    """
    Główna funkcja - Forebet-first flow.
    
    Args:
        sport: Sport do scrapowania
        date: Data YYYY-MM-DD
        min_h2h_percent: Minimalny % H2H do kwalifikacji
        use_sofascore: Czy pobierać SofaScore FanVote
        use_odds: Czy pobierać kursy Pinnacle
    
    Returns:
        Lista zakwalifikowanych meczów z pełnymi danymi
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"\n{'='*70}")
    print(f"🔥 FOREBET-FIRST SCRAPER v1.0")
    print(f"{'='*70}")
    print(f"📅 Data: {date}")
    print(f"⚽ Sport: {sport}")
    print(f"📊 Min H2H: {min_h2h_percent}%")
    print(f"{'='*70}\n")
    
    # KROK 1: Pobierz wszystkie mecze z Forebet
    forebet_matches = get_all_forebet_matches(sport, date)
    
    if not forebet_matches:
        print("❌ Brak meczów na Forebet")
        return []
    
    print(f"\n📋 Forebet: {len(forebet_matches)} meczów do sprawdzenia")
    
    # KROK 2: Dla każdego meczu pobierz SofaScore i szukaj H2H
    qualified_matches = []
    
    for i, match in enumerate(forebet_matches, 1):
        home = match['home_team']
        away = match['away_team']
        print(f"\n[{i}/{len(forebet_matches)}] {home} vs {away}")
        print(f"   🎯 Forebet: {match.get('prediction', '?')} ({match.get('probability', '?')}%)")
        
        # SofaScore Fan Votes - pobierz dla KAŻDEGO meczu
        if use_sofascore and SOFASCORE_AVAILABLE:
            try:
                sofascore = search_and_get_sofascore_votes(
                    home_team=home,
                    away_team=away,
                    sport=sport
                )
                if sofascore and sofascore.get('home_win_pct'):
                    match['sofascore_home'] = sofascore.get('home_win_pct')
                    match['sofascore_draw'] = sofascore.get('draw_pct')
                    match['sofascore_away'] = sofascore.get('away_win_pct')
                    match['sofascore_votes'] = sofascore.get('total_votes')
                    # Output already printed by search_and_get_sofascore_votes
            except Exception as e:
                print(f"   ⚠️ SofaScore error: {e}")
        
        # Szukaj H2H i pobierz formę
        h2h_data = search_h2h_on_livesport(home, away, sport, date=date)
        
        if h2h_data:
            h2h_percent = h2h_data.get('h2h_percent', 0)
            match['h2h_wins'] = h2h_data.get('h2h_wins', 0)
            match['h2h_total'] = h2h_data.get('h2h_total', 5)
            match['h2h_percent'] = h2h_percent
            match['focus_team'] = h2h_data.get('focus_team')
            
            # Forma ogólna
            match['home_form'] = h2h_data.get('home_form_overall', [])
            match['away_form'] = h2h_data.get('away_form_overall', [])
            
            # Forma u siebie / na wyjeździe
            match['home_form_home'] = h2h_data.get('home_form_home', [])
            match['away_form_away'] = h2h_data.get('away_form_away', [])
            match['form_advantage'] = h2h_data.get('form_advantage', False)
            
            # H2H historia
            match['h2h_matches'] = h2h_data.get('h2h_matches', [])
            match['last_meeting_date'] = h2h_data.get('last_meeting_date')
            
            # Wyświetl formę
            home_form_str = ''.join(match['home_form'][:5]) if match['home_form'] else '?'
            away_form_str = ''.join(match['away_form'][:5]) if match['away_form'] else '?'
            home_home_str = ''.join(match['home_form_home'][:5]) if match['home_form_home'] else '?'
            away_away_str = ''.join(match['away_form_away'][:5]) if match['away_form_away'] else '?'
            
            print(f"   📊 Forma ogólna: {home} [{home_form_str}] vs {away} [{away_form_str}]")
            print(f"   🏠 {home} u siebie: [{home_home_str}] | ✈️ {away} na wyjeździe: [{away_away_str}]")
            
            # Wyświetl H2H historię jeśli jest
            if match['h2h_matches']:
                print(f"   🔄 H2H: ostatnie spotkanie: {match['last_meeting_date'] or '?'}")
            
            if h2h_percent >= min_h2h_percent:
                print(f"   ✅ H2H: {h2h_percent}% - KWALIFIKUJE!")
                
                # Odds
                if use_odds and FLASHSCORE_AVAILABLE:
                    try:
                        odds_scraper = FlashScoreOddsScraper(headless=headless)
                        odds = odds_scraper.get_odds(home, away, sport)
                        match['odds'] = odds
                    except Exception as e:
                        print(f"   ⚠️ Odds error: {e}")
                
                qualified_matches.append(match)
            else:
                print(f"   ❌ H2H: {h2h_percent}% - nie kwalifikuje (< {min_h2h_percent}%)")
        else:
            print(f"   ⚠️ Livesport: Nie znaleziono meczu")
            # Dodaj mecz do wyników nawet bez H2H (jeśli ma dane SofaScore/Forebet)
            if match.get('sofascore_home') or match.get('prediction'):
                match['h2h_percent'] = None  # Brak H2H
                # Nie kwalifikujemy bez H2H, ale dane są dostępne
    
    print(f"\n{'='*70}")
    print(f"✅ WYNIK: {len(qualified_matches)}/{len(forebet_matches)} meczów zakwalifikowanych")
    print(f"{'='*70}\n")
    
    return qualified_matches


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Forebet-First Scraper v1.0')
    parser.add_argument('--sport', default='basketball', help='Sport')
    parser.add_argument('--date', default=None, help='Data YYYY-MM-DD')
    parser.add_argument('--min-h2h', type=float, default=60.0, help='Min H2H %')
    parser.add_argument('--no-sofascore', action='store_true', help='Skip SofaScore')
    parser.add_argument('--no-odds', action='store_true', help='Skip odds')
    
    args = parser.parse_args()
    
    matches = scrape_forebet_first(
        sport=args.sport,
        date=args.date,
        min_h2h_percent=args.min_h2h,
        use_sofascore=not args.no_sofascore,
        use_odds=not args.no_odds
    )
    
    print("\n📋 ZAKWALIFIKOWANE MECZE:")
    for m in matches:
        print(f"  • {m['home_team']} vs {m['away_team']} "
              f"[Forebet: {m.get('prediction')} {m.get('probability')}%] "
              f"[H2H: {m.get('h2h_percent', 0)}%]")
