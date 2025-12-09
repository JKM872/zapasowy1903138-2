/**
 * SofaScore Fan Votes Scraper
 * Uses Puppeteer with stealth plugin to bypass Cloudflare and execute JavaScript
 * 
 * Usage: node sofascore_puppeteer.js <match_url>
 * Returns JSON with fan vote percentages
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

async function getFanVotes(matchUrl) {
    const result = {
        success: false,
        home_win_pct: null,
        draw_pct: null,
        away_win_pct: null,
        total_votes: null,
        url: matchUrl,
        error: null
    };

    let browser;
    try {
        browser = await puppeteer.launch({
            headless: 'new',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--window-size=1920,1080'
            ]
        });

        const page = await browser.newPage();

        // Set user agent
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36');

        // Set viewport
        await page.setViewport({ width: 1920, height: 1080 });

        // Navigate to match page
        await page.goto(matchUrl, {
            waitUntil: 'networkidle2',
            timeout: 60000
        });

        // Wait for page to load
        await page.waitForTimeout(3000);

        // Handle consent popup if present
        try {
            const consentButton = await page.$('button[class*="accept"], button[class*="consent"], [data-testid*="accept"]');
            if (consentButton) {
                await consentButton.click();
                await page.waitForTimeout(1000);
            }
        } catch (e) { /* ignore */ }

        // Scroll to load fan votes section (it's usually below the fold)
        await page.evaluate(() => {
            window.scrollBy(0, 500);
        });
        await page.waitForTimeout(2000);

        // Try to find and extract fan votes
        const votes = await page.evaluate(() => {
            const result = { home: null, draw: null, away: null, votes: null, preMatch: false };

            // Find "Who will win" section
            const pageText = document.body.innerText;
            const hasWhoWillWin = /who will win/i.test(pageText);

            if (!hasWhoWillWin) {
                return result;
            }

            // Method 1: Find vote count (e.g. "1234 votes" or "1,234 głosów")
            const voteCountMatch = pageText.match(/(\d[\d,. ]*)\s*(votes|głos|vote)/i);
            if (voteCountMatch) {
                result.votes = parseInt(voteCountMatch[1].replace(/[,. ]/g, ''));
            }

            // Method 2: Look for percentage patterns
            // Find the section that contains "Who will win"
            const sections = document.querySelectorAll('div, section');
            let voteSection = null;

            for (const section of sections) {
                if (/who will win/i.test(section.innerText) && section.innerText.length < 500) {
                    voteSection = section;
                    break;
                }
            }

            if (voteSection) {
                // Look for percentages in this section
                const percentages = voteSection.innerText.match(/(\d{1,3})%/g);
                if (percentages && percentages.length >= 2) {
                    const nums = percentages.map(p => parseInt(p));
                    if (nums.length >= 3) {
                        result.home = nums[0];
                        result.draw = nums[1];
                        result.away = nums[2];
                    } else if (nums.length === 2) {
                        result.home = nums[0];
                        result.away = nums[1];
                    }
                }
            }

            // Method 3: Find percentages near "1", "X", "2" buttons
            if (result.home === null) {
                const allElements = document.querySelectorAll('*');
                const voteButtons = [];

                for (const el of allElements) {
                    const text = el.innerText.trim();
                    if ((text === '1' || text === 'X' || text === '2') && el.clientWidth > 30) {
                        // Check if parent has percentage
                        const parent = el.closest('div');
                        if (parent) {
                            const pctMatch = parent.innerText.match(/(\d{1,3})%/);
                            if (pctMatch) {
                                voteButtons.push({ label: text, pct: parseInt(pctMatch[1]) });
                            }
                        }
                    }
                }

                voteButtons.forEach(btn => {
                    if (btn.label === '1') result.home = btn.pct;
                    else if (btn.label === 'X') result.draw = btn.pct;
                    else if (btn.label === '2') result.away = btn.pct;
                });
            }

            // Method 4: Style-based extraction (width of bars)
            if (result.home === null) {
                const bars = document.querySelectorAll('[class*="Bar"], [class*="bar"], [class*="Progress"]');
                const widths = [];

                bars.forEach(bar => {
                    const style = bar.getAttribute('style') || '';
                    const widthMatch = style.match(/width:\s*(\d+(\.\d+)?)/);
                    if (widthMatch) {
                        widths.push(Math.round(parseFloat(widthMatch[1])));
                    }
                });

                // Filter valid percentages
                const validWidths = widths.filter(w => w > 0 && w <= 100);
                if (validWidths.length >= 2) {
                    result.home = validWidths[0];
                    if (validWidths.length >= 3) {
                        result.draw = validWidths[1];
                        result.away = validWidths[2];
                    } else {
                        result.away = validWidths[1];
                    }
                }
            }

            // Check if this is pre-match (no votes yet)
            if (result.home === null && hasWhoWillWin) {
                result.preMatch = true;
            }

            return result;
        });

        if (votes.home !== null) {
            result.success = true;
            result.home_win_pct = votes.home;
            result.draw_pct = votes.draw;
            result.away_win_pct = votes.away;
            result.total_votes = votes.votes;
        } else if (votes.preMatch) {
            result.success = false;
            result.error = 'Pre-match: no votes yet (match not started)';
            result.pre_match = true;
        } else {
            result.error = 'Could not find fan votes on page';
        }

    } catch (error) {
        result.error = error.message;
    } finally {
        if (browser) {
            await browser.close();
        }
    }

    return result;
}

// Main execution
const args = process.argv.slice(2);
if (args.length === 0) {
    console.log(JSON.stringify({
        success: false,
        error: 'Usage: node sofascore_puppeteer.js <match_url>'
    }));
    process.exit(1);
}

const matchUrl = args[0];
getFanVotes(matchUrl)
    .then(result => {
        console.log(JSON.stringify(result));
    })
    .catch(err => {
        console.log(JSON.stringify({
            success: false,
            error: err.message
        }));
    });
