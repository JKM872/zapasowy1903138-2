"""Channel qualification summary for GitHub Actions step summary.

Usage:
    python ci_step_summary.py <sport> <date>

Reads the JSON written by scrape_and_notify.py and prints a Markdown block
suitable for appending to $GITHUB_STEP_SUMMARY. Designed to never fail the
job: missing files or unexpected shapes are reported as bullet points.
"""
import glob
import json
import os
import sys
from typing import Any, Dict, List


def _find_file(sport: str, date: str) -> str:
    candidates = [
        f"results/matches_{date}_{sport}.json",
    ]
    candidates.extend(sorted(glob.glob(f"results/matches_{date}_*{sport}*.json")))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def _load_matches(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"- ⚠️ Failed to read `{path}`: {exc}")
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        matches = data.get("matches") or []
        return matches if isinstance(matches, list) else []
    return []


def main() -> None:
    if len(sys.argv) < 3:
        print("## channel qualification")
        print("- Missing sport or date argument")
        return

    sport = sys.argv[1]
    date = sys.argv[2]

    print(f"## {sport} — channel qualification ({date})")

    path = _find_file(sport, date)
    if not path:
        print(f"- No results JSON found for {sport} on {date}")
        return

    matches = _load_matches(path)
    total = len(matches)
    base = sum(1 for m in matches if m.get("qualifies"))
    ch = sum(1 for m in matches if m.get("channelQualifies") or m.get("channel_qualifies"))

    reasons: Dict[str, int] = {}
    warnings: Dict[str, int] = {}
    for m in matches:
        for r in m.get("channelSkipReasons") or m.get("channel_skip_reasons") or []:
            reasons[r] = reasons.get(r, 0) + 1
        for w in (
            m.get("channelSkipWarnings")
            or m.get("channel_skip_reasons_warnings")
            or []
        ):
            warnings[w] = warnings.get(w, 0) + 1

    print(f"- File: `{path}`")
    print(f"- Total: **{total}** | base qualifies: **{base}** | channel qualifies: **{ch}**")

    if reasons:
        print("- Top rejection reasons:")
        for r, c in sorted(reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"  - `{r}`: {c}")

    if warnings:
        print("- Soft warnings (non-blocking):")
        for w, c in sorted(warnings.items(), key=lambda x: -x[1])[:5]:
            print(f"  - `{w}`: {c}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"- ⚠️ Step summary failed: {exc}")
