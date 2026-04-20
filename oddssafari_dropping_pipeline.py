"""End-to-end OddsSafari dropping-odds pipeline.

Flow::

    OddsSafari  ->  every sport, every row  ->  audit JSON (events)
                                    |
                                    +->  qualifies (current odds in range
                                         and sport supported)
                                                |
                                                +->  resolve Livesport URL
                                                       |
                                                       +->  process_match /
                                                            process_match_tennis
                                                            (Forebet, SofaScore,
                                                             H2H + form)

Output::

    outputs/oddssafari_dropping_{date}.json
        {
          "meta": {...},
          "events": [ ... every row with qualifies + skip_reason ],
          "qualified": [ ... enriched subset ]
        }

The script intentionally reuses
:func:`livesport_h2h_scraper.process_match` / ``process_match_tennis`` instead
of reimplementing H2H logic — this keeps parity with the main pipeline and
ensures any future improvement to ``process_match`` is picked up here too.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from oddssafari_dropping_scraper import (
    DroppingOddsRow,
    collect_dropping_odds_rows,
    is_qualifying_row,
)


logger = logging.getLogger(__name__)


WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ---------------------------------------------------------------------------
# Livesport URL resolver (shared pattern with forebet_first_scraper)
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    name = (name or "").lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return " ".join(name.split())


def resolve_livesport_match_url(
    driver,
    *,
    home_team: str,
    away_team: str,
    sport: str,
    date: str,
    max_candidates: int = 120,
) -> Tuple[Optional[str], float]:
    """Return (best_url, confidence) for a match on Livesport.

    Uses :func:`livesport_h2h_scraper.get_match_links_from_day` to enumerate
    the day's URLs, then scores each candidate by how many significant words
    from the two team names appear in the slug. ``confidence`` is the total
    match count divided by the number of significant words we looked for,
    capped at 1.0. Callers should treat < 0.5 as a weak match.
    """
    try:
        from livesport_h2h_scraper import get_match_links_from_day
    except ImportError as exc:  # pragma: no cover
        logger.error("livesport_h2h_scraper unavailable: %s", exc)
        return None, 0.0

    try:
        urls = get_match_links_from_day(
            driver, date, sports=[sport], leagues=None
        ) or []
    except Exception as exc:  # pragma: no cover
        logger.warning("get_match_links_from_day failed for %s: %s", sport, exc)
        return None, 0.0

    if not urls:
        return None, 0.0

    home_words = [w for w in _normalize(home_team).split() if len(w) > 3]
    away_words = [w for w in _normalize(away_team).split() if len(w) > 3]
    total_words = max(1, len(home_words) + len(away_words))

    best_url: Optional[str] = None
    best_score = 0

    for candidate in urls[:max_candidates]:
        slug = candidate.lower()
        home_hits = sum(1 for w in home_words if w in slug)
        away_hits = sum(1 for w in away_words if w in slug)
        if home_hits == 0 or away_hits == 0:
            continue
        score = home_hits + away_hits
        if score > best_score:
            best_score = score
            best_url = candidate

    confidence = min(1.0, best_score / total_words)
    return best_url, confidence


# ---------------------------------------------------------------------------
# Enrichment via process_match / process_match_tennis
# ---------------------------------------------------------------------------


def _focus_team_from_outcome(outcome: str) -> Tuple[Optional[str], bool]:
    """Map the dropped outcome to (focus_team, away_team_focus).

    - ``1`` -> ``home`` focus, ``away_team_focus=False``
    - ``2`` -> ``away`` focus, ``away_team_focus=True``
    - ``X`` -> draw, no focus (returns ``('draw', False)``; process_match is
      still invoked so we capture H2H/form data for the audit).
    """
    outcome = (outcome or "").upper().strip()
    if outcome == "1":
        return "home", False
    if outcome == "2":
        return "away", True
    if outcome == "X":
        return "draw", False
    return None, False


def _enrich_row(
    driver,
    row: DroppingOddsRow,
    *,
    date: str,
    use_forebet: bool = True,
    use_sofascore: bool = True,
) -> Dict[str, Any]:
    """Run the costly Livesport enrichment for one qualifying row."""
    result: Dict[str, Any] = {
        "status": "resolve_failed",
        "livesport_url": None,
        "livesport_confidence": 0.0,
        "focus_team": None,
        "away_team_focus": False,
        "enrichment": None,
        "error": None,
    }

    focus_team, away_focus = _focus_team_from_outcome(row.outcome)
    result["focus_team"] = focus_team
    result["away_team_focus"] = away_focus

    sport = row.sport or "football"

    url, confidence = resolve_livesport_match_url(
        driver,
        home_team=row.home_team,
        away_team=row.away_team,
        sport=sport,
        date=date,
    )
    result["livesport_url"] = url
    result["livesport_confidence"] = round(confidence, 3)

    if not url:
        return result

    try:
        if sport == "tennis":
            from livesport_h2h_scraper import process_match_tennis

            info = process_match_tennis(url, driver)
        else:
            from livesport_h2h_scraper import process_match

            info = process_match(
                url,
                driver,
                away_team_focus=away_focus,
                use_forebet=use_forebet,
                use_sofascore=use_sofascore,
                sport=sport,
            )
    except Exception as exc:
        result["status"] = "process_match_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.exception("process_match failed for %s", url)
        return result

    result["status"] = "enriched"
    result["enrichment"] = _compact_enrichment(info)
    return result


_KEEP_KEYS = (
    "home_team", "away_team", "match_time", "sport", "league",
    "h2h_count", "home_wins_in_h2h_last5", "away_wins_in_h2h_last5",
    "win_rate", "qualifies", "home_form", "away_form",
    "home_odds", "draw_odds", "away_odds",
    "forebet_prediction", "forebet_probability",
    "forebet_over_under", "forebet_btts",
    "sofascore_home_win_prob", "sofascore_draw_prob", "sofascore_away_win_prob",
    "sofascore_total_votes",
    "favorite", "advanced_score", "tennis_skip_reason",
)


def _compact_enrichment(info: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the fields used downstream, dropping heavy Selenium refs."""
    if not isinstance(info, dict):
        return {}
    compact: Dict[str, Any] = {}
    for key in _KEEP_KEYS:
        if key in info:
            compact[key] = info[key]
    return compact


# ---------------------------------------------------------------------------
# Output serialization
# ---------------------------------------------------------------------------


def _serialize_event(
    row: DroppingOddsRow,
    *,
    qualifies: bool,
    skip_reason: Optional[str],
    enrichment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = row.to_dict()
    event["qualifies"] = qualifies
    event["skip_reason"] = skip_reason
    focus_team, away_focus = _focus_team_from_outcome(row.outcome)
    event["dropped_outcome"] = row.outcome
    event["focus_team"] = focus_team
    event["away_team_focus"] = away_focus
    if enrichment is not None:
        event["enrichment_status"] = enrichment.get("status")
        event["livesport_url"] = enrichment.get("livesport_url")
        event["livesport_confidence"] = enrichment.get("livesport_confidence")
        event["enrichment"] = enrichment.get("enrichment")
        event["enrichment_error"] = enrichment.get("error")
    return event


def _write_output(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape OddsSafari dropping odds across every sport, then enrich "
            "qualifying rows with Livesport (H2H + form) + Forebet + SofaScore."
        )
    )
    parser.add_argument("--date", help="Date for Livesport lookup (YYYY-MM-DD); "
                                       "defaults to today in Europe/Warsaw.")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run Chrome headless (default).")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Show the browser window (for debugging).")
    parser.add_argument("--min-odds", type=float, default=1.35,
                        help="Lower bound of qualifying current odds (inclusive).")
    parser.add_argument("--max-odds", type=float, default=2.00,
                        help="Upper bound of qualifying current odds (inclusive).")
    parser.add_argument("--max-rows", type=int, default=0,
                        help="Optional cap on rows processed end-to-end (0 = no cap).")
    parser.add_argument("--max-pages", type=int, default=20,
                        help="Max pages of dropping-odds table per sport.")
    parser.add_argument("--sport-ids", default="",
                        help="Comma-separated OddsSafari sport IDs; empty = auto.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip the Livesport enrichment phase entirely.")
    parser.add_argument("--no-forebet", dest="use_forebet", action="store_false",
                        help="Disable Forebet enrichment inside process_match.")
    parser.add_argument("--no-sofascore", dest="use_sofascore", action="store_false",
                        help="Disable SofaScore fan-vote enrichment.")
    parser.add_argument("--output", default="",
                        help="Override output JSON path (default: outputs/oddssafari_dropping_{date}.json).")
    parser.set_defaults(use_forebet=True, use_sofascore=True)
    return parser.parse_args(argv)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    target_date = args.date or datetime.now(WARSAW_TZ).strftime("%Y-%m-%d")
    output_path = args.output or f"outputs/oddssafari_dropping_{target_date}.json"

    print("=" * 70)
    print("OddsSafari Dropping Odds Pipeline")
    print("=" * 70)
    print(f"  Date (Livesport):   {target_date}")
    print(f"  Qualifying range:   [{args.min_odds:.2f}, {args.max_odds:.2f}]")
    print(f"  Output:             {output_path}")
    print(f"  Mode:               {'DRY-RUN' if args.dry_run else 'FULL'}")
    print("=" * 70)

    from livesport_h2h_scraper import start_driver

    driver = start_driver(headless=args.headless)
    run_started = time.time()

    try:
        sport_ids = [s.strip() for s in args.sport_ids.split(",") if s.strip()]
        rows = collect_dropping_odds_rows(
            driver,
            sport_page_ids=sport_ids or None,
            max_pages_per_sport=args.max_pages,
        )
        if args.max_rows:
            rows = rows[: args.max_rows]
        logger.info("OddsSafari returned %d rows in total", len(rows))

        events: List[Dict[str, Any]] = []
        qualified: List[Dict[str, Any]] = []
        reason_counts: Dict[str, int] = {}
        enrichment_counts: Dict[str, int] = {
            "enriched": 0, "resolve_failed": 0, "process_match_error": 0,
        }

        for idx, row in enumerate(rows, 1):
            qualifies, skip_reason = is_qualifying_row(
                row, min_odds=args.min_odds, max_odds=args.max_odds
            )
            enrichment: Optional[Dict[str, Any]] = None

            if qualifies and not args.dry_run:
                print(
                    f"[{idx}/{len(rows)}] enrich {row.home_team} vs "
                    f"{row.away_team} ({row.sport_slug}, outcome={row.outcome}, "
                    f"current={row.current_odds})"
                )
                enrichment = _enrich_row(
                    driver, row,
                    date=target_date,
                    use_forebet=args.use_forebet,
                    use_sofascore=args.use_sofascore,
                )
                status = enrichment.get("status") or "resolve_failed"
                enrichment_counts[status] = enrichment_counts.get(status, 0) + 1

            event = _serialize_event(
                row,
                qualifies=qualifies,
                skip_reason=skip_reason,
                enrichment=enrichment,
            )
            events.append(event)

            if qualifies:
                qualified.append(event)
            else:
                reason_counts[skip_reason or "unknown"] = (
                    reason_counts.get(skip_reason or "unknown", 0) + 1
                )

        payload = {
            "meta": {
                "generated_at": datetime.now(WARSAW_TZ).isoformat(),
                "target_date": target_date,
                "filter": {
                    "min_odds": args.min_odds,
                    "max_odds": args.max_odds,
                },
                "totals": {
                    "events": len(events),
                    "qualified": len(qualified),
                },
                "enrichment_status_counts": enrichment_counts,
                "skip_reason_counts": reason_counts,
                "elapsed_seconds": round(time.time() - run_started, 1),
                "dry_run": bool(args.dry_run),
            },
            "events": events,
            "qualified": qualified,
        }

        _write_output(output_path, payload)
        print("=" * 70)
        print(f"Total events:  {len(events)}")
        print(f"Qualified:     {len(qualified)}")
        if enrichment_counts:
            print(f"Enrichment:    {enrichment_counts}")
        if reason_counts:
            print(f"Skip reasons:  {reason_counts}")
        print(f"Saved:         {output_path}")
        print("=" * 70)
        return 0
    finally:
        try:
            driver.quit()
        except Exception:  # pragma: no cover
            pass


if __name__ == "__main__":
    sys.exit(main())
