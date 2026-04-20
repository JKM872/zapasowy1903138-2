"""GitHub Actions step-summary helper for OddsSafari dropping pipeline.

Usage::

    python ci_oddssafari_summary.py outputs/oddssafari_dropping_2026-04-21.json

Prints a compact Markdown summary to stdout (the workflow redirects it to
``$GITHUB_STEP_SUMMARY``). Silently no-ops when the file is missing.
"""

from __future__ import annotations

import json
import os
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: ci_oddssafari_summary.py <json_path>", file=sys.stderr)
        return 1

    path = argv[1]
    if not os.path.isfile(path):
        print(f"- No output file at `{path}`")
        return 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"- Could not read `{path}`: {exc}")
        return 0

    meta = data.get("meta", {}) or {}
    totals = meta.get("totals", {}) or {}
    filter_cfg = meta.get("filter", {}) or {}
    enr = meta.get("enrichment_status_counts", {}) or {}
    reasons = meta.get("skip_reason_counts", {}) or {}

    print(f"- File: `{path}`")
    print(
        f"- Events: **{totals.get('events', 0)}** | "
        f"qualified: **{totals.get('qualified', 0)}**"
    )
    print(
        f"- Filter: `min={filter_cfg.get('min_odds')}`"
        f" `max={filter_cfg.get('max_odds')}`"
    )
    if enr:
        print(f"- Enrichment: `{enr}`")
    if reasons:
        print("- Top skip reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:5]:
            print(f"  - `{reason}`: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
