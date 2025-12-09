# GitHub Actions Setup Guide

## 🔧 Required Secrets

Go to: **Repository → Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `EMAIL_SENDER` | Email address to send from | `your.email@gmail.com` |
| `EMAIL_PASSWORD` | App password (not regular password) | `xxxx xxxx xxxx xxxx` |
| `EMAIL_RECIPIENT` | Email address to receive notifications | `recipient@email.com` |
| `EMAIL_SMTP_SERVER` | SMTP server (optional) | `smtp.gmail.com` |
| `EMAIL_SMTP_PORT` | SMTP port (optional) | `587` |

### Gmail App Password Setup:
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Factor Authentication
3. Go to "App passwords"
4. Create new app password for "Mail"
5. Copy the 16-character password

---

## 🚀 Usage

### Automatic (Scheduled)
- Runs daily at 8:00 UTC
- Scrapes football by default

### Manual Trigger
1. Go to **Actions** tab
2. Select **Sports Scraper Pipeline**
3. Click **Run workflow**
4. Choose sport and email options

---

## 📦 What's Included

| Component | Purpose |
|-----------|---------|
| FlareSolverr | Cloudflare bypass (Docker) |
| Puppeteer | SofaScore fan votes |
| Selenium | Forebet, Livesport H2H |
| Chrome | Browser automation |

---

## ⚠️ Limitations

- **Run time**: ~10-15 minutes per sport
- **FlareSolverr**: May be slow on first request
- **SofaScore**: ~2 min per match for fan votes

---

## 🔍 Debugging

Check workflow logs:
1. Go to **Actions** tab
2. Click on failed run
3. Expand failed step
4. Check logs

Artifacts available after each run:
- `scraper-results-*`: JSON output
- `scraper-cache-*`: Cached data
