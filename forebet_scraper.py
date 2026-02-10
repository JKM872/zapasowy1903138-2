"""
Forebet.com Scraper
===================
Pobiera predykcje meczów z Forebet.com:
- Prediction (1/X/2) - kto wygra
- Probability (%) - prawdopodobieństwo wyniku
- Over/Under - przewidywana liczba goli
- BTTS (Both Teams To Score) - czy obie drużyny strzelą

🔥 ULTRA POWER CLOUDFLARE BYPASS 🔥
Używa wielu metod aby ominąć Cloudflare w CI/CD:
1. Puppeteer Extra z Stealth (Node.js) - NAJLEPSZA
2. FlareSolverr (Docker)
3. curl_cffi, cloudscraper, drissionpage, itd.

🚀 OPTYMALIZACJA CI (v2):
- Cache wyników na poziomie procesu (sport, home, away, date)
- Drogie źródła tylko dla kwalifikujących się meczów

Autor: AI Assistant
Data: 2025-11-17
"""

import time
import random
import os
import subprocess
import re
from typing import Dict, Optional, Tuple

# ========================================================================
# CACHE DLA FOREBET - unika wielokrotnego sprawdzania tych samych meczów
# ========================================================================
_forebet_cache: Dict[str, Dict] = {}

# 🔥 CACHE DLA ZNORMALIZOWANYCH NAZW DRUŻYN - unika wielokrotnego normalizowania
_normalized_names_cache: Dict[str, str] = {}

# 🔥 CACHE DLA WYNIKÓW AI (Gemini/Groq) - unika wielokrotnych wywołań API
_ai_match_cache: Dict[str, Optional[tuple]] = {}
_AI_CACHE_TTL = 86400  # 24 godziny - mecze się nie zmieniają

def _get_forebet_cache_key(sport: str, home_team: str, away_team: str, match_date: str) -> str:
    """Generuje klucz cache dla danego meczu."""
    return f"{sport}|{home_team.lower().strip()}|{away_team.lower().strip()}|{match_date}"

def _get_cached_forebet(sport: str, home_team: str, away_team: str, match_date: str) -> Optional[Dict]:
    """Pobiera wynik z cache jeśli istnieje."""
    key = _get_forebet_cache_key(sport, home_team, away_team, match_date)
    return _forebet_cache.get(key)

def _set_cached_forebet(sport: str, home_team: str, away_team: str, match_date: str, result: Dict):
    """Zapisuje wynik do cache."""
    key = _get_forebet_cache_key(sport, home_team, away_team, match_date)
    _forebet_cache[key] = result

def _get_cached_normalized_name(name: str) -> Optional[str]:
    """Pobiera znormalizowaną nazwę z cache."""
    return _normalized_names_cache.get(name)

def _set_cached_normalized_name(name: str, normalized: str):
    """Zapisuje znormalizowaną nazwę do cache."""
    _normalized_names_cache[name] = normalized

def _get_ai_match_cache_key(home_team: str, away_team: str) -> str:
    """Generuje klucz cache dla AI match finding."""
    return f"{home_team.lower().strip()}|{away_team.lower().strip()}"

def _get_cached_ai_match(home_team: str, away_team: str) -> Optional[tuple]:
    """Pobiera wynik AI match finding z cache."""
    key = _get_ai_match_cache_key(home_team, away_team)
    cached = _ai_match_cache.get(key)
    if cached is not None:
        result, timestamp = cached
        if time.time() - timestamp < _AI_CACHE_TTL:
            return result
        # Cache expired
        del _ai_match_cache[key]
    return None

def _set_cached_ai_match(home_team: str, away_team: str, result: Optional[tuple]):
    """Zapisuje wynik AI match finding do cache."""
    key = _get_ai_match_cache_key(home_team, away_team)
    _ai_match_cache[key] = (result, time.time())
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

# 🔥 CACHE HTML PER SPORT - żeby nie pobierać tej samej strony 100 razy!
# Klucz: sport (basketball, volleyball, etc.)
# Wartość: (html_content, soup, timestamp)
_forebet_html_cache = {}
_FOREBET_HTML_CACHE_TTL = 3600  # 1 godzina - mecze dzienne się nie zmieniają


def prefetch_forebet_html(sport: str, match_date: str = None) -> bool:
    """
    🔥 PRE-FETCH: Pobiera HTML dla sportu i zapisuje do cache.
    Wywołaj RAZ na początku przed przetwarzaniem meczów!
    
    Args:
        sport: Sport do pobrania (basketball, volleyball, football, etc.)
        match_date: Data meczu (YYYY-MM-DD), domyślnie dzisiaj
    
    Returns:
        True jeśli sukces, False jeśli nie udało się pobrać
    """
    from datetime import datetime
    
    sport_lower = sport.lower()
    if match_date is None:
        match_date = datetime.now().strftime('%Y-%m-%d')
    
    sport_cache_key = f"{sport_lower}_{match_date}"
    
    # Sprawdź czy już w cache
    if sport_cache_key in _forebet_html_cache:
        cached_html, _, cache_time = _forebet_html_cache[sport_cache_key]
        cache_age = time.time() - cache_time
        if cache_age < _FOREBET_HTML_CACHE_TTL:
            print(f"   📋 Forebet {sport}: Już w cache ({len(cached_html)} znaków, {cache_age:.0f}s)")
            return True
    
    print(f"   🔥 Forebet {sport}: Prefetch HTML...")
    
    sport_urls = {
        'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
        'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
        'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
        'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
        'handball': 'https://www.forebet.com/en/handball/predictions-today',
        'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
        'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
        'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
        'rugby': 'https://www.forebet.com/en/rugby/predictions-today',
        'baseball': 'https://www.forebet.com/en/baseball/predictions-today',
    }
    
    base_url = sport_urls.get(sport_lower, sport_urls['football'])
    today = datetime.now().strftime('%Y-%m-%d')
    
    if match_date and match_date != today:
        url = f"{base_url}?date={match_date}"
    else:
        url = base_url
    
    # Keywords do weryfikacji sportu
    sport_check_keywords = {
        'basketball': ['basketball', 'nba', 'euroleague', 'fiba'],
        'volleyball': ['volleyball', 'volley'],
        'handball': ['handball'],
        'hockey': ['hockey', 'nhl', 'khl'],
        'tennis': ['tennis', 'atp', 'wta'],
        'football': ['football', 'soccer', 'liga', 'premier league', 'serie a'],
        'soccer': ['football', 'soccer', 'liga', 'premier league', 'serie a'],
    }
    keywords = sport_check_keywords.get(sport_lower, ['predictions'])
    
    # Retry loop - w CI mniej prób dla szybkości
    max_retries = 2 if IS_CI_CD else 3
    for attempt in range(max_retries):
        try:
            fetch_url = url
            if attempt > 0:
                cache_buster = int(time.time())
                fetch_url = f"{url}{'&' if '?' in url else '?'}_cb={cache_buster}"
                print(f"   🔄 Retry {attempt + 1}/{max_retries}...")
                time.sleep(1.5 if IS_CI_CD else 3)
            
            if CLOUDFLARE_BYPASS_AVAILABLE:
                html_content = fetch_forebet_with_bypass(fetch_url, debug=False, sport=sport_lower)
            else:
                print(f"   ⚠️ Cloudflare Bypass niedostępny")
                return False
            
            if html_content:
                is_forebet = (
                    'class="rcnt"' in html_content or
                    'class="tr_0"' in html_content
                )
                html_lower = html_content.lower()
                sport_matches = any(kw in html_lower for kw in keywords)
                
                if is_forebet and sport_matches:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    _forebet_html_cache[sport_cache_key] = (html_content, soup, time.time())
                    print(f"   ✅ Forebet {sport}: Prefetch SUCCESS! ({len(html_content)} znaków)")
                    return True
                elif is_forebet and not sport_matches:
                    print(f"   ⚠️ Forebet {sport}: HTML nie pasuje do sportu, retry...")
                    continue
        except Exception as e:
            print(f"   ⚠️ Prefetch error: {e}")
    
    print(f"   ❌ Forebet {sport}: Prefetch FAILED po {max_retries} próbach")
    return False


def prefetch_all_sports(sports: list, match_date: str = None) -> dict:
    """
    🔥 PRE-FETCH ALL: Pobiera HTML dla wszystkich sportów na początku.
    
    Args:
        sports: Lista sportów ['basketball', 'volleyball', 'football']
        match_date: Data meczu
    
    Returns:
        Dict {sport: success} np. {'basketball': True, 'volleyball': False}
    """
    print(f"\n{'='*60}")
    print(f"🔥 FOREBET PREFETCH - Ładuję HTML dla {len(sports)} sportów")
    print(f"{'='*60}")
    
    results = {}
    for sport in sports:
        results[sport] = prefetch_forebet_html(sport, match_date)
    
    success_count = sum(results.values())
    print(f"\n✅ Prefetch zakończony: {success_count}/{len(sports)} sportów")
    print(f"{'='*60}\n")
    
    return results

# 🔥 PUPPETEER STEALTH - najlepsza metoda dla CI/CD
def fetch_forebet_with_puppeteer(sport: str) -> Optional[str]:
    """
    Pobierz Forebet używając Puppeteer Extra z Stealth (Node.js).
    To jest najskuteczniejsza metoda dla GitHub Actions!
    """
    output_file = f'forebet_{sport.lower()}_puppeteer.html'
    
    try:
        print(f"      🚀 Puppeteer Stealth: Uruchamiam dla {sport}...")
        
        # Sprawdź czy Node.js i npm są dostępne
        result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print("      ⚠️ Node.js nie jest dostępny")
            return None
        
        # Sprawdź czy dependencies są zainstalowane
        if not os.path.exists('node_modules/puppeteer-extra'):
            print("      📦 Instaluję puppeteer-extra...")
            subprocess.run(['npm', 'install'], capture_output=True, timeout=120)
        
        # Uruchom Puppeteer scraper
        result = subprocess.run(
            ['node', 'forebet_puppeteer.js', sport.lower(), output_file],
            capture_output=True,
            text=True,
            timeout=180  # 3 minuty timeout
        )
        
        # Pokaż output
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                print(f"      {line}")
        if result.stderr:
            for line in result.stderr.strip().split('\n')[:5]:
                print(f"      ⚠️ {line}")
        
        # Sprawdź czy plik został utworzony
        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                html = f.read()
            
            # Weryfikacja
            if 'rcnt' in html or 'tr_0' in html or 'forepr' in html:
                print(f"      ✅ Puppeteer SUCCESS! ({len(html)} znaków)")
                return html
            else:
                print(f"      ⚠️ Puppeteer: HTML nie zawiera meczów Forebet")
                return html  # Zwróć mimo wszystko do analizy
        else:
            print(f"      ❌ Puppeteer: Plik {output_file} nie został utworzony")
            return None
            
    except subprocess.TimeoutExpired:
        print("      ⚠️ Puppeteer: Timeout (3 minuty)")
        return None
    except FileNotFoundError:
        print("      ⚠️ Puppeteer: Node.js nie znaleziony")
        return None
    except Exception as e:
        print(f"      ❌ Puppeteer error: {e}")
        return None

def normalize_team_name(name: str) -> str:
    """
    Normalizuje nazwę drużyny do porównania.
    Usuwa prefixy, sufixy, rozwiązuje skróty, lowercase, trim.
    Używa cache dla wydajności.
    """
    if not name:
        return ""
    
    # 🔥 Sprawdź cache
    cached = _get_cached_normalized_name(name)
    if cached is not None:
        return cached
    
    # Lowercase i trim
    normalized = name.lower().strip()
    
    # 🔥 POLSKIE ZNAKI → ASCII (KRYTYCZNE dla polskich drużyn!)
    polish_chars = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
        # Inne popularne znaki diakrytyczne
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',  # Niemieckie
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',   # Francuskie
        'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ú': 'u', 'ù': 'u', 'û': 'u',
        'ñ': 'n', 'ç': 'c', 'š': 's', 'č': 'c', 'ž': 'z',  # Hiszpańskie/Czeskie
        'ř': 'r', 'ď': 'd', 'ť': 't', 'ň': 'n',  # Czeskie
        'ő': 'o', 'ű': 'u',  # Węgierskie
    }
    for char, replacement in polish_chars.items():
        normalized = normalized.replace(char, replacement)
    
    # 🔥 Usuń prefixy (ROZSZERZONE v2 - luty 2026!)
    prefixes_to_remove = [
        # Uniwersalne
        'fc ', 'afc ', 'cf ', 'club ', 'sporting ', 'real ', 'royal ',
        'sc ', 'sv ', 'vfb ', 'tsv ', 'fk ', 'nk ', 'sk ', 'hk ',
        'ac ', 'as ', 'ss ', 'us ', 'cd ', 'ud ', 'rcd ', 'rc ',
        # Polskie kluby
        'ks ', 'mks ', 'gks ', 'rks ', 'wks ', 'lks ', 'zks ', 'oks ', 'sts ',
        'azs ', 'awf ', 'mrks ', 'mkts ', 'mlks ', 'mzks ', 'tks ', 'luks ',
        # Skandynawskie/Niemieckie
        'bk ', 'if ', 'aik ', 'ik ', 'bsc ', 'vfl ', 'tsg ', 'tb ', 'sg ',
        'spvgg ', 'fsv ', 'ssv ', 'usv ', 'ksc ', 'sfb ', 'eintracht ',
        # Hiszpańskie/Portugalskie/Austriackie
        'ca ', 'ce ', 'sd ', 'rb ', 'red bull ', 'sl ', 'sporting ',
        'atletico ', 'deportivo ', 'racing ', 'cultural ', 'gimnastic ',
        # Izraelskie
        'hapoel ', 'maccabi ', 'beitar ', 'ironi ', 'bnei ',
        # Rosyjskie/Wschodnioeuropejskie
        'dinamo ', 'dynamo ', 'lokomotiv ', 'spartak ', 'cska ', 'ska ',
        'zenit ', 'torpedo ', 'metalist ', 'shakhtar ', 'karpaty ',
        # Austriackie
        'rapid ', 'austria ', 'admira ', 'wolfsberger ', 'lask ', 'wac ',
        # Holenderskie
        'ajax ', 'psv ', 'az ', 'nec ', 'ado ', 'pec ', 'roda ', 'mvv ',
        # Francuskie
        'olympique ', 'stade ', 'ogc ', 'girondins ', 'losc ',
        # Włoskie
        'inter ', 'juventus ', 'roma ', 'lazio ', 'napoli ', 'atalanta ',
        'torino ', 'fiorentina ', 'sampdoria ', 'genoa ', 'hellas ',
        # Tureckie
        'galatasaray ', 'fenerbahce ', 'besiktas ', 'trabzonspor ',
        # Greckie
        'olympiacos ', 'panathinaikos ', 'aek ', 'paok ', 'aris ',
        # Siatkówka/Koszykówka
        'skra ', 'resovia ', 'czarni ', 'trefl ', 'indykpol ', 'cuprum ',
        'asseco ', 'cerrad ', 'projekt ', 'stal ', 'jastrzebski ',
    ]
    for prefix in prefixes_to_remove:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    
    # Usuń sufixy (ROZSZERZONE v2!)
    suffixes_to_remove = [
        # Uniwersalne
        ' fc', ' afc', ' cf', ' united', ' city', ' town', ' club',
        ' wanderers', ' rovers', ' athletic', ' sports', ' sportif',
        # Płeć/kategorie wiekowe
        ' k', ' w', ' kobiety', ' kobiet', ' women', ' womens', ' ladies', ' female',
        ' m', ' men', ' mezczyzni', ' male',
        ' u21', ' u20', ' u19', ' u18', ' u17', ' u16', ' u15', ' u23', ' u25',
        ' b', ' ii', ' iii', ' iv', ' 2', ' 3',
        ' reserves', ' youth', ' juniors', ' academy', ' b team', ' res',
        # Skróty organizacyjne
        ' sc', ' sv', ' fk', ' nk', ' sk', ' kv', ' bk', ' hk',
        ' sa', ' ssa', ' srl', ' spa', ' ssd', ' ag', ' gmbh',
        # Lata założenia
        ' 1900', ' 1901', ' 1902', ' 1903', ' 1904', ' 1905', ' 1906', ' 1907', ' 1908', ' 1909',
        ' 1910', ' 1911', ' 1912', ' 1913', ' 1914', ' 1915', ' 1916', ' 1917', ' 1918', ' 1919',
        ' 1893', ' 1894', ' 1895', ' 1896', ' 1897', ' 1898', ' 1899', ' 1860', ' 1889',
        ' 04', ' 05', ' 06', ' 07', ' 08', ' 09',
        # Włoskie/Hiszpańskie
        ' calcio', ' futbol', ' football', ' futebol', ' voetbal',
        # Miasta w nazwach (czasem sufiks)
        ' moscow', ' minsk', ' kyiv', ' kiev', ' st petersburg',
        # Angielskie
        ' hotspur', ' albion', ' county', ' argyle', ' borough', ' dons', ' vale',
        # Polskie
        ' rzeszow', ' bielsko biala', ' warszawa', ' krakow', ' wroclaw',
        ' poznan', ' gdansk', ' lodz', ' szczecin', ' lublin', ' katowice',
    ]
    for suffix in suffixes_to_remove:
        if normalized.endswith(suffix):
            normalized = normalized[:-len(suffix)].strip()
    
    # 🔥 Rozwiń popularne skróty (ROZSZERZONE v2!)
    abbreviations = {
        # Angielskie
        'st.': 'saint', 'st ': 'saint ', 'st-': 'saint-',
        'man ': 'manchester ', 'man.': 'manchester',
        'utd': 'united', 'utd.': 'united',
        'ath ': 'athletic ', 'ath.': 'athletic',
        'int ': 'inter ', 'int.': 'inter',
        'liv ': 'liverpool ', 'ars ': 'arsenal ',
        'che ': 'chelsea ', 'tot ': 'tottenham ',
        # Wschodnioeuropejskie
        'dynamo': 'dinamo',  # Wariant transliteracji
        'kyiv': 'kiev',  # Wariant pisowni
        # Niemieckie
        'munchen': 'munich', 'koln': 'cologne',
        'dusseldorf': 'duesseldorf', 'nurnberg': 'nuernberg',
        # Polskie
        'ziel ': 'zielona ', 'ziel.': 'zielona',
        'b-b': 'bielsko biala', 'b.b.': 'bielsko biala',
        'wwa': 'warszawa', 'krk': 'krakow', 'wroc': 'wroclaw',
        # Siatkówka
        'bb ': 'bielsko biala ', 'bb': 'bielsko biala',
    }
    for abbr, full in abbreviations.items():
        normalized = normalized.replace(abbr, full)
    
    # Usuń znaki specjalne (zostaw tylko litery, cyfry i spacje)
    normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
    
    # Usuń podwójne spacje
    while '  ' in normalized:
        normalized = normalized.replace('  ', ' ')
    
    result = normalized.strip()
    
    # 🔥 Zapisz do cache
    _set_cached_normalized_name(name, result)
    
    return result


def similarity_score(name1: str, name2: str) -> float:
    """
    Oblicza similarity score między dwoma nazwami drużyn (0.0 - 1.0).
    Używa wielu metod dla lepszego dopasowania (v2 - luty 2026).
    """
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    
    if not norm1 or not norm2:
        return 0.0
    
    # Dokładne dopasowanie po normalizacji
    if norm1 == norm2:
        return 1.0
    
    # Metoda 1: SequenceMatcher (character-based)
    seq_score = SequenceMatcher(None, norm1, norm2).ratio()
    
    # Metoda 2: Token-based Jaccard similarity (word-based)
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    if tokens1 and tokens2:
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        jaccard = intersection / union if union > 0 else 0.0
    else:
        jaccard = 0.0
    
    # Metoda 3: Sprawdź czy jedna nazwa zawiera drugą (dla krótkich nazw)
    containment = 0.0
    if len(norm1) >= 3 and len(norm2) >= 3:
        if norm1 in norm2 or norm2 in norm1:
            # Zwiększ score w zależności od długości dopasowania
            shorter = min(len(norm1), len(norm2))
            longer = max(len(norm1), len(norm2))
            containment = 0.85 + (shorter / longer) * 0.10  # 0.85 - 0.95
    
    # 🔥 Metoda 4: First-word matching (dla nazw miast vs pełnych nazw klubów)
    first_word_score = 0.0
    words1 = norm1.split()
    words2 = norm2.split()
    if words1 and words2:
        # Sprawdź czy pierwsze słowo jednej nazwy jest w drugiej
        if words1[0] in words2 or words2[0] in words1:
            first_word_score = 0.75
        # Sprawdź też ostatnie słowo
        if words1[-1] in words2 or words2[-1] in words1:
            first_word_score = max(first_word_score, 0.75)
        # Jeśli pierwsze słowa są identyczne - jeszcze wyższy score
        if words1[0] == words2[0]:
            first_word_score = max(first_word_score, 0.80)
    
    # 🔥 Metoda 5: Levenshtein-like dla krótkich nazw (bez biblioteki)
    # Sprawdź czy nazwy różnią się tylko o 1-2 znaki
    levenshtein_score = 0.0
    if abs(len(norm1) - len(norm2)) <= 2:
        # Prosta heurystyka: policz wspólne znaki
        common_chars = sum(1 for c in norm1 if c in norm2)
        max_len = max(len(norm1), len(norm2))
        if max_len > 0:
            char_ratio = common_chars / max_len
            if char_ratio >= 0.8:  # 80% wspólnych znaków
                levenshtein_score = char_ratio * 0.9  # Do 0.72
    
    # 🔥 Metoda 6: Dopasowanie "głównego słowa" (najdłuższego słowa)
    main_word_score = 0.0
    if words1 and words2:
        # Znajdź najdłuższe słowo w każdej nazwie (często to nazwa miasta/klubu)
        main1 = max(words1, key=len) if words1 else ''
        main2 = max(words2, key=len) if words2 else ''
        if main1 and main2 and len(main1) >= 3 and len(main2) >= 3:
            if main1 == main2:
                main_word_score = 0.85
            elif main1 in main2 or main2 in main1:
                main_word_score = 0.70
            elif SequenceMatcher(None, main1, main2).ratio() >= 0.8:
                main_word_score = 0.65
    
    # 🔥 Metoda 7: Prefix matching (dla nazw zaczynających się tak samo)
    prefix_score = 0.0
    min_len = min(len(norm1), len(norm2))
    if min_len >= 4:
        # Sprawdź wspólny prefix
        common_prefix = 0
        for i in range(min_len):
            if norm1[i] == norm2[i]:
                common_prefix += 1
            else:
                break
        if common_prefix >= 4:  # Minimum 4 wspólne znaki na początku
            prefix_score = 0.50 + (common_prefix / min_len) * 0.35  # 0.50 - 0.85
    
    # Zwróć najwyższy wynik ze wszystkich metod
    return max(seq_score, jaccard, containment, first_word_score, 
               levenshtein_score, main_word_score, prefix_score)


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


def _call_groq_api(prompt: str) -> Optional[str]:
    """
    🚀 Groq API - ultra-szybki fallback dla Gemini.
    Używa llama-3.3-70b-versatile.
    """
    import os
    import requests
    
    # Try config file first, then environment variable
    api_key = None
    try:
        from groq_config import GROQ_API_KEY, GROQ_ENABLED
        if GROQ_ENABLED:
            api_key = GROQ_API_KEY
    except ImportError:
        pass
    
    if not api_key:
        api_key = os.environ.get('GROQ_API_KEY')
    
    if not api_key:
        print(f"      [!] Groq: Brak GROQ_API_KEY (ustaw w groq_config.py lub zmiennej srodowiskowej)")
        return None
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.3-70b-versatile',  # Najlepszy model Groq dla matchingu
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.1,
                'max_tokens': 200
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            answer = data['choices'][0]['message']['content'].strip()
            print(f"      [GROQ] Odpowiedz: '{answer[:60]}...' " if len(answer) > 60 else f"      [GROQ] Odpowiedz: '{answer}'")
            return answer
        else:
            print(f"      ⚠️ Groq API error: {response.status_code} - {response.text[:100]}")
            return None
            
    except Exception as e:
        print(f"      ⚠️ Groq API error: {e}")
        return None


# 🔥 RATE LIMITING dla AI API - unika 429 errors
_last_ai_call_time = 0.0
_AI_MIN_INTERVAL = 2.0  # Minimum 2 sekundy między wywołaniami AI

# 🔥 BATCH PROCESSING - kolejka meczów do analizy AI
_ai_batch_queue: list = []  # Lista (home_team, away_team) do analizy
_ai_batch_available_matches: list = []  # Lista dostępnych meczów z Forebet
_AI_BATCH_SIZE = 5  # Analizuj 5 meczów naraz


def find_forebet_matches_batch_ai(matches_to_find: list, available_matches: list) -> Dict[str, Optional[tuple]]:
    """
    🤖 BATCH: Używa AI do znalezienia WIELU meczów naraz (oszczędza wywołania API).
    
    Args:
        matches_to_find: Lista [(home_team, away_team), ...] do znalezienia
        available_matches: Lista dostępnych meczów jako stringi 'Home vs Away'
        
    Returns:
        Dict { "home|away": (matching_home, matching_away) lub None }
    """
    import os
    import time as time_module
    global _last_ai_call_time
    
    if not matches_to_find or not available_matches:
        return {}
    
    results = {}
    
    # Sprawdź cache dla wszystkich meczów
    uncached_matches = []
    for home, away in matches_to_find:
        cached = _get_cached_ai_match(home, away)
        if cached is not None:
            key = f"{home.lower().strip()}|{away.lower().strip()}"
            results[key] = cached
            print(f"      📋 AI Batch (cache): {home} vs {away}")
        else:
            uncached_matches.append((home, away))
    
    if not uncached_matches:
        return results
    
    # Rate limiting
    time_since_last = time_module.time() - _last_ai_call_time
    if time_since_last < _AI_MIN_INTERVAL:
        wait_time = _AI_MIN_INTERVAL - time_since_last
        print(f"      ⏳ AI Batch Rate limit: czekam {wait_time:.1f}s...")
        time_module.sleep(wait_time)
    
    # Buduj prompt dla wielu meczów naraz
    matches_text = '\n'.join(available_matches[:50])
    
    matches_to_find_text = '\n'.join([f"- {h} vs {a}" for h, a in uncached_matches])
    
    prompt = f"""Find the best matching matches for these teams from the list below.

TEAMS TO FIND:
{matches_to_find_text}

AVAILABLE MATCHES:
{matches_text}

For each team pair, return the best matching line from AVAILABLE MATCHES.
If no match found for a pair, return "NONE" for that pair.

Return format (one line per team pair, in order):
1. <matching line or NONE>
2. <matching line or NONE>
...

Do not add any explanation or additional text."""

    _last_ai_call_time = time_module.time()
    
    # Próbuj Groq (szybszy i tańszy)
    answer = _call_groq_api(prompt)
    
    # Fallback do Gemini jeśli Groq nie zadziałał
    if not answer:
        gemini_key = os.environ.get('GEMINI_API_KEY')
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                model = genai.GenerativeModel('gemini-2.0-flash-exp')
                response = model.generate_content(prompt)
                answer = response.text.strip()
            except Exception as e:
                print(f"      ⚠️ AI Batch Gemini error: {e}")
    
    # Parsuj odpowiedź
    if answer:
        lines = answer.strip().split('\n')
        for i, (home, away) in enumerate(uncached_matches):
            key = f"{home.lower().strip()}|{away.lower().strip()}"
            
            if i < len(lines):
                line = lines[i].strip()
                # Usuń numerację jeśli jest (np. "1. ")
                if line and line[0].isdigit() and '. ' in line:
                    line = line.split('. ', 1)[1]
                
                if line and line.upper() != 'NONE' and 'vs' in line.lower():
                    parts = None
                    for sep in [' vs ', ' VS ', ' Vs ', ' - ']:
                        if sep in line:
                            parts = line.split(sep)
                            break
                    
                    if parts and len(parts) == 2:
                        result = (parts[0].strip(), parts[1].strip())
                        results[key] = result
                        _set_cached_ai_match(home, away, result)
                        print(f"      ✅ AI Batch: {home} vs {away} → {result[0]} vs {result[1]}")
                        continue
            
            # Nie znaleziono
            results[key] = None
            _set_cached_ai_match(home, away, None)
            print(f"      ⚠️ AI Batch: {home} vs {away} → nie znaleziono")
    
    return results


def find_forebet_match_with_gemini(home_team: str, away_team: str, available_matches: list) -> Optional[tuple]:
    """
    🤖 Używa Gemini AI (+ Groq fallback) do znalezienia meczu na Forebet gdy similarity matching zawodzi.
    Używa cache i rate limiting dla optymalizacji (v2 - luty 2026).
    
    Args:
        home_team: Szukana drużyna gospodarzy
        away_team: Szukana drużyna gości
        available_matches: Lista dostępnych meczów jako stringi 'Home vs Away'
        
    Returns:
        (matching_home, matching_away) lub None jeśli nie znaleziono
    """
    global _last_ai_call_time
    import os
    import time as time_module
    
    # 🔥 Sprawdź cache przed wywołaniem AI
    cached_result = _get_cached_ai_match(home_team, away_team)
    if cached_result is not None:
        print(f"      📋 AI Match (cache hit): {cached_result}")
        return cached_result
    
    # 🔥 Rate limiting - czekaj jeśli zbyt szybko
    time_since_last = time_module.time() - _last_ai_call_time
    if time_since_last < _AI_MIN_INTERVAL:
        wait_time = _AI_MIN_INTERVAL - time_since_last
        print(f"      ⏳ AI Rate limit: czekam {wait_time:.1f}s...")
        time_module.sleep(wait_time)
    
    # Ograniczenie listy meczów do 50 dla mniejszego zużycia tokenów
    matches_text = '\n'.join(available_matches[:50])
    
    prompt = f"""Find the best matching match for teams "{home_team}" vs "{away_team}" from this list:

{matches_text}

The match may have:
- Different name format (e.g., "Bjerringbro/Silkeborg" = "Bjerringbro" or "BSV")
- Different language (e.g., "Niemcy K" = "Germany W" or "Germany Women")
- City vs Club name (e.g., "Jerusalem" = "Hapoel Jerusalem")
- Abbreviations (e.g., "FC" instead of "Football Club")
- Minor spelling differences
- Partial name matches (e.g., "Hamburg" = "Hamburg Towers")

Return ONLY the matching line from the list, exactly as written.
If no match found, return "NONE".
Do not add any explanation or additional text."""

    answer = None
    use_groq_fallback = False
    
    # 🔥 METODA 1: Gemini (główna)
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-2.0-flash-exp')  # Najnowszy model Gemini
            
            # Retry logic for rate limiting
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(prompt)
                    answer = response.text.strip()
                    print(f"      🤖 Gemini odpowiedź: '{answer[:60]}...' " if len(answer) > 60 else f"      🤖 Gemini odpowiedź: '{answer}'")
                    break
                except Exception as e:
                    error_str = str(e)
                    if '429' in error_str:
                        if attempt < max_retries - 1:
                            wait_time = 30 * (attempt + 1)
                            print(f"      ⏳ Gemini rate limit - czekam {wait_time}s...")
                            time_module.sleep(wait_time)
                            continue
                        else:
                            print(f"      ⚠️ Gemini rate limit - przełączam na Groq...")
                            use_groq_fallback = True
                            break
                    raise
                    
        except Exception as e:
            print(f"      ⚠️ Gemini error: {e} - próbuję Groq...")
            use_groq_fallback = True
    else:
        print(f"      ⚠️ Brak GEMINI_API_KEY - próbuję Groq...")
        use_groq_fallback = True
    
    # 🚀 METODA 2: Groq (fallback)
    if use_groq_fallback or not answer:
        groq_answer = _call_groq_api(prompt)
        if groq_answer:
            answer = groq_answer
    
    # 🔥 Aktualizuj czas ostatniego wywołania AI
    _last_ai_call_time = time_module.time()
    
    # Parsuj odpowiedź
    if answer and answer.upper() != 'NONE' and 'vs' in answer.lower():
        parts = None
        for separator in [' vs ', ' VS ', ' Vs ', ' - ']:
            if separator in answer:
                parts = answer.split(separator)
                break
        
        if parts and len(parts) == 2:
            match_home = parts[0].strip()
            match_away = parts[1].strip()
            result = (match_home, match_away)
            print(f"      ✅ AI Match: Znaleziono mecz: {match_home} vs {match_away}")
            # 🔥 Zapisz do cache
            _set_cached_ai_match(home_team, away_team, result)
            return result
    
    if answer:
        print(f"      ⚠️ AI: Nie znaleziono dopasowania (odpowiedź: {answer[:50]})")
    else:
        print(f"      ⚠️ AI: Brak odpowiedzi od Gemini i Groq")
    
    # 🔥 Zapisz negatywny wynik do cache (żeby nie pytać ponownie)
    _set_cached_ai_match(home_team, away_team, None)
    return None


def search_forebet_prediction(
    home_team: str,
    away_team: str,
    match_date: str,
    driver: webdriver.Chrome = None,
    min_similarity: float = 0.35,  # 🔥 Zmniejszone z 0.45 do 0.35 dla jeszcze lepszego znajdywania meczów
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
    
    # Sprawdź cache (z kluczem sport/home/away/date)
    cached = _get_cached_forebet(sport, home_team, away_team, match_date)
    if cached:
        print(f"      📋 Forebet (cache hit): {cached.get('prediction', 'N/A')}")
        if xvfb_display:
            xvfb_display.stop()
        return cached
    
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
    soup = None
    
    # 🔥 CACHE HTML PER SPORT + DATA - najważniejsza optymalizacja!
    sport_lower = sport.lower()
    # WAŻNE: Cache per data + sport, bo Forebet pokazuje mecze tylko dla konkretnej daty!
    sport_cache_key = f"{sport_lower}_{match_date}"
    
    if sport_cache_key in _forebet_html_cache:
        cached_html, cached_soup, cache_time = _forebet_html_cache[sport_cache_key]
        cache_age = time.time() - cache_time
        
        if cache_age < _FOREBET_HTML_CACHE_TTL:
            print(f"      📋 HTML CACHE HIT! ({sport}, {len(cached_html)} znaków, {cache_age:.0f}s stary)")
            html_content = cached_html
            soup = cached_soup
        else:
            print(f"      ⏰ HTML cache expired ({cache_age:.0f}s > {_FOREBET_HTML_CACHE_TTL}s)")
            del _forebet_html_cache[sport_cache_key]
    
    # 🔥 Pobierz HTML tylko jeśli nie ma w cache
    if html_content is None:
        # W CI/CD - od razu FlareSolverr (Puppeteer nie działa)
        if IS_CI_CD and CLOUDFLARE_BYPASS_AVAILABLE:
            print(f"      🔥 CI/CD: Używam FlareSolverr (skip Puppeteer - nie działa)")
            
            # 🔥 WAŻNE: Używamy URL z datą meczu!
            # Forebet wymaga konkretnej daty w URL żeby pokazać mecze z tej daty
            # Format: ?date=YYYY-MM-DD na końcu URL
            sport_urls = {
                'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
                'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
                'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
                'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
                'handball': 'https://www.forebet.com/en/handball/predictions-today',
                'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
                'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
                'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
                'rugby': 'https://www.forebet.com/en/rugby/predictions-today',
                'baseball': 'https://www.forebet.com/en/baseball/predictions-today',
            }
            
            base_url = sport_urls.get(sport_lower, sport_urls['football'])
            
            # Dodaj datę do URL - Forebet filtruje mecze po dacie!
            # Dla "dzisiaj" nie trzeba dodawać, ale dla innych dat tak
            from datetime import datetime, timedelta
            today = datetime.now().strftime('%Y-%m-%d')
            
            if match_date and match_date != today:
                url = f"{base_url}?date={match_date}"
                print(f"      📅 Forebet dla daty: {match_date} (nie dzisiaj)")
            else:
                url = base_url
                print(f"      📅 Forebet dla dzisiaj: {today}")
            
            print(f"      🌐 Forebet ({sport}): {url}")
            
            # 🔥 WERYFIKACJA SPORTU - keywords
            sport_check_keywords = {
                'basketball': ['basketball', 'nba', 'euroleague', 'fiba'],
                'volleyball': ['volleyball', 'volley'],
                'handball': ['handball'],
                'hockey': ['hockey', 'nhl', 'khl'],
                'tennis': ['tennis', 'atp', 'wta'],
                'football': ['football', 'soccer', 'liga', 'premier league', 'serie a'],
                'soccer': ['football', 'soccer', 'liga', 'premier league', 'serie a'],
            }
            keywords = sport_check_keywords.get(sport_lower, ['predictions'])
            
            # 🔥 RETRY LOOP - 2 próby z różnymi sesjami FlareSolverr
            max_retries = 2
            for retry_attempt in range(max_retries):
                try:
                    # 🔥 Przy kolejnej próbie - dodaj timestamp do URL żeby ominąć cache
                    fetch_url = url
                    if retry_attempt > 0:
                        cache_buster = int(time.time())
                        fetch_url = f"{url}{'&' if '?' in url else '?'}_cb={cache_buster}"
                        print(f"      🔄 Retry {retry_attempt + 1}/{max_retries} z cache buster: {fetch_url}")
                    
                    html_content = fetch_forebet_with_bypass(fetch_url, debug=True, sport=sport_lower)
                    
                    if html_content:
                        # 🔥 WERYFIKACJA: Sprawdź czy to prawdziwa strona Forebet!
                        is_cloudflare = (
                            'loading-verifying' in html_content or
                            'lds-ring' in html_content or
                            'checking your browser' in html_content.lower() or
                            'verifying you are human' in html_content.lower()
                        )
                        
                        is_forebet = (
                            'class="rcnt"' in html_content or
                            'class="forepr"' in html_content or
                            'class="tr_0"' in html_content or
                            'class="tr_1"' in html_content
                        )
                        
                        html_lower = html_content.lower()
                        sport_matches = any(kw in html_lower for kw in keywords)
                        
                        if is_cloudflare and not is_forebet:
                            print(f"      ⚠️ Cloudflare Bypass zwrócił stronę challenge!")
                            html_content = None
                        elif is_forebet and sport_matches:
                            print(f"      🔥 Cloudflare Bypass SUCCESS! ({len(html_content)} znaków)")
                            print(f"      ✅ Potwierdzona strona Forebet dla {sport}!")
                            soup = BeautifulSoup(html_content, 'html.parser')
                            # 🔥 Zapisz do cache!
                            _forebet_html_cache[sport_cache_key] = (html_content, soup, time.time())
                            print(f"      💾 HTML zapisany do cache dla {sport}")
                            break  # SUKCES - wyjdź z retry loop
                        elif is_forebet and not sport_matches:
                            print(f"      ⚠️ Forebet HTML nie zawiera sportu {sport}! (FlareSolverr cache?)")
                            if retry_attempt < max_retries - 1:
                                print(f"      🔄 Czekam 3s i próbuję ponownie z nową sesją...")
                                time.sleep(3)  # Czekaj przed retry
                            html_content = None  # NIE cachuj
                        else:
                            print(f"      ⚠️ Bypass zwrócił nieznany HTML")
                            html_content = None
                    else:
                        print(f"      ⚠️ Cloudflare Bypass nie zadziałał")
                        
                except Exception as e:
                    print(f"      ⚠️ Cloudflare Bypass error: {e}")
                    html_content = None
        
        # Lokalnie - Puppeteer + fallback
        elif not IS_CI_CD:
            print(f"      🚀 Lokalnie: Próbuję Puppeteer Stealth...")
            html_content = fetch_forebet_with_puppeteer(sport)
            
            if html_content:
                is_cloudflare = 'loading-verifying' in html_content or 'lds-ring' in html_content
                is_forebet = 'class="rcnt"' in html_content or 'class="tr_0"' in html_content
                
                if is_forebet and not is_cloudflare:
                    print(f"      ✅ Puppeteer SUCCESS! ({len(html_content)} znaków)")
                    soup = BeautifulSoup(html_content, 'html.parser')
                    _forebet_html_cache[sport_cache_key] = (html_content, soup, time.time())
                else:
                    html_content = None
    
    try:
        # Jeśli mamy już HTML, parsuj go i POMIŃ całą logikę Selenium!
        if html_content:
            if soup is None:
                soup = BeautifulSoup(html_content, 'html.parser')
            print(f"      ✅ Używam HTML ({len(html_content)} znaków)")
            # Zapisz debug HTML
            with open('forebet_debug.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"      💾 Debug: Zapisano HTML do forebet_debug.html")
        else:
            # ========================================
            # FALLBACK: Selenium (gdy Bypass nie zadziałał)
            # ========================================
            print(f"      🔄 Fallback: Używam Selenium (bypass nie zadziałał)")
            
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
            
            # 🔥 WAŻNE: Używamy URL z datą meczu!
            sport_urls = {
                'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
                'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
                'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
                'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
                'handball': 'https://www.forebet.com/en/handball/predictions-today',
                'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
                'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
                'rugby': 'https://www.forebet.com/en/rugby/predictions-today',
                'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
                'baseball': 'https://www.forebet.com/en/baseball/predictions-today',
            }
            
            base_url = sport_urls.get(sport.lower(), sport_urls['football'])
            
            # Dodaj datę do URL - Forebet filtruje mecze po dacie!
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            
            if match_date and match_date != today:
                url = f"{base_url}?date={match_date}"
                print(f"      📅 Forebet dla daty: {match_date}")
            else:
                url = base_url
                print(f"      📅 Forebet dla dzisiaj")
            
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
            
            # 🔥 PEŁNE SCROLLOWANIE - ładuje WSZYSTKIE mecze (w tym wieczorne europejskie)
            print(f"      🖱️ Scrollowanie całej strony aby załadować wszystkie mecze...")
            
            # Pobierz początkową liczbę meczów
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            initial_matches = len(soup.find_all('div', class_='rcnt'))
            print(f"      📊 Początkowa liczba meczów: {initial_matches}")
            
            # Scrolluj całą stronę od góry do dołu, czekając na lazy loading
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_scroll_attempts = 25  # Max 25 prób scrollowania (więcej meczy na duże dni)
            
            while scroll_attempts < max_scroll_attempts:
                # Przewiń na dół strony
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(1.5, 2.5))  # Czekaj na lazy loading
                
                # Sprawdź czy strona się powiększyła
                new_height = driver.execute_script("return document.body.scrollHeight")
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                current_matches = len(soup.find_all('div', class_='rcnt'))
                
                print(f"      📊 Scroll {scroll_attempts + 1}: {current_matches} meczów (height: {new_height})")
                
                if new_height == last_height:
                    # Jeszcze jedna próba - czasem potrzeba więcej czasu
                    time.sleep(1)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        print(f"      ✅ Wszystkie mecze załadowane!")
                        break
                
                last_height = new_height
                scroll_attempts += 1
            
            # Przewiń z powrotem na górę i policz finalne mecze
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            final_matches = len(soup.find_all('div', class_='rcnt'))
            print(f"      📊 Finalna liczba meczów: {final_matches} (dodano {final_matches - initial_matches})")
            
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
        
        # DEBUG: Wypisz strukturę pierwszego wiersza
        try:
            if match_rows:
                first_row = match_rows[0]
                print(f"      📋 DEBUG: first_row type={type(first_row)}, truthy={bool(first_row)}")
                if first_row:
                    row_classes = first_row.get('class', []) if hasattr(first_row, 'get') else []
                    all_spans = first_row.find_all('span') if hasattr(first_row, 'find_all') else []
                    all_divs = first_row.find_all('div') if hasattr(first_row, 'find_all') else []
                    print(f"      📋 Struktura pierwszego wiersza: klasy={row_classes}")
                    print(f"      📋 Spany w wierszu: {len(all_spans)}, Divy: {len(all_divs)}")
                    # Wypisz pierwsze 5 spanów z klasami homeTeam/awayTeam
                    for i, span in enumerate(all_spans[:10]):
                        span_class = span.get('class', [])
                        if 'homeTeam' in span_class or 'awayTeam' in span_class or 'tnm' in span_class:
                            span_text = span.get_text(strip=True)[:50]
                            print(f"      📋 Span {i}: class={span_class}, text='{span_text}'")
        except Exception as debug_err:
            print(f"      ⚠️ DEBUG error przy analizie first_row: {debug_err}")
        
        # DEBUG: Wypisz pierwsze 5 meczów z Forebet żeby zobaczyć format
        debug_matches = []
        best_similarity = 0.0  # Track najlepszy wynik similarity
        
        # 🔥 DEBUG: Wypisz CZEGO szukamy
        print(f"      🔎 Szukam meczu: '{home_team}' vs '{away_team}'")
        print(f"      🔎 Znormalizowane: '{normalize_team_name(home_team)}' vs '{normalize_team_name(away_team)}'")
        
        # DEBUG: Zapisz surowy HTML pierwszych 2 wierszy do pliku
        if match_rows:
            try:
                with open('forebet_debug_rows.html', 'w', encoding='utf-8') as f:
                    for i, r in enumerate(match_rows[:2]):
                        f.write(f"<!-- ROW {i+1} -->\n")
                        f.write(str(r))
                        f.write("\n\n")
                print(f"      💾 Zapisano debug HTML do forebet_debug_rows.html")
            except Exception as e:
                print(f"      ⚠️ Nie udało się zapisać debug HTML: {e}")
        
        # Szukaj naszego meczu
        for row in match_rows:
            try:
                # Wyciągnij nazwy drużyn - WIELE WARIANTÓW
                home_name = None
                away_name = None
                
                # Wariant 1: span.homeTeam > span[itemprop="name"] (AKTUALNA STRUKTURA FOREBET 2025)
                home_span = row.find('span', class_='homeTeam')
                away_span = row.find('span', class_='awayTeam')
                if home_span and away_span:
                    # Szukaj zagnieżdżonego span z itemprop="name"
                    home_inner = home_span.find('span', itemprop='name')
                    away_inner = away_span.find('span', itemprop='name')
                    if home_inner and away_inner:
                        home_name = home_inner.get_text(strip=True)
                        away_name = away_inner.get_text(strip=True)
                    else:
                        # Fallback: weź cały tekst ze span.homeTeam/awayTeam
                        home_name = home_span.get_text(strip=True)
                        away_name = away_span.get_text(strip=True)
                
                # Wariant 2: meta itemprop="name" w schema.org (BACKUP)
                if not home_name or not away_name:
                    meta_name = row.find('meta', itemprop='name')
                    if meta_name and meta_name.get('content'):
                        content = meta_name['content']
                        if ' vs ' in content:
                            parts = content.split(' vs ')
                            home_name = parts[0].strip()
                            away_name = parts[1].strip()
                
                # Wariant 3: Szukaj <a> z href zawierającym mecz (np. /bayelsa-united-katsina-united)
                if not home_name or not away_name:
                    links = row.find_all('a', href=True)
                    for link in links:
                        href = link.get('href', '')
                        # Szukaj linków z meczami typu /football/matches/team1-team2-123456
                        if '/matches/' in href or '/predictions/' in href:
                            # Wyciągnij ostatni segment URL
                            url_part = href.split('/')[-1]
                            # Usuń ID meczu (liczby na końcu po myślniku)
                            import re
                            url_part = re.sub(r'-\d+$', '', url_part)
                            # Szukaj wzorca team1-team2
                            if '-' in url_part:
                                # Spróbuj znaleźć podział na dwie drużyny
                                # Szukaj kombinacji słów oddzielonych myślnikami
                                words = url_part.split('-')
                                # Spróbuj różnych podziałów
                                for i in range(1, len(words)):
                                    potential_home = ' '.join(words[:i]).title()
                                    potential_away = ' '.join(words[i:]).title()
                                    if len(potential_home) > 2 and len(potential_away) > 2:
                                        home_name = potential_home
                                        away_name = potential_away
                                        break
                                if home_name and away_name:
                                    break
                
                # Wariant 4: div.tnms - kontener na drużyny
                if not home_name or not away_name:
                    tnms_div = row.find('div', class_='tnms')
                    if tnms_div:
                        home_span = tnms_div.find('span', class_='homeTeam')
                        away_span = tnms_div.find('span', class_='awayTeam')
                        if home_span and away_span:
                            home_name = home_span.get_text(strip=True)
                            away_name = away_span.get_text(strip=True)
                
                if not home_name or not away_name:
                    # DEBUG: Sprawdź co jest w wierszu
                    if len(debug_matches) < 3:
                        row_text = row.get_text(strip=True)[:100] if row else "None"
                        debug_matches.append(f"[EMPTY] {row_text}")
                    continue
                
                forebet_home = home_name
                forebet_away = away_name
                
                # DEBUG: Zbierz WSZYSTKIE mecze do Gemini (limit 100)
                if len(debug_matches) < 100:
                    debug_matches.append(f"{forebet_home} vs {forebet_away}")
                    print(f"      🏟️ Forebet mecz znaleziony: {forebet_home} vs {forebet_away}")
                
                # Sprawdź similarity
                home_score = similarity_score(home_team, forebet_home)
                away_score = similarity_score(away_team, forebet_away)
                
                # DEBUG: Loguj wysokie (ale niewystarczające) similarity scores
                if home_score >= 0.35 or away_score >= 0.35:
                    print(f"      🔍 Potencjalny match: {forebet_home} vs {forebet_away} | Home={home_score:.2f} Away={away_score:.2f}")
                
                # � POPRAWIONE WARUNKI - elastyczne dopasowanie (v3 - luty 2026)
                # Uproszczone i bardziej niezawodne niż 7 warunków
                combined_score = (home_score + away_score) / 2
                min_score = min(home_score, away_score)
                max_score = max(home_score, away_score)
                
                # Track najlepszy wynik dla Gemini decyzji
                if combined_score > best_similarity:
                    best_similarity = combined_score
                
                # === WARUNKI MATCHOWANIA (v3 - uproszczone) ===
                # W1: Obie drużyny przyzwoite (>= 0.35)
                cond_both = home_score >= 0.35 and away_score >= 0.35
                # W2: Suma wyników >= 0.85 (pozwala 0.50 + 0.35)
                cond_sum = (home_score + away_score) >= 0.85
                # W3: Jedna drużyna bardzo pewna (>= 0.75), druga min 0.20
                cond_one_strong = max_score >= 0.75 and min_score >= 0.20
                # W4: Jedna drużyna dokładne dopasowanie (>= 0.90)
                cond_exact = max_score >= 0.90
                
                if cond_both or cond_sum or cond_one_strong or cond_exact:
                    print(f"      ✅ Znaleziono mecz na Forebet: {forebet_home} vs {forebet_away}")
                    print(f"         Similarity: Home={home_score:.2f}, Away={away_score:.2f}")
                    
                    # 🔥 FIX: Ustaw success/found NATYCHMIAST po znalezieniu meczu
                    # Dzięki temu nawet jeśli ekstrakcja danych rzuci wyjątek,
                    # mecz będzie oznaczony jako znaleziony
                    result['success'] = True
                    result['found'] = True  # Wymagane przez scrape_and_notify.py
                    result['home_team_forebet'] = forebet_home
                    result['away_team_forebet'] = forebet_away
                    
                    # Wyciągnij predykcję - POPRAWIONA STRUKTURA
                    extraction_success = False
                    
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
                                
                                extraction_success = True
                                print(f"         📊 Probability: {home_prob}%-{draw_prob}%-{away_prob}% → {result['prediction']}")
                            except (ValueError, IndexError) as e:
                                print(f"         ⚠️ Błąd parsowania prawdopodobieństw: {e}")
                    else:
                        print(f"         ⚠️ Brak div.fprc - szukam alternatyw...")
                    
                    # 2. Predykcja tekstowa (div.predict > span.forepr)
                    forepr_elem = row.find('span', class_='forepr')
                    if forepr_elem and not result.get('prediction'):
                        pred_text = forepr_elem.get_text(strip=True)
                        if pred_text in ['1', 'X', '2']:
                            result['prediction'] = pred_text
                            extraction_success = True
                            print(f"         📊 Prediction (forepr): {pred_text}")
                    
                    # 3. Dokładny wynik (div.ex_sc)
                    ex_sc_elem = row.find('div', class_='ex_sc')
                    if ex_sc_elem:
                        # Non-football sports (handball, basketball, hockey, volleyball)
                        # use <br> tag as separator: "29<br><b>32</b>" -> "29-32"
                        # Football uses text with " - ": "1 - 0"
                        if ex_sc_elem.find('br'):
                            scores = list(ex_sc_elem.stripped_strings)
                            if len(scores) == 2:
                                result['exact_score'] = f"{scores[0]}-{scores[1]}"
                            else:
                                result['exact_score'] = ex_sc_elem.get_text(strip=True)
                        else:
                            result['exact_score'] = ex_sc_elem.get_text(strip=True)
                    
                    # 4. Average Goals (div.avg_sc)
                    avg_sc_elem = row.find('div', class_='avg_sc')
                    if avg_sc_elem:
                        avg_text = avg_sc_elem.get_text(strip=True)
                        try:
                            result['avg_goals'] = float(avg_text)
                            # Over/Under - różne thresholdy per sport
                            if sport_lower in ['football', 'soccer']:
                                # Football: Over/Under 2.5 goli
                                if result['avg_goals'] > 2.5:
                                    result['over_under'] = 'Over 2.5'
                                else:
                                    result['over_under'] = 'Under 2.5'
                            elif sport_lower in ['hockey', 'ice-hockey']:
                                # Hockey: Over/Under 5.5 goli
                                if result['avg_goals'] > 5.5:
                                    result['over_under'] = 'Over 5.5'
                                else:
                                    result['over_under'] = 'Under 5.5'
                            elif sport_lower in ['basketball']:
                                # Basketball: Over/Under - wartość z Forebet (punkty, nie gole)
                                pass  # avg_goals jest saved, ale Over/Under threshold zależy od ligi
                            elif sport_lower in ['handball']:
                                # Handball: Over/Under - wartość z Forebet 
                                pass  # avg_goals saved
                            # Inne sporty: zachowaj avg_goals bez Over/Under
                        except ValueError:
                            pass
                    
                    # 5. BTTS - sprawdź czy oba zespoły strzelą
                    # TYLKO dla football i hockey - nie ma sensu dla basketball/handball/volleyball
                    # (tam wyniki są np. 78-95 / 29-32 - oba zawsze "strzelają")
                    if sport_lower in ['football', 'soccer']:
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
                    elif sport_lower in ['hockey', 'ice-hockey']:
                        # Hockey też ma niskie wyniki - BTTS ma sens
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
                    
                    # 🔥 ALTERNATYWNA EKSTRAKCJA: Jeśli fprc nie znaleziono, szukaj w innych miejscach
                    if not result.get('prediction'):
                        # Alternatywa 1: span.ex_sc może zawierać predykcję dla niektórych sportów
                        ex_spans = row.find_all('span', class_=['ex_sc', 'ex1', 'ex2', 'ex3'])
                        for ex_span in ex_spans:
                            text = ex_span.get_text(strip=True)
                            if text in ['1', 'X', '2', '1X', 'X2', '12']:
                                result['prediction'] = text
                                extraction_success = True
                                print(f"         📊 Prediction (ex_span): {text}")
                                break
                        
                        # Alternatywa 2: Szukaj w całym wierszu
                        if not result.get('prediction'):
                            all_text = row.get_text()
                            # Szukaj wzorca prawdopodobieństw (np. 45% 30% 25%)
                            import re
                            probs = re.findall(r'(\d{1,2})%', all_text)
                            if len(probs) >= 2:
                                try:
                                    # Dla sportów bez remisu (handball, volleyball, basketball)
                                    if sport_lower in ['handball', 'volleyball', 'basketball', 'tennis']:
                                        p1, p2 = int(probs[0]), int(probs[1])
                                        result['probability'] = float(max(p1, p2))
                                        result['prediction'] = '1' if p1 > p2 else '2'
                                        extraction_success = True
                                        print(f"         📊 Probability (regex 2-way): {p1}%-{p2}% → {result['prediction']}")
                                    elif len(probs) >= 3:
                                        p1, px, p2 = int(probs[0]), int(probs[1]), int(probs[2])
                                        max_prob = max(p1, px, p2)
                                        result['probability'] = float(max_prob)
                                        if max_prob == p1:
                                            result['prediction'] = '1'
                                        elif max_prob == px:
                                            result['prediction'] = 'X'
                                        else:
                                            result['prediction'] = '2'
                                        extraction_success = True
                                        print(f"         📊 Probability (regex 3-way): {p1}%-{px}%-{p2}% → {result['prediction']}")
                                except (ValueError, IndexError):
                                    pass
                    
                    # Log status ekstrakcji
                    if extraction_success:
                        print(f"         ✅ Ekstrakcja danych zakończona sukcesem")
                    else:
                        print(f"         ⚠️ Mecz znaleziony, ale nie udało się wyciągnąć predykcji")
                    
                    # Zawsze break po znalezieniu meczu (nawet jeśli ekstrakcja zawiodła)
                    break
                    
            except Exception as e:
                print(f"      ⚠️ Błąd parsowania wiersza Forebet: {type(e).__name__}: {e}")
                continue
        
        if not result['success']:
            # 🤖 GEMINI/GROQ FALLBACK: Użyj gdy algorytm nie znalazł meczu
            # Gemini używamy gdy najlepszy similarity score < 0.55
            # (znaczy że nie znaleźliśmy pewnego dopasowania)
            # Zwiększono z 0.50 na 0.55 aby zmniejszyć liczbę wywołań AI i uniknąć rate limitów
            
            AI_SIMILARITY_THRESHOLD = 0.55
            use_gemini = (
                best_similarity < AI_SIMILARITY_THRESHOLD and  # Brak pewnych dopasowań
                debug_matches and 
                len([m for m in debug_matches if 'vs' in m]) >= 2  # Min 2 mecze
            )
            
            if use_gemini:
                print(f"      🤖 Forebet: Najlepszy score={best_similarity:.2f} < {AI_SIMILARITY_THRESHOLD} - używam Gemini AI ({len(debug_matches)} meczów)...")
                gemini_match = find_forebet_match_with_gemini(home_team, away_team, debug_matches)
                
                if gemini_match:
                    gemini_home, gemini_away = gemini_match
                    
                    # Znajdź wiersz z dopasowanym meczem i wyciągnij predykcję
                    for row in match_rows:  # 🔥 FIX: użyj match_rows zamiast rows
                        try:
                            # Wyciągnij nazwy drużyn z wiersza (używając tych samych metod co wcześniej)
                            row_home, row_away = None, None
                            
                            home_span = row.find('span', class_='homeTeam')
                            away_span = row.find('span', class_='awayTeam')
                            if home_span and away_span:
                                row_home = home_span.get_text(strip=True)
                                row_away = away_span.get_text(strip=True)
                            
                            # Sprawdź czy to nasz mecz
                            if row_home and row_away:
                                if (row_home.lower() == gemini_home.lower() and 
                                    row_away.lower() == gemini_away.lower()):
                                    print(f"      ✅ Gemini: Znaleziono predykcję dla {row_home} vs {row_away}")
                                    
                                    # 🔥 FIX: Ustaw success/found NATYCHMIAST
                                    result['found'] = True
                                    result['success'] = True
                                    result['home_team_forebet'] = row_home
                                    result['away_team_forebet'] = row_away
                                    
                                    # Wyciągnij predykcję (taki sam kod jak wcześniej)
                                    try:
                                        fprc_div = row.find('div', class_='fprc')
                                        if fprc_div:
                                            spans = fprc_div.find_all('span')
                                            if len(spans) >= 3:
                                                try:
                                                    home_prob = int(spans[0].get_text(strip=True))
                                                    draw_prob = int(spans[1].get_text(strip=True))
                                                    away_prob = int(spans[2].get_text(strip=True))
                                                    
                                                    max_prob = max(home_prob, draw_prob, away_prob)
                                                    result['probability'] = float(max_prob)
                                                    
                                                    if max_prob == home_prob:
                                                        result['prediction'] = '1'
                                                    elif max_prob == draw_prob:
                                                        result['prediction'] = 'X'
                                                    else:
                                                        result['prediction'] = '2'
                                                except (ValueError, IndexError):
                                                    pass
                                        
                                        # Exact score
                                        ex_sc_elem = row.find('div', class_='ex_sc')
                                        if ex_sc_elem:
                                            if ex_sc_elem.find('br'):
                                                scores = list(ex_sc_elem.stripped_strings)
                                                if len(scores) == 2:
                                                    result['exact_score'] = f"{scores[0]}-{scores[1]}"
                                                else:
                                                    result['exact_score'] = ex_sc_elem.get_text(strip=True)
                                            else:
                                                result['exact_score'] = ex_sc_elem.get_text(strip=True)
                                    except Exception as extraction_err:
                                        print(f"      ⚠️ Gemini: Błąd ekstrakcji: {extraction_err}")
                                    
                                    break
                        except Exception as e:
                            print(f"      ⚠️ Gemini: Błąd przetwarzania wiersza: {e}")
                            continue
            
            # Jeśli nadal nie znaleziono - ustaw error
            if not result['success']:
                if debug_matches:
                    print(f"      📋 Próbki meczów na Forebet: {debug_matches[:5]}")
                    print(f"      🔎 Szukany mecz: {home_team} vs {away_team}")
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
            except Exception as e:
                # Ignoruj błędy przy zamykaniu drivera - może już być zamknięty
                pass
        
        # Zamknij Xvfb jeśli był użyty
        if xvfb_display:
            try:
                xvfb_display.stop()
                print(f"      🖥️ Xvfb virtual display stopped")
            except Exception as e:
                # Ignoruj błędy przy zamykaniu Xvfb
                pass
    
    # Zapisz do cache (nowy system z kluczem sport)
    _set_cached_forebet(sport, home_team, away_team, match_date, result)
    
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
