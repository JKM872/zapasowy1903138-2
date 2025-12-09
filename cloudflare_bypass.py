"""
🔥 CLOUDFLARE BYPASS - ULTRA POWER MODE 🔥
==========================================
Agresywne techniki omijania Cloudflare dla GitHub Actions.

Metody (w kolejności próbowania):
1. Puppeteer Stealth (Node.js) - najskuteczniejsza!
2. FlareSolverr (Docker service)
3. FlareSolverr z sesją (retry)
4. curl_cffi (TLS fingerprint)
5. cloudscraper
6. Zenrows API (free tier)
7. ScraperAPI (free tier) 
8. DrissionPage
9. Playwright stealth
10. Selenium undetected
11. httpx HTTP/2
12. Archive.org cache (fallback)
"""

import os
import sys
import time
import random
import json
import subprocess
import requests
from typing import Optional, Dict, Any

# Patch for undetected_chromedriver WinError 6 on Windows
# This must be done BEFORE importing undetected_chromedriver
if sys.platform == 'win32':
    _original_excepthook = sys.excepthook
    def _patched_excepthook(exc_type, exc_val, exc_tb):
        if exc_type is OSError and 'WinError 6' in str(exc_val):
            pass  # Suppress WinError 6 "Invalid handle"
        else:
            _original_excepthook(exc_type, exc_val, exc_tb)
    sys.excepthook = _patched_excepthook

# Detekcja CI/CD (GitHub Actions)
IS_CI = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'

# FlareSolverr URL (Docker service)
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')

# API Keys (można ustawić jako secrets w GitHub Actions)
ZENROWS_API_KEY = os.environ.get('ZENROWS_API_KEY', '')
SCRAPERAPI_KEY = os.environ.get('SCRAPERAPI_KEY', '')
SCRAPINGBEE_KEY = os.environ.get('SCRAPINGBEE_KEY', '')

# Xvfb helper dla CI/CD
_xvfb_process = None

def start_xvfb():
    """Uruchom Xvfb virtual display dla CI/CD"""
    global _xvfb_process
    if IS_CI and _xvfb_process is None:
        try:
            # Sprawdź czy Xvfb jest dostępny
            subprocess.run(['which', 'Xvfb'], check=True, capture_output=True)
            
            # Uruchom Xvfb na display :99
            _xvfb_process = subprocess.Popen(
                ['Xvfb', ':99', '-screen', '0', '1920x1080x24'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            os.environ['DISPLAY'] = ':99'
            time.sleep(1)  # Daj czas na start
            print("      🖥️ Xvfb virtual display started for bypass")
            return True
        except Exception as e:
            print(f"      ⚠️ Xvfb nie dostępny: {e}")
            return False
    return True

def stop_xvfb():
    """Zatrzymaj Xvfb"""
    global _xvfb_process
    if _xvfb_process:
        _xvfb_process.terminate()
        _xvfb_process = None

# Sprawdź dostępne metody
METHODS_AVAILABLE = {}

# Metoda 0: Puppeteer Stealth (Node.js) - najskuteczniejsza!
METHODS_AVAILABLE['puppeteer'] = True  # Wymaga Node.js i npm

# Metoda 1: FlareSolverr (zawsze dostępna jeśli serwer działa)
METHODS_AVAILABLE['flaresolverr'] = True
METHODS_AVAILABLE['flaresolverr_session'] = True

# Metoda 2: API services (jeśli skonfigurowane)
METHODS_AVAILABLE['zenrows'] = bool(ZENROWS_API_KEY)
METHODS_AVAILABLE['scraperapi'] = bool(SCRAPERAPI_KEY)
METHODS_AVAILABLE['scrapingbee'] = bool(SCRAPINGBEE_KEY)

# Metoda 3: Archive.org (zawsze dostępna jako fallback)
METHODS_AVAILABLE['archive'] = True

# Metoda 1: DrissionPage
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    METHODS_AVAILABLE['drissionpage'] = True
except ImportError:
    METHODS_AVAILABLE['drissionpage'] = False

# Metoda 2: Playwright
try:
    from playwright.sync_api import sync_playwright
    METHODS_AVAILABLE['playwright'] = True
except ImportError:
    METHODS_AVAILABLE['playwright'] = False

# Metoda 3: curl_cffi
try:
    from curl_cffi import requests as curl_requests
    METHODS_AVAILABLE['curl_cffi'] = True
except ImportError:
    METHODS_AVAILABLE['curl_cffi'] = False

# Metoda 4: cloudscraper
try:
    import cloudscraper
    METHODS_AVAILABLE['cloudscraper'] = True
except ImportError:
    METHODS_AVAILABLE['cloudscraper'] = False

# Metoda 5: undetected_chromedriver
try:
    import undetected_chromedriver as uc
    METHODS_AVAILABLE['undetected'] = True
    
    # Patch quit() and __del__() to suppress WinError 6 on Windows
    if sys.platform == 'win32':
        _original_quit = uc.Chrome.quit
        def _patched_quit(self):
            try:
                _original_quit(self)
            except OSError:
                pass  # Suppress WinError 6
            except Exception:
                pass
        uc.Chrome.quit = _patched_quit
        
        def _patched_del(self):
            try:
                self.quit()
            except Exception:
                pass
        uc.Chrome.__del__ = _patched_del
        
except ImportError:
    METHODS_AVAILABLE['undetected'] = False

# Metoda 6: httpx z custom headers
try:
    import httpx
    METHODS_AVAILABLE['httpx'] = True
except ImportError:
    METHODS_AVAILABLE['httpx'] = False


def get_random_user_agent() -> str:
    """Zwraca losowy, aktualny User-Agent"""
    agents = [
        # Chrome Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        # Chrome Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        # Firefox
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
        # Edge
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
    ]
    return random.choice(agents)


def get_browser_headers() -> Dict[str, str]:
    """Zwraca nagłówki imitujące prawdziwą przeglądarkę"""
    return {
        'User-Agent': get_random_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }


def human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """Losowe opóźnienie symulujące człowieka"""
    time.sleep(random.uniform(min_sec, max_sec))


# 🍪 CONSENT BUTTON SELECTORS (różne wersje)
CONSENT_SELECTORS = [
    # FundingChoices (Google) - Forebet używa tego
    'button.fc-cta-consent',
    'button.fc-button.fc-cta-consent',
    '.fc-cta-consent',
    # GDPR consent
    'button[data-cookiefirst-action="accept"]',
    '#onetrust-accept-btn-handler',
    '.onetrust-accept-btn-handler',
    '#accept-cookies',
    '.accept-cookies',
    '#cookie-accept',
    '.cookie-accept',
    'button[id*="accept"]',
    'button[class*="accept"]',
    # Generic
    'button:contains("Accept")',
    'button:contains("Agree")',
    'button:contains("Zgadzam")',
    'button:contains("Akceptuj")',
    'a.agree-button',
    '.agree-button',
    '#agree-button',
]


class CloudflareBypass:
    """Ultra-power Cloudflare bypass"""
    
    def __init__(self, debug: bool = True):
        self.debug = debug
        self.session = None
        self.driver = None
        self.method_used = None
        
    def log(self, msg: str):
        if self.debug:
            print(f"      🔥 CF-Bypass: {msg}")
    
    def _click_consent_selenium(self, driver):
        """Kliknij przycisk consent/cookie jeśli istnieje (Selenium/UC)"""
        from selenium.webdriver.common.by import By
        
        consent_clicked = False
        
        # Priorytetowe selektory dla Forebet (FundingChoices)
        priority_selectors = [
            (By.CSS_SELECTOR, 'button.fc-cta-consent'),
            (By.CSS_SELECTOR, '.fc-cta-consent'),
            (By.CSS_SELECTOR, 'button.fc-button.fc-cta-consent'),
        ]
        
        # Najpierw spróbuj priorytetowych
        for by, selector in priority_selectors:
            try:
                buttons = driver.find_elements(by, selector)
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        self.log(f"🍪 Klikam consent: {selector}")
                        btn.click()
                        human_delay(1, 2)
                        consent_clicked = True
                        break
                if consent_clicked:
                    break
            except Exception:
                pass
        
        if consent_clicked:
            return True
        
        # Fallback - szukaj po tekście
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                try:
                    text = btn.text.lower()
                    if any(word in text for word in ['zgadzam', 'accept', 'agree', 'akceptuj', 'consent']):
                        if btn.is_displayed() and btn.is_enabled():
                            self.log(f"🍪 Klikam consent (text match): {btn.text[:30]}")
                            btn.click()
                            human_delay(1, 2)
                            return True
                except Exception:
                    pass
        except Exception:
            pass
        
        return False
    
    def get_page(self, url: str, timeout: int = 30) -> Optional[str]:
        """
        Pobiera stronę omijając Cloudflare.
        Próbuje kolejnych metod aż jedna zadziała.
        """
        
        # Uruchom Xvfb jeśli w CI/CD (dla metod przeglądarkowych)
        if IS_CI:
            start_xvfb()
        
        # 🔥 W CI/CD - FlareSolverr PIERWSZA (Puppeteer nie działa na GitHub Actions!)
        if IS_CI:
            methods = [
                ('flaresolverr', self._try_flaresolverr),  # 🔥 DZIAŁA W CI/CD!
                ('flaresolverr_session', self._try_flaresolverr_with_session),
                ('zenrows', self._try_zenrows),  # API services
                ('scraperapi', self._try_scraperapi),
                ('scrapingbee', self._try_scrapingbee),
                # Puppeteer pominięty - nie działa na GitHub Actions
                ('curl_cffi', self._try_curl_cffi),
                ('cloudscraper', self._try_cloudscraper),
                ('archive', self._try_archive),  # Fallback
            ]
        else:
            methods = [
                ('undetected', self._try_undetected_chrome),  # Lokalnie najlepsza
                ('puppeteer', self._try_puppeteer),
                ('flaresolverr', self._try_flaresolverr),
                ('curl_cffi', self._try_curl_cffi),
                ('cloudscraper', self._try_cloudscraper),
                ('drissionpage', self._try_drissionpage),
                ('playwright', self._try_playwright),
                ('httpx', self._try_httpx),
            ]
        
        try:
            for method_name, method_func in methods:
                if not METHODS_AVAILABLE.get(method_name, False):
                    self.log(f"{method_name}: niedostępny, pomijam")
                    continue
                
                self.log(f"Próbuję metodę: {method_name}")
                
                try:
                    html = method_func(url, timeout)
                    if html and len(html) > 1000:
                        # Sprawdź czy to nie Cloudflare challenge
                        html_lower = html.lower()
                        is_challenge = (
                            'checking your browser' in html_lower or 
                            'verifying you are human' in html_lower or
                            'just a moment' in html_lower or
                            'cloudflare' in html[:1000].lower() or
                            'loading-verifying' in html or
                            'lds-ring' in html
                        )
                        
                        if not is_challenge:
                            self.method_used = method_name
                            self.log(f"✅ SUKCES z metodą: {method_name}")
                            return html
                        else:
                            self.log(f"⚠️ {method_name}: Cloudflare challenge wykryty, strona nie przeszła")
                    else:
                        self.log(f"⚠️ {method_name}: za krótka odpowiedź ({len(html) if html else 0} znaków)")
                except Exception as e:
                    self.log(f"❌ {method_name}: {str(e)[:50]}")
            
            self.log("❌ Wszystkie metody zawiodły!")
            return None
        finally:
            # Zatrzymaj Xvfb jeśli uruchomiony
            if IS_CI:
                stop_xvfb()
    
    def _try_flaresolverr(self, url: str, timeout: int) -> Optional[str]:
        """
        🔥 FlareSolverr - Docker service do omijania Cloudflare
        Najlepsza metoda dla CI/CD! Działa przez HTTP API.
        Próbuje 3 razy z rosnącym timeoutem.
        """
        # 🔥 Forebet wymaga DUŻO czasu - próbujemy 3 razy
        timeouts = [120000, 180000, 300000]  # 2, 3, 5 minut
        
        # 🍪 GDPR Consent cookies - Forebet używa FundingChoices (fc)
        consent_cookies = [
            {
                "name": "FCNEC",
                "value": "%5B%5B%22AKsRol8ZpxKNdC2MbqKzW3Fy3mlXdWXWLPQaKxR-xwT3vFJGFbvnEzqQHYB_mNAqkxfSZQvkVjVwxMkXxXxXxXx%22%5D%2Cnull%2C%5B%5D%5D",
                "domain": ".forebet.com"
            },
            {
                "name": "FCCDCF",  
                "value": "%5B%5B%22AKsRol8K5HbKRwEAAABKABkAAABKAEoAIABYAGAAaABwAHgAgACIAJAAmACgAKgAsAC4AMAA%22%5D%2Cnull%2C%5B%5D%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2C%5B%5B%5B%22https%3A%2F%2Fforebet.com%22%5D%2C%22null%22%5D%5D%5D",
                "domain": ".forebet.com"
            },
            {
                "name": "__gads",
                "value": "ID=00000000000:T=1705000000:RT=1705000000:S=ALNI_MaXxXxXxXxXxXx",
                "domain": ".forebet.com"
            },
            {
                "name": "__gpi",
                "value": "UID=00000000000:T=1705000000:RT=1705000000:S=ALNI_MaXxXxXxXxXxXx",  
                "domain": ".forebet.com"
            }
        ]
        
        for attempt, flare_timeout in enumerate(timeouts, 1):
            try:
                self.log(f"🐳 FlareSolverr (próba {attempt}/3, timeout: {flare_timeout//1000}s)")
                
                # 🍪 Wstrzyknij cookies consent w żądaniu
                payload = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": flare_timeout,
                    "cookies": consent_cookies  # 🔥 GDPR consent bypass!
                }
                
                response = requests.post(
                    FLARESOLVERR_URL,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=flare_timeout // 1000 + 60  # timeout + 60 sekund buffer
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("status") == "ok":
                        solution = data.get("solution", {})
                        html = solution.get("response", "")
                        
                        if html:
                            # 🔥 WERYFIKACJA: Sprawdź czy to prawdziwa strona, nie challenge!
                            html_lower = html.lower()
                            
                            # Cloudflare challenge indicators - jeśli są, to FAIL
                            has_loading_verifying = 'loading-verifying' in html
                            has_lds_ring = 'lds-ring' in html
                            has_checking_browser = 'checking your browser' in html_lower
                            has_verifying_human = 'verifying you are human' in html_lower
                            has_just_moment = 'just a moment' in html_lower
                            
                            is_cloudflare_challenge = (
                                has_loading_verifying or 
                                has_lds_ring or 
                                has_checking_browser or 
                                has_verifying_human or
                                has_just_moment
                            )
                            
                            # Forebet content indicators - MUSZĄ BYĆ OBECNE!
                            # Use flexible matching - HTML can have class="rcnt" or class='rcnt' or class=rcnt
                            has_rcnt = 'class="rcnt"' in html or "class='rcnt'" in html or 'class=rcnt' in html
                            has_forepr = 'forepr' in html or 'fprc' in html
                            has_match_rows = 'tr_0' in html or 'tr_1' in html
                            has_schema = 'schema' in html
                            has_homeTeam = 'homeTeam' in html  # Most reliable indicator
                            
                            is_forebet_page = has_rcnt or has_forepr or has_match_rows or has_schema or has_homeTeam
                            
                            # 🔥 NOWA LOGIKA: Wymaga POZYTYWNEJ WERYFIKACJI Forebet!
                            # Jeśli mamy Cloudflare indicators LUB brak Forebet indicators - FAIL!
                            
                            if is_cloudflare_challenge:
                                self.log(f"⚠️ Próba {attempt}: Cloudflare challenge (loading-verifying={has_loading_verifying}, lds-ring={has_lds_ring})")
                                if attempt < len(timeouts):
                                    self.log(f"   Próbuję ponownie z dłuższym timeout...")
                                    time.sleep(5)  # Krótka pauza
                                    continue
                                else:
                                    self.log(f"❌ Wszystkie próby wyczerpane - Cloudflare nie został ominięty")
                                    return None
                            
                            # 🔥 KRYTYCZNE: Wymaga elementów Forebet!
                            if not is_forebet_page:
                                self.log(f"⚠️ Próba {attempt}: Brak elementów Forebet (rcnt={has_rcnt}, tr_0/1={has_match_rows})")
                                if attempt < len(timeouts):
                                    self.log(f"   Próbuję ponownie z dłuższym timeout...")
                                    time.sleep(5)
                                    continue
                                else:
                                    self.log(f"❌ Wszystkie próby wyczerpane - brak elementów Forebet")
                                    return None
                            
                            # ✅ SUKCES: Ma elementy Forebet i NIE ma Cloudflare challenge!
                            self.log(f"🐳 FlareSolverr SUCCESS! ({len(html)} znaków)")
                            
                            cookies = solution.get("cookies", [])
                            if cookies:
                                self.log(f"🍪 Otrzymano {len(cookies)} cookies")
                            
                            self.log(f"✅ Potwierdzona strona Forebet (rcnt={has_rcnt}, tr_0/1={has_match_rows})")
                            
                            return html
                        else:
                            self.log("⚠️ FlareSolverr: pusta odpowiedź")
                    else:
                        error_msg = data.get("message", "Unknown error")
                        self.log(f"⚠️ FlareSolverr error: {error_msg}")
                else:
                    self.log(f"⚠️ FlareSolverr HTTP {response.status_code}")
                    
            except requests.exceptions.ConnectionError:
                self.log("⚠️ FlareSolverr: serwer niedostępny")
                return None  # Nie ma sensu próbować dalej
            except requests.exceptions.Timeout:
                self.log(f"⚠️ FlareSolverr: timeout próby {attempt}")
                continue  # Spróbuj z dłuższym timeout
            except Exception as e:
                self.log(f"⚠️ FlareSolverr error: {str(e)[:50]}")
                continue
        
        return None
    
    def _try_flaresolverr_with_session(self, url: str, timeout: int) -> Optional[str]:
        """
        🔥 FlareSolverr z sesją - tworzy sesję, rozwiązuje challenge, potem pobiera stronę
        Czasami challenge wymaga wielu prób.
        """
        import uuid
        session_id = f"forebet_{uuid.uuid4().hex[:8]}"
        
        try:
            self.log(f"🐳 FlareSolverr SESSION: Tworzę sesję {session_id}")
            
            # 1. Utwórz sesję
            create_payload = {
                "cmd": "sessions.create",
                "session": session_id
            }
            
            response = requests.post(
                FLARESOLVERR_URL,
                headers={"Content-Type": "application/json"},
                json=create_payload,
                timeout=30
            )
            
            if response.status_code != 200:
                self.log(f"⚠️ Nie można utworzyć sesji")
                return None
            
            # 2. Pobierz stronę z sesją (max 3 próby)
            for attempt in range(3):
                self.log(f"🐳 Próba {attempt + 1}/3 z sesją...")
                
                get_payload = {
                    "cmd": "request.get",
                    "url": url,
                    "session": session_id,
                    "maxTimeout": 120000  # 2 minuty
                }
                
                response = requests.post(
                    FLARESOLVERR_URL,
                    headers={"Content-Type": "application/json"},
                    json=get_payload,
                    timeout=180
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("status") == "ok":
                        solution = data.get("solution", {})
                        html = solution.get("response", "")
                        
                        if html:
                            # 🔥 Sprawdź czy to Cloudflare challenge (FAIL indicators)
                            is_challenge = (
                                'loading-verifying' in html or 
                                'lds-ring' in html or
                                'checking your browser' in html.lower() or
                                'verifying you are human' in html.lower()
                            )
                            
                            # Sprawdź czy to Forebet (musi być class= nie sam tekst)
                            is_forebet = (
                                'class="rcnt"' in html or 
                                'class="forepr"' in html or 
                                'class="tr_0"' in html or
                                'class="tr_1"' in html or
                                'class="schema' in html
                            )
                            
                            if is_challenge:
                                self.log(f"⚠️ Próba {attempt + 1}: Nadal Cloudflare challenge, czekam...")
                                time.sleep(5)  # Czekaj przed kolejną próbą
                            elif is_forebet:
                                self.log(f"✅ FlareSolverr SESSION SUCCESS! ({len(html)} znaków)")
                                self._cleanup_flaresolverr_session(session_id)
                                return html
                            else:
                                self.log(f"⚠️ Próba {attempt + 1}: Brak elementów Forebet, czekam...")
                                time.sleep(5)
            
            # Usuń sesję po nieudanych próbach
            self._cleanup_flaresolverr_session(session_id)
            
        except Exception as e:
            self.log(f"⚠️ FlareSolverr SESSION error: {str(e)[:50]}")
            self._cleanup_flaresolverr_session(session_id)
        
        return None
    
    def _cleanup_flaresolverr_session(self, session_id: str):
        """Usuń sesję FlareSolverr"""
        try:
            destroy_payload = {
                "cmd": "sessions.destroy",
                "session": session_id
            }
            requests.post(
                FLARESOLVERR_URL,
                headers={"Content-Type": "application/json"},
                json=destroy_payload,
                timeout=10
            )
        except:
            pass
    
    def _try_curl_cffi(self, url: str, timeout: int) -> Optional[str]:
        """curl_cffi - emuluje TLS fingerprint przeglądarki"""
        from curl_cffi import requests as curl_requests
        
        # Impersonate Chrome
        response = curl_requests.get(
            url,
            impersonate="chrome131",
            timeout=timeout,
            headers=get_browser_headers(),
            allow_redirects=True
        )
        
        if response.status_code == 200:
            return response.text
        return None
    
    def _try_cloudscraper(self, url: str, timeout: int) -> Optional[str]:
        """cloudscraper - rozwiązuje Cloudflare JavaScript challenge"""
        import cloudscraper
        
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            },
            delay=10
        )
        
        response = scraper.get(url, timeout=timeout, headers=get_browser_headers())
        
        if response.status_code == 200:
            return response.text
        return None
    
    def _try_drissionpage(self, url: str, timeout: int) -> Optional[str]:
        """DrissionPage - najnowsza biblioteka anti-detection"""
        from DrissionPage import ChromiumPage, ChromiumOptions
        
        co = ChromiumOptions()
        # NIE używaj headless - Cloudflare to wykrywa!
        co.set_argument('--disable-gpu')
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument(f'--user-agent={get_random_user_agent()}')
        co.set_argument('--window-size=1920,1080')
        
        # Wyłącz WebDriver detection
        co.set_pref('credentials_enable_service', False)
        co.set_pref('profile.password_manager_enabled', False)
        
        page = ChromiumPage(co)
        
        try:
            page.get(url, timeout=timeout)
            
            # 🔥 KLUCZOWE: Czekaj na rozwiązanie Cloudflare challenge
            max_wait = 30  # max 30 sekund na challenge
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                html = page.html
                
                # Sprawdź czy wciąż jesteśmy na stronie weryfikacji
                if 'Verifying you are human' in html or 'checking your browser' in html.lower() or 'Just a moment' in html:
                    self.log("⏳ Cloudflare challenge w toku, czekam...")
                    human_delay(2, 3)
                    continue
                
                # Sprawdź czy strona ma prawdziwe treści (mecze, typy bukmacherskie itp)
                if 'rcnt' in html or 'contentmiddle' in html or 'schema' in html or len(html) > 50000:
                    self.log("✅ Strona załadowana pomyślnie!")
                    break
                    
                human_delay(1, 2)
            
            # 🍪 KLIKNIJ CONSENT/COOKIE BUTTON (DrissionPage)
            self._click_consent_drissionpage(page)
            
            human_delay(1, 2)
            
            # Symulacja scrollowania
            for _ in range(3):
                page.scroll.down(random.randint(200, 400))
                human_delay(0.3, 0.7)
            
            html = page.html
            return html
        finally:
            page.quit()
    
    def _click_consent_drissionpage(self, page):
        """Kliknij przycisk consent/cookie (DrissionPage)"""
        selectors = [
            'button.fc-cta-consent',
            '.fc-cta-consent',
            'button.fc-button.fc-cta-consent',
        ]
        
        for selector in selectors:
            try:
                btn = page.ele(selector, timeout=2)
                if btn:
                    self.log(f"🍪 Klikam consent (DrissionPage): {selector}")
                    btn.click()
                    human_delay(1, 2)
                    return True
            except Exception:
                pass
        
        # Fallback - szukaj po tekście
        try:
            buttons = page.eles('tag:button')
            for btn in buttons:
                try:
                    text = btn.text.lower() if btn.text else ''
                    if any(word in text for word in ['zgadzam', 'accept', 'agree', 'akceptuj']):
                        self.log(f"🍪 Klikam consent (text): {btn.text[:30]}")
                        btn.click()
                        human_delay(1, 2)
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        
        return False
    
    def _try_playwright(self, url: str, timeout: int) -> Optional[str]:
        """Playwright z stealth mode"""
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Użyj Firefox (mniej wykrywalny) - NIE headless!
            browser = p.firefox.launch(headless=False)
            
            context = browser.new_context(
                user_agent=get_random_user_agent(),
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='Europe/Warsaw'
            )
            
            page = context.new_page()
            
            # Block unnecessary resources
            page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}", lambda route: route.abort())
            
            try:
                page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')
                
                # 🔥 Czekaj na rozwiązanie Cloudflare challenge
                max_wait = 30
                start_time = time.time()
                
                while time.time() - start_time < max_wait:
                    html = page.content()
                    
                    if 'Verifying you are human' in html or 'checking your browser' in html.lower() or 'Just a moment' in html:
                        self.log("⏳ Playwright: Cloudflare challenge w toku...")
                        human_delay(2, 3)
                        continue
                    
                    if 'rcnt' in html or 'contentmiddle' in html or len(html) > 50000:
                        break
                        
                    human_delay(1, 2)
                
                # 🍪 KLIKNIJ CONSENT/COOKIE BUTTON (Playwright)
                self._click_consent_playwright(page)
                
                human_delay(1, 2)
                
                # Symulacja ludzkiego zachowania
                page.mouse.move(random.randint(100, 500), random.randint(100, 500))
                human_delay(0.2, 0.5)
                
                # Scroll
                for _ in range(3):
                    page.mouse.wheel(0, random.randint(200, 400))
                    human_delay(0.3, 0.7)
                
                html = page.content()
                return html
            finally:
                browser.close()
    
    def _click_consent_playwright(self, page):
        """Kliknij przycisk consent/cookie (Playwright)"""
        selectors = [
            'button.fc-cta-consent',
            '.fc-cta-consent',
            'button.fc-button.fc-cta-consent',
        ]
        
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    self.log(f"🍪 Klikam consent (Playwright): {selector}")
                    btn.click()
                    human_delay(1, 2)
                    return True
            except Exception:
                pass
        
        # Fallback - szukaj po tekście
        try:
            for text in ['Zgadzam się', 'Accept', 'Agree', 'Akceptuję']:
                try:
                    btn = page.get_by_role('button', name=text)
                    if btn.is_visible():
                        self.log(f"🍪 Klikam consent (text): {text}")
                        btn.click()
                        human_delay(1, 2)
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        
        return False
    
    def _try_undetected_chrome(self, url: str, timeout: int) -> Optional[str]:
        """undetected_chromedriver z agresywnymi ustawieniami"""
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        options = uc.ChromeOptions()
        # NIE używaj headless - Cloudflare to wykrywa!
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument(f'--user-agent={get_random_user_agent()}')
        
        # Losowe rozdzielczości
        resolutions = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900)]
        width, height = random.choice(resolutions)
        options.add_argument(f'--window-size={width},{height}')
        
        driver = uc.Chrome(options=options, version_main=None)
        
        try:
            driver.get(url)
            
            # 🔥 Czekaj na rozwiązanie Cloudflare challenge
            max_wait = 30
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                html = driver.page_source
                
                if 'Verifying you are human' in html or 'checking your browser' in html.lower() or 'Just a moment' in html:
                    self.log("⏳ Undetected Chrome: Cloudflare challenge w toku...")
                    human_delay(2, 3)
                    continue
                
                if 'rcnt' in html or 'contentmiddle' in html or len(html) > 50000:
                    self.log("✅ Cloudflare challenge rozwiązany!")
                    break
                    
                human_delay(1, 2)
            
            # 🍪 KLIKNIJ CONSENT/COOKIE BUTTON jeśli istnieje
            self._click_consent_selenium(driver)
            
            human_delay(1, 2)
            
            # Symulacja scrollowania
            for _ in range(5):
                scroll_amount = random.randint(100, 300)
                driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                human_delay(0.2, 0.5)
            
            # Symulacja ruchu myszą (JavaScript)
            driver.execute_script("""
                var event = new MouseEvent('mousemove', {
                    'view': window,
                    'bubbles': true,
                    'cancelable': true,
                    'clientX': Math.random() * 500,
                    'clientY': Math.random() * 500
                });
                document.dispatchEvent(event);
            """)
            
            human_delay(1, 2)
            
            return driver.page_source
        finally:
            try:
                driver.quit()
            except OSError:
                # WinError 6 "Invalid handle" is common with undetected_chromedriver on Windows
                pass
            except Exception:
                pass
    
    def _try_httpx(self, url: str, timeout: int) -> Optional[str]:
        """httpx z HTTP/2 support"""
        import httpx
        
        with httpx.Client(
            http2=True,
            timeout=timeout,
            follow_redirects=True,
            headers=get_browser_headers()
        ) as client:
            response = client.get(url)
            if response.status_code == 200:
                return response.text
        return None
    
    def _try_puppeteer(self, url: str, timeout: int) -> Optional[str]:
        """
        🔥 Puppeteer Extra z Stealth Plugin (Node.js)
        Najskuteczniejsza metoda dla Cloudflare!
        """
        # Sprawdź sport z URL
        sport = 'football'
        if '/basketball/' in url:
            sport = 'basketball'
        elif '/tennis/' in url:
            sport = 'tennis'
        elif '/volleyball/' in url:
            sport = 'volleyball'
        elif '/handball/' in url:
            sport = 'handball'
        elif '/hockey/' in url:
            sport = 'hockey'
        
        output_file = f'forebet_{sport}_puppeteer.html'
        
        try:
            self.log(f"🚀 Puppeteer Stealth: Uruchamiam...")
            
            # Sprawdź czy Node.js jest dostępny
            result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                self.log("⚠️ Node.js nie jest dostępny")
                return None
            
            # Sprawdź czy plik forebet_puppeteer.js istnieje
            if not os.path.exists('forebet_puppeteer.js'):
                self.log("⚠️ Brak pliku forebet_puppeteer.js")
                return None
            
            # Sprawdź czy dependencies są zainstalowane
            if not os.path.exists('node_modules/puppeteer-extra'):
                self.log("📦 Instaluję puppeteer-extra...")
                subprocess.run(['npm', 'install'], capture_output=True, timeout=180)
            
            # Uruchom Puppeteer scraper
            result = subprocess.run(
                ['node', 'forebet_puppeteer.js', sport, output_file],
                capture_output=True,
                text=True,
                timeout=300  # 5 minut timeout
            )
            
            # Sprawdź output
            if 'SUKCES' in result.stdout or 'SUCCESS' in result.stdout:
                if os.path.exists(output_file):
                    with open(output_file, 'r', encoding='utf-8') as f:
                        html = f.read()
                    
                    # Weryfikacja
                    if self._is_forebet_content(html) and not self._is_cloudflare_challenge(html):
                        self.log(f"✅ Puppeteer SUCCESS! ({len(html)} znaków)")
                        return html
            
            self.log(f"⚠️ Puppeteer nie zadziałał")
            return None
            
        except subprocess.TimeoutExpired:
            self.log("⚠️ Puppeteer: Timeout")
            return None
        except FileNotFoundError:
            self.log("⚠️ Puppeteer: Node.js nie znaleziony")
            return None
        except Exception as e:
            self.log(f"⚠️ Puppeteer error: {str(e)[:50]}")
            return None
    
    def _try_zenrows(self, url: str, timeout: int) -> Optional[str]:
        """
        ZenRows API - darmowy tier 1000 requestów/miesiąc
        https://www.zenrows.com/
        """
        if not ZENROWS_API_KEY:
            return None
        
        try:
            self.log(f"🌐 ZenRows API...")
            
            api_url = "https://api.zenrows.com/v1/"
            params = {
                'apikey': ZENROWS_API_KEY,
                'url': url,
                'js_render': 'true',
                'antibot': 'true',
                'premium_proxy': 'true'
            }
            
            response = requests.get(api_url, params=params, timeout=timeout + 30)
            
            if response.status_code == 200:
                html = response.text
                if self._is_forebet_content(html) and not self._is_cloudflare_challenge(html):
                    self.log(f"✅ ZenRows SUCCESS! ({len(html)} znaków)")
                    return html
            
            self.log(f"⚠️ ZenRows HTTP {response.status_code}")
            return None
            
        except Exception as e:
            self.log(f"⚠️ ZenRows error: {str(e)[:50]}")
            return None
    
    def _try_scraperapi(self, url: str, timeout: int) -> Optional[str]:
        """
        ScraperAPI - darmowy tier 5000 requestów/miesiąc
        https://www.scraperapi.com/
        """
        if not SCRAPERAPI_KEY:
            return None
        
        try:
            self.log(f"🌐 ScraperAPI...")
            
            api_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={url}&render=true&country_code=us"
            
            response = requests.get(api_url, timeout=timeout + 60)
            
            if response.status_code == 200:
                html = response.text
                if self._is_forebet_content(html) and not self._is_cloudflare_challenge(html):
                    self.log(f"✅ ScraperAPI SUCCESS! ({len(html)} znaków)")
                    return html
            
            self.log(f"⚠️ ScraperAPI HTTP {response.status_code}")
            return None
            
        except Exception as e:
            self.log(f"⚠️ ScraperAPI error: {str(e)[:50]}")
            return None
    
    def _try_scrapingbee(self, url: str, timeout: int) -> Optional[str]:
        """
        ScrapingBee API - darmowy tier 1000 requestów/miesiąc
        https://www.scrapingbee.com/
        """
        if not SCRAPINGBEE_KEY:
            return None
        
        try:
            self.log(f"🌐 ScrapingBee API...")
            
            api_url = "https://app.scrapingbee.com/api/v1/"
            params = {
                'api_key': SCRAPINGBEE_KEY,
                'url': url,
                'render_js': 'true',
                'premium_proxy': 'true',
                'stealth_proxy': 'true'
            }
            
            response = requests.get(api_url, params=params, timeout=timeout + 60)
            
            if response.status_code == 200:
                html = response.text
                if self._is_forebet_content(html) and not self._is_cloudflare_challenge(html):
                    self.log(f"✅ ScrapingBee SUCCESS! ({len(html)} znaków)")
                    return html
            
            self.log(f"⚠️ ScrapingBee HTTP {response.status_code}")
            return None
            
        except Exception as e:
            self.log(f"⚠️ ScrapingBee error: {str(e)[:50]}")
            return None
    
    def _try_archive(self, url: str, timeout: int) -> Optional[str]:
        """
        Archive.org Wayback Machine - jako fallback
        Zwraca najnowszą zarchiwizowaną wersję strony
        """
        try:
            self.log(f"📦 Archive.org (fallback)...")
            
            # Sprawdź czy jest dostępna wersja
            check_url = f"https://archive.org/wayback/available?url={url}"
            response = requests.get(check_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                snapshots = data.get('archived_snapshots', {})
                closest = snapshots.get('closest', {})
                
                if closest.get('available'):
                    archive_url = closest.get('url')
                    timestamp = closest.get('timestamp', '')
                    
                    self.log(f"📦 Znaleziono snapshot z {timestamp[:8]}")
                    
                    # Pobierz zarchiwizowaną stronę
                    archive_response = requests.get(archive_url, timeout=timeout)
                    
                    if archive_response.status_code == 200:
                        html = archive_response.text
                        
                        # Archive.org może nie mieć aktualnych danych, ale przynajmniej coś zwróci
                        if len(html) > 5000:
                            self.log(f"📦 Archive.org: ({len(html)} znaków) - UWAGA: może być nieaktualne!")
                            return html
            
            self.log("⚠️ Archive.org: brak dostępnej wersji")
            return None
            
        except Exception as e:
            self.log(f"⚠️ Archive.org error: {str(e)[:50]}")
            return None
    
    def _is_cloudflare_challenge(self, html: str) -> bool:
        """Sprawdź czy HTML to strona Cloudflare challenge"""
        if not html:
            return True
        
        html_lower = html.lower()
        return (
            'loading-verifying' in html or
            'lds-ring' in html or
            'checking your browser' in html_lower or
            'verifying you are human' in html_lower or
            'just a moment' in html_lower
        )
    
    def _is_forebet_content(self, html: str) -> bool:
        """Sprawdź czy HTML zawiera prawdziwe dane Forebet"""
        if not html:
            return False
        
        return (
            'class="rcnt"' in html or
            'class="forepr"' in html or
            'class="fprc"' in html or
            'class="tr_0"' in html or
            'class="tr_1"' in html or
            'class="schema' in html
        )
    
    def close(self):
        """Zamknij zasoby"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass


def fetch_forebet_with_bypass(url: str, debug: bool = True, sport: str = None) -> Optional[str]:
    """
    Główna funkcja - pobiera stronę Forebet omijając Cloudflare
    
    Args:
        url: URL strony do pobrania
        debug: Czy wypisywać debug info
        sport: Opcjonalny sport (do przyszłej optymalizacji per-sport sessions)
    
    Returns:
        HTML strony lub None jeśli się nie udało
    """
    bypass = CloudflareBypass(debug=debug)
    
    # 🔥 Loguj sport jeśli podany
    if sport and debug:
        print(f"      🔥 CF-Bypass: Pobieranie dla sportu: {sport}")
    
    try:
        html = bypass.get_page(url, timeout=30)
        
        if html:
            if debug:
                print(f"      🔥 Sukces! Użyto metody: {bypass.method_used}")
                print(f"      🔥 Rozmiar HTML: {len(html)} znaków")
            return html
        else:
            if debug:
                print(f"      ❌ Nie udało się pobrać strony")
            return None
            
    finally:
        bypass.close()


def print_available_methods():
    """Wyświetla dostępne metody bypass"""
    print("\n🔥 CLOUDFLARE BYPASS - Dostępne metody:")
    print("=" * 50)
    for method, available in METHODS_AVAILABLE.items():
        status = "✅ DOSTĘPNA" if available else "❌ brak"
        print(f"  {method}: {status}")
    print("=" * 50)


# Test
if __name__ == '__main__':
    print_available_methods()
    
    test_url = "https://www.forebet.com/en/football-tips-and-predictions-for-today"
    print(f"\n🔥 Testuję bypass dla: {test_url}\n")
    
    html = fetch_forebet_with_bypass(test_url)
    
    if html:
        print(f"\n✅ SUKCES! Pobrano {len(html)} znaków")
        
        # Zapisz do pliku
        with open('cf_bypass_test.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"💾 Zapisano do cf_bypass_test.html")
        
        # Sprawdź czy są mecze
        if 'rcnt' in html or 'homeTeam' in html:
            print("✅ HTML zawiera dane meczów!")
        else:
            print("⚠️ HTML może nie zawierać danych meczów")
    else:
        print("\n❌ PORAŻKA - nie udało się ominąć Cloudflare")
