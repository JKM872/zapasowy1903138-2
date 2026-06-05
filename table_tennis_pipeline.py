# -*- coding: utf-8 -*-
"""
🏓 TABLE TENNIS PIPELINE — SofaScore-sourced
=============================================

Why a separate pipeline?
------------------------
LiveSport lists too few table-tennis matches (especially amateur / lower-tier
events like TT Elite Series). SofaScore covers virtually all of them, so for
table tennis we source the match list directly from SofaScore's
``scheduled-events`` endpoint instead of scraping LiveSport.

Qualification priorities (per requirements):
  • H2H        — used when available (head-to-head record between the two)
  • Odds       — REQUIRED: favourite must be >= 1.35 (value filter)
  • Form       — general recent form (previous matches), home/away irrelevant
  • Fan vote   — OPTIONAL bonus signal (amateur matches often have 0 votes,
                 and those are exactly the events we still want)

To avoid hammering the SofaScore API (which 403s after ~700 calls), we filter
by ODDS FIRST (one cheap call per event), drop events without a clear
favourite, and only then fetch H2H + form (+ optional votes) for survivors.

Phases:
  FAZA 1  — list all table-tennis events for the date from SofaScore.
  FAZA 2a — odds gate: keep only events whose favourite >= 1.35.
  FAZA 2b — enrich survivors: H2H, form, (optional) fan vote.
  FAZA 2.5— score survivors with TennisScoringEngine (2-way, no draw).
  FAZA 2.9— unified qualification gate (odds + future-only).
  OUTPUT  — CSV + JSON, optional Telegram summary.

Everything reuses the existing battle-tested SofaScore HTTP stack
(``_api_get_json`` → curl_cffi / FlareSolverr / WARP), the TennisScoringEngine,
and the qualification_gate + telegram_notifier modules.

Usage:
    python table_tennis_pipeline.py --date 2026-06-04
    python table_tennis_pipeline.py --date 2026-06-04 --max-matches 50 --no-telegram
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPORT = "table_tennis"
SPORT_LABEL = "Table Tennis"

# Minimum decimal odds the favourite must have to be considered a value pick.
TT_MIN_FAVOURITE_ODDS = 1.35

# ---------------------------------------------------------------------------
# Table-tennis scoring profile
# ---------------------------------------------------------------------------
# Table tennis on SofaScore exposes odds + H2H + recent form (and sometimes a
# fan vote), but almost never rankings or surface (unlike ATP/WTA tennis). The
# default TennisScoringEngine weights/threshold assume that rich data, so they
# would disqualify every table-tennis match. We use a profile that concentrates
# weight on the signals that ARE available, with a lower advanced_score
# threshold calibrated so clear favourites (positive EV) qualify while
# coin-flips do not. Fan vote keeps weight but contributes neutral 0.5 when
# absent, so vote-less amateur matches are NOT penalised.
TT_WEIGHTS: Dict[str, float] = {
    "odds":         0.34,
    "h2h":          0.26,
    "form":         0.20,
    "sofascore":    0.12,
    "serve_model":  0.08,
    "surface_form": 0.0,
    "ranking":      0.0,
    "fatigue":      0.0,
    "availability": 0.0,
}
TT_THRESHOLD = 25.0


# ---------------------------------------------------------------------------
# SofaScore imports (graceful — module must import even if scraper is absent)
# ---------------------------------------------------------------------------

try:
    from sofascore_scraper import (
        list_scheduled_events,
        get_votes_via_api,
        get_odds_via_api,
        get_event_h2h,
        get_team_recent_form,
        is_sofascore_unreachable,
    )
    _SOFASCORE_OK = True
except Exception as e:  # pragma: no cover - import guard
    _SOFASCORE_OK = False
    _SOFASCORE_IMPORT_ERROR = str(e)
    print(f"⚠️ sofascore_scraper niedostępny: {e}")
    def is_sofascore_unreachable() -> bool:  # type: ignore
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_match_time(ts: Optional[int]) -> str:
    """Convert a unix timestamp (UTC seconds) to 'DD.MM.YYYY HH:MM' (UTC).

    The downstream qualification gate / telegram parse this exact format.
    """
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, OverflowError, OSError):
        return ""


def _vote_probs_two_way(votes: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Normalize SofaScore vote dict to 2-way home/away percentages.

    Table tennis has no draw, so any drawn-vote share is ignored and the
    home/away split is renormalized to 100%.
    """
    if not votes:
        return None
    h = votes.get("sofascore_home_win_prob")
    a = votes.get("sofascore_away_win_prob")
    if h is None or a is None:
        return None
    try:
        h = float(h)
        a = float(a)
    except (ValueError, TypeError):
        return None
    total = h + a
    if total <= 0:
        return None
    return {
        "home": round(h / total * 100, 1),
        "away": round(a / total * 100, 1),
        "total_votes": votes.get("sofascore_total_votes", 0) or 0,
    }


def _build_row(event: Dict[str, Any]) -> Dict[str, Any]:
    """Build the base row dict for a SofaScore table-tennis event.

    The field contract matches what TennisScoringEngine, qualification_gate
    and telegram_notifier expect (Player A = home, Player B = away).
    """
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    event_id = event.get("event_id")
    return {
        "event_id": event_id,
        "home_id": event.get("home_id"),
        "away_id": event.get("away_id"),
        "match_url": f"https://www.sofascore.com/event/{event_id}" if event_id else "",
        "home_team": home,
        "away_team": away,
        "match_time": _ts_to_match_time(event.get("start_timestamp")),
        "sport": SPORT,
        "league": event.get("tournament", ""),
        "category": event.get("category", ""),
        "focus_team": "home",

        # SofaScore fan vote (filled in enrichment)
        "sofascore_home_win_prob": None,
        "sofascore_draw_prob": None,
        "sofascore_away_win_prob": None,
        "sofascore_total_votes": 0,
        "sofascore_found": False,
        "sofascore_skip_reason": None,

        # Odds
        "home_odds": None,
        "away_odds": None,
        "odds_bookmaker": None,

        # H2H (Player A / Player B framing)
        "h2h_last5": [],
        "home_wins_in_h2h_last5": 0,
        "away_wins_in_h2h_last5": 0,
        "h2h_count": 0,
        "win_rate": 0.0,

        # Tennis-engine compatibility fields (neutral defaults — no synthetic data)
        "ranking_a": None,
        "ranking_b": None,
        "form_a": [],
        "form_b": [],
        "surface": "",
        "surface_form_a": [],
        "surface_form_b": [],

        "qualifies": False,
        "tt_skip_reason": None,
    }


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def _favourite_odds(row: Dict[str, Any]) -> Optional[float]:
    """Return the lower (favourite) of home/away odds, or None if unavailable."""
    ho = row.get("home_odds")
    ao = row.get("away_odds")
    try:
        ho = float(ho) if ho else None
        ao = float(ao) if ao else None
    except (ValueError, TypeError):
        return None
    candidates = [o for o in (ho, ao) if o and o > 1.0]
    return min(candidates) if candidates else None


def fetch_odds(row: Dict[str, Any]) -> bool:
    """Fetch SofaScore odds for a row (in place). Returns True if odds found.

    This is the CHEAP first-pass gate: one API call, used to drop events
    without a clear favourite before spending calls on H2H/form/votes.
    """
    event_id = row.get("event_id")
    if not event_id:
        return False
    try:
        odds = get_odds_via_api(event_id)
    except Exception:
        odds = None
    if odds and odds.get("odds_found"):
        row["home_odds"] = odds.get("home_odds")
        row["away_odds"] = odds.get("away_odds")
        row["odds_bookmaker"] = odds.get("bookmaker")
        return True
    return False


def enrich_row(row: Dict[str, Any], with_votes: bool = True) -> Dict[str, Any]:
    """Fetch H2H, recent form and (optional) fan vote for a survivor row.

    Called only for events that already passed the odds gate, to minimise
    SofaScore API calls. Fan vote is a BONUS signal — its absence does not
    disqualify the event (amateur matches commonly have 0 votes).
    """
    event_id = row.get("event_id")
    if not event_id:
        row["tt_skip_reason"] = "no_event_id"
        return row

    # --- H2H (used when available) ---
    try:
        h2h = get_event_h2h(event_id)
    except Exception:
        h2h = None
    if h2h:
        row["home_wins_in_h2h_last5"] = h2h.get("home_wins", 0)
        row["away_wins_in_h2h_last5"] = h2h.get("away_wins", 0)
        row["h2h_count"] = h2h.get("total", 0)
        total = h2h.get("total", 0)
        if total > 0:
            row["win_rate"] = round(h2h.get("home_wins", 0) / total, 3)

    # --- General recent form (previous matches; venue irrelevant) ---
    try:
        row["form_a"] = get_team_recent_form(row.get("home_id"), row.get("home_team", ""))
    except Exception:
        row["form_a"] = []
    try:
        row["form_b"] = get_team_recent_form(row.get("away_id"), row.get("away_team", ""))
    except Exception:
        row["form_b"] = []

    # --- Fan vote (OPTIONAL bonus) ---
    if with_votes:
        try:
            votes = get_votes_via_api(event_id)
        except Exception:
            votes = None
        probs = _vote_probs_two_way(votes)
        if probs:
            row["sofascore_home_win_prob"] = probs["home"]
            row["sofascore_away_win_prob"] = probs["away"]
            row["sofascore_total_votes"] = probs["total_votes"]
            row["sofascore_found"] = True
        else:
            row["sofascore_found"] = False
            row["sofascore_skip_reason"] = "no_fan_vote"

    return row


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_rows(rows: List[Dict[str, Any]]) -> int:
    """Score qualifying rows with the TennisScoringEngine (2-way model).

    Returns the number of rows scored.
    """
    try:
        from tennis_scoring_engine import TennisScoringEngine
    except Exception as e:
        print(f"⚠️ TennisScoringEngine niedostępny: {e}")
        return 0

    engine = TennisScoringEngine(weights=dict(TT_WEIGHTS), threshold=TT_THRESHOLD)
    # Re-assert the table-tennis profile AFTER construction: the engine's
    # _load_calibration() may overwrite self.weights from a tennis calibration
    # file. Table tennis has its own data regime, so we force our profile here
    # to stay independent of any ATP/WTA calibration.
    engine.weights = dict(TT_WEIGHTS)
    engine.threshold = TT_THRESHOLD
    scored = 0
    for row in rows:
        if not row.get("qualifies"):
            continue
        try:
            sm = engine.score_match(row)
            row["scoring_pick"] = sm.best_pick
            row["scoring_prob"] = round(sm.best_prob * 100, 1)
            row["scoring_ev"] = round(sm.ev, 3)
            row["scoring_edge"] = round(sm.edge, 1)
            row["scoring_kelly"] = round(sm.kelly, 1)
            row["scoring_confidence"] = round(sm.confidence, 0)
            row["scoring_data_quality"] = round(sm.data_quality, 2)
            row["scoring_prob_a"] = round(sm.cal_a * 100, 1)
            row["scoring_prob_b"] = round(sm.cal_b * 100, 1)
            row["advanced_score"] = round(sm.advanced_score, 1)
            row["favorite"] = sm.favorite
            # Final qualification: engine's advanced_score must clear threshold.
            row["qualifies"] = sm.advanced_score >= engine.threshold
            if not row["qualifies"]:
                row["tt_skip_reason"] = (
                    f"advanced_score {sm.advanced_score:.1f} < {engine.threshold:.0f}"
                )
            scored += 1
        except Exception as e:
            print(f"   ⚠️ Scoring error {row.get('home_team')} vs {row.get('away_team')}: {e}")
    return scored


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------

def apply_odds_gate(rows: List[Dict[str, Any]], min_fav_odds: float = TT_MIN_FAVOURITE_ODDS) -> int:
    """Keep only events whose favourite odds are >= ``min_fav_odds``.

    Per requirements, odds are REQUIRED and the favourite must clear 1.35
    (a value filter that drops both no-odds events and prohibitive favourites
    where there is no betting value). Sets ``qualifies`` in place; returns the
    number of rows that PASS.
    """
    passed = 0
    for row in rows:
        fav = _favourite_odds(row)
        if fav is not None and fav >= min_fav_odds:
            row["qualifies"] = True
            passed += 1
        else:
            row["qualifies"] = False
            if fav is None:
                row["tt_skip_reason"] = "no_odds"
            else:
                row["tt_skip_reason"] = f"favourite_odds {fav:.2f} < {min_fav_odds:.2f}"
    return passed


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _to_frontend_json(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compact JSON object for the frontend (mirrors scrape_and_notify shape)."""
    return {
        "id": row.get("event_id"),
        "homeTeam": row.get("home_team"),
        "awayTeam": row.get("away_team"),
        "time": row.get("match_time"),
        "sport": SPORT,
        "league": row.get("league"),
        "matchUrl": row.get("match_url"),
        "qualifies": bool(row.get("qualifies")),
        "channelQualifies": bool(row.get("channel_qualifies")),
        "odds": {
            "home": row.get("home_odds"),
            "away": row.get("away_odds"),
            "bookmaker": row.get("odds_bookmaker"),
        },
        "sofascore": {
            "home": row.get("sofascore_home_win_prob"),
            "away": row.get("sofascore_away_win_prob"),
            "votes": row.get("sofascore_total_votes"),
            "found": row.get("sofascore_found"),
        },
        "h2h": {
            "home": row.get("home_wins_in_h2h_last5"),
            "away": row.get("away_wins_in_h2h_last5"),
            "total": row.get("h2h_count"),
        },
        "form": {
            "home": row.get("form_a"),
            "away": row.get("form_b"),
        },
        "scoring": {
            "pick": row.get("scoring_pick"),
            "prob": row.get("scoring_prob"),
            "ev": row.get("scoring_ev"),
            "edge": row.get("scoring_edge"),
            "confidence": row.get("scoring_confidence"),
            "favorite": row.get("favorite"),
        },
    }


def write_outputs(rows: List[Dict[str, Any]], date_str: str) -> Dict[str, str]:
    """Write CSV + JSON outputs; returns the paths written."""
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("results", exist_ok=True)

    csv_path = os.path.join("outputs", f"table_tennis_{date_str}.csv")
    json_path = os.path.join("results", f"matches_{date_str}_table_tennis.json")

    # CSV (flat) — reuse pandas if available, else manual.
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        if "h2h_last5" in df.columns:
            df["h2h_last5"] = df["h2h_last5"].apply(lambda x: str(x) if x else "")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"   ⚠️ CSV (pandas) failed, writing minimal CSV: {e}")
        import csv as _csv
        if rows:
            keys = sorted({k for r in rows for k in r.keys()})
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
                w = _csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                for r in rows:
                    w.writerow({k: (str(r.get(k)) if isinstance(r.get(k), (list, dict)) else r.get(k)) for k in keys})

    # JSON (frontend)
    frontend = {
        "date": date_str,
        "sport": SPORT,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "matches": [_to_frontend_json(r) for r in rows],
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(frontend, fh, ensure_ascii=False, indent=2)

    return {"csv": csv_path, "json": json_path}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(date_str: str, max_matches: Optional[int] = None,
        send_telegram: bool = True, verbose: bool = True,
        with_votes: bool = True) -> Dict[str, Any]:
    """Run the full table-tennis pipeline for a date.

    Returns a summary dict with counts and output paths.
    """
    if not _SOFASCORE_OK:
        print(f"❌ SofaScore scraper niedostępny — pipeline przerwany ({_SOFASCORE_IMPORT_ERROR})")
        return {"error": "sofascore_unavailable", "matches": 0}

    print("=" * 70)
    print(f"🏓 TABLE TENNIS PIPELINE — {date_str}")
    print("=" * 70)

    # ── FAZA 1: list events from SofaScore ──
    print("\n[FAZA 1] Pobieram listę meczów z SofaScore...")
    events = list_scheduled_events(SPORT, date_str)
    print(f"   📋 Znaleziono {len(events)} zdarzeń table tennis")

    # Keep only not-yet-finished events (notstarted / inprogress).
    upcoming = [e for e in events if (e.get("status") or "").lower() != "finished"]
    if len(upcoming) != len(events):
        print(f"   ⏭️  Pomijam {len(events) - len(upcoming)} zakończonych — zostaje {len(upcoming)}")

    if max_matches:
        upcoming = upcoming[:max_matches]
        print(f"   ✂️  Limit --max-matches: przetwarzam {len(upcoming)}")

    rows = [_build_row(e) for e in upcoming]

    # ── FAZA 2a: ODDS GATE (cheap first pass to minimise API calls) ──
    # Fetch odds for every event (1 call each), then keep only those with a
    # favourite >= 1.35. This drops the bulk of events BEFORE we spend calls on
    # H2H/form/votes, which is what prevents the Cloudflare 403 storm.
    print(f"\n[FAZA 2a] Odds gate ({len(rows)} meczów, favourite ≥ {TT_MIN_FAVOURITE_ODDS})...")
    odds_found = 0
    for i, row in enumerate(rows, 1):
        if is_sofascore_unreachable():
            print(f"   🛑 SofaScore niedostępne (circuit breaker) — przerywam odds gate na {i}/{len(rows)}")
            break
        if fetch_odds(row):
            odds_found += 1
        if verbose and (i % 50 == 0 or i == len(rows)):
            print(f"   [{i}/{len(rows)}] odds: {odds_found} znalezionych")
    passed_odds = apply_odds_gate(rows)
    survivors = [r for r in rows if r.get("qualifies")]
    print(f"   💰 Odds: {odds_found}/{len(rows)} | po filtrze 1.35: {passed_odds} kandydatów")

    # ── FAZA 2b: enrich survivors only (H2H + form + optional votes) ──
    print(f"\n[FAZA 2b] Wzbogacam {len(survivors)} kandydatów (H2H + forma{' + fan vote' if with_votes else ''})...")
    found_votes = 0
    for i, row in enumerate(survivors, 1):
        if is_sofascore_unreachable():
            print(f"   🛑 SofaScore niedostępne — przerywam wzbogacanie na {i}/{len(survivors)}")
            break
        enrich_row(row, with_votes=with_votes)
        if row.get("sofascore_found"):
            found_votes += 1
        if verbose and (i % 25 == 0 or i == len(survivors)):
            print(f"   [{i}/{len(survivors)}] wzbogacono (fan vote: {found_votes})")
    if with_votes:
        print(f"   👥 Fan vote (bonus): {found_votes}/{len(survivors)}")

    # ── FAZA 2.5: scoring (only survivors are scored) ──
    print("\n[FAZA 2.5] Scoring (TennisScoringEngine, profil table tennis)...")
    scored = score_rows(rows)
    qualified = sum(1 for r in rows if r.get("qualifies"))
    print(f"   🧠 {scored} ocenionych, {qualified} kwalifikujących się (advanced_score ≥ {TT_THRESHOLD:.0f})")

    # ── FAZA 2.9: qualification gate (odds + future-only) ──
    try:
        from qualification_gate import apply_qualification_gate
        channel_q = apply_qualification_gate(rows, date_str)
        print(f"\n[FAZA 2.9] Qualification gate: {channel_q} channel-qualified")
    except Exception as e:
        print(f"\n⚠️ Qualification gate error: {e}")
        for row in rows:
            row["channel_qualifies"] = row.get("qualifies", False)

    # ── OUTPUT ──
    paths = write_outputs(rows, date_str)
    print(f"\n💾 Zapisano:\n   CSV:  {paths['csv']}\n   JSON: {paths['json']}")

    # ── Telegram ──
    if send_telegram:
        try:
            from telegram_notifier import send_telegram_summary
            cq = sum(1 for r in rows if r.get("channel_qualifies"))
            send_telegram_summary(rows, cq, date_str)
            print("   ✅ Telegram summary wysłane")
        except Exception as e:
            print(f"   ⚠️ Telegram error: {e}")

    summary = {
        "date": date_str,
        "total_events": len(events),
        "processed": len(rows),
        "odds_candidates": passed_odds,
        "fan_vote_found": found_votes,
        "scored": scored,
        "qualified": sum(1 for r in rows if r.get("qualifies")),
        "channel_qualified": sum(1 for r in rows if r.get("channel_qualifies")),
        "outputs": paths,
    }
    print("\n" + "=" * 70)
    print(f"🏓 DONE — {summary['channel_qualified']} kwalifikujących się z {len(rows)} przetworzonych")
    print("=" * 70)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Table Tennis Pipeline (SofaScore-sourced)")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="Date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--max-matches", type=int, default=None,
                    help="Cap number of matches processed (testing)")
    ap.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification")
    ap.add_argument("--no-votes", action="store_true",
                    help="Skip the optional fan-vote fetch (saves API calls)")
    args = ap.parse_args()

    run(args.date, max_matches=args.max_matches,
        send_telegram=not args.no_telegram, with_votes=not args.no_votes)


if __name__ == "__main__":
    main()
