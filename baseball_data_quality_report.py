"""Baseball data quality report — called from CI workflow."""
import json
import sys
import os


def main() -> None:
    today = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TODAY", "unknown")
    path = f"results/matches_baseball_{today}.json"

    if not os.path.isfile(path):
        print(f"WARNING: No baseball results file found ({path})")
        return

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    matches = data if isinstance(data, list) else data.get("matches", [])
    total = len(matches)
    with_pitcher = sum(1 for m in matches if m.get("pitcher_home") and m.get("pitcher_away"))
    with_odds = sum(1 for m in matches if m.get("home_odds") and m.get("away_odds"))
    qualified = sum(1 for m in matches if m.get("channel_qualifies"))

    pct = lambda n: n * 100 // max(total, 1)
    print(f"Total games:       {total}")
    print(f"With pitchers:     {with_pitcher}/{total} ({pct(with_pitcher)}%)")
    print(f"With odds:         {with_odds}/{total} ({pct(with_odds)}%)")
    print(f"Qualified:         {qualified}/{total} ({pct(qualified)}%)")
    print()

    if with_pitcher == 0:
        print("WARNING: No pitcher data found - model quality degraded")
    if qualified == 0:
        print("No games qualified for notification (expected in experimental phase)")


if __name__ == "__main__":
    main()
