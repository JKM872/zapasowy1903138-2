#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📊 CHECK RESULTS — Sprawdza wyniki meczów wysłanych mailem

Czyta manifest mailed events (zapisany przez email_notifier w momencie wysyłki),
sprawdza finalne wyniki każdego meczu i wysyła raport skuteczności.

Użycie:
  python check_results.py --date 2025-10-07 --headless
  python check_results.py --date 2025-10-07 --send-email --to user@gmail.com ...
  python check_results.py --yesterday --headless --send-email ...
"""

import json
import argparse
import glob
import math
import os
import smtplib
import time as time_module
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Union

# Result store for persistent accumulation
try:
    from result_store import ResultStore
    _result_store_ok = True
except ImportError:
    _result_store_ok = False

# Name-based settlement over the SofaScore API. Preferred over the browser
# path: it needs no Chrome (the whole report then fits a couple of CI minutes),
# it covers AiScore fixtures the Livesport parser cannot read at all, and it
# settles by who won rather than by table position.
try:
    from result_resolver import resolve_result, settle_from_result
    _resolver_ok = True
except ImportError:
    _resolver_ok = False

# Selenium — optional; results can also come from API
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from bs4 import BeautifulSoup
    _selenium_ok = True
except ImportError:
    webdriver = None  # type: ignore[assignment]
    Options = None  # type: ignore[assignment,misc]
    Service = None  # type: ignore[assignment,misc]
    BeautifulSoup = None  # type: ignore[assignment,misc]
    _selenium_ok = False

# ---------------------------------------------------------------------------
# SMTP config (reused from email_notifier)
# ---------------------------------------------------------------------------
SMTP_CONFIG: Dict[str, Dict[str, Union[str, int, bool]]] = {
    'gmail': {'server': 'smtp.gmail.com', 'port': 587, 'use_tls': True},
    'outlook': {'server': 'smtp-mail.outlook.com', 'port': 587, 'use_tls': True},
    'yahoo': {'server': 'smtp.mail.yahoo.com', 'port': 587, 'use_tls': True},
}


# ═══════════════════════════════════════════════════════════════════════════
# 1. MANIFEST LOADING
# ═══════════════════════════════════════════════════════════════════════════

def load_manifests(date: str) -> List[Dict[str, Any]]:
    """Load all mailed-event manifest files for a given date and merge.

    Plik z sufiksem ``_empty`` jest celowo wyprodukowanym przez
    ``email_notifier`` markerem typu „pipeline OK, ale nic nie kwalifikowało
    się do wysyłki” — nie traktujemy go jako rekord meczu, ale jego
    obecność pozwala odróżnić ten przypadek od „manifest zaginął”.
    """
    pattern = f'outputs/mailed_manifest_{date}*.json'
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"❌ Brak manifestów email dla daty {date}")
        print(f"   Szukano: {pattern}")
        return []

    all_matches: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get('empty_reason'):
                print(f"   ℹ️ {fpath}: empty marker (reason={data[0].get('empty_reason')})")
                continue
            for m in data:
                url = m.get('match_url')
                if url and url not in seen_urls:
                    all_matches.append(m)
                    seen_urls.add(url)
            print(f"   📂 {fpath}: {len(data)} meczów")
        except (json.JSONDecodeError, OSError) as e:
            print(f"   ⚠️ Błąd wczytywania {fpath}: {e}")

    print(f"✅ Wczytano łącznie {len(all_matches)} unikalnych meczów z manifestów email")
    return all_matches


def diagnose_manifest_state(date: str, source: str) -> Dict[str, Any]:
    """Return a structured diagnosis of manifest availability for *date*.

    Keys:
      - ``state``: one of
        ``has_matches``  – manifest jest, są mecze do oceny
        ``empty_run``    – manifest jest, ale to marker pustego runu
        ``no_manifest``  – brak jakiegokolwiek pliku
        ``no_results``   – brak ``results/`` jako fallback w tej dacie
      - ``files``: lista znalezionych ścieżek
      - ``empty_reasons``: zebrane powody z empty markerów
      - ``has_results_fallback``: bool, czy `results/*{date}*` istnieje
    """
    info: Dict[str, Any] = {
        'state': 'no_manifest',
        'files': [],
        'empty_reasons': [],
        'has_results_fallback': False,
    }

    if source == 'telegram':
        path = f'outputs/telegram_manifest_{date}.json'
        if os.path.isfile(path):
            info['files'].append(path)
            info['state'] = 'has_matches'
        return info

    pattern = f'outputs/mailed_manifest_{date}*.json'
    files = sorted(glob.glob(pattern))
    info['files'] = files

    has_real = False
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get('empty_reason'):
            info['empty_reasons'].append(data[0].get('empty_reason'))
            continue
        if isinstance(data, list) and data:
            has_real = True

    if has_real:
        info['state'] = 'has_matches'
    elif info['empty_reasons']:
        info['state'] = 'empty_run'
    elif not files:
        info['state'] = 'no_manifest'
    else:
        info['state'] = 'no_manifest'

    # Fallback do scrapingu
    results_pattern = f'results/*{date}*.json'
    info['has_results_fallback'] = bool(glob.glob(results_pattern))

    return info


def save_diagnostic_summary(date: str, diagnosis: Dict[str, Any], source: str) -> str:
    """Zapisz diagnostyczny `results_summary_{date}.json`, gdy nie ma danych
    do oceny — workflow `Check Results` ma wtedy artefakt do commita zamiast
    cichego "brak meczów".
    """
    os.makedirs('outputs', exist_ok=True)
    tag = '' if source == 'email' else source
    suffix = f'_{tag}' if tag else ''
    path = f'outputs/results_summary_{date}{suffix}.json'

    state = diagnosis.get('state', 'no_manifest')
    if state == 'empty_run':
        human_status = 'pipeline_ok_but_no_qualified_matches'
    elif state == 'no_manifest' and diagnosis.get('has_results_fallback'):
        human_status = 'manifest_missing_but_results_present'
    elif state == 'no_manifest':
        human_status = 'manifest_missing_no_upstream_data'
    else:
        human_status = state

    summary = {
        'date': date,
        'generated_at': datetime.now().isoformat(),
        'source': source,
        'status': human_status,
        'state': state,
        'empty_reasons': diagnosis.get('empty_reasons', []),
        'manifest_files': diagnosis.get('files', []),
        'has_results_fallback': diagnosis.get('has_results_fallback', False),
        'total': 0,
        'finished': 0,
        'won': 0,
        'lost': 0,
        'draw': 0,
        'pending': 0,
        'errors': 0,
        'accuracy': 0.0,
        'roi_pct': 0.0,
        'roi_pln': 0.0,
        'matches': [],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"📁 Diagnostic summary zapisany: {path} (status={human_status})")
    return path


def load_telegram_manifest(date: str) -> List[Dict[str, Any]]:
    """Load the Telegram manifest for *date* and return a list of match dicts.

    Supports both the current schema (``{"matches": [...]}``) and a legacy
    flat-list schema. Matches without ``match_url`` are skipped with a warning
    because the result scraper relies on it.
    """
    path = f'outputs/telegram_manifest_{date}.json'
    if not os.path.isfile(path):
        print(f"❌ Brak manifestu Telegram dla daty {date}")
        print(f"   Szukano: {path}")
        return []

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"   ⚠️ Błąd wczytywania {path}: {e}")
        return []

    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get('matches', []) or []
    else:
        raw = []

    matches: List[Dict[str, Any]] = []
    missing_url = 0
    seen_urls: set[str] = set()
    for m in raw:
        if not isinstance(m, dict):
            continue
        url = m.get('match_url')
        if not url:
            missing_url += 1
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        matches.append(m)

    print(f"   📂 {path}: {len(matches)} meczów")
    if missing_url:
        print(
            f"   ⚠️ Pominięto {missing_url} rekord(ów) bez match_url — "
            "manifest pochodzi ze starej wersji telegram_notifier.py"
        )
    print(f"✅ Wczytano łącznie {len(matches)} unikalnych meczów z manifestu Telegram")
    return matches


def merge_manifests(*manifests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge one or more manifest lists, deduplicating by ``match_url``.

    Later manifests can enrich earlier entries with fields that were missing
    (e.g. the Telegram manifest may carry ``prediction_grade`` while the mail
    manifest wins on URL presence).
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for manifest in manifests:
        for m in manifest:
            url = m.get('match_url')
            if not url:
                continue
            if url not in merged:
                merged[url] = dict(m)
                order.append(url)
            else:
                for k, v in m.items():
                    if v not in (None, '') and merged[url].get(k) in (None, ''):
                        merged[url][k] = v
    return [merged[u] for u in order]


# ═══════════════════════════════════════════════════════════════════════════
# 2. RESULT SCRAPING
# ═══════════════════════════════════════════════════════════════════════════

def _init_driver(headless: bool = True) -> Any:
    """Initialize Selenium WebDriver."""
    if not _selenium_ok:
        raise RuntimeError("Selenium/BeautifulSoup not installed")

    opts = Options()  # type: ignore[misc]
    if headless:
        opts.add_argument('--headless')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])  # type: ignore[union-attr]
    opts.add_experimental_option('useAutomationExtension', False)  # type: ignore[union-attr]

    # Try chromedriver from PATH first, fall back to webdriver-manager
    try:
        driver = webdriver.Chrome(options=opts)  # type: ignore[union-attr]
    except Exception:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(  # type: ignore[union-attr]
            service=Service(ChromeDriverManager().install()),  # type: ignore[misc]
            options=opts,
        )
    return driver


def scrape_match_result(driver: Any, match_url: str) -> Dict[str, Any]:
    """Scrape final score for a single match URL.

    Returns dict with keys: status, score_home, score_away, winner.
    """
    try:
        driver.get(match_url)
        time_module.sleep(2.0)

        soup = BeautifulSoup(driver.page_source, 'html.parser')  # type: ignore[misc]

        # Check if match finished
        status_elem = soup.find('div', class_='detailScore__status')
        if status_elem:
            status_text = status_elem.get_text(strip=True).lower()
            finished_keywords = ['zakończony', 'finished', 'ft', 'ao', 'po dogrywce',
                                 'po karnych', 'walkower', 'ended']
            if not any(kw in status_text for kw in finished_keywords):
                return {'status': 'not_finished'}

        score_home = None
        score_away = None

        # Method 1: detailScore__wrapper divs
        score_divs = soup.find_all('div', class_='detailScore__wrapper')
        if len(score_divs) >= 2:
            try:
                score_home = int(score_divs[0].get_text(strip=True))
                score_away = int(score_divs[1].get_text(strip=True))
            except (ValueError, TypeError):
                pass

        # Method 2: JSON-LD structured data
        if score_home is None:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    if isinstance(data, dict) and 'homeTeam' in data:
                        score_home = int(data['homeTeam']['score'])  # type: ignore[arg-type]
                        score_away = int(data['awayTeam']['score'])  # type: ignore[arg-type]
                        break
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue

        if score_home is None or score_away is None:
            return {'status': 'no_score'}

        if score_home > score_away:
            winner = 'home'
        elif score_away > score_home:
            winner = 'away'
        else:
            winner = 'draw'

        return {
            'status': 'finished',
            'score_home': score_home,
            'score_away': score_away,
            'winner': winner,
        }

    except Exception as e:
        return {'status': 'error', 'error': str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 3. EVALUATION LOGIC
# ═══════════════════════════════════════════════════════════════════════════

def _predicted_winner(match: Dict[str, Any]) -> str:
    """Determine who our pipeline predicted to win.

    For tennis: scoring_pick or favorite field.
    For team sports: the focus team (home by default, away if away_team_focus).
    """
    sport = (match.get('sport') or 'football').lower()

    # Tennis – check scoring_pick first, then favorite
    if sport == 'tennis':
        pick = match.get('scoring_pick', '')
        if pick:
            return 'home' if '1' in str(pick) or 'A' in str(pick).upper() else 'away'
        fav = match.get('favorite', '')
        if fav:
            return 'home' if str(fav).upper() == 'A' else 'away'
        return 'home'  # fallback

    # Team sports: focus_team tells us who we bet on
    focus = (match.get('focus_team') or '').lower()
    if focus == 'away':
        return 'away'
    return 'home'


def evaluate(matches: List[Dict[str, Any]], results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate the outcomes for mailed matches.

    Args:
        matches: list of match dicts from manifest
        results: dict mapping match_url → scrape result

    Returns:
        stats dict with totals, per-sport breakdown, and detailed results list.
    """
    stats: Dict[str, Any] = {
        'total': len(matches),
        'finished': 0,
        'won': 0,
        'lost': 0,
        'draw': 0,
        'pending': 0,
        'void': 0,
        'errors': 0,
        'details': [],
        'by_sport': {},
    }

    for m in matches:
        url = m.get('match_url', '')
        res = results.get(url, {'status': 'error', 'error': 'no result fetched'})
        sport = (m.get('sport') or 'football').lower()

        # Ensure per-sport bucket
        if sport not in stats['by_sport']:
            stats['by_sport'][sport] = {'total': 0, 'won': 0, 'lost': 0, 'draw': 0,
                                        'pending': 0, 'void': 0, 'errors': 0}
        sp = stats['by_sport'][sport]
        sp['total'] += 1

        predicted = _predicted_winner(m)

        detail: Dict[str, Any] = {
            'home_team': m.get('home_team', '?'),
            'away_team': m.get('away_team', '?'),
            'sport': sport,
            'predicted': predicted,
            'focus_team': (m.get('focus_team') or 'home').lower(),
            'home_odds': m.get('home_odds'),
            'away_odds': m.get('away_odds'),
            'match_url': url,
            'match_date': m.get('match_date'),
            # Carried through from the manifest so the outcome can be judged
            # against what the model claimed, not just counted.
            'scoring_pick': m.get('scoring_pick'),
            'scoring_prob': m.get('scoring_prob'),
            'scoring_ev': m.get('scoring_ev'),
            'scoring_edge': m.get('scoring_edge'),
            'scoring_confidence': m.get('scoring_confidence'),
            'advanced_score': m.get('advanced_score'),
            'prediction_grade': m.get('prediction_grade'),
        }

        # Name-resolved results settle by *who won*, never by position: the
        # manifest's home/away order does not always agree with the source's,
        # so comparing 'home' to 'home' can credit the wrong side.
        if _resolver_ok and res.get('source'):
            settled = settle_from_result(m, res)
            detail.update({k: v for k, v in settled.items() if v is not None})
            outcome = settled['outcome']
            if outcome != 'pending':
                if outcome in ('won', 'lost', 'draw'):
                    stats['finished'] += 1
                stats[outcome] = stats.get(outcome, 0) + 1
                sp[outcome] = sp.get(outcome, 0) + 1
            else:
                stats['pending'] += 1
                sp['pending'] += 1
            stats['details'].append(detail)
            continue

        if res['status'] == 'finished':
            stats['finished'] += 1
            winner = res['winner']
            detail['score'] = f"{res['score_home']}-{res['score_away']}"
            detail['actual'] = winner

            if winner == 'draw':
                stats['draw'] += 1
                sp['draw'] += 1
                detail['outcome'] = 'draw'
            elif winner == predicted:
                stats['won'] += 1
                sp['won'] += 1
                detail['outcome'] = 'won'
            else:
                stats['lost'] += 1
                sp['lost'] += 1
                detail['outcome'] = 'lost'

        elif res['status'] in ('not_finished', 'no_score'):
            stats['pending'] += 1
            sp['pending'] += 1
            detail['outcome'] = 'pending'
            detail['score'] = '—'
            detail['actual'] = '—'
        else:
            stats['errors'] += 1
            sp['errors'] += 1
            detail['outcome'] = 'error'
            detail['score'] = '—'
            detail['actual'] = '—'

        stats['details'].append(detail)

    # Global accuracy (exclude draws and pending/errors from denominator)
    decided = stats['won'] + stats['lost']
    stats['accuracy'] = (stats['won'] / decided * 100) if decided > 0 else 0.0

    # ROI calculation (100 PLN flat stake)
    roi_total = 0.0
    roi_count = 0
    stake = 100
    for d in stats['details']:
        if d['outcome'] in ('won', 'lost'):
            odds_key = 'home_odds' if d['predicted'] == 'home' else 'away_odds'
            odds = d.get(odds_key)
            try:
                odds_f = float(odds)
                if math.isnan(odds_f):
                    continue
            except (TypeError, ValueError):
                continue
            if d['outcome'] == 'won':
                roi_total += (odds_f * stake - stake)
            else:
                roi_total -= stake
            roi_count += 1
    stats['roi_pln'] = roi_total
    stats['roi_pct'] = (roi_total / (roi_count * stake) * 100) if roi_count > 0 else 0.0

    return stats


# ═══════════════════════════════════════════════════════════════════════════
# 4. REPORT EMAIL
# ═══════════════════════════════════════════════════════════════════════════

SPORT_EMOJI = {
    'football': '⚽', 'basketball': '🏀', 'handball': '🤾',
    'volleyball': '🏐', 'tennis': '🎾', 'hockey': '🏒',
}


def generate_report_html(stats: Dict[str, Any], date: str) -> str:
    """Generate a transparent accuracy report as HTML email."""
    total = stats['total']
    won = stats['won']
    lost = stats['lost']
    draw = stats['draw']
    pending = stats['pending']
    void = stats.get('void', 0)
    _errors = stats['errors']
    accuracy = stats['accuracy']
    roi_pln = stats['roi_pln']
    roi_pct = stats['roi_pct']

    # Per-sport rows
    sport_rows = ''
    for sport in sorted(stats['by_sport'].keys()):
        sp = stats['by_sport'][sport]
        emoji = SPORT_EMOJI.get(sport, '🏆')
        sp_decided = sp['won'] + sp['lost']
        sp_acc = (sp['won'] / sp_decided * 100) if sp_decided > 0 else 0
        sport_rows += f"""
        <tr>
            <td>{emoji} {sport.capitalize()}</td>
            <td style="text-align:center">{sp['total']}</td>
            <td style="text-align:center;color:#27ae60;font-weight:700">{sp['won']}</td>
            <td style="text-align:center;color:#e74c3c;font-weight:700">{sp['lost']}</td>
            <td style="text-align:center;color:#f39c12">{sp['draw']}</td>
            <td style="text-align:center;color:#7f8c8d">{sp['pending']}</td>
            <td style="text-align:center;font-weight:700">{sp_acc:.0f}%</td>
        </tr>"""

    # Match detail rows
    detail_rows = ''
    for d in stats['details']:
        emoji = SPORT_EMOJI.get(d['sport'], '🏆')
        if d['outcome'] == 'won':
            color = '#27ae60'
            icon = '✅'
        elif d['outcome'] == 'lost':
            color = '#e74c3c'
            icon = '❌'
        elif d['outcome'] == 'draw':
            color = '#f39c12'
            icon = '🟡'
        elif d['outcome'] == 'pending':
            color = '#95a5a6'
            icon = '⏳'
        elif d['outcome'] == 'void':
            color = '#8b949e'
            icon = '🚫'
        else:
            color = '#95a5a6'
            icon = '⚠️'

        # Name the pick outright. '1 (Home)' is unreadable when the manifest's
        # orientation disagrees with the source's, which happens often enough
        # that a positional label was actively misleading.
        picked = d.get('picked_name') or (
            d['home_team'] if d['predicted'] == 'home' else d['away_team'])
        pred_label = picked
        detail_rows += f"""
        <tr>
            <td>{emoji}</td>
            <td>{d['home_team']} vs {d['away_team']}</td>
            <td style="text-align:center">{pred_label}</td>
            <td style="text-align:center">{d['score']}</td>
            <td style="text-align:center;color:{color};font-weight:700">{icon} {d['outcome'].upper()}</td>
        </tr>"""

    accuracy_color = '#27ae60' if accuracy >= 55 else '#e74c3c' if accuracy < 45 else '#f39c12'
    roi_color = '#27ae60' if roi_pln > 0 else '#e74c3c'

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background:#0d1117">
<div style="max-width:700px;margin:20px auto;background:#161b22;border-radius:12px;overflow:hidden;border:1px solid #30363d">

  <!-- HEADER -->
  <div style="background:linear-gradient(135deg,#1a73e8,#7c3aed);padding:24px;text-align:center">
    <div style="font-size:28px;font-weight:800;color:#fff">📊 RAPORT SKUTECZNOŚCI</div>
    <div style="font-size:14px;color:rgba(255,255,255,0.8);margin-top:4px">{date} — tylko zdarzenia wysłane mailem</div>
  </div>

  <!-- SUMMARY CARDS -->
  <div style="display:flex;flex-wrap:wrap;gap:10px;padding:20px;justify-content:center">
    <div style="flex:1;min-width:130px;background:#0d1117;border-radius:10px;padding:16px;text-align:center;border:1px solid #30363d">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Trafność</div>
      <div style="font-size:32px;font-weight:800;color:{accuracy_color}">{accuracy:.0f}%</div>
      <div style="font-size:11px;color:#8b949e">{won}/{won + lost} meczów</div>
    </div>
    <div style="flex:1;min-width:130px;background:#0d1117;border-radius:10px;padding:16px;text-align:center;border:1px solid #30363d">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase">ROI (100 PLN/mecz)</div>
      <div style="font-size:32px;font-weight:800;color:{roi_color}">{roi_pct:+.1f}%</div>
      <div style="font-size:11px;color:#8b949e">{roi_pln:+.0f} PLN</div>
    </div>
    <div style="flex:1;min-width:130px;background:#0d1117;border-radius:10px;padding:16px;text-align:center;border:1px solid #30363d">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Łącznie</div>
      <div style="font-size:32px;font-weight:800;color:#e6edf3">{total}</div>
      <div style="font-size:11px;color:#8b949e">✅{won} ❌{lost} 🟡{draw} ⏳{pending} 🚫{void}</div>
    </div>
  </div>

  <!-- PER-SPORT TABLE -->
  <div style="padding:0 20px 10px">
    <div style="font-size:16px;font-weight:700;color:#e6edf3;margin-bottom:8px">📈 Per sport</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;color:#c9d1d9">
      <tr style="background:#21262d">
        <th style="padding:8px;text-align:left">Sport</th>
        <th style="padding:8px;text-align:center">Total</th>
        <th style="padding:8px;text-align:center">✅</th>
        <th style="padding:8px;text-align:center">❌</th>
        <th style="padding:8px;text-align:center">🟡</th>
        <th style="padding:8px;text-align:center">⏳</th>
        <th style="padding:8px;text-align:center">Acc</th>
      </tr>
      {sport_rows}
    </table>
  </div>

  <!-- MATCH DETAILS TABLE -->
  <div style="padding:0 20px 20px">
    <div style="font-size:16px;font-weight:700;color:#e6edf3;margin-bottom:8px">📋 Pełna lista meczów</div>
    <table style="width:100%;border-collapse:collapse;font-size:12px;color:#c9d1d9">
      <tr style="background:#21262d">
        <th style="padding:6px"></th>
        <th style="padding:6px;text-align:left">Mecz</th>
        <th style="padding:6px;text-align:center">Typ</th>
        <th style="padding:6px;text-align:center">Wynik</th>
        <th style="padding:6px;text-align:center">Status</th>
      </tr>
      {detail_rows}
    </table>
  </div>

  <!-- FOOTER -->
  <div style="background:#0d1117;padding:16px;text-align:center;border-top:1px solid #30363d">
    <div style="font-size:11px;color:#484f58">
      📧 Wygenerowano automatycznie przez Check Results Pipeline<br>
      Raport obejmuje wyłącznie zdarzenia wysłane mailem po wszystkich filtrach
    </div>
  </div>

</div>
</body>
</html>"""
    return html


def send_report_email(
    html: str,
    subject: str,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = 'gmail',
) -> bool:
    """Send HTML report via SMTP. Returns True on success."""
    try:
        smtp_cfg: Dict[str, Union[str, int, bool]] = SMTP_CONFIG[provider]
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(str(smtp_cfg['server']), int(smtp_cfg['port'])) as server:
            if smtp_cfg['use_tls']:
                server.starttls()
            server.login(from_email, password)
            server.send_message(msg)

        print(f"✅ Raport wysłany do {to_email}")
        return True
    except Exception as e:
        print(f"❌ Błąd wysyłania raportu: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 5. SUMMARY PERSISTENCE (idempotent)
# ═══════════════════════════════════════════════════════════════════════════

def save_summary(stats: Dict[str, Any], date: str, tag: str = '') -> str:
    """Save evaluation summary JSON for auditing. Returns file path.

    ``tag`` suffixes the filename so email and Telegram audits do not
    overwrite each other (e.g. ``results_summary_2026-04-21_telegram.json``).
    """
    os.makedirs('outputs', exist_ok=True)
    suffix = f'_{tag}' if tag else ''
    path = f'outputs/results_summary_{date}{suffix}.json'

    # Strip full details for the summary file (keep it concise)
    summary = {k: v for k, v in stats.items() if k != 'details'}
    summary['date'] = date
    summary['generated_at'] = datetime.now().isoformat()
    summary['match_count'] = len(stats.get('details', []))

    # Detail list. This is the only place an outcome sits next to what the model
    # claimed *before* the match, so it is the audit trail for every question
    # that matters: does Grade A beat Grade C, do positive-EV picks pay, is the
    # stated probability honest. It used to keep only the pick and the odds, so
    # none of that could be measured — a segmentation by model probability came
    # back empty on 255 settled picks, and match_url was dropped too, which left
    # no key to join anything back on.
    summary['matches'] = [
        {
            'home': d['home_team'],
            'away': d['away_team'],
            # Kept under both names: 'home'/'away' for readers, '*_team' so the
            # row joins against manifests and results/*.json without mapping.
            'home_team': d['home_team'],
            'away_team': d['away_team'],
            'match_url': d.get('match_url'),
            'match_date': d.get('match_date') or date,
            'sport': d['sport'],
            'predicted': d['predicted'],
            'picked_name': d.get('picked_name'),
            'focus_team': d.get('focus_team', 'home'),
            'home_odds': d.get('home_odds'),
            'away_odds': d.get('away_odds'),
            'score': d.get('score', '—'),
            'outcome': d['outcome'],
            'winner_name': d.get('winner_name'),
            'resolved_by': d.get('resolved_by'),
            # What the model claimed beforehand.
            'scoring_pick': d.get('scoring_pick'),
            'scoring_prob': d.get('scoring_prob'),
            'scoring_ev': d.get('scoring_ev'),
            'scoring_edge': d.get('scoring_edge'),
            'scoring_confidence': d.get('scoring_confidence'),
            'advanced_score': d.get('advanced_score'),
            'prediction_grade': d.get('prediction_grade'),
        }
        for d in stats.get('details', [])
    ]

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"📁 Summary zapisany: {path}")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# 6. CLI MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='📊 Sprawdź wyniki meczów wysłanych mailem i wygeneruj raport skuteczności'
    )
    parser.add_argument('--date', help='Data do sprawdzenia (YYYY-MM-DD)')
    parser.add_argument('--yesterday', action='store_true', help='Sprawdź wczorajsze mecze')
    parser.add_argument('--headless', action='store_true', help='Uruchom przeglądarkę w trybie headless')
    parser.add_argument('--no-browser', action='store_true',
                        help='Tylko API — pomiń zapasową ścieżkę przez przeglądarkę')
    parser.add_argument('--send-email', action='store_true', help='Wyślij raport mailem')
    parser.add_argument('--to', help='Email odbiorcy raportu')
    parser.add_argument('--from-email', help='Email nadawcy')
    parser.add_argument('--password', help='Hasło email (lub App Password)')
    parser.add_argument('--provider', default='gmail', choices=['gmail', 'outlook', 'yahoo'])
    parser.add_argument(
        '--manifest',
        default='email',
        choices=['email', 'telegram', 'both'],
        help=(
            'Źródło manifestu: email (domyślnie; outputs/mailed_manifest_*.json), '
            'telegram (outputs/telegram_manifest_{date}.json) lub both (unia po match_url).'
        ),
    )

    args = parser.parse_args()

    # Determine date
    if args.yesterday:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    elif args.date:
        target_date = args.date
    else:
        target_date = datetime.now().strftime('%Y-%m-%d')

    source = args.manifest
    summary_tag = '' if source == 'email' else source  # email keeps legacy filename
    channel_label = {
        'email': 'wysłanych mailem',
        'telegram': 'wysłanych na Telegram',
        'both': 'wysłanych mailem lub na Telegram',
    }[source]

    print(f"\n{'='*70}")
    print(f"📊 CHECK RESULTS — {target_date} ({source})")
    print(f"{'='*70}\n")

    # 1. Load manifests
    if source == 'email':
        matches = load_manifests(target_date)
    elif source == 'telegram':
        matches = load_telegram_manifest(target_date)
    else:  # both
        matches = merge_manifests(
            load_manifests(target_date),
            load_telegram_manifest(target_date),
        )
    if not matches:
        diagnosis = diagnose_manifest_state(target_date, source)
        state = diagnosis['state']
        print("⚠️ Brak danych do sprawdzenia — koniec.")
        if state == 'empty_run':
            print(
                "   ℹ️ Pipeline zakończył się poprawnie, ale żaden mecz nie "
                "zakwalifikował się do wysyłki (empty marker)."
            )
            if diagnosis.get('empty_reasons'):
                print(f"   📌 Powody: {', '.join(sorted(set(diagnosis['empty_reasons'])))}")
        elif state == 'no_manifest' and diagnosis.get('has_results_fallback'):
            print(
                "   ⚠️ Manifest jest pusty, ale w `results/` są dane scrapingu — "
                "prawdopodobnie upstream workflow nie commitował manifestu "
                "(np. baseball / przerwany run)."
            )
        elif state == 'no_manifest':
            print(
                "   ❌ Brak manifestu i brak fallback `results/` — "
                "scraping w ogóle się nie wydarzył lub artefakty nie zostały "
                "wgrane do repo."
            )
        save_diagnostic_summary(target_date, diagnosis, source)
        return

    # 2. Resolve results — API first, browser only for what is left over
    print(f"\n🔎 Sprawdzam wyniki {len(matches)} meczów...")
    results: Dict[str, Dict[str, Any]] = {}
    unresolved: List[Dict[str, Any]] = []

    if _resolver_ok:
        print("   🌐 Etap 1: SofaScore API (bez przeglądarki)")
        for i, m in enumerate(matches, 1):
            url = m.get('match_url', '')
            home = m.get('home_team', '?')
            away = m.get('away_team', '?')
            if not url:
                results[url] = {'status': 'error', 'error': 'no URL'}
                continue

            # Rows whose match_date never reached the manifest fall back to the
            # report's date. Without a date the resolver refuses to settle,
            # because name-only matching demonstrably picks the wrong fixture.
            try:
                res = resolve_result(home, away,
                                     (m.get('sport') or 'football').lower(),
                                     (m.get('match_date') or '') or target_date)
            except Exception as e:
                print(f"  [{i}/{len(matches)}] {home} vs {away} → ⚠️ API: {str(e)[:60]}")
                res = None

            if res:
                results[url] = res
                if res.get('status') == 'void':
                    print(f"  [{i}/{len(matches)}] {home} vs {away} "
                          f"→ 🚫 {res.get('event_status')}")
                else:
                    print(f"  [{i}/{len(matches)}] {home} vs {away} "
                          f"→ {res.get('score_home')}-{res.get('score_away')}")
            else:
                unresolved.append(m)
            time_module.sleep(0.2)

        print(f"   ✅ API rozstrzygnęło {len(results)}/{len(matches)}, "
              f"zostało {len(unresolved)}")
    else:
        unresolved = list(matches)

    # Browser fallback: only started when something actually needs it, so a
    # fully-resolved card costs no Chrome startup in CI.
    if unresolved and _selenium_ok and not args.no_browser:
        print(f"   🌐 Etap 2: przeglądarka dla {len(unresolved)} meczów")
        try:
            driver = _init_driver(headless=args.headless)
        except Exception as e:
            print(f"   ⚠️ Nie udało się uruchomić przeglądarki: {str(e)[:100]}")
            driver = None

        if driver is not None:
            try:
                for i, m in enumerate(unresolved, 1):
                    url = m.get('match_url', '')
                    home = m.get('home_team', '?')
                    away = m.get('away_team', '?')
                    print(f"  [{i}/{len(unresolved)}] {home} vs {away}")

                    res = scrape_match_result(driver, url)
                    results[url] = res

                    status = res['status']
                    if status == 'finished':
                        print(f"    → {res['score_home']}-{res['score_away']}")
                    elif status == 'not_finished':
                        print(f"    → ⏳ mecz jeszcze trwa")
                    else:
                        print(f"    → ⚠️ {status}")

                    time_module.sleep(0.5)
            finally:
                driver.quit()
    elif unresolved:
        for m in unresolved:
            results.setdefault(m.get('match_url', ''),
                               {'status': 'not_finished'})

    # 3. Evaluate
    stats = evaluate(matches, results)

    print(f"\n{'='*70}")
    print(f"📊 PODSUMOWANIE — {target_date}")
    print(f"{'='*70}")
    print(f"  Łącznie {channel_label}: {stats['total']}")
    print(f"  Zakończone:              {stats['finished']}")
    print(f"  ✅ Wygrane:               {stats['won']}")
    print(f"  ❌ Przegrane:             {stats['lost']}")
    print(f"  🟡 Remisy:                {stats['draw']}")
    print(f"  ⏳ Pending:               {stats['pending']}")
    print(f"  Trafność:                {stats['accuracy']:.1f}%")
    print(f"  ROI:                     {stats['roi_pct']:+.1f}% ({stats['roi_pln']:+.0f} PLN)")
    print(f"{'='*70}\n")

    # 4. Save summary
    save_summary(stats, target_date, tag=summary_tag)

    # 4b. Persist to result store for backtesting
    if _result_store_ok:
        store = ResultStore()
        added = 0
        for m in matches:
            url = m.get('match_url', '')
            res = results.get(url, {})
            if url and res.get('status') == 'finished':
                was_new = store.add_result(
                    match_url=url,
                    result=res,
                    sport=(m.get('sport') or 'football').lower(),
                    home_team=m.get('home_team', ''),
                    away_team=m.get('away_team', ''),
                    date=target_date,
                )
                if was_new:
                    added += 1
        if added:
            store.save()
            print(f'📦 Result store: +{added} results (total: {len(store)})')

    # 5. Send email report
    if args.send_email:
        if not all([args.to, args.from_email, args.password]):
            print("❌ --send-email wymaga --to, --from-email i --password")
            return

        html = generate_report_html(stats, target_date)
        subject = (
            f"📊 Raport skuteczności {target_date}: "
            f"{stats['accuracy']:.0f}% trafność "
            f"({stats['won']}W/{stats['lost']}L/{stats['draw']}D/{stats['pending']}P)"
        )
        send_report_email(
            html=html,
            subject=subject,
            to_email=args.to,
            from_email=args.from_email,
            password=args.password,
            provider=args.provider,
        )

    print("✨ ZAKOŃCZONO!")


if __name__ == '__main__':
    main()
