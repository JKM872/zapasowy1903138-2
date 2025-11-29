"""
🔥 CLOUDFLARE BYPASS - ULTRA POWER MODE 🔥
==========================================
Agresywne techniki omijania Cloudflare dla GitHub Actions.

Metody:
1. DrissionPage (najnowsza biblioteka anti-detection)
2. Playwright z stealth
3. curl_cffi (TLS fingerprint jak przeglądarka)
4. Requests z Cloudflare scraper
5. Selenium undetected + random delays
6. Puppeteer-like behavior simulation
"""

import os
import time
import random
import json
import subprocess
from typing import Optional, Dict, Any

# Detekcja CI/CD (GitHub Actions)
IS_CI = os.environ.get('CI') == 'true' or os.environ.get('GITHUB_ACTIONS') == 'true'

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
    
    def get_page(self, url: str, timeout: int = 30) -> Optional[str]:
        """
        Pobiera stronę omijając Cloudflare.
        Próbuje kolejnych metod aż jedna zadziała.
        """
        
        # Uruchom Xvfb jeśli w CI/CD
        if IS_CI:
            start_xvfb()
        
        methods = [
            ('curl_cffi', self._try_curl_cffi),
            ('cloudscraper', self._try_cloudscraper),
            ('drissionpage', self._try_drissionpage),
            ('playwright', self._try_playwright),
            ('undetected', self._try_undetected_chrome),
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
            
            # Symulacja scrollowania
            for _ in range(3):
                page.scroll.down(random.randint(200, 400))
                human_delay(0.3, 0.7)
            
            html = page.html
            return html
        finally:
            page.quit()
    
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
    
    def _try_undetected_chrome(self, url: str, timeout: int) -> Optional[str]:
        """undetected_chromedriver z agresywnymi ustawieniami"""
        import undetected_chromedriver as uc
        
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
