# -*- coding: utf-8 -*-
"""
🏓 TABLE TENNIS PIPELINE — AiScore-sourced (HOME / AWAY focus)
==============================================================

A SEPARATE pipeline for table tennis that sources the match list, head-to-head
and recent form from **AiScore** (https://www.aiscore.com/table-tennis) — which
lists virtually every table-tennis match including amateur events.

It is intentionally isolated from the other sports' pipelines
(``scrape_and_notify.py`` and the SofaScore-sourced ``table_tennis_pipeline.py``
are left untouched). It only REUSES existing, battle-tested building blocks:

  • aiscore_scraper          — match list + H2H + form (the new source)
  • sofascore_scraper        — MANDATORY Fan Vote (get_sofascore_prediction)
  • pinnacle_full_odds       — odds (best-effort; AiScore exposes no TT odds)
  • tennis_scoring_engine    — 2-way (no-draw) scoring with a table-tennis profile
  • qualification_gate       — channel_qualifies / email_qualifies
  • email_notifier           — e-mail (same gate/template as tennis)
  • telegram_notifier        — Telegram summary

Qualification rules (per requirements):
  1. H2H ≥ 60%   — the FOCUS player (home or away) must have won at least 60%
                   of head-to-head meetings vs the rival.            (HARD GATE)
  2. Fan Vote    — SofaScore Fan Vote is MANDATORY (must be found).  (HARD GATE)
  3. Future-only — match must not have started yet.                  (HARD GATE)
  4. Odds        — Pinnacle if available, otherwise another source; used to
                   enrich scoring / EV. Absence does NOT disqualify (AiScore
                   has no table-tennis odds, and many amateur events have none).

HOME vs AWAY:
  Two workflows run this file with ``--focus home`` and ``--focus away``.
  • --focus home → only emits picks for the HOME player (uses home-venue form,
                   home-player H2H win-rate vs the rival).
  • --focus away → only emits picks for the AWAY player.
  This mirrors the existing scrape.yml (home) / scrape_away.yml (away) split.

Usage:
    python table_tennis_aiscore_pipeline.py --focus home --date 2026-06-05
    python table_tennis_aiscore_pipeline.py --focus away --no-email --no-telegram
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPORT = "table_tennis"
SPORT_LABEL = "Table Tennis"

# Favourite must have won at least this share of the direct H2H to qualify.
H2H_MIN_WIN_RATE = 0.60
# Need at least this many decided H2H meetings to trust the rate.
H2H_MIN_MATCHES = 3

# ── Table-tennis scoring profile (kept in sync with table_tennis_pipeline) ──
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
# Imports of reused building blocks (graceful guards)
# ---------------------------------------------------------------------------

try:
    import aiscore_scraper as ai
    _AI_OK = True
except Exception as e:  # pragma: no cover
    _AI_OK = False
    _AI_ERR = str(e)

try:
    from sofascore_scraper import get_sofascore_prediction
    _SOFA_OK = True
except Exception as e:  # pragma: no cover
    _SOFA_OK = False
    _SOFA_ERR = str(e)
    def get_sofascore_prediction(*a, **k):  # type: ignore
        return {"found": False}


# ---------------------------------------------------------------------------
# Odds (Pinnacle best-effort; another source as fallback)
# ---------------------------------------------------------------------------

def resolve_odds(home: str, away: str, date_str: str,
                 match_url: Optional[str] = None) -> Dict[str, Any]:
    """Best-effort odds resolution for a table-tennis match.

    AiScore exposes no table-tennis odds, so we try Pinnacle (via the shared
    ``pinnacle_full_odds`` client) and fall back to "no odds". Pinnacle is keyed
    on a Livesport event id, so it only succeeds when a matching Livesport
    event URL is supplied. Returns {home_odds, away_odds, bookmaker} (values may
    be None). Missing odds are NON-blocking for qualification.
    """
    out: Dict[str, Any] = {"home_odds": None, "away_odds": None, "bookmaker": None}
    if not match_url or "livesport" not in match_url:
        return out
    try:
        from pinnacle_full_odds import PinnacleFullOdds
        pkg = PinnacleFullOdds().get_full_odds_for_match(match_url)
        market = (pkg.get("markets") or {}).get("HOME_DRAW_AWAY")
        if market:
            h = (market.get("home") or {}).get("value")
            a = (market.get("away") or {}).get("value")
            out["home_odds"] = h
            out["away_odds"] = a
            out["bookmaker"] = "Pinnacle"
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------

def _build_row(home: str, away: str, focus: str, match_url: str,
               match_time: str, league: str = "") -> Dict[str, Any]:
    """Base row whose contract matches TennisScoringEngine / gate / email.

    Player A is always the FOCUS player (home or away), Player B the rival, so
    the engine's home-centric features describe the side we actually pick.
    """
    return {
        "home_team": home,
        "away_team": away,
        "focus": focus,
        "focus_team": focus,
        "match_url": match_url,
        "match_time": match_time,
        "sport": SPORT,
        "league": league,

        # SofaScore fan vote (mandatory, filled later)
        "sofascore_home_win_prob": None,
        "sofascore_draw_prob": None,
        "sofascore_away_win_prob": None,
        "sofascore_total_votes": 0,
        "sofascore_found": False,

        # Odds (best-effort)
        "home_odds": None,
        "away_odds": None,
        "odds_bookmaker": None,

        # H2H
        "h2h_last5": [],
        "home_wins_in_h2h_last5": 0,
        "away_wins_in_h2h_last5": 0,
        "h2h_count": 0,
        "win_rate": 0.0,
        "h2h_fav_win_rate": 0.0,

        # Form
        "form_a": [],
        "form_b": [],
        "ranking_a": None,
        "ranking_b": None,
        "surface": "",
        "surface_form_a": [],
        "surface_form_b": [],

        "qualifies": False,
        "tt_skip_reason": None,
    }


# ---------------------------------------------------------------------------
# Per-match processing
# ---------------------------------------------------------------------------

def process_match(driver: Any, url: str, focus: str, date_str: str,
                  verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Scrape one AiScore match page and build a scored, gated row.

    Returns the row dict, or None when the page could not be parsed at all.
    The row's ``qualifies`` reflects the H2H ≥60% + mandatory Fan Vote gates.
    """
    page = ai.scrape_match_page(driver, url)
    all_matches = page.get("all_matches") or []
    home = page.get("home")
    away = page.get("away")
    if not home or not away:
        if verbose:
            print(f"   ⚠️  Pominięto (brak uczestników): {url}")
        return None

    match_time = ai.iso_to_match_time(page.get("match_date")) or ""
    row = _build_row(home, away, focus, url, match_time)

    # --- which side do we pick? (focus = home/away) ---
    if focus == "away":
        favourite, rival = away, home
    else:
        favourite, rival = home, away

    # --- H2H GATE: favourite must have won >= 60% vs the rival ---
    passes, rec = ai.favourite_meets_h2h_threshold(
        all_matches, favourite, rival,
        threshold=H2H_MIN_WIN_RATE, min_matches=H2H_MIN_MATCHES,
    )
    row["h2h_count"] = rec["total"]
    row["h2h_fav_win_rate"] = rec["fav_win_rate"]
    # Record H2H in the engine's home/away framing.
    if focus == "away":
        row["away_wins_in_h2h_last5"] = rec["fav_wins"]
        row["home_wins_in_h2h_last5"] = rec["total"] - rec["fav_wins"]
    else:
        row["home_wins_in_h2h_last5"] = rec["fav_wins"]
        row["away_wins_in_h2h_last5"] = rec["total"] - rec["fav_wins"]
    row["win_rate"] = round(rec["fav_win_rate"], 3)

    if not passes:
        row["qualifies"] = False
        if rec["total"] < H2H_MIN_MATCHES:
            row["tt_skip_reason"] = f"h2h_too_few ({rec['total']}<{H2H_MIN_MATCHES})"
        else:
            row["tt_skip_reason"] = (
                f"h2h_fav_win_rate {rec['fav_win_rate']:.2f} < {H2H_MIN_WIN_RATE:.2f}"
            )
        return row

    # --- FORM (general + venue split for the focus side) ---
    venue = "away" if focus == "away" else "home"
    row["form_a"] = ai.recent_form(all_matches, favourite, venue=venue, limit=5) \
        or ai.recent_form(all_matches, favourite, limit=5)
    row["form_b"] = ai.recent_form(all_matches, rival, limit=5)

    # --- ODDS (best-effort, non-blocking) ---
    odds = resolve_odds(home, away, date_str, match_url=url)
    row["home_odds"] = odds.get("home_odds")
    row["away_odds"] = odds.get("away_odds")
    row["odds_bookmaker"] = odds.get("bookmaker")

    # --- FAN VOTE (MANDATORY) ---
    try:
        pred = get_sofascore_prediction(home, away, sport="table-tennis", date_str=date_str)
    except Exception as e:
        pred = {"found": False}
        if verbose:
            print(f"   ⚠️  SofaScore błąd dla {home} vs {away}: {e}")
    if pred.get("found"):
        row["sofascore_found"] = True
        row["sofascore_home_win_prob"] = pred.get("home_win_prob")
        row["sofascore_away_win_prob"] = pred.get("away_win_prob")
        row["sofascore_total_votes"] = pred.get("total_votes", 0) or 0
    else:
        row["sofascore_found"] = False
        row["qualifies"] = False
        row["tt_skip_reason"] = "sofascore_fan_vote_required"
        return row

    # Passed both hard gates.
    row["qualifies"] = True
    return row


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_rows(rows: List[Dict[str, Any]]) -> int:
    """Score qualifying rows with the TennisScoringEngine (table-tennis profile)."""
    try:
        from tennis_scoring_engine import TennisScoringEngine
    except Exception as e:
        print(f"⚠️ TennisScoringEngine niedostępny: {e}")
        return 0

    engine = TennisScoringEngine(weights=dict(TT_WEIGHTS), threshold=TT_THRESHOLD)
    # Re-assert the TT profile AFTER construction (calibration file may override).
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
            row["scoring_confidence"] = round(sm.confidence, 0)
            row["advanced_score"] = round(sm.advanced_score, 1)
            row["favorite"] = sm.favorite
            scored += 1
        except Exception as e:
            print(f"   ⚠️ Scoring error {row.get('home_team')} vs {row.get('away_team')}: {e}")
    return scored


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(rows: List[Dict[str, Any]], date_str: str, focus: str) -> Dict[str, str]:
    """Write CSV + JSON. Filenames carry the focus so home/away never collide."""
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("results", exist_ok=True)

    csv_path = os.path.join("outputs", f"table_tennis_aiscore_{focus}_{date_str}.csv")
    json_path = os.path.join("results", f"matches_{date_str}_table_tennis_aiscore_{focus}.json")

    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        for col in ("h2h_last5", "form_a", "form_b", "surface_form_a", "surface_form_b"):
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x) if isinstance(x, (list, dict)) else x)
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

    frontend = {
        "date": date_str,
        "sport": SPORT,
        "source": "aiscore",
        "focus": focus,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "matches": [
            {
                "homeTeam": r.get("home_team"),
                "awayTeam": r.get("away_team"),
                "time": r.get("match_time"),
                "focus": r.get("focus"),
                "matchUrl": r.get("match_url"),
                "qualifies": bool(r.get("qualifies")),
                "channelQualifies": bool(r.get("channel_qualifies")),
                "emailQualifies": bool(r.get("email_qualifies")),
                "h2h": {
                    "favWinRate": r.get("h2h_fav_win_rate"),
                    "total": r.get("h2h_count"),
                },
                "sofascore": {
                    "found": r.get("sofascore_found"),
                    "votes": r.get("sofascore_total_votes"),
                },
                "odds": {
                    "home": r.get("home_odds"),
                    "away": r.get("away_odds"),
                    "bookmaker": r.get("odds_bookmaker"),
                },
                "scoring": {
                    "pick": r.get("scoring_pick"),
                    "prob": r.get("scoring_prob"),
                    "ev": r.get("scoring_ev"),
                    "favorite": r.get("favorite"),
                },
            }
            for r in rows
        ],
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(frontend, fh, ensure_ascii=False, indent=2)

    return {"csv": csv_path, "json": json_path}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(focus: str, date_str: str, max_matches: Optional[int] = None,
        send_email: bool = True, send_telegram: bool = True,
        email_cfg: Optional[Dict[str, str]] = None, verbose: bool = True) -> Dict[str, Any]:
    """Run the AiScore table-tennis pipeline for one focus (home/away)."""
    if not _AI_OK:
        print(f"❌ aiscore_scraper niedostępny — przerwano ({_AI_ERR})")
        return {"error": "aiscore_unavailable", "matches": 0}

    focus = "away" if str(focus).lower().startswith("a") else "home"
    print("=" * 70)
    print(f"🏓 TABLE TENNIS (AiScore) — focus={focus.upper()} — {date_str}")
    print("=" * 70)

    # ── start browser (reuse the LiveSport scraper's hardened driver) ──
    try:
        from livesport_h2h_scraper import start_driver
        driver = start_driver(headless=True)
    except Exception as e:
        print(f"❌ Nie można uruchomić przeglądarki: {e}")
        return {"error": "driver_unavailable", "matches": 0}

    rows: List[Dict[str, Any]] = []
    try:
        # ── FAZA 1: list match URLs from AiScore ──
        print("\n[FAZA 1] Pobieram listę meczów z AiScore...")
        urls = ai.list_match_urls(driver, date_str)
        print(f"   📋 Znaleziono {len(urls)} linków meczów")
        if max_matches:
            urls = urls[:max_matches]
            print(f"   ✂️  Limit --max-matches: {len(urls)}")

        # ── FAZA 2: process each match (H2H gate + form + odds + fan vote) ──
        print(f"\n[FAZA 2] Przetwarzam {len(urls)} meczów (H2H ≥{int(H2H_MIN_WIN_RATE*100)}% + Fan Vote)...")
        for i, url in enumerate(urls, 1):
            try:
                row = process_match(driver, url, focus, date_str, verbose=verbose)
            except Exception as e:
                print(f"   ⚠️ Błąd przetwarzania {url}: {e}")
                row = None
            if row:
                rows.append(row)
            if verbose and (i % 10 == 0 or i == len(urls)):
                q = sum(1 for r in rows if r.get("qualifies"))
                print(f"   [{i}/{len(urls)}] kwalifikujących się dotąd: {q}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # ── FAZA 2.5: scoring ──
    print("\n[FAZA 2.5] Scoring (TennisScoringEngine, profil table tennis)...")
    scored = score_rows(rows)
    qualified = sum(1 for r in rows if r.get("qualifies"))
    print(f"   🧠 {scored} ocenionych, {qualified} kwalifikujących się")

    # ── FAZA 2.9: qualification gate (channel + email) ──
    try:
        from qualification_gate import apply_qualification_gate
        cq = apply_qualification_gate(rows, date_str)
        print(f"\n[FAZA 2.9] Qualification gate: {cq} channel-qualified")
    except Exception as e:
        print(f"\n⚠️ Qualification gate error: {e}")
        for r in rows:
            r["channel_qualifies"] = r.get("qualifies", False)
            r["email_qualifies"] = r.get("qualifies", False)

    # ── OUTPUT ──
    paths = write_outputs(rows, date_str, focus)
    print(f"\n💾 Zapisano:\n   CSV:  {paths['csv']}\n   JSON: {paths['json']}")

    # ── EMAIL (like tennis) ──
    if send_email and email_cfg and email_cfg.get("to") and email_cfg.get("from"):
        try:
            from email_notifier import send_email_notification
            send_email_notification(
                csv_file=paths["csv"],
                to_email=email_cfg["to"],
                from_email=email_cfg["from"],
                password=email_cfg.get("password", ""),
                provider=email_cfg.get("provider", "gmail"),
                subject=f"🏓 Table Tennis ({focus}) — {date_str}",
                date=date_str,
                # AiScore exposes no table-tennis odds, so DON'T drop no-odds
                # matches — otherwise every qualifying pick is filtered out and
                # no e-mail is sent. Qualification already happened upstream
                # (H2H ≥60% + mandatory Fan Vote).
                skip_no_odds=False,
                min_odds_threshold=0.0,
            )
            print("   ✅ Email wysłany (jeśli były kwalifikujące się)")
        except Exception as e:
            print(f"   ⚠️ Email error: {e}")
    elif send_email:
        print("   ℹ️ Email pominięty (brak konfiguracji --to/--from-email)")

    # ── TELEGRAM ──
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
        "focus": focus,
        "processed": len(rows),
        "scored": scored,
        "qualified": sum(1 for r in rows if r.get("qualifies")),
        "channel_qualified": sum(1 for r in rows if r.get("channel_qualifies")),
        "email_qualified": sum(1 for r in rows if r.get("email_qualifies")),
        "outputs": paths,
    }
    print("\n" + "=" * 70)
    print(f"🏓 DONE ({focus}) — {summary['channel_qualified']} channel / "
          f"{summary['email_qualified']} email z {len(rows)} przetworzonych")
    print("=" * 70)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Table Tennis Pipeline (AiScore-sourced)")
    ap.add_argument("--focus", choices=["home", "away"], default="home",
                    help="Which side to evaluate/pick (home=gospodarze, away=goście)")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="Date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--max-matches", type=int, default=None,
                    help="Cap number of matches processed (testing)")
    ap.add_argument("--to", default=os.getenv("EMAIL_RECIPIENT", ""), help="Email recipient")
    ap.add_argument("--from-email", default=os.getenv("EMAIL_SENDER", ""), help="Email sender")
    ap.add_argument("--password", default=os.getenv("EMAIL_PASSWORD", ""), help="Email password")
    ap.add_argument("--provider", default="gmail", help="Email provider (gmail/outlook/yahoo)")
    ap.add_argument("--no-email", action="store_true", help="Skip e-mail notification")
    ap.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification")
    args = ap.parse_args()

    email_cfg = {
        "to": args.to,
        "from": args.from_email,
        "password": args.password,
        "provider": args.provider,
    }
    run(args.focus, args.date, max_matches=args.max_matches,
        send_email=not args.no_email, send_telegram=not args.no_telegram,
        email_cfg=email_cfg)


if __name__ == "__main__":
    main()
