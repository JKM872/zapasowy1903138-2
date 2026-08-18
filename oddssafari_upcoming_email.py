"""
Hourly e-mail for the OddsSafari upcoming-odds pipeline
=======================================================

Why this exists instead of calling ``dropping_odds_email.py`` directly: that
script mails everything in the JSON every time it runs. That is right for a
report fired three times a day, but this pipeline runs **hourly** — the same
fixture stays on the card for hours, so the naive version would deliver the
identical match 12 times before kick-off and the mail would stop being read.

So this module owns one decision: *which fixtures are worth mailing now?*
Rendering and sending are delegated untouched to
:func:`dropping_odds_email.send_dropping_odds_email`, so the cards look exactly
like the other mails and keep looking like them as that template changes.

A fixture is mailed when:

* it has not been mailed today yet, **or**
* its price fell materially further since the last mail (default +5 pp) — the
  market moving again is new information, **or**
* the model changed its pick — that is the opposite of noise.

State lives in ``outputs/upcoming_mailed_{date}_{sport}.json``. Deliberately
*not* in ``outputs/mailed_manifest_*``: that glob is the settlement source for
the main pipeline (``check_results.py`` reads it), and mixing hourly upcoming
picks into it would corrupt the accuracy accounting.

Usage
-----
    python oddssafari_upcoming_email.py outputs/oddssafari_upcoming_2026-08-18_football.json \\
        --to you@example.com --from-email bot@example.com --password "app-pass" \\
        --sport football --min-score 40
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A re-send needs a materially deeper drop, not a rounding wobble.
DEFAULT_MIN_DROP_INCREASE = 5.0
# Below this score a fixture is market noise; mailing it trains the reader to
# ignore the mail. 0 disables the floor.
DEFAULT_MIN_SCORE = 0.0


# ---------------------------------------------------------------------------
# State (pure)
# ---------------------------------------------------------------------------


def manifest_path(date: str, sport: str, directory: str = "outputs") -> str:
    return os.path.join(directory, f"upcoming_mailed_{date}_{sport}.json")


def load_manifest(path: str) -> Dict[str, Dict[str, Any]]:
    """Previously mailed fixtures, keyed by fixture id. Missing file = empty."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read mail manifest %s: %s", path, exc)
        return {}
    if isinstance(data, dict):
        entries = data.get("sent") if isinstance(data.get("sent"), dict) else data
        return entries if isinstance(entries, dict) else {}
    return {}


def save_manifest(path: str, sent: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sent": sent}, f, ensure_ascii=False, indent=2, default=str)


def event_key(event: Dict[str, Any]) -> str:
    """Stable identity for a fixture across hourly runs."""
    match_id = event.get("match_id")
    if match_id:
        return str(match_id)
    url = event.get("match_url")
    if url:
        return str(url)
    return (f"{event.get('home_team', '')}|{event.get('away_team', '')}"
            f"|{event.get('kickoff_utc', '')}")


def _model_pick(event: Dict[str, Any]) -> Optional[str]:
    prediction = event.get("prediction") or {}
    ai = prediction.get("ai") or {}
    return ai.get("pick") or prediction.get("pick")


def should_send(event: Dict[str, Any],
                previous: Optional[Dict[str, Any]],
                *,
                min_drop_increase: float = DEFAULT_MIN_DROP_INCREASE,
                ) -> Tuple[bool, str]:
    """Decide whether *event* is worth mailing, given what was mailed before."""
    if previous is None:
        return True, "new"

    drop_now = float(event.get("drop_pct") or 0.0)
    drop_then = float(previous.get("drop_pct") or 0.0)
    if drop_now - drop_then >= min_drop_increase:
        return True, f"drop_deepened_{drop_then:g}->{drop_now:g}"

    pick_now = _model_pick(event)
    pick_then = previous.get("model_pick")
    if pick_now and pick_then and pick_now != pick_then:
        return True, f"model_pick_changed_{pick_then}->{pick_now}"

    return False, "already_mailed"


def has_analysis(event: Dict[str, Any]) -> bool:
    """Did this fixture actually get form/H2H data?

    Matters because the enrichment budget (``--max-enrich``) leaves most of a
    big card unenriched, and a fixture can still clear the score floor on market
    signals alone (drop 30 + consensus 20 + favourite 15 + value 10). Mailing
    those produced cards with "—" in every form field, which is worse than not
    mailing them: the reader cannot act on them and learns to skim the mail.
    """
    enrichment = event.get("enrichment") or {}
    if not isinstance(enrichment, dict) or not enrichment:
        return False
    if event.get("form_orientation") == "unverified":
        return False
    return any(enrichment.get(key) for key in
               ("home_form_overall", "away_form_overall",
                "home_form", "away_form", "h2h_last5"))


def select_events(data: Dict[str, Any],
                  manifest: Dict[str, Dict[str, Any]],
                  *,
                  min_score: float = DEFAULT_MIN_SCORE,
                  min_drop_increase: float = DEFAULT_MIN_DROP_INCREASE,
                  require_analysis: bool = True,
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Pick the fixtures to mail from a pipeline payload."""
    stats: Dict[str, int] = {}

    def bump(reason: str) -> None:
        stats[reason] = stats.get(reason, 0) + 1

    chosen: List[Dict[str, Any]] = []
    for event in data.get("qualified") or []:
        if require_analysis and not has_analysis(event):
            bump("no_analysis_data")
            continue
        score = float(event.get("score") or 0.0)
        if min_score and score < min_score:
            bump("below_min_score")
            continue
        send, reason = should_send(
            event, manifest.get(event_key(event)),
            min_drop_increase=min_drop_increase,
        )
        bump(reason if send else "already_mailed")
        if send:
            chosen.append(event)

    return chosen, stats


def record_sent(manifest: Dict[str, Dict[str, Any]],
                events: List[Dict[str, Any]],
                generated_at: str = "") -> Dict[str, Dict[str, Any]]:
    """Return *manifest* updated with the fixtures just mailed."""
    updated = dict(manifest)
    for event in events:
        updated[event_key(event)] = {
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "kickoff_utc": event.get("kickoff_utc"),
            "outcome": event.get("outcome"),
            "current_odds": event.get("current_odds"),
            "drop_pct": event.get("drop_pct"),
            "bookmakers": event.get("bookmakers"),
            "score": event.get("score"),
            "model_pick": _model_pick(event),
            "mailed_at": generated_at,
        }
    return updated


# ---------------------------------------------------------------------------
# Presentation touch-ups
# ---------------------------------------------------------------------------


def annotate_for_email(event: Dict[str, Any]) -> Dict[str, Any]:
    """Surface this pipeline's own signals in the shared card template.

    The bookmaker count is the point of using the coupon, and the template
    renders ``odds_bookmaker`` verbatim — so the count goes there rather than
    being lost. The full 1-X-2 line is copied into ``enrichment`` because that
    is where the card (and the scoring input) look for prices.
    """
    out = dict(event)
    books = out.get("bookmakers")
    if books:
        out["odds_bookmaker"] = f"OddsSafari ({books} bk)"

    enrichment = dict(out.get("enrichment") or {})
    for key in ("home_odds", "draw_odds", "away_odds"):
        if not enrichment.get(key) and out.get(key):
            enrichment[key] = out[key]
    if enrichment:
        out["enrichment"] = enrichment
    return out


def build_payload(data: Dict[str, Any],
                  events: List[Dict[str, Any]],
                  stats: Dict[str, int]) -> Dict[str, Any]:
    """A pipeline-shaped payload holding only the fixtures being mailed."""
    meta = dict(data.get("meta") or {})
    meta["mail_selection"] = stats
    totals = dict(meta.get("totals") or {})
    totals["qualified"] = len(events)
    meta["totals"] = totals
    annotated = [annotate_for_email(e) for e in events]
    return {"meta": meta, "events": annotated, "qualified": annotated}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Mail the new/changed fixtures from an upcoming-odds "
                     "pipeline JSON, skipping what was already sent today."))
    parser.add_argument("json_path", help="outputs/oddssafari_upcoming_*.json")
    parser.add_argument("--to", default=os.getenv("EMAIL_RECIPIENT", ""),
                        help="Recipient (default: $EMAIL_RECIPIENT).")
    parser.add_argument("--from-email", default=os.getenv("EMAIL_SENDER", ""),
                        help="Sender (default: $EMAIL_SENDER).")
    parser.add_argument("--password", default=os.getenv("EMAIL_PASSWORD", ""),
                        help="App password (default: $EMAIL_PASSWORD).")
    parser.add_argument("--provider", default="gmail",
                        choices=["gmail", "outlook", "yahoo"])
    parser.add_argument("--sport", default="",
                        help="Sport label for the subject and the manifest name.")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"Only mail fixtures scoring at least this "
                             f"(default {DEFAULT_MIN_SCORE:g} = no floor).")
    parser.add_argument("--min-drop-increase", type=float,
                        default=DEFAULT_MIN_DROP_INCREASE,
                        help="Re-mail a fixture when its drop deepened by at "
                             f"least this many points (default "
                             f"{DEFAULT_MIN_DROP_INCREASE:g}).")
    parser.add_argument("--allow-missing-analysis", dest="require_analysis",
                        action="store_false",
                        help="Also mail fixtures with no form/H2H data (they "
                             "render with empty form fields).")
    parser.add_argument("--manifest", default="",
                        help="Override the sent-state file path.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be mailed, send nothing, and "
                             "leave the manifest untouched.")
    parser.set_defaults(require_analysis=True)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    args = _parse_args(argv)

    if not os.path.isfile(args.json_path):
        # A per-sport job legitimately produces no JSON when the card is empty.
        print(f"ℹ️  Brak pliku {args.json_path} — nie ma czego wysyłać")
        return 0

    with open(args.json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("meta") or {}
    date = meta.get("target_date") or ""
    sport = (args.sport or meta.get("sport") or "").lower() or "all"
    path = args.manifest or manifest_path(date, sport)

    manifest = load_manifest(path)
    events, stats = select_events(
        data, manifest,
        min_score=args.min_score,
        min_drop_increase=args.min_drop_increase,
        require_analysis=args.require_analysis,
    )

    print("=" * 70)
    print(f"Mail nadchodzących kursów — {sport} {date}")
    print(f"  Kwalifikuje w JSON:  {len(data.get('qualified') or [])}")
    print(f"  Już wysłane wcześniej: {len(manifest)}")
    print(f"  Do wysłania teraz:   {len(events)}")
    print(f"  Decyzje:             {stats or '{}'}")
    print(f"  Manifest:            {path}")
    print("=" * 70)
    for event in events:
        model = _model_pick(event)
        model_note = f" | model {model}" if model else ""
        print(f"  {event.get('score')} | {event.get('kickoff_local')} | "
              f"{event.get('home_team')} vs {event.get('away_team')} | "
              f"rynek {event.get('outcome')} @ {event.get('current_odds')} | "
              f"{event.get('bookmakers')} bk | "
              f"drop {event.get('drop_pct') or 0}%{model_note}")

    if not events:
        # Silence is the correct output for an hourly job with nothing new.
        print("✅ Nic nowego — nie wysyłam maila")
        return 0

    if args.dry_run:
        print("🧪 DRY-RUN — nie wysyłam i nie zapisuję manifestu")
        return 0

    if not (args.to and args.from_email and args.password):
        print("⚠️  Brak danych SMTP (--to/--from-email/--password lub "
              "EMAIL_RECIPIENT/EMAIL_SENDER/EMAIL_PASSWORD) — pomijam wysyłkę")
        return 0

    payload = build_payload(data, events, stats)
    tmp_path = ""
    try:
        # send_dropping_odds_email reads from disk, so hand it a payload holding
        # only the selected fixtures instead of duplicating its renderer.
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                        encoding="utf-8") as tmp:
            json.dump(payload, tmp, ensure_ascii=False, default=str)
            tmp_path = tmp.name

        from dropping_odds_email import send_dropping_odds_email
        ok = send_dropping_odds_email(
            tmp_path,
            to_email=args.to,
            from_email=args.from_email,
            password=args.password,
            provider=args.provider,
            sport=sport,
            # An hourly job must never send "nothing to report" mails.
            send_empty=False,
            min_recent_wins=0,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not ok:
        print("❌ Wysyłka nie udała się — manifest zostaje bez zmian, "
              "następny bieg spróbuje ponownie")
        return 1

    save_manifest(path, record_sent(manifest, events,
                                    generated_at=meta.get("generated_at", "")))
    print(f"✅ Wysłano {len(events)} zdarzeń i zapisano manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
