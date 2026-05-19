"""
Run Daily Telegram Results Report
===================================

CLI entry-point for the daily accuracy summary sent to Telegram.

Logika raportu (zgodnie z wymaganiem):
    1) bierzemy WYŁĄCZNIE mecze z manifestu Telegrama dla danego dnia
       (czyli te, które faktycznie zostały wysłane subskrybentom),
    2) zliczamy tylko Grade A (manifest Telegrama trzyma A/B → tu tniemy
       jeszcze do A),
    3) typy 1/2 ewaluujemy w trybie Draw No Bet — remis to push (zwrot
       stawki), nie loss; typy X (jeśli były) traktujemy normalnie,
    4) okno czasowe to "od dnia dzisiejszego" (label = today w Warszawie,
       z opcją --date YYYY-MM-DD do nadpisania).

Bez manifestu raport NIE jest wysyłany — to gwarantuje, że pokazujemy
wyłącznie skuteczność typów rzeczywiście zakomunikowanych na kanale.

Usage:
    python run_daily_telegram_results.py                  # today
    python run_daily_telegram_results.py --date 2026-05-19
    python run_daily_telegram_results.py --dry-run        # preview
    python run_daily_telegram_results.py --grades A,B     # rozluźnienie filtra
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import List, Optional, Set

try:
    from zoneinfo import ZoneInfo
    _WARSAW_TZ = ZoneInfo("Europe/Warsaw")
except Exception:  # pragma: no cover
    _WARSAW_TZ = None  # type: ignore

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _today_warsaw() -> str:
    if _WARSAW_TZ is not None:
        return datetime.now(_WARSAW_TZ).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def _load_telegram_manifest(date: str) -> Optional[List[dict]]:
    """Load telegram manifest matches for *date* (YYYY-MM-DD).

    Returns the list of match dicts, or None when the file is missing.
    Empty manifest (file present, zero matches) returns []."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "outputs", f"telegram_manifest_{date}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        matches = data.get("matches", []) or []
        print(f"📋 Loaded telegram manifest: {path} ({len(matches)} matches)")
        return matches
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️  Cannot read manifest {path}: {exc}")
        return None


def _parse_grades(spec: str) -> Set[str]:
    """Parse a comma-separated grade list, e.g. 'A' or 'A,B'."""
    parts = [p.strip().upper() for p in (spec or "").split(",") if p.strip()]
    return {p for p in parts if p in ("A", "B", "C", "D", "F")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram daily results report (Grade A · DNB)")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Report date (YYYY-MM-DD, Warsaw TZ). Default: today.",
    )
    parser.add_argument(
        "--grades",
        type=str,
        default="A",
        help="Comma-separated grade filter (default: A). Use '' to disable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message to stdout, don't send to Telegram.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Legacy fallback window. Ignored when manifest exists.",
    )
    args = parser.parse_args()

    report_date = args.date or _today_warsaw()
    grade_filter = _parse_grades(args.grades) if args.grades else None

    if grade_filter:
        print(f"🎯 Grade filter: {sorted(grade_filter)}")
    else:
        print("🎯 Grade filter: disabled (all grades)")

    # ── 1. Manifest first — without it we don't send anything ─────
    manifest_matches = _load_telegram_manifest(report_date)
    if manifest_matches is None:
        print(
            f"ℹ️  Brak manifestu Telegrama dla {report_date} — pomijam raport "
            f"(raport bazuje wyłącznie na meczach faktycznie wysłanych na Telegram)."
        )
        return 0
    if not manifest_matches:
        print(
            f"ℹ️  Manifest Telegrama dla {report_date} jest pusty — brak typów "
            f"do oceny, pomijam raport."
        )
        return 0

    # ── 2. Fetch stats from Supabase ──────────────────────────────
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

    print(f"📊 Liczę statystyki dla manifestu z {report_date}…")
    stats = db.get_telegram_daily_stats(
        hours=args.hours,
        manifest_matches=manifest_matches,
        grade_filter=grade_filter,
    )

    g = stats.get("global", {})
    print(
        f"   Grade(s): {','.join(sorted(grade_filter)) if grade_filter else 'ALL'}"
        f" · Łącznie: {g.get('total', 0)}"
        f"  ✅ {g.get('win', 0)}"
        f"  ❌ {g.get('loss', 0)}"
        f"  ↩ {g.get('push', 0)}"
        f"  ⏳ {g.get('pending', 0)}"
    )

    # ── 3. Build & maybe send ─────────────────────────────────────
    from telegram_results_report import (
        build_daily_results_summary,
        send_daily_results_summary,
        should_send_daily_results_summary,
    )

    if g.get("total", 0) == 0:
        print("ℹ️  Brak meczów spełniających kryteria (Grade A) — pomijam raport.")
        return 0

    if not should_send_daily_results_summary(stats):
        print("ℹ️  Żaden mecz jeszcze się nie rozstrzygnął — pomijam raport.")
        return 0

    text = build_daily_results_summary(stats, report_date)

    if args.dry_run:
        print("\n--- DRY RUN (message preview) ---")
        print(text)
        print("--- END ---")
        return 0

    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    if not enabled:
        print("ℹ️  TELEGRAM_ENABLED != true — pomijam wysyłkę (użyj --dry-run aby zobaczyć treść)")
        return 0

    ok = send_daily_results_summary(stats, report_date)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
