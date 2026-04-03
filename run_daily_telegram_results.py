"""
Run Daily Telegram Results Report
===================================

CLI entry-point for the daily accuracy summary sent to Telegram.
Reads qualifying predictions from the last N hours, computes win/loss/pending,
builds a formatted message, and sends it via the Telegram Bot API.

Usage:
    python run_daily_telegram_results.py                  # default: last 24h
    python run_daily_telegram_results.py --hours 48       # last 48h
    python run_daily_telegram_results.py --dry-run        # print message without sending
    python run_daily_telegram_results.py --date 2026-03-30  # label override
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


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

    print(f"📊 Pobieram statystyki za ostatnie {args.hours}h…")
    stats = db.get_telegram_daily_stats(hours=args.hours)

    g = stats.get("global", {})
    print(f"   Łącznie: {g.get('total', 0)}  ✅ {g.get('win', 0)}  ❌ {g.get('loss', 0)}  ⏳ {g.get('pending', 0)}")

    # ── 2. Build message ─────────────────────────────────────
    from telegram_results_report import build_daily_results_summary, send_daily_results_summary

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
