/**
 * 🔥 FOREBET PUPPETEER SCRAPER - STEALTH MODE 🔥
 * ================================================
 * Używa Puppeteer Extra z pluginem Stealth do ominięcia Cloudflare.
 * Zapisuje HTML do pliku dla Python scrapera.
 * 
 * Uruchomienie:
 *   node forebet_puppeteer.js <sport> <output_file>
 * 
 * Przykład:
 *   node forebet_puppeteer.js football forebet_football.html
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');

// Dodaj plugin stealth
puppeteer.use(StealthPlugin());

// Sport URLs
const SPORT_URLS = {
    // Ten sam URL co w mapie `forebet_scraper.py` — strona /predictions-1x2 to
    // kanoniczna dzienna lista 1X2 i tylko na niej `?date=` filtruje dzień.
    // Rozjazd między JS i Pythonem oznaczał, że obie ścieżki pobierały inną
    // stronę dla tego samego sportu.
    'football': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
    'soccer': 'https://www.forebet.com/en/football-tips-and-predictions-for-today/predictions-1x2',
    'basketball': 'https://www.forebet.com/en/basketball/predictions-today',
    'tennis': 'https://www.forebet.com/en/tennis/predictions-today',
    'volleyball': 'https://www.forebet.com/en/volleyball/predictions-today',
    'handball': 'https://www.forebet.com/en/handball/predictions-today',
    'hockey': 'https://www.forebet.com/en/hockey/predictions-today',
    'ice-hockey': 'https://www.forebet.com/en/hockey/predictions-today',
    // Dodane dla forebet_pipeline.py — te sporty istniały już w mapie URL
    // scrapera Python (forebet_scraper.py), ale nie tutaj, więc ścieżka
    // Puppeteer (jedyna klikająca "More") ich nie obsługiwała.
    'rugby': 'https://www.forebet.com/en/rugby/predictions-today',
    'baseball': 'https://www.forebet.com/en/baseball/predictions-today'
};

// Consent button selectors
const CONSENT_SELECTORS = [
    'button.fc-cta-consent',
    '.fc-cta-consent',
    'button[data-cookiefirst-action="accept"]',
    '#onetrust-accept-btn-handler',
    'button:has-text("Accept")',
    'button:has-text("Agree")',
    'button:has-text("Zgadzam")'
];

async function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function randomDelay(min = 1000, max = 3000) {
    const ms = Math.floor(Math.random() * (max - min + 1)) + min;
    return delay(ms);
}

async function clickConsent(page) {
    console.log('🍪 Szukam przycisku consent...');

    for (const selector of CONSENT_SELECTORS) {
        try {
            const button = await page.$(selector);
            if (button) {
                const isVisible = await button.isIntersectingViewport();
                if (isVisible) {
                    console.log(`🍪 Klikam: ${selector}`);
                    await button.click();
                    await delay(2000);
                    return true;
                }
            }
        } catch (e) {
            // Kontynuuj do następnego selektora
        }
    }

    // Fallback - szukaj po tekście
    try {
        const buttons = await page.$$('button');
        for (const button of buttons) {
            const text = await page.evaluate(el => el.textContent, button);
            if (text && /accept|agree|zgadzam|consent/i.test(text)) {
                console.log(`🍪 Klikam button z tekstem: ${text.substring(0, 30)}`);
                await button.click();
                await delay(2000);
                return true;
            }
        }
    } catch (e) {
        // Ignore
    }

    console.log('🍪 Nie znaleziono przycisku consent');
    return false;
}

async function waitForContent(page) {
    console.log('⏳ Czekam na załadowanie treści...');

    // Czekaj na różne możliwe selektory meczów
    const selectors = [
        'div.rcnt',
        'tr.tr_0',
        'tr.tr_1',
        'div.schema',
        '.contentmiddle',
        'table.schema'
    ];

    for (const selector of selectors) {
        try {
            await page.waitForSelector(selector, { timeout: 10000 });
            console.log(`✅ Znaleziono: ${selector}`);
            return true;
        } catch (e) {
            // Kontynuuj do następnego
        }
    }

    return false;
}

async function simulateHumanBehavior(page) {
    console.log('🖱️ Symulacja zachowania człowieka...');

    // Scroll
    await page.evaluate(() => {
        window.scrollBy(0, 300);
    });
    await randomDelay(500, 1500);

    await page.evaluate(() => {
        window.scrollBy(0, 500);
    });
    await randomDelay(500, 1500);

    // Scroll back up
    await page.evaluate(() => {
        window.scrollTo(0, 0);
    });
    await randomDelay(1000, 2000);
}

// 🔥 NEW: Click "Load More" / "Show More" button to get all matches
async function clickLoadMore(page, maxClicks = 10) {
    console.log('📄 Szukam przycisku "Pokaż więcej"...');

    const loadMoreSelectors = [
        // Forebet specific
        '.showmore',
        '#showmore',
        'a.showmore',
        'button.showmore',
        '.show-more',
        '#show-more',
        // Generic patterns
        'a:has-text("Show more")',
        'a:has-text("Load more")',
        'a:has-text("Pokaż więcej")',
        'a:has-text("Więcej")',
        'button:has-text("Show more")',
        'button:has-text("Load more")',
        // Class patterns
        '[class*="loadmore"]',
        '[class*="showmore"]',
        '[class*="load-more"]',
        '[class*="show-more"]',
        // ID patterns
        '[id*="loadmore"]',
        '[id*="showmore"]'
    ];

    let clickCount = 0;
    let foundButton = true;

    while (foundButton && clickCount < maxClicks) {
        foundButton = false;

        // First, scroll to bottom to trigger lazy loading
        await page.evaluate(() => {
            window.scrollTo(0, document.body.scrollHeight);
        });
        await delay(1500);

        // Try each selector
        for (const selector of loadMoreSelectors) {
            try {
                const elements = await page.$$(selector);
                for (const element of elements) {
                    try {
                        const isVisible = await element.isIntersectingViewport().catch(() => false);
                        const isClickable = await page.evaluate(el => {
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0 &&
                                window.getComputedStyle(el).display !== 'none' &&
                                window.getComputedStyle(el).visibility !== 'hidden';
                        }, element).catch(() => false);

                        if (isClickable) {
                            // Scroll element into view
                            await page.evaluate(el => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), element);
                            await delay(500);

                            console.log(`   📄 Klikam "Load More" (${selector}) - próba ${clickCount + 1}/${maxClicks}`);
                            await element.click();
                            clickCount++;
                            foundButton = true;

                            // Wait for content to load
                            await delay(2000);
                            break;
                        }
                    } catch (e) {
                        // Element not clickable
                    }
                }
                if (foundButton) break;
            } catch (e) {
                // Selector not found
            }
        }

        // Also try clicking by text
        if (!foundButton) {
            try {
                const links = await page.$$('a, button');
                for (const link of links) {
                    const text = await page.evaluate(el => el.textContent, link).catch(() => '');
                    if (text && /show\s*more|load\s*more|pokaż\s*więcej|więcej\s*meczów/i.test(text)) {
                        const isClickable = await page.evaluate(el => {
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        }, link).catch(() => false);

                        if (isClickable) {
                            console.log(`   📄 Klikam link z tekstem: "${text.trim().substring(0, 30)}"`);
                            await link.click();
                            clickCount++;
                            foundButton = true;
                            await delay(2000);
                            break;
                        }
                    }
                }
            } catch (e) {
                // Ignore
            }
        }

        // If still no button found, try scrolling more to trigger infinite scroll
        if (!foundButton) {
            const prevHeight = await page.evaluate(() => document.body.scrollHeight);

            // Scroll multiple times
            for (let i = 0; i < 3; i++) {
                await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
                await delay(1000);
            }

            const newHeight = await page.evaluate(() => document.body.scrollHeight);

            // If page grew, continue scrolling
            if (newHeight > prevHeight) {
                console.log(`   📄 Infinite scroll: strona powiększona (${prevHeight} -> ${newHeight})`);
                foundButton = true; // Continue loop
                clickCount++;
            }
        }
    }

    if (clickCount > 0) {
        console.log(`✅ Załadowano więcej treści (${clickCount} interakcji)`);
    } else {
        console.log('📄 Brak przycisku "Pokaż więcej" lub wszystkie mecze załadowane');
    }

    // Scroll back to top
    await page.evaluate(() => window.scrollTo(0, 0));
    await delay(500);

    return clickCount;
}

async function scrapeForebet(sport, outputFile, dateStr, cfSession) {
    const baseUrl = SPORT_URLS[sport.toLowerCase()] || SPORT_URLS['football'];
    // Forebet pokazuje dzień dzisiejszy domyślnie; inne dni tylko z ?date=.
    // Pipeline zawsze podaje datę, więc nie zgadujemy który dzień dostaliśmy.
    const url = dateStr
        ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}date=${dateStr}`
        : baseUrl;
    console.log(`🌐 Forebet ${sport}: ${url}`);

    let browser;

    try {
        // Opcje przeglądarki
        const launchOptions = {
            headless: 'new',  // Nowy headless mode
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--window-size=1920,1080',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            ]
        };

        console.log('🚀 Uruchamiam przeglądarkę...');
        browser = await puppeteer.launch(launchOptions);

        const page = await browser.newPage();

        // 🍪 Sesja Cloudflare z FlareSolverr (cf_clearance + User-Agent).
        // Stealth nie przechodzi Turnstile na runnerze GitHuba, a bez wejscia
        // na strone nie da sie kliknac "More" — czyli widzimy tylko poczatek
        // dnia. FlareSolverr challenge przechodzi, a poniewaz dziala na tym
        // samym IP, jego cf_clearance jest wazne rowniez tutaj.
        // cf_clearance jest powiazane z User-Agentem, wiec musi byc ten sam.
        if (cfSession) {
            try {
                if (cfSession.userAgent) {
                    await page.setUserAgent(cfSession.userAgent);
                    console.log(`🍪 User-Agent z FlareSolverr ustawiony`);
                }
                const cookies = (cfSession.cookies || []).map(c => {
                    const out = {
                        name: c.name,
                        value: c.value,
                        domain: c.domain,
                        path: c.path || '/',
                        httpOnly: !!c.httpOnly,
                        secure: !!c.secure
                    };
                    if (typeof c.expires === 'number' && c.expires > 0) {
                        out.expires = c.expires;
                    }
                    // FlareSolverr zwraca m.in. 'unspecified', czego Puppeteer
                    // nie przyjmuje — dopuszczamy tylko poprawne wartosci.
                    if (['Strict', 'Lax', 'None'].includes(c.sameSite)) {
                        out.sameSite = c.sameSite;
                    }
                    return out;
                });
                if (cookies.length) {
                    await page.setCookie(...cookies);
                    console.log(`🍪 Wstrzyknieto ${cookies.length} cookies Cloudflare`);
                }
            } catch (e) {
                console.log(`⚠️ Nie udalo sie wstrzyknac sesji CF: ${e.message}`);
            }
        }

        // Ustaw viewport
        await page.setViewport({ width: 1920, height: 1080 });

        // Ustaw extra headers
        await page.setExtraHTTPHeaders({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
        });

        console.log('🌐 Ładuję stronę...');
        await page.goto(url, {
            waitUntil: 'networkidle2',
            timeout: 60000
        });

        // Czekaj na potencjalny challenge
        console.log('⏳ Czekam na Cloudflare...');
        await delay(5000);

        // Symuluj człowieka
        await simulateHumanBehavior(page);

        // Kliknij consent
        await clickConsent(page);

        // Czekaj na content
        const hasContent = await waitForContent(page);

        if (!hasContent) {
            console.log('⚠️ Nie znaleziono treści, czekam jeszcze...');
            await delay(10000);
            await simulateHumanBehavior(page);
        }

        // 🔥 Click "Load More" to get all matches.
        // Każdy sport na Forebet ma "More" — bez wyklikania go do końca
        // widzimy tylko pierwszą porcję wierszy, a pipeline ma analizować
        // WSZYSTKIE mecze dnia. Limit podnoszony przez env dla pełnej listy.
        const maxClicks = parseInt(process.env.FOREBET_LOAD_MORE_CLICKS || '10', 10);
        const loadMoreClicks = await clickLoadMore(page, Number.isNaN(maxClicks) ? 10 : maxClicks);
        console.log(`📊 Załadowano strony: ${loadMoreClicks + 1}`);

        // Pobierz HTML
        const html = await page.content();

        // Sprawdź czy to prawdziwa strona
        const isChallenge = html.includes('loading-verifying') ||
            html.includes('lds-ring') ||
            html.includes('Checking your browser');

        const isForebet = html.includes('rcnt') ||
            html.includes('forepr') ||
            html.includes('tr_0');

        if (isChallenge && !isForebet) {
            console.log('❌ Cloudflare challenge nie został rozwiązany!');

            // Jeszcze jedna próba - czekaj dłużej
            console.log('⏳ Ostatnia próba - czekam 30 sekund...');
            await delay(30000);
            await simulateHumanBehavior(page);
            await clickConsent(page);

            const html2 = await page.content();

            if (html2.includes('rcnt') || html2.includes('tr_0')) {
                console.log('✅ Sukces po dodatkowym czekaniu!');
                fs.writeFileSync(outputFile, html2);
                console.log(`💾 Zapisano: ${outputFile} (${html2.length} znaków)`);
            } else {
                // Zapisz do debug
                fs.writeFileSync('forebet_challenge_debug.html', html2);
                console.log('❌ NIEPOWODZENIE - zapisano debug HTML');
                process.exit(1);
            }
        } else if (isForebet) {
            console.log(`✅ SUKCES! Strona Forebet załadowana (${html.length} znaków)`);
            fs.writeFileSync(outputFile, html);
            console.log(`💾 Zapisano: ${outputFile}`);
        } else {
            console.log('⚠️ Nieznana strona - zapisuję do analizy');
            fs.writeFileSync(outputFile, html);
        }

    } catch (error) {
        console.error(`❌ Błąd: ${error.message}`);
        process.exit(1);
    } finally {
        if (browser) {
            await browser.close();
            console.log('🔒 Przeglądarka zamknięta');
        }
    }
}

// Main
const sport = process.argv[2] || 'football';
const outputFile = process.argv[3] || 'forebet_output.html';
// Opcjonalny 4. argument: data YYYY-MM-DD. Pominięty => dzisiejsza strona.
const dateArg = (process.argv[4] || '').trim();
const dateStr = /^\d{4}-\d{2}-\d{2}$/.test(dateArg) ? dateArg : '';

// Opcjonalny 5. argument: plik JSON z sesja Cloudflare od FlareSolverr
// ({cookies: [...], userAgent: "..."}).
let cfSession = null;
const cfPath = (process.argv[5] || '').trim();
if (cfPath) {
    try {
        cfSession = JSON.parse(fs.readFileSync(cfPath, 'utf-8'));
    } catch (e) {
        console.log(`⚠️ Nie moge odczytac sesji CF z ${cfPath}: ${e.message}`);
    }
}

console.log('🔥 FOREBET PUPPETEER SCRAPER - STEALTH MODE 🔥');
console.log(`Sport: ${sport}`);
console.log(`Output: ${outputFile}`);
console.log(`Date: ${dateStr || '(dzisiaj)'}`);
console.log(`Sesja CF: ${cfSession ? (cfSession.cookies || []).length + ' cookies' : 'brak'}`);
console.log('');

scrapeForebet(sport, outputFile, dateStr, cfSession)
    .then(() => {
        console.log('✅ Zakończono');
        process.exit(0);
    })
    .catch(err => {
        console.error(`❌ Fatal error: ${err.message}`);
        process.exit(1);
    });
