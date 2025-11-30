"""
🔥 CLOUDFLARE BYPASS - ULTRA POWER MODE 🔥
==========================================
Agresywne techniki omijania Cloudflare dla GitHub Actions.

Metody:
1. FlareSolverr (Docker service - najlepsza dla CI/CD!)
2. DrissionPage (najnowsza biblioteka anti-detection)
3. Playwright z stealth
4. curl_cffi (TLS fingerprint jak przeglądarka)
5. Requests z Cloudflare scraper
6. Selenium undetected + random delays
7. httpx z HTTP/2
"""

import os
import time
import random
import json
import subprocess
import requests
from typing import Optional, Dict, Any

# Detekcja CI/CD (GitHub Actions)
IS_CI = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'

# FlareSolverr URL (Docker service)
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')

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

# Metoda 0: FlareSolverr (zawsze dostępna jeśli serwer działa)
METHODS_AVAILABLE['flaresolverr'] = True  # Sprawdzamy dostępność przy wywołaniu
METHODS_AVAILABLE['flaresolverr_session'] = True  # Wersja z sesją

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
        
        # W CI/CD - FlareSolverr jako PIERWSZA metoda (najlepsza!)
        # Lokalnie - standardowe metody
        if IS_CI:
            methods = [
                ('flaresolverr', self._try_flaresolverr),  # 🔥 NAJLEPSZA dla CI/CD
                ('flaresolverr_session', self._try_flaresolverr_with_session),  # 🔥 Wersja z sesją (retry)
                ('curl_cffi', self._try_curl_cffi),
                ('cloudscraper', self._try_cloudscraper),
                ('drissionpage', self._try_drissionpage),
                ('playwright', self._try_playwright),
                ('undetected', self._try_undetected_chrome),
                ('httpx', self._try_httpx),
            ]
        else:
            methods = [
                ('undetected', self._try_undetected_chrome),  # Lokalnie najlepsza
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
        """
        try:
            self.log(f"🐳 Łączę z FlareSolverr: {FLARESOLVERR_URL}")
            
            # 🔥 Forebet wymaga dłuższego czasu - 120 sekund!
            # Challenge może trwać długo
            flare_timeout = max(timeout * 1000, 120000)  # min 120 sekund
            
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": flare_timeout
            }
            
            response = requests.post(
                FLARESOLVERR_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=180  # 3 minuty na całość
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
                        
                        # Forebet content indicators - muszą być PRAWDZIWE elementy strony
                        # Sprawdzamy czy są w <body>, nie w skryptach
                        has_rcnt = '<div class="rcnt"' in html or 'class="rcnt"' in html
                        has_forepr = 'class="forepr"' in html or 'class="fprc"' in html
                        has_match_rows = 'class="tr_0"' in html or 'class="tr_1"' in html
                        has_schema = 'class="schema' in html
                        
                        is_forebet_page = has_rcnt or has_forepr or has_match_rows or has_schema
                        
                        # 🔥 KLUCZOWE: Jeśli są elementy Cloudflare challenge - to FAIL!
                        if is_cloudflare_challenge:
                            self.log(f"⚠️ FlareSolverr: Strona zawiera Cloudflare challenge!")
                            self.log(f"   loading-verifying={has_loading_verifying}, lds-ring={has_lds_ring}")
                            self.log(f"   checking_browser={has_checking_browser}, verifying_human={has_verifying_human}")
                            return None  # Zwróć None żeby próbować inne metody
                        
                        # Jeśli nie ma Cloudflare ale też nie ma Forebet - ostrzeżenie
                        if not is_forebet_page:
                            self.log(f"⚠️ FlareSolverr: Brak elementów Forebet w HTML!")
                            self.log(f"   rcnt={has_rcnt}, forepr={has_forepr}, match_rows={has_match_rows}")
                            # Mimo to zwróć do dalszej analizy
                        
                        self.log(f"🐳 FlareSolverr SUCCESS! ({len(html)} znaków)")
                        
                        # Zapisz cookies do przyszłego użycia
                        cookies = solution.get("cookies", [])
                        user_agent = solution.get("userAgent", "")
                        
                        if cookies:
                            self.log(f"🍪 Otrzymano {len(cookies)} cookies")
                        
                        # Dodatkowa weryfikacja - czy to na pewno Forebet?
                        if is_forebet_page:
                            self.log(f"✅ Potwierdzona strona Forebet (znaleziono elementy meczów)")
                        else:
                            self.log(f"⚠️ Strona nie wygląda jak Forebet, ale zwracam HTML do analizy")
                        
                        return html
                    else:
                        self.log("⚠️ FlareSolverr: pusta odpowiedź")
                else:
                    error_msg = data.get("message", "Unknown error")
                    self.log(f"⚠️ FlareSolverr error: {error_msg}")
            else:
                self.log(f"⚠️ FlareSolverr HTTP {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            self.log("⚠️ FlareSolverr: serwer niedostępny (nie działa Docker?)")
        except requests.exceptions.Timeout:
            self.log("⚠️ FlareSolverr: timeout")
        except Exception as e:
            self.log(f"⚠️ FlareSolverr error: {str(e)[:50]}")
        
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
            driver.quit()
    
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
    
    def close(self):
        """Zamknij zasoby"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass


def fetch_forebet_with_bypass(url: str, debug: bool = True) -> Optional[str]:
    """
    Główna funkcja - pobiera stronę Forebet omijając Cloudflare
    
    Returns:
        HTML strony lub None jeśli się nie udało
    """
    bypass = CloudflareBypass(debug=debug)
    
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
