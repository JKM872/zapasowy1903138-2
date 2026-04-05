"""
Run Daily Telegram Results Report
===================================

CLI entry-point for the daily accuracy summary sent to Telegram.
Reads qualifying predictions from the last N hours, computes win/loss/pending,
builds a formatted message, and sends it via the Telegram Bot API.

Prefers the telegram manifest (saved by telegram_notifier) when available,
so the follow-up reports only on matches that were actually sent to Telegram.

Usage:
    python run_daily_telegram_results.py                  # default: last 24h
    python run_daily_telegram_results.py --hours 48       # last 48h
    python run_daily_telegram_results.py --dry-run        # print message without sending
    python run_daily_telegram_results.py --date 2026-03-30  # label override
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _load_telegram_manifest(date: str) -> list[dict] | None:
    """Try to load the telegram manifest for *date* (YYYY-MM-DD).
    Returns list of match dicts or None if not found."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "outputs", f"telegram_manifest_{date}.json")
    if not os.path.isfile(path):
        # Also search one day before (scraper may run around midnight)
        from datetime import timedelta
        prev = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        path_prev = os.path.join(base, "outputs", f"telegram_manifest_{prev}.json")
        if os.path.isfile(path_prev):
            path = path_prev
        else:
            return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        matches = data.get("matches", [])
        if matches:
            print(f"📋 Loaded telegram manifest: {path} ({len(matches)} matches)")
        return matches or None
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️  Cannot read manifest {path}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram daily results report")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours (default: 24)")
    parser.add_argument("--date", type=str, default=None, help="Report date label (YYYY-MM-DD). Default: today")
    parser.add_argument("--dry-run", action="store_true", help="Print message to stdout, don't send")
    args = parser.parse_args()

    report_date = args.date or datetime.now().strftime("%Y-%m-%d")

    # ── 1. Fetch stats from Supabase ─────────────────────────
    try:
        from supabase_manager import SupabaseManager
    except ImportError:
        print("❌ supabase_manager niedostępny — upewnij się, że supabase jest zainstalowany")
        return 1

    try:
        db = SupabaseManager()
    except RuntimeError as exc:
        print(f"❌ Nie można połączyć z Supabase: {exc}")
        return 1

    # Try manifest first (only matches actually sent to Telegram)
    manifest_matches = _load_telegram_manifest(report_date)

    print(f"📊 Pobieram statystyki za ostatnie {args.hours}h…")
    stats = db.get_telegram_daily_stats(
        hours=args.hours,
        manifest_matches=manifest_matches,
    )

    g = stats.get("global", {})
    source = "manifest" if manifest_matches else "24h window"
    print(f"   Źródło: {source}")
    print(f"   Łącznie: {g.get('total', 0)}  ✅ {g.get('win', 0)}  ❌ {g.get('loss', 0)}  ⏳ {g.get('pending', 0)}")

    # ── 2. Build message ─────────────────────────────────────
    from telegram_results_report import (
        build_daily_results_summary,
        send_daily_results_summary,
        should_send_daily_results_summary,
    )

    if not should_send_daily_results_summary(stats):
        print("ℹ️  No settled matches yet — skipping Telegram results report")
        return 0

    text = build_daily_results_summary(stats, report_date)

    if args.dry_run:
        print("\n--- DRY RUN (message preview) ---")
        print(text)
        print("--- END ---")
        return 0

    # ── 3. Send ──────────────────────────────────────────────
    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    if not enabled:
        print("ℹ️  TELEGRAM_ENABLED != true — pomijam wysyłkę (użyj --dry-run aby zobaczyć treść)")
        return 0

    ok = send_daily_results_summary(stats, report_date)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
