"""Baseball data quality report — called from CI workflow.

Reads the JSON produced by scrape_and_notify.py for baseball and prints a
compact data-quality summary (pitcher coverage, odds coverage, channel
qualification breakdown).

The scraper writes results to `results/matches_{date}_baseball.json` in the
form `{"date": ..., "sport": "baseball", "matches": [...]}`, where each match
uses the frontend camelCase schema (`homeTeam`, `odds`, `channelQualifies`,
`pitcher*`, etc.). For backwards compatibility we also accept the legacy
`matches_baseball_{date}.json` path and snake_case fields.
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional


def _find_results_file(today: str) -> Optional[str]:
    """Return the first matching results file for the target date, or None."""
    candidates = [
        f"results/matches_{today}_baseball.json",       # current scraper layout
        f"results/matches_baseball_{today}.json",       # legacy layout
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _load_matches(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("matches", []) or []
    return []


def _has_pitcher(m: Dict[str, Any]) -> bool:
    """Accept both camelCase (`pitcherHome`) and snake_case (`pitcher_home`)."""
    home = m.get("pitcherHome") or m.get("pitcher_home")
    away = m.get("pitcherAway") or m.get("pitcher_away")
    return bool(home) and bool(away)


def _has_odds(m: Dict[str, Any]) -> bool:
    """Odds can live either nested under `odds` (frontend schema) or flat."""
    odds = m.get("odds")
    if isinstance(odds, dict):
        if odds.get("home") and odds.get("away"):
            return True
    if m.get("home_odds") and m.get("away_odds"):
        return True
    return False


def _channel_qualified(m: Dict[str, Any]) -> bool:
    return bool(m.get("channelQualifies") or m.get("channel_qualifies"))


def _base_qualified(m: Dict[str, Any]) -> bool:
    return bool(m.get("qualifies"))


def main() -> None:
    today = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TODAY", "unknown")

    path = _find_results_file(today)
    if path is None:
        print(f"WARNING: No baseball results file found for {today}")
        print("         Looked for:")
        print(f"           - results/matches_{today}_baseball.json")
        print(f"           - results/matches_baseball_{today}.json")
        return

    matches = _load_matches(path)
    total = len(matches)

    with_pitcher = sum(1 for m in matches if _has_pitcher(m))
    with_odds = sum(1 for m in matches if _has_odds(m))
    base_qualified = sum(1 for m in matches if _base_qualified(m))
    channel_qualified = sum(1 for m in matches if _channel_qualified(m))

    pct = lambda n: n * 100 // max(total, 1)
    print(f"File:              {path}")
    print(f"Total games:       {total}")
    print(f"With pitchers:     {with_pitcher}/{total} ({pct(with_pitcher)}%)")
    print(f"With odds:         {with_odds}/{total} ({pct(with_odds)}%)")
    print(f"Base qualified:    {base_qualified}/{total} ({pct(base_qualified)}%)")
    print(f"Channel qualified: {channel_qualified}/{total} ({pct(channel_qualified)}%)")
    print()

    if total == 0:
        print("WARNING: No games scraped (empty matches list)")
        return

    if with_pitcher == 0:
        print("WARNING: No pitcher data found - model quality degraded")
    if channel_qualified == 0:
        print("No games qualified for notification (expected in experimental phase)")


if __name__ == "__main__":
    main()
