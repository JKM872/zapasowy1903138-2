#!/usr/bin/env python3
"""
Noon Refresh Script — re-fetches SofaScore fan votes and Forebet predictions
for matches that were sent in the morning email, then sends an updated email.

Usage:
    python refresh_qualified_manifest.py \
        --date 2026-04-06 \
        --to recipient@example.com \
        --from-email sender@example.com \
        --password "app-password" \
        --provider gmail \
        --headless
"""

import argparse
import json
import os
import sys
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List

# ── Local imports ──
from email_notifier import (
    SMTP_CONFIG,
    SPORT_EMOJI,
    SPORT_LABEL,
    create_html_email,
)
from forebet_scraper import search_forebet_prediction
from sofascore_scraper import search_event_via_api, get_votes_via_api


# Fields that get refreshed from Forebet
_FOREBET_FIELDS = [
    'forebet_prediction',
    'forebet_probability',
]

# Fields that get refreshed from SofaScore
_SOFASCORE_FIELDS = [
    'sofascore_home_win_prob',
    'sofascore_draw_prob',
    'sofascore_away_win_prob',
    'sofascore_total_votes',
]


def load_morning_manifest(date: str) -> List[Dict[str, Any]]:
    """Load all morning manifest files for the given date and merge them."""
    outputs_dir = 'outputs'
    prefix = f'mailed_manifest_{date}'
    all_matches: List[Dict[str, Any]] = []
    seen_urls: set = set()

    if not os.path.isdir(outputs_dir):
        print(f"⚠️  Katalog {outputs_dir} nie istnieje — brak manifestu porannego")
        return []

    for fname in sorted(os.listdir(outputs_dir)):
        if fname.startswith(prefix) and fname.endswith('.json'):
            # Skip noon manifests from previous runs
            if '_noon' in fname:
                continue
            path = os.path.join(outputs_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for match in data:
                    url = match.get('match_url')
                    if url and url not in seen_urls:
                        all_matches.append(match)
                        seen_urls.add(url)
                print(f"   📂 Wczytano {len(data)} meczów z {fname}")
            except (json.JSONDecodeError, OSError) as e:
                print(f"   ⚠️  Błąd odczytu {fname}: {e}")

    return all_matches


def refresh_forebet(match: Dict[str, Any], headless: bool = True) -> Dict[str, Any]:
    """Re-fetch Forebet prediction for a single match."""
    home = match.get('home_team', '')
    away = match.get('away_team', '')
    date = match.get('match_date', '')
    sport = match.get('sport', 'football')

    if not home or not away:
        return {}

    try:
        result = search_forebet_prediction(
            home_team=home,
            away_team=away,
            match_date=date,
            sport=sport,
            headless=headless,
            timeout=15,
        )
        if result and result.get('success'):
            return {
                'forebet_prediction': result.get('prediction'),
                'forebet_probability': result.get('probability'),
            }
    except Exception as e:
        print(f"      ⚠️  Forebet error for {home} vs {away}: {e}")

    return {}


def refresh_sofascore(match: Dict[str, Any]) -> Dict[str, Any]:
    """Re-fetch SofaScore fan votes for a single match."""
    home = match.get('home_team', '')
    away = match.get('away_team', '')
    sport = match.get('sport', 'football')
    date = match.get('match_date', '')

    if not home or not away:
        return {}

    try:
        event_id = search_event_via_api(
            home_team=home,
            away_team=away,
            sport=sport,
            date_str=date,
        )
        if event_id:
            votes = get_votes_via_api(event_id)
            if votes:
                return {
                    'sofascore_home_win_prob': votes.get('sofascore_home_win_prob'),
                    'sofascore_draw_prob': votes.get('sofascore_draw_prob'),
                    'sofascore_away_win_prob': votes.get('sofascore_away_win_prob'),
                    'sofascore_total_votes': votes.get('sofascore_total_votes'),
                }
    except Exception as e:
        print(f"      ⚠️  SofaScore error for {home} vs {away}: {e}")

    return {}


def refresh_matches(
    matches: List[Dict[str, Any]],
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """Refresh Forebet and SofaScore data for all matches."""
    total = len(matches)
    refreshed: List[Dict[str, Any]] = []
    forebet_updated = 0
    sofascore_updated = 0

    for i, match in enumerate(matches, 1):
        home = match.get('home_team', '?')
        away = match.get('away_team', '?')
        sport = match.get('sport', '?')
        print(f"   [{i}/{total}] {sport}: {home} vs {away}")

        updated = dict(match)  # shallow copy — preserve all morning fields

        # Refresh Forebet
        fb = refresh_forebet(match, headless=headless)
        if fb:
            updated.update(fb)
            forebet_updated += 1
            print(f"      ✅ Forebet: {fb.get('forebet_prediction')} ({fb.get('forebet_probability')}%)")

        # Small delay between API calls
        time.sleep(0.3)

        # Refresh SofaScore
        ss = refresh_sofascore(match)
        if ss:
            updated.update(ss)
            sofascore_updated += 1
            home_pct = ss.get('sofascore_home_win_prob', '?')
            draw_pct = ss.get('sofascore_draw_prob', '?')
            away_pct = ss.get('sofascore_away_win_prob', '?')
            votes = ss.get('sofascore_total_votes', '?')
            print(f"      ✅ SofaScore: {home_pct}/{draw_pct}/{away_pct} ({votes} głosów)")

        refreshed.append(updated)

    print()
    print(f"   📊 Podsumowanie odświeżania:")
    print(f"      Forebet zaktualizowano:  {forebet_updated}/{total}")
    print(f"      SofaScore zaktualizowano: {sofascore_updated}/{total}")
    return refreshed


def save_noon_manifest(matches: List[Dict[str, Any]], date: str) -> str:
    """Save refreshed manifest as the noon version."""
    os.makedirs('outputs', exist_ok=True)
    path = f'outputs/mailed_manifest_{date}_noon.json'

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

    print(f"   📋 Noon manifest zapisany: {path} ({len(matches)} meczów)")
    return path


def send_noon_email(
    matches: List[Dict[str, Any]],
    date: str,
    to_email: str,
    from_email: str,
    password: str,
    provider: str = 'gmail',
) -> int:
    """Send refreshed noon email, one per sport — same layout as morning."""
    # Group by sport
    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    for m in matches:
        sport = m.get('sport', 'football')
        by_sport.setdefault(sport, []).append(m)

    smtp_config = SMTP_CONFIG[provider]
    sent_count = 0

    try:
        with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
            if smtp_config['use_tls']:
                server.starttls()
            server.login(from_email, password)

            for sport in sorted(by_sport):
                sport_matches = by_sport[sport]
                emoji = SPORT_EMOJI.get(sport, '🏆')
                label = SPORT_LABEL.get(sport, sport.capitalize())

                html = create_html_email(sport_matches, date, sort_by='time')
                subj = f"🔄 {emoji} {label} Update 12:00 — {len(sport_matches)} meczów — {date}"

                msg = MIMEMultipart('alternative')
                msg['Subject'] = subj
                msg['From'] = from_email
                msg['To'] = to_email
                msg.attach(MIMEText(html, 'html'))
                server.send_message(msg)
                sent_count += 1
                print(f"   ✅ Wysłano: {subj}")

    except Exception as e:
        print(f"   ❌ Błąd wysyłania: {e}")

    return sent_count


def main():
    parser = argparse.ArgumentParser(
        description='Noon refresh: update Forebet + SofaScore for morning matches'
    )
    parser.add_argument('--date', required=True, help='Data YYYY-MM-DD')
    parser.add_argument('--to', required=True, help='Email odbiorcy')
    parser.add_argument('--from-email', required=True, help='Email nadawcy')
    parser.add_argument('--password', required=True, help='Hasło email (App Password)')
    parser.add_argument('--provider', default='gmail',
                        choices=['gmail', 'outlook', 'yahoo'],
                        help='Provider email (domyślnie: gmail)')
    parser.add_argument('--headless', action='store_true',
                        help='Uruchom Forebet w trybie headless')
    parser.add_argument('--skip-email', action='store_true',
                        help='Pomiń wysyłanie emaili (tylko odśwież dane)')
    args = parser.parse_args()

    print("=" * 70)
    print(f"🔄 NOON REFRESH — {args.date}")
    print("=" * 70)

    # 1. Load morning manifest
    print("\n📂 Ładowanie manifestu porannego...")
    matches = load_morning_manifest(args.date)
    if not matches:
        print("   ℹ️  Brak meczów do odświeżenia — kończę.")
        sys.exit(0)
    print(f"   Znaleziono {len(matches)} meczów z rana\n")

    # 2. Refresh Forebet + SofaScore
    print("🔄 Odświeżanie danych...")
    refreshed = refresh_matches(matches, headless=args.headless)

    # 3. Save noon manifest
    print("\n💾 Zapisywanie noon manifestu...")
    save_noon_manifest(refreshed, args.date)

    # 4. Send email
    if args.skip_email:
        print("\n📧 Wysyłanie emaili pominięte (--skip-email)")
    else:
        print("\n📧 Wysyłanie odświeżonych emaili...")
        sent = send_noon_email(
            matches=refreshed,
            date=args.date,
            to_email=args.to,
            from_email=args.from_email,
            password=args.password,
            provider=args.provider,
        )
        print(f"\n   📬 Wysłano {sent} emaili")

    print("\n✅ Noon refresh zakończony!")


if __name__ == '__main__':
    main()
