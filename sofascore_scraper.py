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

import os
import time
import re
import json
import hashlib
import threading
import logging
import random
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, List
from difflib import SequenceMatcher

# Logging setup
logger = logging.getLogger(__name__)

# Preferuj curl_cffi (omija Cloudflare), fallback do requests
CURL_CFFI_AVAILABLE = False
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
    REQUESTS_AVAILABLE = True
except ImportError:
    curl_requests = None

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    if not CURL_CFFI_AVAILABLE:
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
# W CI: 30s (wystarczająco na 3 daty × retry), lokalnie: 35s
import os as _os_timeout
_IS_CI_TIMEOUT = _os_timeout.getenv('CI') == 'true' or _os_timeout.getenv('GITHUB_ACTIONS') == 'true'
SOFASCORE_GLOBAL_TIMEOUT = 30 if _IS_CI_TIMEOUT else 35

# Sporty BEZ REMISÓW (tylko Home/Away win)
SPORTS_WITHOUT_DRAW = ['volleyball', 'tennis', 'basketball', 'handball', 'hockey', 'ice-hockey', 'baseball', 'cricket']

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
    'baseball': 'baseball',
    'cricket': 'cricket',
}

# Headers dla requests API - v5.0: Zaktualizowane do Chrome 136
API_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Origin': 'https://www.sofascore.com',
    'Referer': 'https://www.sofascore.com/',
    'Sec-Ch-Ua': '"Google Chrome";v="136", "Chromium";v="136", "Not_A Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Cache-Control': 'no-cache',
}

# ============================================================================
# API SESSION SINGLETON (v3.5)
# ============================================================================

_api_session = None
_session_initialized: bool = False

# Circuit breaker dla Selenium fallback w CI
_selenium_failures: int = 0
_selenium_max_failures: int = 5  # v4: Raised from 3 to 5 for more resilience before tripping
_selenium_last_reset: float = 0.0
_SELENIUM_RESET_INTERVAL: int = 180  # v4: Faster reset (3 min instead of 5)

def _get_api_session():
    """
    Zwraca singleton session.
    v4.0: Preferuje curl_cffi (omija Cloudflare 403).
    Fallback do requests.Session z warmup cookies.
    """
    global _api_session, _session_initialized
    
    if _api_session is not None and _session_initialized:
        return _api_session
    
    if not REQUESTS_AVAILABLE:
        return None
    
    # Preferuj curl_cffi - omija Cloudflare bez potrzeby cookies
    if CURL_CFFI_AVAILABLE:
        # curl_cffi nie potrzebuje session warmup - impersonuje Chrome TLS
        _api_session = 'curl_cffi'  # sentinel value
        _session_initialized = True
        print(f"   🚀 SofaScore: curl_cffi (Chrome TLS impersonation)")
        return _api_session
    
    # Fallback: requests.Session z warmup cookies
    _api_session = requests.Session()
    _api_session.headers.update(API_HEADERS)
    
    warmup_headers = {
        'User-Agent': API_HEADERS['User-Agent'],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Upgrade-Insecure-Requests': '1',
    }
    
    max_warmup_attempts = 2
    for attempt in range(max_warmup_attempts):
        try:
            r = _api_session.get('https://www.sofascore.com/', headers=warmup_headers, timeout=8)
            cookies_count = len(_api_session.cookies.get_dict())
            if cookies_count > 0:
                print(f"   🍪 SofaScore session: {cookies_count} cookies OK")
                break
            else:
                if attempt < max_warmup_attempts - 1:
                    time.sleep(1)
                else:
                    print(f"   ⚠️ SofaScore session: 0 cookies (API może zwracać 403)")
        except Exception as e:
            if attempt < max_warmup_attempts - 1:
                time.sleep(1)
            else:
                print(f"   ⚠️ SofaScore session warmup failed: {type(e).__name__}")
    
    _session_initialized = True
    return _api_session


def _build_warmed_requests_session():
    """Create a one-off requests session for curl_cffi 403 fallback."""
    if 'requests' not in globals():
        return None

    session = requests.Session()
    session.headers.update(API_HEADERS)
    warmup_headers = {
        'User-Agent': API_HEADERS['User-Agent'],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        session.get('https://www.sofascore.com/', headers=warmup_headers, timeout=8)
    except Exception as e:
        logger.debug(f"SofaScore requests fallback warmup failed: {type(e).__name__}")
    return session


# ============================================================================
# HTTP DIAGNOSTICS COUNTER (v4.1)
# ============================================================================
# Globalny licznik wyników HTTP per klient - na koniec runu wypisujemy
# zwięzłe statystyki, dzięki którym widać od razu czy problem to 403/WAF
# (większość requestów na 403), timeout (większość na timeout) czy zwykły
# brak meczu (200/404 dominują, a Fan Vote i tak nie przychodzi).

_http_stats: Dict[str, Dict[str, int]] = {
    "curl_cffi": {},
    "requests": {},
    "flaresolverr": {},
    "selenium": {},
}


def _record_http_outcome(client: str, outcome: str) -> None:
    """Zarejestruj wynik requestu (np. 'ok', '403', '404', 'timeout', 'error').

    `client` ∈ {'curl_cffi', 'requests', 'flaresolverr', 'selenium'}.
    """
    bucket = _http_stats.setdefault(client, {})
    bucket[outcome] = bucket.get(outcome, 0) + 1


def get_http_stats_snapshot() -> Dict[str, Dict[str, int]]:
    """Zwróć kopię statystyk HTTP, czytaną przez orchestrator (scrape_and_notify).
    Pozwala wypisać po runie: ile requestów dostało 200/403/404/timeout
    z rozbiciem na klienta. Kluczowe dla diagnozy `Fan Vote` w CI.
    """
    return {client: dict(v) for client, v in _http_stats.items()}


def _format_http_stats(stats: Optional[Dict[str, Dict[str, int]]] = None) -> str:
    """Krótki, czytelny dump dla logów CI (jeden wiersz per klient)."""
    snap = stats if stats is not None else get_http_stats_snapshot()
    lines: List[str] = []  # type: ignore[name-defined]
    for client, buckets in snap.items():
        if not buckets:
            continue
        total = sum(buckets.values())
        parts = ", ".join(f"{k}={v}" for k, v in sorted(buckets.items()))
        lines.append(f"   📊 SofaScore HTTP[{client}] total={total} ({parts})")
    return "\n".join(lines)


def print_http_stats() -> None:
    """Wypisz statystyki HTTP do stdout (no-op gdy brak requestów).

    Wywoływane przez orchestrator po zakończeniu fazy scrapowania, żeby
    user/CI miał wprost odpowiedź "ile 403 w tym runie", bez przekopywania
    setek linii logów.
    """
    snap = get_http_stats_snapshot()
    body = _format_http_stats(snap)
    if body:
        print("📊 SofaScore HTTP statistics:")
        print(body)


# ============================================================================
# FLARESOLVERR FALLBACK FOR SOFASCORE API (v4.1)
# ============================================================================
# Workflow GitHub Actions już wystawia FlareSolverr na FLARESOLVERR_URL
# (`scrape.yml` / pokrewne), ale dotąd korzystał z niego tylko Forebet.
# Po serii `403` z `curl_cffi`/`requests` próbujemy SofaScore przez
# FlareSolverr, bo on wykonuje request prawdziwą przeglądarką i ma
# znacznie wyższą szansę przejścia ochrony WAF z runnerów GitHub.

_FLARESOLVERR_URL_ENV = os.getenv('FLARESOLVERR_URL', '').strip()
# Domyślnie unikamy `localhost:8191` poza CI, żeby nie blokować lokalnego
# uruchomienia 60-sekundowym timeoutem na nieistniejący serwis.
_FLARESOLVERR_AVAILABLE = bool(_FLARESOLVERR_URL_ENV)
_flaresolverr_disabled_for_run: bool = False


def _try_flaresolverr_json(url: str, timeout: int = 25) -> Optional[Any]:
    """Pobierz JSON z SofaScore API przez FlareSolverr (fallback po 403).

    Zwraca sparsowany JSON albo `None`. Po pierwszej porażce na poziomie
    samego serwisu (np. brak FlareSolverr, błąd transportu) wyłącza dalsze
    próby w tym runie, żeby nie przepalać czasu w CI.
    """
    global _flaresolverr_disabled_for_run

    if not _FLARESOLVERR_AVAILABLE or _flaresolverr_disabled_for_run:
        return None
    if 'requests' not in globals():
        return None

    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max(20000, timeout * 1000),
    }
    try:
        resp = requests.post(
            _FLARESOLVERR_URL_ENV,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout + 30,
        )
    except Exception as e:
        logger.debug(f"FlareSolverr transport error for SofaScore: {type(e).__name__}")
        _flaresolverr_disabled_for_run = True
        _record_http_outcome('flaresolverr', 'error')
        return None

    if resp.status_code != 200:
        _record_http_outcome('flaresolverr', f'http_{resp.status_code}')
        return None

    try:
        data = resp.json()
    except Exception:
        _record_http_outcome('flaresolverr', 'parse_error')
        return None

    if data.get("status") != "ok":
        _record_http_outcome('flaresolverr', 'fs_error')
        return None

    solution = data.get("solution") or {}
    body = solution.get("response") or ""
    if not body:
        _record_http_outcome('flaresolverr', 'empty')
        return None

    # FlareSolverr zwraca pełny HTML; dla endpointów `api.sofascore.com/...`
    # zwykle to JSON owinięty w `<pre>...</pre>` lub czysty JSON.
    text = body
    if '<pre' in text:
        m = re.search(r'<pre[^>]*>(.*?)</pre>', text, re.DOTALL)
        if m:
            text = m.group(1)
    text = text.strip()
    try:
        parsed = __import__('json').loads(text)
        _record_http_outcome('flaresolverr', 'ok')
        return parsed
    except Exception:
        _record_http_outcome('flaresolverr', 'json_error')
        logger.debug("FlareSolverr returned non-JSON body for SofaScore API")
        return None

# ============================================================================
# CACHE SYSTEM
# ============================================================================

_sofascore_cache: Dict[str, Dict] = {}
_cache_expiry: Dict[str, datetime] = {}
CACHE_DURATION_MINUTES = 30

# v7.1 — Cache shape contract for clause 3.8 (preservation across strategies).
# Every strategy that writes via _set_cached_result MUST produce a dict whose
# `set(keys()) == EXPECTED_CACHE_KEYS`. Pinned by tests/test_sofascore_cache_shape.py.
EXPECTED_CACHE_KEYS = frozenset({
    'sofascore_home_win_prob',
    'sofascore_draw_prob',
    'sofascore_away_win_prob',
    'sofascore_total_votes',
    'sofascore_btts_yes',
    'sofascore_btts_no',
    'sofascore_url',
    'sofascore_found',
})


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

# Wykrywanie CI - w CI zmniejszamy retry aby nie tracić czasu.
IS_CI = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'

# W CI: 2 próby (1 retry), lokalnie: 3 próby
MAX_RETRIES = 2 if IS_CI else 3
RETRY_BACKOFF = [0.5, 1, 2] if IS_CI else [1, 2, 4]  # Szybsze w CI

# ============================================================================
# IMPERSONATE PROFILE ROTATION (v5.2)
# ============================================================================
# Cloudflare na GHA blokuje stale TLS fingerprints. Rotujemy profile,
# żeby zwiększyć szansę przejścia przez WAF.

_IMPERSONATE_PROFILES = ['chrome131', 'chrome124', 'chrome120', 'chrome110', 'safari17_0', 'edge101']
_impersonate_idx: int = 0


def _next_impersonate_profile() -> str:
    """Zwróć następny profil TLS w rotacji."""
    global _impersonate_idx
    profile = _IMPERSONATE_PROFILES[_impersonate_idx % len(_IMPERSONATE_PROFILES)]
    _impersonate_idx += 1
    return profile


# ============================================================================
# GLOBAL API CIRCUIT BREAKER (v5.0)
# ============================================================================
# Po N kolejnych 403 z WSZYSTKICH klientów (curl_cffi + requests + FlareSolverr)
# całkowicie wyłączamy SofaScore API na resztę runu. Zapobiega sytuacji
# gdzie 400 meczów × 15+ requestów = 6000+ martwych requestów i 6h runu.

_api_consecutive_403: int = 0
_API_403_CIRCUIT_BREAKER_THRESHOLD: int = 5  # v5.2: podniesiono z 3 do 5 (dajemy rotacji profili szansę)
_api_circuit_breaker_tripped: bool = False


def _api_cb_record_success() -> None:
    """Reset circuit breaker po udanym requeście."""
    global _api_consecutive_403
    _api_consecutive_403 = 0


def _api_cb_record_403() -> None:
    """Inkrementuj licznik 403 i trip jeśli przekroczono próg."""
    global _api_consecutive_403, _api_circuit_breaker_tripped
    _api_consecutive_403 += 1
    if _api_consecutive_403 >= _API_403_CIRCUIT_BREAKER_THRESHOLD and not _api_circuit_breaker_tripped:
        _api_circuit_breaker_tripped = True
        print(
            f"   🛑 SofaScore API CIRCUIT BREAKER: {_api_consecutive_403} kolejnych 403 — "
            f"wyłączam SofaScore API na resztę runu (oszczędzam czas CI)."
        )


def _retry_request_with_session(url: str, timeout: int = 10, **kwargs):
    """
    Wykonuje request z exponential backoff.
    v4.0: Preferuje curl_cffi (omija Cloudflare), fallback do requests session.
    
    Args:
        url: URL do pobrania
        timeout: Timeout w sekundach
        **kwargs: Dodatkowe argumenty
        
    Returns:
        Response jeśli sukces, None jeśli wszystkie próby zawiodą
    """
    session = _get_api_session()
    if session is None:
        return None
    
    use_curl = CURL_CFFI_AVAILABLE and session == 'curl_cffi'
    
    last_exception = None
    tried_requests_fallback = False
    
    for attempt in range(MAX_RETRIES):
        try:
            if use_curl:
                # v5.2: rotacja profili TLS — każdy request próbuje inny
                # fingerprint, zwiększając szansę przejścia przez WAF.
                profile = _next_impersonate_profile()
                response = curl_requests.get(
                    url,
                    impersonate=profile,
                    headers=API_HEADERS,
                    timeout=timeout,
                )
            else:
                response = session.get(url, timeout=timeout, **kwargs)
            client_label = 'curl_cffi' if use_curl else 'requests'
            if response.status_code == 200:
                if response.content and len(response.content) > 2:
                    _record_http_outcome(client_label, 'ok')
                    return response
                else:
                    _record_http_outcome(client_label, 'empty_200')
                    logger.debug(f"SofaScore API: Pusta odpowiedź (200 ale {len(response.content or b'')}B)")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else RETRY_BACKOFF[-1])
                    continue
            elif response.status_code in [429, 503]:
                _record_http_outcome(client_label, str(response.status_code))
                wait_time = RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else RETRY_BACKOFF[-1]
                logger.debug(f"SofaScore API: Status {response.status_code}, czekam {wait_time}s...")
                if IS_CI:
                    print(f"   ⚠️ SofaScore API: {response.status_code} - retry za {wait_time}s")
                time.sleep(wait_time)
                continue
            elif response.status_code == 403:
                _record_http_outcome(client_label, '403')
                logger.debug(f"SofaScore API: 403 Forbidden - prawdopodobnie brak cookies lub rate limit")
                if IS_CI:
                    print(f"   ⚠️ SofaScore API: 403 Forbidden ({client_label})")
                if use_curl and not tried_requests_fallback:
                    tried_requests_fallback = True
                    fallback_session = _build_warmed_requests_session()
                    if fallback_session is not None:
                        if IS_CI:
                            print("   🔄 SofaScore API: 403 z curl_cffi, próba requests session")
                        try:
                            fallback_response = fallback_session.get(url, timeout=timeout, **kwargs)
                            if fallback_response.status_code == 200:
                                if fallback_response.content and len(fallback_response.content) > 2:
                                    _record_http_outcome('requests', 'ok')
                                    return fallback_response
                                _record_http_outcome('requests', 'empty_200')
                                logger.debug(
                                    "SofaScore API fallback: pusta odpowiedź "
                                    f"(200 ale {len(fallback_response.content or b'')}B)"
                                )
                            else:
                                _record_http_outcome('requests', str(fallback_response.status_code))
                            return fallback_response
                        except Exception as e:
                            last_exception = e
                            _record_http_outcome('requests', 'error')
                            logger.debug(f"SofaScore API fallback failed: {type(e).__name__}: {str(e)[:100]}")
                return response  # Zwróć 403 - caller zdecyduje (ew. FlareSolverr)
            else:
                _record_http_outcome(client_label, str(response.status_code))
                return response
        except (TimeoutError, OSError) as e:
            last_exception = e
            _record_http_outcome('curl_cffi' if use_curl else 'requests', 'timeout')
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF[attempt]
                logger.debug(f"SofaScore API: Timeout/Connection error, próba {attempt + 2}/{MAX_RETRIES}...")
                time.sleep(wait_time)
            else:
                if IS_CI:
                    print(f"   ⚠️ SofaScore API: {type(e).__name__} po {MAX_RETRIES} próbach")
        except Exception as e:
            last_exception = e
            _record_http_outcome('curl_cffi' if use_curl else 'requests', 'error')
            logger.debug(f"SofaScore API: Nieoczekiwany błąd: {type(e).__name__}: {str(e)[:100]}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt] if attempt < len(RETRY_BACKOFF) else RETRY_BACKOFF[-1])
            else:
                break

    if last_exception:
        logger.debug(f"SofaScore API: Wszystkie próby zawiodły - {type(last_exception).__name__}")
    return None


def _try_alt_domain_url(url: str) -> Optional[str]:
    """Zamień api.sofascore.com na www.sofascore.com/api (same-origin path).

    Przeglądarka SofaScore używa www.sofascore.com/api/v1/... zamiast
    api.sofascore.com/api/v1/... — same-origin requesty mogą mieć inne
    (łagodniejsze) reguły WAF niż cross-origin na subdomenie api.
    """
    if 'api.sofascore.com/api/' in url:
        return url.replace('api.sofascore.com/api/', 'www.sofascore.com/api/')
    return None


def _api_get_json(url: str, timeout: int = 10) -> Optional[Any]:
    """Pobierz JSON z SofaScore API z wielostopniową ścieżką klientów.

    v5.1 — kolejność prób:
    1. curl_cffi na oryginalnym URL (api.sofascore.com)
    2. curl_cffi na alternatywnej domenie (www.sofascore.com/api) z profilem chrome124
    3. requests.Session z warmupem na alt domenie
    4. FlareSolverr (jeśli dostępny)

    Globalny circuit breaker — po 3 kolejnych 403 zwraca None natychmiast.
    """
    # CIRCUIT BREAKER: jeśli tripped, natychmiast None
    if _api_circuit_breaker_tripped:
        return None

    response = _retry_request_with_session(url, timeout=timeout)
    if response is not None:
        if response.status_code == 200:
            _api_cb_record_success()
            try:
                return response.json()
            except Exception:
                return None
        if response.status_code == 403:
            # ── Fallback A: alternatywna domena (www.sofascore.com/api) ──
            alt_url = _try_alt_domain_url(url)
            if alt_url and CURL_CFFI_AVAILABLE:
                try:
                    alt_resp = curl_requests.get(
                        alt_url,
                        impersonate='chrome124',
                        headers={**API_HEADERS, 'Referer': 'https://www.sofascore.com/'},
                        timeout=timeout,
                    )
                    if alt_resp.status_code == 200 and alt_resp.content and len(alt_resp.content) > 2:
                        _record_http_outcome('curl_cffi', 'ok_alt')
                        _api_cb_record_success()
                        try:
                            return alt_resp.json()
                        except Exception:
                            pass
                    else:
                        _record_http_outcome('curl_cffi', f'{alt_resp.status_code}_alt')
                except Exception:
                    _record_http_outcome('curl_cffi', 'error_alt')

            # ── Fallback B: requests session na alt domenie ──
            if alt_url:
                fallback_session = _build_warmed_requests_session()
                if fallback_session is not None:
                    try:
                        fb_resp = fallback_session.get(alt_url, timeout=timeout)
                        if fb_resp.status_code == 200 and fb_resp.content and len(fb_resp.content) > 2:
                            _record_http_outcome('requests', 'ok_alt')
                            _api_cb_record_success()
                            try:
                                return fb_resp.json()
                            except Exception:
                                pass
                        else:
                            _record_http_outcome('requests', f'{fb_resp.status_code}_alt')
                    except Exception:
                        _record_http_outcome('requests', 'error_alt')

            _api_cb_record_403()
            if _api_circuit_breaker_tripped:
                return None

            # ── Fallback C: FlareSolverr ──
            if _FLARESOLVERR_AVAILABLE:
                if IS_CI:
                    print("   🐳 SofaScore: 403 z curl/requests, próba FlareSolverr...")
                # Próbuj FlareSolverr na alt URL jeśli dostępny
                fs_url = alt_url or url
                data = _try_flaresolverr_json(fs_url, timeout=max(timeout, 25))
                if data is not None:
                    _api_cb_record_success()
                    return data
        return None
    if _FLARESOLVERR_AVAILABLE and not _api_circuit_breaker_tripped:
        if IS_CI:
            print("   🐳 SofaScore: brak odpowiedzi curl/requests, próba FlareSolverr...")
        data = _try_flaresolverr_json(url, timeout=max(timeout, 25))
        if data is not None:
            _api_cb_record_success()
            return data
    return None


def _retry_request(request_func, *args, **kwargs):
    """
    [LEGACY] Wrapper do wielokrotnych prób wykonania requestu z exponential backoff.
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
    """Normalizuje nazwę drużyny do porównania - v3.7 mniej agresywna wersja"""
    if not name:
        return ""
    name = name.lower().strip()
    
    # POLSKIE/EUROPEJSKIE ZNAKI → ASCII
    char_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
        'é': 'e', 'è': 'e', 'ê': 'e', 'á': 'a', 'à': 'a', 'â': 'a',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ú': 'u', 'ù': 'u', 'û': 'u',
        'ñ': 'n', 'ç': 'c', 'š': 's', 'č': 'c', 'ž': 'z', 'ř': 'r',
        'ď': 'd', 'ť': 't', 'ň': 'n', 'ő': 'o', 'ű': 'u',
        'ý': 'y', 'ã': 'a', 'õ': 'o', 'ø': 'o', 'å': 'a', 'æ': 'ae',
        'ð': 'd', 'þ': 'th', 'ğ': 'g', 'ı': 'i', 'ş': 's',
    }
    for char, replacement in char_map.items():
        name = name.replace(char, replacement)
    
    # Usuń TYLKO krótkie prefiksy (2-3 literowe skróty klubów)
    # NIE usuwamy dłuższych jak 'hapoel', 'maccabi', 'dinamo' - mogą być częścią nazwy
    short_prefixes = ['fc ', 'afc ', 'cf ', 'sc ', 'sv ', 'fk ', 'nk ', 'sk ', 'bk ',
                      'ac ', 'as ', 'ss ', 'us ', 'cd ', 'ud ', 'rcd ', 'ks ', 'mks ']
    for prefix in short_prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break  # Usuń tylko jeden prefix
    
    # Usuń sufiksy wiekowe/kategorii (U21, U19, Women, etc.) - ale ZACHOWAJ inne
    name = re.sub(r'\s+(u21|u19|u18|u17|u16|u23|women|kobiety|ladies|w)\s*$', '', name, flags=re.IGNORECASE)
    
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def similarity_score(name1: str, name2: str) -> float:
    """
    Oblicza similarity score między dwoma nazwami (0.0 - 1.0).
    v3.7: Używa wielu metod i zwraca najwyższy wynik (jak forebet).
    """
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    if not norm1 or not norm2:
        return 0.0
    
    # Metoda 1: SequenceMatcher (standard)
    seq_score = SequenceMatcher(None, norm1, norm2).ratio()
    
    # Metoda 2: Containment check ("psg" in "paris saint germain")
    containment = 0.0
    if norm1 in norm2:
        containment = max(0.85, len(norm1) / len(norm2))
    elif norm2 in norm1:
        containment = max(0.85, len(norm2) / len(norm1))
    
    # Metoda 3: Jaccard na tokenach (słowach)
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    if tokens1 and tokens2:
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        jaccard = len(intersection) / len(union) if union else 0.0
    else:
        jaccard = 0.0
    
    # Metoda 4: First/Main word match
    first_word_score = 0.0
    words1, words2 = norm1.split(), norm2.split()
    if words1 and words2:
        # Najdłuższe słowo z każdej nazwy (main word)
        main1 = max(words1, key=len)
        main2 = max(words2, key=len)
        main_sim = SequenceMatcher(None, main1, main2).ratio()
        if main_sim >= 0.80:
            first_word_score = max(0.75, main_sim * 0.85)
        # Pierwsze słowo match
        if words1[0] == words2[0] and len(words1[0]) >= 3:
            first_word_score = max(first_word_score, 0.70)
    
    # Metoda 5: Common prefix (>= 4 chars)
    prefix_score = 0.0
    common_prefix_len = 0
    for c1, c2 in zip(norm1, norm2):
        if c1 == c2:
            common_prefix_len += 1
        else:
            break
    if common_prefix_len >= 4:
        max_len = max(len(norm1), len(norm2))
        prefix_score = min(0.85, common_prefix_len / max_len + 0.3)
    
    return max(seq_score, containment, jaccard, first_word_score, prefix_score)


def teams_match(team1: str, team2: str, threshold: float = 0.35) -> bool:
    """Sprawdza czy dwie nazwy drużyn są podobne"""
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
    v3.5: Używa session z cookies
    """
    if not REQUESTS_AVAILABLE:
        logger.warning("SofaScore API: requests module not available")
        return None
    try:
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/votes"
        # v4.1: jednolity helper z FlareSolverr fallbackiem po 403.
        data = _api_get_json(url, timeout=10)
        if data is None:
            return None

        vote = data.get('vote', {})
        if not vote or vote.get('vote1') is None:
            print(f"   ⚠️ SofaScore API: Brak danych głosowania (event_id={event_id})")
            return None

        vote1 = vote.get('vote1', 0) or 0
        voteX = vote.get('voteX', 0) or 0
        vote2 = vote.get('vote2', 0) or 0
        total_votes = vote1 + voteX + vote2

        if total_votes == 0:
            print(f"   ⚠️ SofaScore API: 0 głosów (event_id={event_id})")
            return None

        home_pct = round(vote1 / total_votes * 100)
        draw_pct = round(voteX / total_votes * 100) if voteX else None
        away_pct = round(vote2 / total_votes * 100)

        btts = data.get('bothTeamsToScoreVote', {})
        btts_yes = btts.get('voteYes', 0) or 0
        btts_no = btts.get('voteNo', 0) or 0
        btts_total = btts_yes + btts_no

        result = {
            'sofascore_home_win_prob': home_pct,
            'sofascore_draw_prob': draw_pct,
            'sofascore_away_win_prob': away_pct,
            'sofascore_total_votes': total_votes,
        }
        if btts_total > 0:
            result['sofascore_btts_yes'] = round(btts_yes / btts_total * 100)
            result['sofascore_btts_no'] = round(btts_no / btts_total * 100)
        return result
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
        response = _retry_request_with_session(url, timeout=5)
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



def _search_event_for_date(home_team: str, away_team: str, sport_slug: str, search_date: str, debug: bool = False) -> Optional[int]:
    """
    Wewnętrzna funkcja: szuka event ID dla konkretnej daty.
    v3.5: Wydzielono z search_event_via_api dla date window search.
    v3.8: Dodano debug logging dla diagnostyki.
    v4.1: `_api_get_json` automatycznie próbuje FlareSolverr po 403.
    """
    url = f"https://api.sofascore.com/api/v1/sport/{sport_slug}/scheduled-events/{search_date}"
    data = _api_get_json(url, timeout=10)

    if data is None:
        if debug:
            print(f"      [DEBUG] SofaScore API: No response for {search_date}")
        return None

    events = data.get('events', []) if isinstance(data, dict) else []
    if debug:
        print(f"      [DEBUG] SofaScore API returned {len(events)} events for {search_date}")
    
    if not events:
        return None
    
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)
    
    if debug:
        print(f"      [DEBUG] Searching for: '{home_norm}' vs '{away_norm}'")
    
    best_match_id = None
    best_combined_sim = 0.0
    best_match_info = None
    
    for event in events:
        event_home = event.get('homeTeam', {}).get('name', '')
        event_away = event.get('awayTeam', {}).get('name', '')
        if not event_home or not event_away:
            continue
        
        event_home_norm = normalize_team_name(event_home)
        event_away_norm = normalize_team_name(event_away)
        
        # Multi-method similarity (v3.7: containment, jaccard, prefix, etc.)
        home_sim = similarity_score(home_team, event_home)
        away_sim = similarity_score(away_team, event_away)
        combined_sim = home_sim + away_sim
        min_sim = min(home_sim, away_sim)
        max_sim = max(home_sim, away_sim)
        
        # === WARUNKI MATCHOWANIA (v3.7 - wielopoziomowe) ===
        # W1: Obie drużyny mają przyzwoity similarity (>= 0.35)
        cond_both_decent = home_sim >= 0.35 and away_sim >= 0.35
        # W2: Suma similarity >= 0.85 (pozwala na jedną słabszą)
        cond_combined = combined_sim >= 0.85
        # W3: Jedna drużyna pewna (>= 0.75), druga przyzwoita (>= 0.25)
        cond_one_strong = max_sim >= 0.75 and min_sim >= 0.25
        # W4: Partial word containment (obie drużyny mają wspólne słowa >= 3 znaki)
        home_match_partial = any(p in event_home_norm for p in home_norm.split() if len(p) >= 3)
        away_match_partial = any(p in event_away_norm for p in away_norm.split() if len(p) >= 3)
        home_match_reverse = any(p in home_norm for p in event_home_norm.split() if len(p) >= 3)
        away_match_reverse = any(p in away_norm for p in event_away_norm.split() if len(p) >= 3)
        cond_partial = (home_match_partial or home_match_reverse) and (away_match_partial or away_match_reverse)
        # W5: Jedna drużyna dokładne dopasowanie (>= 0.90)
        cond_exact_one = max_sim >= 0.90 and min_sim >= 0.20
        
        is_match = cond_both_decent or cond_combined or cond_one_strong or cond_partial or cond_exact_one
        
        if is_match and combined_sim > best_combined_sim:
            best_combined_sim = combined_sim
            best_match_id = event.get('id')
            best_match_info = f"{event_home} vs {event_away}"
            if debug:
                print(f"      [DEBUG] ✅ Match candidate: {event_home} vs {event_away} (h:{home_sim:.2f} a:{away_sim:.2f} sum:{combined_sim:.2f})")
            logger.debug(f"SofaScore match: {event_home} vs {event_away} "
                       f"(h:{home_sim:.2f} a:{away_sim:.2f} sum:{combined_sim:.2f})")
    
    if debug:
        if best_match_id:
            print(f"      [DEBUG] Best match: {best_match_info} (score: {best_combined_sim:.2f})")
        else:
            print(f"      [DEBUG] No match found for '{home_norm}' vs '{away_norm}' in {len(events)} events")
    
    return best_match_id


def search_event_via_api(home_team: str, away_team: str, sport: str = 'football', date_str: str = None) -> Optional[int]:
    """
    Szuka event ID przez SofaScore API.
    
    v3.2: Dodano retry logic z exponential backoff.
    v3.4: Ulepszone logowanie dla CI/CD
    v3.5: Date window search (today, yesterday, tomorrow) + session cookies
    """
    if not REQUESTS_AVAILABLE:
        logger.warning("SofaScore search API: requests module not available")
        return None
    
    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    
    # Date window: dzisiaj, wczoraj, jutro (dla timezone mismatches)
    # Używamy UTC jawnie - GitHub Actions działa w UTC
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    if date_str:
        try:
            base_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            base_date = today
    else:
        base_date = today
    
    # Date window: w CI ±1 dzień (oszczędność requestów), lokalnie ±3 dni
    if IS_CI:
        dates_to_try = [
            base_date.strftime('%Y-%m-%d'),                          # Podana data
            (base_date - timedelta(days=1)).strftime('%Y-%m-%d'),    # -1 dzień
            (base_date + timedelta(days=1)).strftime('%Y-%m-%d'),    # +1 dzień
        ]
    else:
        dates_to_try = [
            base_date.strftime('%Y-%m-%d'),
            (base_date - timedelta(days=1)).strftime('%Y-%m-%d'),
            (base_date + timedelta(days=1)).strftime('%Y-%m-%d'),
            (base_date - timedelta(days=2)).strftime('%Y-%m-%d'),
            (base_date + timedelta(days=2)).strftime('%Y-%m-%d'),
            (base_date - timedelta(days=3)).strftime('%Y-%m-%d'),
            (base_date + timedelta(days=3)).strftime('%Y-%m-%d'),
        ]
    
    # ====== STRATEGY 1: Standard search (both teams, strict matching) ======
    for search_date in dates_to_try:
        event_id = _search_event_for_date(home_team, away_team, sport_slug, search_date, debug=False)
        if event_id:
            logger.debug(f"SofaScore: Znaleziono mecz na dacie {search_date} (Strategy 1)")
            return event_id
    
    # ====== STRATEGY 2: Team search API (search by team name) ======
    print(f"   🔄 SofaScore Strategy 2: Szukam przez team search API...")
    for team_query in [home_team, away_team]:
        try:
            search_url = f"https://api.sofascore.com/api/v1/search/teams/{team_query.replace(' ', '%20')}"
            search_data = _api_get_json(search_url, timeout=10)
            if search_data and isinstance(search_data, dict):
                teams = search_data.get('teams', [])
                if teams:
                    team_id = teams[0].get('id')
                    team_name = teams[0].get('name', '')
                    print(f"      Found team: '{team_name}' (ID: {team_id})")
                    for endpoint in ['next', 'last']:
                        events_url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/{endpoint}/0"
                        ev_data = _api_get_json(events_url, timeout=10)
                        if ev_data and isinstance(ev_data, dict):
                            events = ev_data.get('events', [])
                            for event in events:
                                event_home = event.get('homeTeam', {}).get('name', '')
                                event_away = event.get('awayTeam', {}).get('name', '')
                                other_team = away_team if team_query == home_team else home_team
                                other_event = event_away if team_query == home_team else event_home
                                other_sim = similarity_score(other_team, other_event)
                                if other_sim >= 0.30:
                                    print(f"   ✅ SofaScore Strategy 2: Found {event_home} vs {event_away} (sim:{other_sim:.2f})")
                                    return event.get('id')
        except Exception as e:
            logger.debug(f"SofaScore team search error for '{team_query}': {e}")

    # ====== STRATEGY 3: Relaxed matching (home-only or away-only with lower threshold) ======
    print(f"   🔄 SofaScore Strategy 3: Luźne dopasowanie (home/away osobno)...")
    for search_date in dates_to_try[:3]:  # Only first 3 dates
        url = f"https://api.sofascore.com/api/v1/sport/{sport_slug}/scheduled-events/{search_date}"
        data = _api_get_json(url, timeout=10)
        if data and isinstance(data, dict):
            try:
                events = data.get('events', [])
                best_event_id = None
                best_score = 0.0
                for event in events:
                    event_home = event.get('homeTeam', {}).get('name', '')
                    event_away = event.get('awayTeam', {}).get('name', '')
                    home_sim = similarity_score(home_team, event_home)
                    away_sim = similarity_score(away_team, event_away)
                    # Relaxed: one team >= 0.70, other >= 0.20
                    if (home_sim >= 0.70 and away_sim >= 0.20) or (away_sim >= 0.70 and home_sim >= 0.20):
                        combined = home_sim + away_sim
                        if combined > best_score:
                            best_score = combined
                            best_event_id = event.get('id')
                            print(f"      Relaxed candidate: {event_home} vs {event_away} (h:{home_sim:.2f} a:{away_sim:.2f})")
                if best_event_id:
                    print(f"   ✅ SofaScore Strategy 3: Found match (score: {best_score:.2f})")
                    return best_event_id
            except Exception:
                pass
    
    # ====== STRATEGY 4: Debug - log first date's events for diagnosis ======
    print(f"   ⚠️ SofaScore: Nie znaleziono po 3 strategiach ({sport}/{dates_to_try[0]})")
    # Debug: show what API returned for main date
    _search_event_for_date(home_team, away_team, sport_slug, dates_to_try[0], debug=True)
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
        print(f"   ❌ SofaScore: Błąd: {type(e).__name__}: {e}")
        # 🔥 FIX: Jeśli mecz został znaleziony (match_url jest ustawiony), zachowaj found=True
        if result.get('sofascore_url'):
            result['sofascore_found'] = True
            print(f"   ℹ️ SofaScore: Mecz znaleziony, ale ekstrakcja danych nie powiodła się")
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


# ============================================================================
# BROWSER-BASED API FETCH (v7.0) — bypass Cloudflare WAF
# ============================================================================
# Cloudflare na GHA blokuje WSZYSTKIE server-side requesty (curl_cffi,
# requests, FlareSolverr) z 403. Ale API działa z kontekstu przeglądarki
# (same-origin). Więc otwieramy sofascore.com w headless Chrome i robimy
# fetch() z poziomu JS — WAF to przepuszcza.

_browser_api_session_driver = None
_browser_api_session_ready: bool = False
_browser_api_failed_count: int = 0
_BROWSER_API_MAX_FAILURES: int = 3

# v7.1 — Specific Change 1: gate the browser-fetch path on CI by default.
# Local runs (neither GITHUB_ACTIONS nor CI set, and no explicit opt-in) keep
# the curl_cffi fast path as primary so clause 3.1 holds bit-for-bit.
_SOFASCORE_BROWSER_FETCH_ENABLED: bool = (
    IS_CI
    or os.getenv('SOFASCORE_BROWSER_FETCH_ENABLED', '').strip().lower() in ('1', 'true', 'yes')
)

# v7.1 — Specific Change 6: cap singleton driver reuse to mitigate Risk #3
# (memory growth across many matches in a matrix shard). Default 50, override
# via env var.
try:
    _SOFASCORE_BROWSER_FETCH_MAX_REUSE: int = max(
        1, int(os.getenv('SOFASCORE_BROWSER_FETCH_MAX_REUSE', '50') or '50')
    )
except (TypeError, ValueError):
    _SOFASCORE_BROWSER_FETCH_MAX_REUSE = 50

_browser_api_reuse_counter: int = 0


def _create_lightweight_driver():
    """Tworzy minimalny headless Chrome driver do API fetch."""
    if not SELENIUM_AVAILABLE:
        return None
    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1280,720')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--blink-settings=imagesEnabled=false')
        chrome_options.add_argument(f'--user-agent={API_HEADERS["User-Agent"]}')
        chrome_options.page_load_strategy = 'eager'

        chrome_bin = os.getenv('CHROME_BIN')
        if chrome_bin and os.path.exists(chrome_bin):
            chrome_options.binary_location = chrome_bin
        elif IS_CI:
            for candidate in (
                '/usr/bin/google-chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/chromium',
                '/usr/bin/chromium-browser',
            ):
                if os.path.exists(candidate):
                    chrome_options.binary_location = candidate
                    break

        chromedriver_path = os.getenv('CHROMEDRIVER_PATH')
        service = None
        if chromedriver_path and os.path.exists(chromedriver_path):
            service = Service(executable_path=chromedriver_path)
        elif IS_CI:
            # Ubuntu 24.04 runner: CHROMEWEBDRIVER=/usr/local/share/chromedriver-linux64
            # Ubuntu 22.04 runner: /usr/bin/chromedriver
            # nanasess/setup-chromedriver action: /usr/local/bin/chromedriver
            for _cd in (
                os.path.join(os.getenv('CHROMEWEBDRIVER', ''), 'chromedriver'),
                '/usr/local/bin/chromedriver',
                '/usr/bin/chromedriver',
                '/usr/local/share/chromedriver-linux64/chromedriver',
            ):
                if _cd and os.path.exists(_cd):
                    service = Service(executable_path=_cd)
                    break

        if service:
            d = webdriver.Chrome(service=service, options=chrome_options)
        else:
            d = webdriver.Chrome(options=chrome_options)
        # v7.1 — Specific Change 6: tighter CI timeouts (12s page-load, 8s script)
        d.set_page_load_timeout(12)
        d.set_script_timeout(8)
        return d
    except Exception as e:
        logger.debug(f"_create_lightweight_driver failed: {type(e).__name__}: {e}")
        return None


def _get_browser_api_session():
    """Zwraca (driver, ready) gotowy do fetch() z sofascore.com.

    Singleton — tworzy driver raz, nawiguje do sofascore.com,
    akceptuje consent, i potem reużywa do wielokrotnych fetch().

    v7.1: po `_SOFASCORE_BROWSER_FETCH_MAX_REUSE` udanych użyciach driver
    jest recyklowany (mitigation Risk #3 — wzrost pamięci w matrix shard).
    """
    global _browser_api_session_driver, _browser_api_session_ready
    global _browser_api_failed_count, _browser_api_reuse_counter

    if _browser_api_failed_count >= _BROWSER_API_MAX_FAILURES:
        return None, False

    # v7.1 — Specific Change 6: recycle the singleton after MAX_REUSE successful uses.
    if (
        _browser_api_session_driver is not None
        and _browser_api_session_ready
        and _browser_api_reuse_counter >= _SOFASCORE_BROWSER_FETCH_MAX_REUSE
    ):
        print(
            f"   ♻️ SofaScore Browser API: rotuję driver po "
            f"{_browser_api_reuse_counter} użyciach (max={_SOFASCORE_BROWSER_FETCH_MAX_REUSE})"
        )
        try:
            _browser_api_session_driver.quit()
        except Exception:
            pass
        _browser_api_session_driver = None
        _browser_api_session_ready = False
        _browser_api_reuse_counter = 0

    if _browser_api_session_driver is not None and _browser_api_session_ready:
        _browser_api_reuse_counter += 1
        return _browser_api_session_driver, True

    print(f"   🌐 SofaScore Browser API: Tworzę sesję przeglądarki...")
    driver = _create_lightweight_driver()
    if not driver:
        _browser_api_failed_count += 1
        return None, False

    try:
        driver.get('https://www.sofascore.com/football')
        time.sleep(2)
        accept_consent_popup(driver)
        time.sleep(1)
        _browser_api_session_driver = driver
        _browser_api_session_ready = True
        _browser_api_reuse_counter = 1
        print(f"   ✅ SofaScore Browser API: Sesja gotowa")
        return driver, True
    except Exception as e:
        logger.debug(f"Browser API session setup failed: {type(e).__name__}: {e}")
        _browser_api_failed_count += 1
        try:
            driver.quit()
        except Exception:
            pass
        return None, False


def _fetch_json_via_browser(driver, api_path: str, timeout: int = 8) -> Optional[Any]:
    """Wykonaj fetch() do SofaScore API z kontekstu przeglądarki.

    Używa window.fetch() z same-origin na www.sofascore.com, co omija
    Cloudflare WAF (przeglądarka ma cookies i challenge-token).

    Args:
        driver: Selenium driver z załadowaną stroną sofascore.com
        api_path: Ścieżka API, np. '/api/v1/event/12345/votes'
        timeout: Timeout w sekundach

    Returns:
        Sparsowany JSON lub None
    """
    # Upewnij się, że ścieżka zaczyna się od /api/
    if not api_path.startswith('/api/'):
        if 'api.sofascore.com/api/' in api_path:
            api_path = '/api/' + api_path.split('api.sofascore.com/api/')[1]
        elif 'sofascore.com/api/' in api_path:
            api_path = '/api/' + api_path.split('sofascore.com/api/')[1]

    js_script = f"""
    var callback = arguments[arguments.length - 1];
    fetch({json.dumps(api_path)}, {{
        method: 'GET',
        credentials: 'include',
        headers: {{
            'Accept': 'application/json, text/plain, */*',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept-Language': 'en-US,en;q=0.9'
        }},
        cache: 'no-cache',
        referrerPolicy: 'strict-origin-when-cross-origin'
    }})
        .then(function(response) {{
            if (!response.ok) {{
                callback(JSON.stringify({{"_error": response.status}}));
                return;
            }}
            return response.text().then(function(t) {{
                try {{ return JSON.parse(t); }} catch (e) {{ return null; }}
            }});
        }})
        .then(function(data) {{
            if (data) callback(JSON.stringify(data));
            else callback(JSON.stringify({{"_error": "empty_or_unparseable"}}));
        }})
        .catch(function(err) {{
            callback(JSON.stringify({{"_error": err.toString()}}));
        }});
    """

    try:
        driver.set_script_timeout(timeout)
        raw = driver.execute_async_script(js_script)
        if not raw:
            _record_http_outcome('selenium', 'empty')
            return None
        data = json.loads(raw)
        if isinstance(data, dict) and '_error' in data:
            err = data['_error']
            # v7.1 — Specific Change 3: classify the JS-side error so
            # `print_http_stats()` shows actionable buckets (e.g. selenium=403=2).
            if isinstance(err, int):
                _record_http_outcome('selenium', str(err))
            elif isinstance(err, str) and err.isdigit():
                _record_http_outcome('selenium', err)
            else:
                _record_http_outcome('selenium', 'js_error')
            logger.debug(f"Browser fetch error for {api_path}: {err}")
            return None
        _record_http_outcome('selenium', 'ok')
        return data
    except Exception as e:
        # Map common transport-level failures into stable buckets.
        if isinstance(e, TimeoutException):
            _record_http_outcome('selenium', 'timeout')
        else:
            _record_http_outcome('selenium', 'error')
        logger.debug(f"Browser fetch exception for {api_path}: {type(e).__name__}: {e}")
        return None


def _fetch_next_data_via_browser(api_path: str, sport: str, date_str: Optional[str] = None) -> Optional[Dict]:
    """v7.3 — Pobierz `__NEXT_DATA__` JSON z renderowanej HTML strony SofaScore.

    Cloudflare puszcza HTML page navigations (mamy clearance cookie) ale
    blokuje bezpośrednie API XHR. Next.js embeduje pełen state w
    `<script id="__NEXT_DATA__">{...}</script>`, w tym `events` z
    `scheduledEventsByDay/{date}` oraz `votes` w stronie meczu.

    Args:
        api_path: ścieżka aplikacyjna SofaScore (np. '/football/2026-05-15')
        sport: sport (do logowania)
        date_str: data, jeśli api_path nie zawiera

    Returns:
        Sparsowany `props.pageProps` lub None
    """
    driver, ready = _get_browser_api_session()
    if not ready or not driver:
        return None

    url = f'https://www.sofascore.com{api_path}'
    try:
        driver.set_page_load_timeout(15)
    except Exception:
        pass
    try:
        driver.get(url)
    except Exception as e:
        logger.debug(f"_fetch_next_data_via_browser: get() error: {type(e).__name__}: {e}")
    try:
        accept_consent_popup(driver)
    except Exception:
        pass

    # Niech JS się załaduje (Next.js hydration), choć __NEXT_DATA__ jest
    # już w HTML response (server-rendered), więc nie musimy długo czekać.
    time.sleep(1.0)

    try:
        page_html = driver.page_source
    except Exception as e:
        logger.debug(f"_fetch_next_data_via_browser: page_source error: {type(e).__name__}: {e}")
        return None

    # Wyciągnij <script id="__NEXT_DATA__">...</script>
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_html, re.DOTALL
    )
    if not m:
        logger.debug(f"_fetch_next_data_via_browser ({sport}/{api_path}): brak __NEXT_DATA__ w HTML")
        _record_http_outcome('selenium', 'no_next_data')
        return None

    raw = m.group(1).strip()
    try:
        next_data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug(f"_fetch_next_data_via_browser: JSON decode error: {e}")
        _record_http_outcome('selenium', 'next_data_parse_error')
        return None

    page_props = (
        (next_data.get('props') or {}).get('pageProps') or {}
    )
    if not page_props:
        logger.debug(f"_fetch_next_data_via_browser ({sport}/{api_path}): pusty pageProps")
        return None

    _record_http_outcome('selenium', 'next_data_ok')
    _api_cb_record_success()
    return page_props


def _build_candidate_list_via_next_data(
    home_team: str,
    away_team: str,
    sport: str,
    date_str: Optional[str],
    max_candidates: int = 80,
) -> List[Dict]:
    """v7.3 — alternatywny budowniczy listy kandydatów: HTML page → __NEXT_DATA__.

    Wywoływany gdy `_build_candidate_list_via_browser` (czysty fetch JSON API)
    zwrócił pustą listę, czyli prawdopodobnie Cloudflare zablokował same-origin
    fetch. HTML page navigation jest cookie-bearing i przechodzi.
    """
    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    if date_str:
        try:
            base_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            base_date = today
    else:
        base_date = today

    home_norm = normalize_team_name(home_team).lower()
    away_norm = normalize_team_name(away_team).lower()
    home_tokens = [t for t in home_norm.split() if len(t) > 2]
    away_tokens = [t for t in away_norm.split() if len(t) > 2]

    candidates: List[Dict] = []
    seen_ids: set = set()

    for offset in (0, -1, 1):
        d = (base_date + timedelta(days=offset)).strftime('%Y-%m-%d')
        page_path = f'/{sport_slug}/{d}'
        page_props = _fetch_next_data_via_browser(page_path, sport, d)
        if not page_props or not isinstance(page_props, dict):
            continue

        # SofaScore Next.js zwraca events pod różnymi kluczami w zależności
        # od wersji frontendu. Spróbujmy wszystkich znanych ścieżek.
        events: List[Dict] = []
        for key in ('events', 'scheduledEvents', 'eventsByDay'):
            cand = page_props.get(key)
            if isinstance(cand, list) and cand:
                events = cand
                break
            if isinstance(cand, dict):
                # Czasem to dict {date: [events]}; sklejmy wszystkie wartości.
                merged = []
                for v in cand.values():
                    if isinstance(v, list):
                        merged.extend(v)
                if merged:
                    events = merged
                    break

        # Fallback — szukaj zagnieżdżonych „events" na dowolnej głębokości.
        if not events:
            events = _walk_collect_events(page_props)

        for event in events:
            if not isinstance(event, dict):
                continue
            ev_id = event.get('id')
            if not ev_id or ev_id in seen_ids:
                continue
            ev_home = (event.get('homeTeam', {}) or {}).get('name', '') or ''
            ev_away = (event.get('awayTeam', {}) or {}).get('name', '') or ''
            if not ev_home or not ev_away:
                continue
            ev_home_l = ev_home.lower()
            ev_away_l = ev_away.lower()

            home_hit = (
                any(t in ev_home_l for t in home_tokens)
                or any(t in ev_home_l for t in away_tokens)
                or similarity_score(home_team, ev_home) >= 0.3
            )
            away_hit = (
                any(t in ev_away_l for t in away_tokens)
                or any(t in ev_away_l for t in home_tokens)
                or similarity_score(away_team, ev_away) >= 0.3
            )
            if not (home_hit or away_hit):
                continue

            tournament = (event.get('tournament', {}) or {}).get('name', '') or ''
            seen_ids.add(ev_id)
            candidates.append({
                'id': int(ev_id),
                'home': ev_home,
                'away': ev_away,
                'tournament': tournament,
                'date': d,
            })
            if len(candidates) >= max_candidates:
                return candidates

    return candidates


def _walk_collect_events(node: Any, depth: int = 0, max_depth: int = 6) -> List[Dict]:
    """Best-effort: rekurencyjnie szuka list „events" w zagnieżdżonej strukturze."""
    if depth > max_depth or node is None:
        return []
    found: List[Dict] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == 'events' and isinstance(v, list):
                found.extend([e for e in v if isinstance(e, dict)])
            else:
                found.extend(_walk_collect_events(v, depth + 1, max_depth))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_collect_events(item, depth + 1, max_depth))
    return found


def _search_event_via_browser(home_team: str, away_team: str, sport: str = 'football', date_str: str = None) -> Optional[int]:
    """Szuka event ID przez Browser API Fetch (bypass WAF).

    Używa Selenium + JS fetch() żeby pobrać scheduled-events z kontekstu
    przeglądarki — WAF nie blokuje same-origin requestów.
    """
    driver, ready = _get_browser_api_session()
    if not ready or not driver:
        return None

    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    if date_str:
        try:
            base_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            base_date = today
    else:
        base_date = today

    dates_to_try = [
        base_date.strftime('%Y-%m-%d'),
        (base_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        (base_date + timedelta(days=1)).strftime('%Y-%m-%d'),
    ]

    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    for search_date in dates_to_try:
        api_path = f'/api/v1/sport/{sport_slug}/scheduled-events/{search_date}'
        data = _fetch_json_via_browser(driver, api_path, timeout=10)
        if not data or not isinstance(data, dict):
            continue

        events = data.get('events', [])
        if not events:
            continue

        best_match_id = None
        best_combined_sim = 0.0

        for event in events:
            event_home = event.get('homeTeam', {}).get('name', '')
            event_away = event.get('awayTeam', {}).get('name', '')
            if not event_home or not event_away:
                continue

            home_sim = similarity_score(home_team, event_home)
            away_sim = similarity_score(away_team, event_away)
            combined_sim = home_sim + away_sim
            min_sim = min(home_sim, away_sim)
            max_sim = max(home_sim, away_sim)

            is_match = (
                (home_sim >= 0.35 and away_sim >= 0.35)
                or combined_sim >= 0.85
                or (max_sim >= 0.75 and min_sim >= 0.25)
                or (max_sim >= 0.90 and min_sim >= 0.20)
            )

            if is_match and combined_sim > best_combined_sim:
                best_combined_sim = combined_sim
                best_match_id = event.get('id')

        if best_match_id:
            return best_match_id

    return None


def _parse_vote_payload(data: Dict) -> Optional[Dict]:
    """v7.3 — wspólny parser SofaScore vote JSON.

    Akceptuje zarówno wynik z `/api/v1/event/{id}/votes` jak i z
    `__NEXT_DATA__.props.pageProps.event.vote` (struktura jest identyczna).
    """
    if not isinstance(data, dict):
        return None
    vote = data.get('vote') if 'vote' in data else data
    if not isinstance(vote, dict) or vote.get('vote1') is None:
        return None

    vote1 = vote.get('vote1', 0) or 0
    voteX = vote.get('voteX', 0) or 0
    vote2 = vote.get('vote2', 0) or 0
    total_votes = vote1 + voteX + vote2
    if total_votes == 0:
        return None

    home_pct = round(vote1 / total_votes * 100)
    draw_pct = round(voteX / total_votes * 100) if voteX else None
    away_pct = round(vote2 / total_votes * 100)

    btts = data.get('bothTeamsToScoreVote', {}) if isinstance(data, dict) else {}
    btts_yes = (btts or {}).get('voteYes', 0) or 0
    btts_no = (btts or {}).get('voteNo', 0) or 0
    btts_total = btts_yes + btts_no

    result = {
        'sofascore_home_win_prob': home_pct,
        'sofascore_draw_prob': draw_pct,
        'sofascore_away_win_prob': away_pct,
        'sofascore_total_votes': total_votes,
    }
    if btts_total > 0:
        result['sofascore_btts_yes'] = round(btts_yes / btts_total * 100)
        result['sofascore_btts_no'] = round(btts_no / btts_total * 100)
    return result


def _get_votes_via_browser(event_id: int, sport: str = 'football') -> Optional[Dict]:
    """Pobiera głosy Fan Vote przez Browser API Fetch (bypass WAF).

    v7.3: gdy fetch JSON zwraca 403/empty, fallbackuje na pobranie pełnej
    HTML strony meczu i wyciągnięcie `vote` z `__NEXT_DATA__.props.pageProps`.
    """
    driver, ready = _get_browser_api_session()
    if not ready or not driver:
        return None

    # Próba 1: same-origin fetch JSON API (działa gdy Cloudflare puszcza XHR)
    api_path = f'/api/v1/event/{event_id}/votes'
    data = _fetch_json_via_browser(driver, api_path, timeout=8)
    parsed = _parse_vote_payload(data) if isinstance(data, dict) else None
    if parsed:
        _api_cb_record_success()
        return parsed

    # Próba 2: __NEXT_DATA__ ze strony meczu (cookie-bearing HTML nav)
    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    page_props = _fetch_next_data_via_browser(
        f'/{sport_slug}/match/{event_id}', sport, None
    )
    if not page_props:
        return None

    # Struktura NEXT_DATA może mieć vote pod różnymi kluczami
    candidate_objs = []
    for key in ('event', 'fanVote', 'votes', 'vote'):
        v = page_props.get(key)
        if isinstance(v, dict):
            candidate_objs.append(v)

    for obj in candidate_objs:
        parsed = _parse_vote_payload(obj)
        if parsed:
            _api_cb_record_success()
            return parsed

    # Ostatnia próba: rekursywnie znajdź dict z polami vote1/vote2
    found_vote = _walk_find_vote(page_props)
    if found_vote:
        parsed = _parse_vote_payload(found_vote)
        if parsed:
            _api_cb_record_success()
            return parsed

    return None


def _walk_find_vote(node: Any, depth: int = 0, max_depth: int = 6) -> Optional[Dict]:
    """Best-effort: rekursywnie szuka dict z `vote1` / `vote2` (struktura
    SofaScore fan vote)."""
    if depth > max_depth or node is None:
        return None
    if isinstance(node, dict):
        if 'vote1' in node and 'vote2' in node:
            return node
        for v in node.values():
            res = _walk_find_vote(v, depth + 1, max_depth)
            if res is not None:
                return res
    elif isinstance(node, list):
        for item in node:
            res = _walk_find_vote(item, depth + 1, max_depth)
            if res is not None:
                return res
    return None


def _get_votes_via_browser_html(
    home_team: str,
    away_team: str,
    sport: str = 'football',
    event_id: Optional[int] = None,
) -> Optional[Dict]:
    """v7.1 — Specific Change 5: rendered-HTML fan-vote fallback (METODA 3).

    Uses the same singleton browser driver from `_get_browser_api_session`
    to navigate the rendered match page and parse percentages via
    `extract_votes_from_page`. Independent of having a numeric API event id
    (clause 2.4): when `event_id` is None we discover the URL through
    `find_match_on_main_page`.

    Returns the same dict shape as `_get_votes_via_browser` (without
    `sofascore_url` / `sofascore_found` — those are filled in by the
    caller in `scrape_sofascore_full` to keep cache-shape consistency,
    clause 3.8).
    """
    driver, ready = _get_browser_api_session()
    if not ready or not driver:
        return None

    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')

    match_url: Optional[str] = None
    if event_id:
        match_url = f"https://www.sofascore.com/{sport_slug}/match/{event_id}"
    else:
        try:
            match_url = find_match_on_main_page(driver, home_team, away_team, sport)
        except Exception as e:
            logger.debug(
                f"_get_votes_via_browser_html: find_match_on_main_page error: "
                f"{type(e).__name__}: {e}"
            )
            match_url = None

    if not match_url:
        return None

    try:
        try:
            driver.set_page_load_timeout(12)
        except Exception:
            pass
        try:
            driver.get(match_url)
        except Exception as e:
            logger.debug(f"_get_votes_via_browser_html: driver.get error: {type(e).__name__}: {e}")
        # Consent popup may reappear on a fresh navigation
        try:
            accept_consent_popup(driver)
        except Exception:
            pass
        # Scroll to the fan-vote section (rendered lazily lower on the page)
        try:
            time.sleep(1.5)
            for _ in range(4):
                driver.execute_script('window.scrollBy(0, 600);')
                time.sleep(0.25)
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight / 2);')
            time.sleep(0.5)
        except Exception as e:
            logger.debug(f"_get_votes_via_browser_html: scroll error: {type(e).__name__}: {e}")

        votes = extract_votes_from_page(driver, sport)
    except Exception as e:
        logger.debug(
            f"_get_votes_via_browser_html: extract error: {type(e).__name__}: {e}"
        )
        return None

    if not votes or votes.get('sofascore_home_win_prob') is None:
        return None
    # Synthesise the URL for the caller and reset the breaker on success.
    votes['sofascore_url'] = match_url
    _api_cb_record_success()
    return votes


# ============================================================================
# v7.2 — GROQ EVENT RESOLVER (LLM-assisted match identification)
# ============================================================================
# Gdy `_search_event_via_browser` nie znajdzie eventu (np. nazwy drużyn po PL,
# aliasy, transliteracje cyrylica↔łacina), Groq dostaje listę kandydatów z
# scheduled-events JSON i wybiera najlepszy match.

def _build_candidate_list_via_browser(
    home_team: str,
    away_team: str,
    sport: str,
    date_str: Optional[str],
    max_candidates: int = 80,
) -> List[Dict]:
    """Pobiera scheduled-events przez browser fetch (same-origin) i filtruje
    wstępnie po częściowym dopasowaniu nazw — żeby Groq dostawał ≤ N
    kandydatów, a nie 1500+ meczów dziennie."""
    driver, ready = _get_browser_api_session()
    if not ready or not driver:
        return []

    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    if date_str:
        try:
            base_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            base_date = today
    else:
        base_date = today

    dates_to_try = [
        base_date.strftime('%Y-%m-%d'),
        (base_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        (base_date + timedelta(days=1)).strftime('%Y-%m-%d'),
    ]

    home_norm = normalize_team_name(home_team).lower()
    away_norm = normalize_team_name(away_team).lower()
    home_tokens = [t for t in home_norm.split() if len(t) > 2]
    away_tokens = [t for t in away_norm.split() if len(t) > 2]

    candidates: List[Dict] = []
    seen_ids: set = set()

    for search_date in dates_to_try:
        api_path = f'/api/v1/sport/{sport_slug}/scheduled-events/{search_date}'
        data = _fetch_json_via_browser(driver, api_path, timeout=10)
        if not data or not isinstance(data, dict):
            continue

        for event in data.get('events', []) or []:
            ev_id = event.get('id')
            if not ev_id or ev_id in seen_ids:
                continue

            ev_home = (event.get('homeTeam', {}) or {}).get('name', '') or ''
            ev_away = (event.get('awayTeam', {}) or {}).get('name', '') or ''
            if not ev_home or not ev_away:
                continue

            ev_home_l = ev_home.lower()
            ev_away_l = ev_away.lower()

            # Wstępny filtr: choć jeden token z nazw oryginalnych musi być
            # widoczny w ev_home lub ev_away — żeby Groq nie dostał 1500
            # losowych meczów.
            home_hit = (
                any(t in ev_home_l for t in home_tokens)
                or any(t in ev_home_l for t in away_tokens)
                or similarity_score(home_team, ev_home) >= 0.3
            )
            away_hit = (
                any(t in ev_away_l for t in away_tokens)
                or any(t in ev_away_l for t in home_tokens)
                or similarity_score(away_team, ev_away) >= 0.3
            )
            if not (home_hit or away_hit):
                continue

            tournament = (event.get('tournament', {}) or {}).get('name', '') or ''
            seen_ids.add(ev_id)
            candidates.append({
                'id': int(ev_id),
                'home': ev_home,
                'away': ev_away,
                'tournament': tournament,
                'date': search_date,
            })

            if len(candidates) >= max_candidates:
                return candidates

    return candidates


def _build_event_resolver_prompt(
    home_team: str, away_team: str, sport: str, candidates: List[Dict]
) -> str:
    """Buduje prompt dla Groq LLM event-resolvera.

    Prompt musi być deterministyczny — żądamy odpowiedzi WYŁĄCZNIE w JSON
    z `event_id` lub `null`.
    """
    rows = []
    for c in candidates:
        # Forma: "id|home|away|tournament|date"
        row = f"{c['id']}|{c['home']}|{c['away']}|{c['tournament']}|{c['date']}"
        rows.append(row)

    candidates_block = "\n".join(rows) if rows else "(no candidates)"

    return (
        "You are matching a single sports fixture to one of a list of "
        "candidate events from SofaScore.\n\n"
        f"TARGET FIXTURE:\n  sport     : {sport}\n"
        f"  home_team : {home_team}\n"
        f"  away_team : {away_team}\n\n"
        "CANDIDATES (one per line, format: "
        "id|home_team|away_team|tournament|date):\n"
        f"{candidates_block}\n\n"
        "Pick the SINGLE best matching candidate. Consider that team names "
        "may differ in language (e.g. Polish vs English), transliteration "
        "(Cyrillic vs Latin), use of city/sponsor prefixes, and abbreviations. "
        "Home/away orientation MUST match (do NOT pick a candidate where "
        "home and away are swapped relative to the target).\n\n"
        "If NO candidate is a confident match, return null.\n\n"
        "Respond with ONLY valid JSON, no markdown:\n"
        '{"event_id": <number or null>, "confidence": <0.0..1.0>, '
        '"reason": "<short>"}'
    )


def _resolve_event_via_groq(
    home_team: str,
    away_team: str,
    sport: str,
    date_str: Optional[str] = None,
) -> Optional[int]:
    """v7.2 — Groq LLM event-resolver.

    Wywoływane gdy `_search_event_via_browser` zwraca None: pobiera listę
    kandydatów z scheduled-events przez browser fetch, wysyła do Groq LLM
    i zwraca wybrany `event_id` (lub None).

    Rotuje przez `_GROQ_TEXT_MODEL_CHAIN` na 429 / deprecated-model errors.
    """
    global _groq_active_text_model

    groq_module = _get_groq()
    if not groq_module:
        logger.debug("SofaScore Groq Resolver: groq module niedostępne")
        return None

    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        try:
            from groq_config import GROQ_API_KEY  # type: ignore[no-redef]
            api_key = GROQ_API_KEY
        except ImportError:
            pass
    if not api_key:
        logger.debug("SofaScore Groq Resolver: Brak GROQ_API_KEY")
        return None

    candidates = _build_candidate_list_via_browser(home_team, away_team, sport, date_str)
    if not candidates:
        # v7.3 — fallback: HTML page → __NEXT_DATA__ (cookie-bearing nav,
        # przechodzi przez Cloudflare nawet gdy fetch() z JS jest blokowany).
        print(
            f"   🔄 SofaScore Groq Resolver: pusta lista z fetch JSON, "
            f"próbuję __NEXT_DATA__..."
        )
        candidates = _build_candidate_list_via_next_data(
            home_team, away_team, sport, date_str
        )
    if not candidates:
        print(f"   ⚠️ SofaScore Groq Resolver: brak kandydatów (pusta lista scheduled-events)")
        return None

    print(f"   🤖 SofaScore Groq Resolver: {len(candidates)} kandydatów dla {home_team} vs {away_team}")

    try:
        client = groq_module.Groq(api_key=api_key)
    except Exception as e:
        print(f"   ⚠️ SofaScore Groq Resolver: client init error: {type(e).__name__}: {e}")
        return None

    prompt = _build_event_resolver_prompt(home_team, away_team, sport, candidates)
    chain = list(_GROQ_TEXT_MODEL_CHAIN)
    if _groq_active_text_model and _groq_active_text_model in chain:
        chain.remove(_groq_active_text_model)
        chain.insert(0, _groq_active_text_model)

    last_err: Optional[BaseException] = None
    for model_name in chain:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=128,
                temperature=0.0,
                response_format={'type': 'json_object'},
            )
            if not response or not response.choices:
                continue

            text = response.choices[0].message.content or ''
            try:
                parsed = json.loads(text.strip())
            except (json.JSONDecodeError, TypeError):
                # Spróbuj wyciąć { ... }
                m = re.search(r'\{[^{}]*\}', text or '')
                if not m:
                    print(f"   ⚠️ SofaScore Groq Resolver ({model_name}): JSON parse fail, raw={text[:200]}")
                    return None
                try:
                    parsed = json.loads(m.group(0))
                except (json.JSONDecodeError, TypeError):
                    print(f"   ⚠️ SofaScore Groq Resolver ({model_name}): JSON parse fail (rescue), raw={text[:200]}")
                    return None

            ev_id = parsed.get('event_id')
            confidence = parsed.get('confidence') or 0.0
            reason = parsed.get('reason') or ''

            _groq_active_text_model = model_name

            if ev_id is None:
                print(f"   ❌ SofaScore Groq Resolver ({model_name}): no match (reason={reason!r})")
                return None

            try:
                ev_id_int = int(ev_id)
            except (TypeError, ValueError):
                print(f"   ⚠️ SofaScore Groq Resolver ({model_name}): event_id nie int: {ev_id!r}")
                return None

            # Sanity check: event_id musi być na naszej liście kandydatów
            cand_ids = {c['id'] for c in candidates}
            if ev_id_int not in cand_ids:
                print(
                    f"   ⚠️ SofaScore Groq Resolver ({model_name}): "
                    f"event_id {ev_id_int} nie ma na liście kandydatów — odrzucam"
                )
                return None

            print(
                f"   ✅ SofaScore Groq Resolver ({model_name}): "
                f"event_id={ev_id_int} confidence={confidence:.2f} ({reason[:50]})"
            )
            return ev_id_int

        except Exception as e:
            last_err = e
            if _is_quota_or_rate_error(e):
                print(f"   🔁 SofaScore Groq Resolver ({model_name}): quota/rate limit — rotuję")
                continue
            if _is_model_unavailable_error(e):
                print(f"   🔁 SofaScore Groq Resolver ({model_name}): model niedostępny — rotuję")
                continue
            print(f"   ⚠️ SofaScore Groq Resolver ({model_name}) błąd: {type(e).__name__}: {str(e)[:80]}")
            return None

    if last_err is not None:
        print(
            f"   ⚠️ SofaScore Groq Resolver: wyczerpano modele ({len(chain)}) — "
            f"ostatni błąd: {type(last_err).__name__}"
        )
    return None


def cleanup_browser_api_session():
    """Zamknij singleton browser API session (wywoływane na koniec runu)."""
    global _browser_api_session_driver, _browser_api_session_ready
    if _browser_api_session_driver:
        try:
            _browser_api_session_driver.quit()
        except Exception:
            pass
        _browser_api_session_driver = None
        _browser_api_session_ready = False


# ============================================================================
# AI VISION EXTRACTION (v6.0) — Gemini / Groq fallback po 403
# ============================================================================
# Gdy SofaScore API zwraca 403 (Cloudflare/WAF), robimy screenshot
# sekcji fan vote i wysyłamy do Gemini Vision API lub Groq Vision API
# żeby AI wyekstraktował procenty głosowania z obrazu.

# Lazy imports — ładowane tylko gdy potrzebne
_GENAI_MODULE = None
_GROQ_MODULE = None

# ──────────────────────────────────────────────────────────────────────
# v7.2 — AI MODEL CONFIGURATION (rotation + production-ready defaults)
# ──────────────────────────────────────────────────────────────────────
# Gemini text/vision models, próbowane po kolei. Pierwszy dostępny zostaje
# zapamiętany w `_gemini_active_model` aby nie marnować quoty na sondaże.
# Model można nadpisać env var `SOFASCORE_GEMINI_MODELS=model1,model2,...`.
_GEMINI_MODEL_CHAIN_DEFAULT = [
    'gemini-2.5-flash',         # Najnowszy production flash (maj 2025)
    'gemini-2.0-flash-001',     # Stable production
    'gemini-2.0-flash',          # Alias bieżącej generacji
    'gemini-1.5-flash-002',      # Starszy stable
    'gemini-1.5-flash-8b',       # Najtańszy fallback
]
_GEMINI_MODEL_CHAIN: List[str] = [
    m.strip() for m in (
        os.getenv('SOFASCORE_GEMINI_MODELS', '').strip()
        or ','.join(_GEMINI_MODEL_CHAIN_DEFAULT)
    ).split(',') if m.strip()
]
_gemini_active_model: Optional[str] = None  # zapamiętany pierwszy działający

# Groq models — production replacements po deprecations 04/2025.
# llama-3.2-*-vision-preview → llama-4-scout (vision capable).
# llama-3.3-70b-versatile dla text-only event resolution.
_GROQ_VISION_MODEL_CHAIN = [
    'meta-llama/llama-4-scout-17b-16e-instruct',
    'meta-llama/llama-4-maverick-17b-128e-instruct',
]
_GROQ_TEXT_MODEL_CHAIN = [
    'llama-3.3-70b-versatile',
    'llama-3.1-8b-instant',
    'meta-llama/llama-4-scout-17b-16e-instruct',  # vision model also handles text
]
_groq_active_vision_model: Optional[str] = None
_groq_active_text_model: Optional[str] = None


def _is_quota_or_rate_error(exc: BaseException) -> bool:
    """Heurystyka: czy wyjątek to 429/RESOURCE_EXHAUSTED/quota — sygnał do
    rotacji modelu (zamiast natychmiastowej rezygnacji)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        '429', 'resource_exhausted', 'quota', 'rate limit',
        'rate_limit', 'too many requests', 'overloaded',
    )
    return any(n in msg for n in needles)


def _is_model_unavailable_error(exc: BaseException) -> bool:
    """Heurystyka: czy wyjątek to 'model nie istnieje / deprecated /
    decommissioned' — sygnał do rotacji modelu zamiast retry."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        'model_not_found', 'model not found', 'decommissioned',
        'deprecated', 'does not exist', 'invalid model',
        'not_found_error', 'unsupported model', '404',
    )
    return any(n in msg for n in needles)



def _get_genai():
    """Lazy import google.generativeai."""
    global _GENAI_MODULE
    if _GENAI_MODULE is not None:
        return _GENAI_MODULE
    try:
        import google.generativeai as genai
        _GENAI_MODULE = genai
        return genai
    except ImportError:
        _GENAI_MODULE = False
        return False


def _get_groq():
    """Lazy import groq."""
    global _GROQ_MODULE
    if _GROQ_MODULE is not None:
        return _GROQ_MODULE
    try:
        import groq as groq_module
        _GROQ_MODULE = groq_module
        return groq_module
    except ImportError:
        _GROQ_MODULE = False
        return False


def _take_fan_vote_screenshot(driver, event_url: str) -> Optional[bytes]:
    """
    Otwiera stronę meczu SofaScore, scrolluje do sekcji fan vote
    i robi screenshot widocznej strony.

    Returns:
        bytes PNG obrazu lub None jeśli nie udało się.
    """
    if not SELENIUM_AVAILABLE:
        return None

    try:
        try:
            driver.set_page_load_timeout(15)
        except (WebDriverException,) as e:
            logger.debug(f"Nie można ustawić page_load_timeout: {e}")

        try:
            driver.get(event_url)
        except (TimeoutException, WebDriverException) as e:
            logger.debug(f"Timeout przy ładowaniu strony fan vote (kontynuuję): {e}")

        # Akceptuj consent popup
        accept_consent_popup(driver)

        # Czekaj na załadowanie JS
        time.sleep(4)

        # Scroll w dół żeby załadować sekcję fan vote
        for _ in range(8):
            driver.execute_script('window.scrollBy(0, 400);')
            time.sleep(0.3)

        # Scroll do ~połowy strony gdzie zwykle jest fan vote
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight * 0.4);')
        time.sleep(1.5)

        # Zrób screenshot całej widocznej strony
        screenshot_bytes = driver.get_screenshot_as_png()
        if screenshot_bytes and len(screenshot_bytes) > 1000:
            print(f"   📸 SofaScore AI Vision: Screenshot OK ({len(screenshot_bytes)//1024}KB)")
            return screenshot_bytes
        else:
            print(f"   ⚠️ SofaScore AI Vision: Screenshot za mały")
            return None

    except Exception as e:
        print(f"   ⚠️ SofaScore AI Vision: Błąd screenshot: {type(e).__name__}: {e}")
        return None


def _build_vision_prompt(home_team: str, away_team: str, sport: str) -> str:
    """Buduje prompt do ekstrakcji fan vote z screenshota."""
    has_draw = sport not in SPORTS_WITHOUT_DRAW
    draw_part = ', "draw_pct": <number or null>' if has_draw else ''
    return (
        f"This is a screenshot of a SofaScore match page for {home_team} vs {away_team}.\n"
        f"Find the \"Who will win?\" or \"Kto wygra?\" fan vote section.\n"
        f"Extract the voting percentages shown in the widget.\n"
        f"The widget shows three buttons: home team, draw (X), and away team, "
        f"with percentage bars below them.\n\n"
        f"Respond ONLY with valid JSON (no markdown, no extra text):\n"
        f'{{"home_pct": <number>, "away_pct": <number>{draw_part}, '
        f'"total_votes": <number or null>, "found": true}}\n\n'
        f'If you cannot find the fan vote section, respond with:\n'
        f'{{"found": false}}'
    )


def _parse_vision_response(response_text: str, sport: str) -> Optional[Dict]:
    """Parsuje odpowiedź AI Vision na dict z procentami."""
    has_draw = sport not in SPORTS_WITHOUT_DRAW
    try:
        # Wyczyść odpowiedź — AI czasem opakowuje w markdown
        text = response_text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        data = json.loads(text)

        if not data.get('found', False):
            return None

        home_pct = data.get('home_pct')
        away_pct = data.get('away_pct')
        if home_pct is None or away_pct is None:
            return None

        result = {
            'sofascore_home_win_prob': int(round(float(home_pct))),
            'sofascore_away_win_prob': int(round(float(away_pct))),
            'sofascore_draw_prob': None,
            'sofascore_total_votes': int(data.get('total_votes') or 0),
        }

        if has_draw and data.get('draw_pct') is not None:
            result['sofascore_draw_prob'] = int(round(float(data['draw_pct'])))

        # Walidacja — procenty powinny sumować się do ~100%
        total_pct = result['sofascore_home_win_prob'] + result['sofascore_away_win_prob']
        if result['sofascore_draw_prob'] is not None:
            total_pct += result['sofascore_draw_prob']
        if total_pct < 80 or total_pct > 120:
            logger.warning(f"SofaScore AI Vision: procenty sumują się do {total_pct}% — odrzucam")
            return None

        return result

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug(f"SofaScore AI Vision: Błąd parsowania: {e}, raw: {response_text[:200]}")
        return None


def _extract_votes_via_gemini_vision(
    image_bytes: bytes,
    home_team: str,
    away_team: str,
    sport: str = 'football'
) -> Optional[Dict]:
    """
    Wyślij screenshot do Gemini Vision API i wyekstraktuj fan vote.

    v7.2: rotuje przez `_GEMINI_MODEL_CHAIN` przy 429 / quota / deprecated
    model errors — zamiast cicho zwracać None na 1. niepowodzeniu.

    Returns:
        Dict z sofascore_home_win_prob, sofascore_draw_prob, etc. lub None
    """
    global _gemini_active_model
    genai = _get_genai()
    if not genai:
        logger.debug("SofaScore AI Vision: google-generativeai niedostępne")
        return None

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        try:
            from gemini_config import GEMINI_API_KEY
            api_key = GEMINI_API_KEY
        except ImportError:
            pass
    if not api_key:
        logger.debug("SofaScore AI Vision: Brak GEMINI_API_KEY")
        return None

    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        print(f"   ⚠️ SofaScore Gemini Vision: configure() błąd: {type(e).__name__}: {e}")
        return None

    prompt = _build_vision_prompt(home_team, away_team, sport)
    image_part = {'mime_type': 'image/png', 'data': image_bytes}

    # v7.2 — preferuj zapamiętany model jeśli był ostatnio OK.
    chain = list(_GEMINI_MODEL_CHAIN)
    if _gemini_active_model and _gemini_active_model in chain:
        chain.remove(_gemini_active_model)
        chain.insert(0, _gemini_active_model)

    last_err: Optional[BaseException] = None
    for model_name in chain:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, image_part])
            text = response.text if response else None
            if not text:
                print(f"   ⚠️ SofaScore Gemini Vision ({model_name}): pusta odpowiedź")
                continue

            result = _parse_vision_response(text, sport)
            if result:
                _gemini_active_model = model_name
                print(f"   ✅ SofaScore Gemini Vision ({model_name}): wyekstraktowano fan vote")
                return result
            print(f"   ⚠️ SofaScore Gemini Vision ({model_name}): brak fan vote w screenshocie")
            logger.debug(f"Gemini Vision raw ({model_name}): {text[:300]}")
            # Pusty parsing nie jest powodem do rotacji modelu — wracamy.
            return None

        except Exception as e:
            last_err = e
            if _is_quota_or_rate_error(e):
                print(f"   🔁 SofaScore Gemini Vision ({model_name}): quota/rate limit — rotuję")
                continue
            if _is_model_unavailable_error(e):
                print(f"   🔁 SofaScore Gemini Vision ({model_name}): model niedostępny — rotuję")
                continue
            print(f"   ⚠️ SofaScore Gemini Vision ({model_name}) błąd: {type(e).__name__}: {str(e)[:80]}")
            return None

    if last_err is not None:
        print(
            f"   ⚠️ SofaScore Gemini Vision: wyczerpano modele ({len(chain)}) — "
            f"ostatni błąd: {type(last_err).__name__}"
        )
    return None


def _extract_votes_via_groq_vision(
    image_bytes: bytes,
    home_team: str,
    away_team: str,
    sport: str = 'football'
) -> Optional[Dict]:
    """
    Wyślij screenshot do Groq Vision API i wyekstraktuj fan vote.
    Fallback po Gemini.

    Returns:
        Dict z sofascore_home_win_prob, sofascore_draw_prob, etc. lub None
    """
    groq_module = _get_groq()
    if not groq_module:
        logger.debug("SofaScore AI Vision: groq module niedostępne")
        return None

    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        try:
            from groq_config import GROQ_API_KEY
            api_key = GROQ_API_KEY
        except ImportError:
            pass
    if not api_key:
        logger.debug("SofaScore AI Vision: Brak GROQ_API_KEY")
        return None

    try:
        client = groq_module.Groq(api_key=api_key)
    except Exception as e:
        print(f"   ⚠️ SofaScore Groq Vision: client init error: {type(e).__name__}: {e}")
        return None

    global _groq_active_vision_model
    prompt = _build_vision_prompt(home_team, away_team, sport)
    b64_image = base64.b64encode(image_bytes).decode('utf-8')

    chain = list(_GROQ_VISION_MODEL_CHAIN)
    if _groq_active_vision_model and _groq_active_vision_model in chain:
        chain.remove(_groq_active_vision_model)
        chain.insert(0, _groq_active_vision_model)

    last_err: Optional[BaseException] = None
    for model_name in chain:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': prompt},
                            {
                                'type': 'image_url',
                                'image_url': {
                                    'url': f'data:image/png;base64,{b64_image}',
                                },
                            },
                        ],
                    }
                ],
                max_tokens=256,
                temperature=0.1,
            )

            if not response or not response.choices:
                print(f"   ⚠️ SofaScore Groq Vision ({model_name}): pusta odpowiedź")
                continue

            text = response.choices[0].message.content or ''
            result = _parse_vision_response(text, sport)
            if result:
                _groq_active_vision_model = model_name
                print(f"   ✅ SofaScore Groq Vision ({model_name}): wyekstraktowano fan vote")
                return result
            print(f"   ⚠️ SofaScore Groq Vision ({model_name}): brak fan vote w screenshocie")
            logger.debug(f"Groq Vision raw ({model_name}): {text[:300]}")
            return None

        except Exception as e:
            last_err = e
            if _is_quota_or_rate_error(e):
                print(f"   🔁 SofaScore Groq Vision ({model_name}): quota/rate limit — rotuję")
                continue
            if _is_model_unavailable_error(e):
                print(f"   🔁 SofaScore Groq Vision ({model_name}): model niedostępny — rotuję")
                continue
            print(f"   ⚠️ SofaScore Groq Vision ({model_name}) błąd: {type(e).__name__}: {str(e)[:80]}")
            return None

    if last_err is not None:
        print(
            f"   ⚠️ SofaScore Groq Vision: wyczerpano modele ({len(chain)}) — "
            f"ostatni błąd: {type(last_err).__name__}"
        )
    return None


def extract_fan_vote_via_ai_vision(
    driver,
    event_url: str,
    home_team: str,
    away_team: str,
    sport: str = 'football'
) -> Optional[Dict]:
    """
    Orchestrator: screenshot → Gemini Vision → Groq Vision.

    Próbuje wyekstraktować fan vote z screenshota strony meczu
    używając AI Vision (Gemini preferowane, Groq jako fallback).

    Returns:
        Dict z sofascore_* kluczami lub None
    """
    print(f"   🤖 SofaScore AI Vision: Próbuję ekstrakcję ze screenshota...")

    # 1. Zrób screenshot
    screenshot = _take_fan_vote_screenshot(driver, event_url)
    if not screenshot:
        return None

    # 2. Próbuj Gemini Vision
    result = _extract_votes_via_gemini_vision(screenshot, home_team, away_team, sport)
    if result:
        return result

    # 3. Fallback: Groq Vision
    result = _extract_votes_via_groq_vision(screenshot, home_team, away_team, sport)
    if result:
        return result

    print(f"   ⚠️ SofaScore AI Vision: Żadne AI nie wyekstraktowało fan vote")
    return None


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
    # METODA 1: Bezpośredni API (bez Selenium)
    # =============================================
    event_id = None
    if REQUESTS_AVAILABLE and not _api_circuit_breaker_tripped:
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
    # METODA 2: Browser API Fetch (v7.0 — bypass WAF)
    # =============================================
    # Cloudflare blokuje curl/requests z 403, ale same-origin fetch()
    # z kontekstu przeglądarki przechodzi. Otwieramy sofascore.com
    # w headless Chrome i robimy fetch() przez JS.
    # v7.1 — Specific Change 2: gate the path on _SOFASCORE_BROWSER_FETCH_ENABLED
    # (defaults to IS_CI). Local runs without GITHUB_ACTIONS / CI keep the
    # curl_cffi fast path as primary so clause 3.1 stays bit-for-bit.
    if (
        SELENIUM_AVAILABLE
        and _SOFASCORE_BROWSER_FETCH_ENABLED
        and _browser_api_failed_count < _BROWSER_API_MAX_FAILURES
    ):
        print(f"   🌐 SofaScore: Browser API Fetch (bypass WAF)...")
        browser_event_id = event_id  # reuse if found above
        if not browser_event_id:
            browser_event_id = _search_event_via_browser(home_team, away_team, sport, date_str)

        if browser_event_id:
            browser_votes = _get_votes_via_browser(browser_event_id, sport)
            if browser_votes and browser_votes.get('sofascore_home_win_prob') is not None:
                result.update(browser_votes)
                sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
                result['sofascore_url'] = f"https://www.sofascore.com/{sport_slug}/match/{browser_event_id}"
                result['sofascore_found'] = True
                draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
                print(f"   ✅ Fan Vote (Browser API): 🏠{result['sofascore_home_win_prob']}% | "
                      f"{draw_str}✈️{result['sofascore_away_win_prob']}% "
                      f"({result['sofascore_total_votes']:,} głosów)")
                if use_cache:
                    _set_cached_result(home_team, away_team, sport, result)
                return result
            elif browser_event_id and not event_id:
                event_id = browser_event_id  # zachowaj na wypadek AI Vision

        # =============================================
        # METODA 2.5: Groq Event Resolver (v7.2 — LLM-assisted match)
        # =============================================
        # `_search_event_via_browser` używa similarity_score na łacinkowych
        # tokenach; potyka się o aliasy PL↔EN, transliteracje cyrylica→łacina
        # i nazwy z prefiksami sponsora. Groq dostaje listę kandydatów ze
        # scheduled-events i wybiera prawidłowy event_id.
        if not event_id:
            try:
                groq_event_id = _resolve_event_via_groq(
                    home_team, away_team, sport, date_str
                )
            except Exception as e:
                logger.debug(
                    f"METODA 2.5 (Groq Resolver) error: {type(e).__name__}: {e}"
                )
                groq_event_id = None

            if groq_event_id:
                event_id = groq_event_id
                # Spróbuj jeszcze raz fan-vote przez Browser API z odzyskanym id
                browser_votes_retry = _get_votes_via_browser(groq_event_id, sport)
                if (
                    browser_votes_retry
                    and browser_votes_retry.get('sofascore_home_win_prob') is not None
                ):
                    result.update(browser_votes_retry)
                    sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
                    result['sofascore_url'] = (
                        f"https://www.sofascore.com/{sport_slug}/match/{groq_event_id}"
                    )
                    result['sofascore_found'] = True
                    draw_str = (
                        f"🤝{result['sofascore_draw_prob']}% | "
                        if result['sofascore_draw_prob'] else ""
                    )
                    print(
                        f"   ✅ Fan Vote (Browser API + Groq Resolver): "
                        f"🏠{result['sofascore_home_win_prob']}% | {draw_str}"
                        f"✈️{result['sofascore_away_win_prob']}% "
                        f"({result['sofascore_total_votes']:,} głosów)"
                    )
                    if use_cache:
                        _set_cached_result(home_team, away_team, sport, result)
                    return result

        # =============================================
        # METODA 3: Browser HTML fallback (v7.1 — Specific Change 5)
        # =============================================
        # Same-origin fetch() returned no votes (or no event id at all):
        # navigate the singleton driver to the rendered match page (via
        # `find_match_on_main_page` if needed) and parse percentages from
        # the DOM via `extract_votes_from_page`. Satisfies clause 2.4 — the
        # rendered HTML path no longer needs a numeric API event id.
        try:
            html_votes = _get_votes_via_browser_html(
                home_team, away_team, sport, event_id=event_id
            )
        except Exception as e:
            logger.debug(
                f"METODA 3 (_get_votes_via_browser_html) error: {type(e).__name__}: {e}"
            )
            html_votes = None

        if html_votes and html_votes.get('sofascore_home_win_prob') is not None:
            html_url = html_votes.pop('sofascore_url', None)
            result.update(html_votes)
            if html_url:
                result['sofascore_url'] = html_url
            elif event_id:
                sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
                result['sofascore_url'] = f"https://www.sofascore.com/{sport_slug}/match/{event_id}"
            result['sofascore_found'] = True
            draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
            total_str = (
                f" ({result['sofascore_total_votes']:,} głosów)"
                if result.get('sofascore_total_votes')
                else ""
            )
            print(
                f"   ✅ Fan Vote (Browser HTML): 🏠{result['sofascore_home_win_prob']}% | "
                f"{draw_str}✈️{result['sofascore_away_win_prob']}%{total_str}"
            )
            if use_cache:
                _set_cached_result(home_team, away_team, sport, result)
            return result
    
    # =============================================
    # METODA AI VISION: Screenshot → Gemini/Groq (v6.0)
    # =============================================
    # Jeśli API nie zadziałało (403 / brak danych), ale mamy event_id,
    # próbuj AI Vision ze screenshotem strony meczu.
    if event_id and SELENIUM_AVAILABLE:
        sport_slug = SOFASCORE_SPORT_SLUGS.get(sport, 'football')
        event_url = f"https://www.sofascore.com/{sport_slug}/match/{event_id}"
        
        # Potrzebujemy drivera — stwórzmy tymczasowy
        _vision_driver = None
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-notifications')
            chrome_options.add_argument(f'--user-agent={API_HEADERS["User-Agent"]}')
            chrome_options.page_load_strategy = 'eager'

            chrome_bin = os.getenv('CHROME_BIN')
            if chrome_bin and os.path.exists(chrome_bin):
                chrome_options.binary_location = chrome_bin
            elif IS_CI:
                for candidate in (
                    '/usr/bin/google-chrome',
                    '/usr/bin/google-chrome-stable',
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser',
                ):
                    if os.path.exists(candidate):
                        chrome_options.binary_location = candidate
                        break

            chromedriver_path = os.getenv('CHROMEDRIVER_PATH')
            service = None
            if chromedriver_path and os.path.exists(chromedriver_path):
                service = Service(executable_path=chromedriver_path)
            elif IS_CI and os.path.exists('/usr/bin/chromedriver'):
                service = Service(executable_path='/usr/bin/chromedriver')

            if service:
                _vision_driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                _vision_driver = webdriver.Chrome(options=chrome_options)
            _vision_driver.set_page_load_timeout(15)
            _vision_driver.set_script_timeout(5)

            vision_result = extract_fan_vote_via_ai_vision(
                _vision_driver, event_url, home_team, away_team, sport
            )
            if vision_result and vision_result.get('sofascore_home_win_prob') is not None:
                result.update(vision_result)
                result['sofascore_url'] = event_url
                result['sofascore_found'] = True
                draw_str = f"🤝{result['sofascore_draw_prob']}% | " if result['sofascore_draw_prob'] else ""
                print(f"   ✅ Fan Vote (AI Vision): 🏠{result['sofascore_home_win_prob']}% | "
                      f"{draw_str}✈️{result['sofascore_away_win_prob']}%")
                if use_cache:
                    _set_cached_result(home_team, away_team, sport, result)
                return result
        except Exception as e:
            print(f"   ⚠️ SofaScore AI Vision: Błąd drivera: {type(e).__name__}: {e}")
        finally:
            if _vision_driver:
                try:
                    _vision_driver.quit()
                except Exception:
                    pass
    
    # =============================================
    # METODA WOLNA: Selenium (fallback)
    # ZAWSZE tworzy dedykowany driver z krótkim timeout
    # (nie używa zewnętrznego drivera który może mieć 60-120s timeout)
    # =============================================
    if _api_circuit_breaker_tripped:
        print("   🛑 SofaScore: Circuit breaker aktywny — pomijam (oszczędzam czas CI)")
        return result

    if not SELENIUM_AVAILABLE:
        print("   ❌ SofaScore: Selenium niedostępne, API nie znalazło meczu")
        return result
    
    # Circuit breaker: skip Selenium w CI po zbyt wielu failures
    global _selenium_failures, _selenium_last_reset
    if IS_CI and _selenium_failures >= _selenium_max_failures:
        # Reset co 5 minut
        if time.time() - _selenium_last_reset > _SELENIUM_RESET_INTERVAL:
            _selenium_failures = 0
            _selenium_last_reset = time.time()
            logger.debug("SofaScore Selenium circuit breaker: reset")
        else:
            print(f"   ⚠️ SofaScore: Selenium wyłączony (circuit breaker: {_selenium_failures} failures)")
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

        chrome_bin = os.getenv('CHROME_BIN')
        if chrome_bin and os.path.exists(chrome_bin):
            chrome_options.binary_location = chrome_bin
        elif IS_CI:
            for candidate in (
                '/usr/bin/google-chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/chromium',
                '/usr/bin/chromium-browser',
            ):
                if os.path.exists(candidate):
                    chrome_options.binary_location = candidate
                    break

        chromedriver_path = os.getenv('CHROMEDRIVER_PATH')
        service = None
        if chromedriver_path and os.path.exists(chromedriver_path):
            service = Service(executable_path=chromedriver_path)
        elif IS_CI and os.path.exists('/usr/bin/chromedriver'):
            service = Service(executable_path='/usr/bin/chromedriver')

        if service:
            sofascore_driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
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
            if IS_CI:
                _selenium_failures += 1
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
            if IS_CI:
                _selenium_failures += 1
            return result
        
        result = scrape_result[0]
        if use_cache and result.get('sofascore_found'):
            _set_cached_result(home_team, away_team, sport, result)
        return result
        
    except Exception as e:
        logger.error(f"SofaScore scraping error: {type(e).__name__}: {e}")
        print(f"   ❌ SofaScore scraping error: {e}")
        if IS_CI:
            _selenium_failures += 1
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
