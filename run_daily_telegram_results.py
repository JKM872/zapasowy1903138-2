"""
Run Daily Telegram Results Report
===================================

CLI entry-point for the daily accuracy summary sent to Telegram.

Logika raportu (zgodnie z wymaganiem):
    1) bierzemy WYŁĄCZNIE mecze z manifestów Telegrama (czyli te, które
       faktycznie zostały wysłane subskrybentom),
    2) okno czasowe to ostatnie N dni (domyślnie 3) — manifest dnia X
       zawiera Grade A/B picki wysłane tego dnia; my je sklejamy w jeden
       raport, więc poranny raport pokazuje też wczoraj,
    3) zliczamy tylko Grade A (manifest Telegrama trzyma A/B → tu tniemy
       jeszcze do A),
    4) typy 1/2 ewaluujemy w trybie Draw No Bet — remis to push (zwrot
       stawki), nie loss; typy X traktujemy normalnie,
    5) raport wysyłamy ZAWSZE, gdy mamy choć jeden Grade A pick w oknie —
       nawet jak wszystko jeszcze pending. Subskrybent widzi wtedy listę
       "in play" zamiast głuchej ciszy.

Usage:
    python run_daily_telegram_results.py                    # 3 dni wstecz
    python run_daily_telegram_results.py --days 7           # tydzień
    python run_daily_telegram_results.py --date 2026-05-19  # tylko ten dzień
    python run_daily_telegram_results.py --dry-run
    python run_daily_telegram_results.py --grades A,B
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

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


def _date_window(end_date: str, days: int) -> List[str]:
    """Return list of YYYY-MM-DD dates ending on ``end_date`` (inclusive)."""
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    return [
        (end - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]


def _load_manifest_for_date(date: str) -> Optional[List[dict]]:
    """Load matches list for a specific date or None when file missing."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "outputs", f"telegram_manifest_{date}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("matches", []) or []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"⚠️  Cannot read manifest {path}: {exc}")
        return None


def _load_telegram_manifests(dates: List[str]) -> Tuple[List[dict], List[str]]:
    """Load and merge manifests for ``dates``. Returns (merged, dates_used)."""
    merged: List[dict] = []
    dates_used: List[str] = []
    for d in dates:
        matches = _load_manifest_for_date(d)
        if matches is None:
            print(f"   · {d}: no manifest")
            continue
        if not matches:
            print(f"   · {d}: manifest empty")
            dates_used.append(d)
            continue
        # Tag each match with the manifest date so we can dedupe/inspect later.
        for m in matches:
            m.setdefault("match_date", d)
        merged.extend(matches)
        dates_used.append(d)
        print(f"   · {d}: {len(matches)} matches")
    return merged, dates_used


def _dedupe_matches(matches: List[dict]) -> List[dict]:
    """Drop duplicates that may appear when the same match was sent on
    multiple days (e.g. evening + morning re-send). Keeps the last copy."""
    seen: Dict[Tuple[str, str, str], dict] = {}
    for m in matches:
        key = (
            (m.get("home_team") or "").strip(),
            (m.get("away_team") or "").strip(),
            (m.get("match_date") or "").strip(),
        )
        if key[0] and key[1]:
            seen[key] = m
    return list(seen.values())


def _parse_grades(spec: str) -> Optional[Set[str]]:
    """Parse a comma-separated grade list, e.g. 'A' or 'A,B'.

    Returns None when spec is empty (filter disabled)."""
    parts = [p.strip().upper() for p in (spec or "").split(",") if p.strip()]
    valid = {p for p in parts if p in ("A", "B", "C", "D", "F")}
    return valid or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram daily results report (Grade A · DNB)")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="End-of-window date (YYYY-MM-DD, Warsaw TZ). Default: today.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="How many days to include in the report (default: 3).",
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
        help="Legacy fallback window. Ignored when manifests exist.",
    )
    args = parser.parse_args()

    end_date = args.date or _today_warsaw()
    days = max(1, int(args.days))
    grade_filter = _parse_grades(args.grades) if args.grades else None
    window_dates = _date_window(end_date, days)
    start_date = window_dates[-1]

    print(f"📅 Report window: {start_date} → {end_date} ({days} day(s))")
    if grade_filter:
        print(f"🎯 Grade filter: {sorted(grade_filter)}")
    else:
        print("🎯 Grade filter: disabled (all grades)")

    # ── 1. Load manifests for the whole window ────────────────────
    print("📋 Loading Telegram manifests:")
    manifest_matches_raw, dates_used = _load_telegram_manifests(window_dates)
    manifest_matches = _dedupe_matches(manifest_matches_raw)

    used_fallback = False
    if not manifest_matches:
        print(
            f"ℹ️  Brak manifestów Telegrama w oknie {start_date} → {end_date}. "
            f"Próbuję fallback: rekonstrukcja z Supabase (qualifies=true)…"
        )
        used_fallback = True
    else:
        print(f"📦 Łącznie {len(manifest_matches)} unikalnych meczów w manifestach.")

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

    print(f"📊 Liczę statystyki…")
    if used_fallback:
        print(
            "⚠️  Tryb fallback: brak manifestów Telegrama, używam Supabase "
            "(qualifies=true). Filtr Grade A pomijany — baza nie ma kolumny "
            "prediction_grade."
        )
        stats = db.get_telegram_daily_stats(
            hours=args.hours,
            manifest_matches=None,
            grade_filter=grade_filter,
            match_dates=window_dates,
        )
    else:
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

    if not should_send_daily_results_summary(stats):
        print(
            "ℹ️  Brak Grade A picków w manifestach okna — pomijam raport."
        )
        return 0

    date_range = (start_date, end_date)
    text = build_daily_results_summary(stats, end_date, date_range=date_range)

    if args.dry_run:
        print("\n--- DRY RUN (message preview) ---")
        print(text)
        print("--- END ---")
        return 0

    enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    if not enabled:
        print("ℹ️  TELEGRAM_ENABLED != true — pomijam wysyłkę (użyj --dry-run aby zobaczyć treść)")
        return 0

    ok = send_daily_results_summary(stats, end_date, date_range=date_range)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
