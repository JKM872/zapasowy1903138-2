#!/usr/bin/env python3
"""Verdict for a dropping-odds move: has a move like this paid, historically?

It does NOT guess why the price fell. Injuries, line-ups, weather and sharp
money are not in our data, and a model asked "why" will always produce a
plausible reason it does not know. What we can answer from evidence is whether
moves in the same segment — sport and the side the price fell on — have made
money on settled history.

Measured on 4 826 settled moves (2026-07-27 .. 2026-10-21), the gate has to be
strict:

* overall, backing the side the price fell on lost 3.7%; football, 58% of the
  volume, lost 7.9%;
* of 13 segments profitable in the earlier 60% of days, 7 lost money in the
  later 40%;
* ROI is measured at the price seen when OddsSafari was scraped. Someone acting
  later on a falling price gets less, so every segment is re-priced 5% lower
  before it can earn a positive verdict.

So "warto" requires all of: enough history, profit in both halves of the
timeline, and profit after the 5% haircut. "Nie warto" requires enough history
and a loss after the haircut. Everything else is "za malo danych", which is the
honest answer for most segments.

Usage::

    python dropping_odds_advisor.py               # write outputs/dropping_odds_model.json
    python dropping_odds_advisor.py --print-only  # show the table, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "outputs", "dropping_odds_model.json")

# Thresholds. Each one is a decision about how much evidence buys a verdict.
MIN_SAMPLE = 100          # total settled moves before any verdict is given
MIN_HALF_SAMPLE = 40      # per half of the timeline, so neither half is noise
PRICE_HAIRCUT = 0.05      # realistic price is 5% worse than the scraped one
TRAIN_FRACTION = 0.6      # earlier share of days used as the "discovery" half

VERDICT_GOOD = "warto"
VERDICT_BAD = "nie_warto"
VERDICT_UNKNOWN = "za_malo_danych"

SIDES = ("home", "away", "draw")


def _roi(rows: List[Dict[str, Any]], haircut: float = 0.0) -> Optional[float]:
    if not rows:
        return None
    payout = sum(r["odds"] * (1.0 - haircut) for r in rows if r["hit"])
    return (payout - len(rows)) / len(rows) * 100.0


def _hit_rate(rows: List[Dict[str, Any]]) -> Optional[float]:
    if not rows:
        return None
    return sum(1 for r in rows if r["hit"]) / len(rows) * 100.0


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)


def _split_by_date(picks: List[Dict[str, Any]]) -> Tuple[str, List[Dict], List[Dict]]:
    days = sorted({p["date"] for p in picks if p.get("date")})
    if len(days) < 2:
        return "", list(picks), []
    cut = days[min(len(days) - 1, int(len(days) * TRAIN_FRACTION))]
    early = [p for p in picks if p.get("date") and p["date"] < cut]
    late = [p for p in picks if p.get("date") and p["date"] >= cut]
    return cut, early, late


def judge(early: List[Dict[str, Any]], late: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verdict and supporting numbers for one segment. Pure."""
    rows = early + late
    n = len(rows)
    roi = _roi(rows)
    roi_hc = _roi(rows, PRICE_HAIRCUT)
    roi_early = _roi(early)
    roi_late = _roi(late)

    enough = n >= MIN_SAMPLE
    both_halves = len(early) >= MIN_HALF_SAMPLE and len(late) >= MIN_HALF_SAMPLE

    if enough and both_halves and roi_hc is not None and roi_hc > 0 \
            and (roi_early or 0) > 0 and (roi_late or 0) > 0:
        verdict, reason = VERDICT_GOOD, (
            "zarabia w obu okresach i po obnizeniu kursu o 5%")
    elif enough and roi_hc is not None and roi_hc < 0:
        verdict, reason = VERDICT_BAD, (
            "traci po realistycznym kursie" if (roi or 0) >= 0
            else "traci na historii")
    elif not enough:
        verdict, reason = VERDICT_UNKNOWN, f"za malo rozstrzygnietych ({n} z {MIN_SAMPLE})"
    elif not both_halves:
        verdict, reason = VERDICT_UNKNOWN, "historia zbyt krotka, by sprawdzic trwalosc"
    else:
        verdict, reason = VERDICT_UNKNOWN, "wynik niestabilny w czasie"

    return {
        "verdict": verdict,
        "reason": reason,
        "n": n,
        "hitRate": _round(_hit_rate(rows)),
        "avgOdds": round(sum(r["odds"] for r in rows) / n, 2) if n else None,
        "roi": _round(roi),
        "roiRealistic": _round(roi_hc),
        "roiEarly": _round(roi_early),
        "roiLate": _round(roi_late),
        "nEarly": len(early),
        "nLate": len(late),
    }


def build_model(picks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Segment table keyed 'sport|side' and 'sport|*'. Pure — no I/O."""
    picks = [p for p in picks if (p.get("odds") or 0) > 1.0 and p.get("side")]
    cut, early, late = _split_by_date(picks)

    keys: Dict[str, Callable[[Dict[str, Any]], str]] = {
        "sport_side": lambda p: f"{p['sport']}|{p['side']}",
        "sport": lambda p: f"{p['sport']}|*",
    }
    segments: Dict[str, Dict[str, Any]] = {}
    for fn in keys.values():
        grouped_early: Dict[str, List] = defaultdict(list)
        grouped_late: Dict[str, List] = defaultdict(list)
        for p in early:
            grouped_early[fn(p)].append(p)
        for p in late:
            grouped_late[fn(p)].append(p)
        for key in set(grouped_early) | set(grouped_late):
            segments[key] = judge(grouped_early.get(key, []), grouped_late.get(key, []))

    dates = sorted(p["date"] for p in picks if p.get("date"))
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dateRange": {"from": dates[0], "to": dates[-1]} if dates else None,
        "splitDate": cut,
        "settled": len(picks),
        "overall": judge(early, late),
        "thresholds": {
            "minSample": MIN_SAMPLE,
            "minHalfSample": MIN_HALF_SAMPLE,
            "priceHaircutPct": PRICE_HAIRCUT * 100,
        },
        "segments": dict(sorted(segments.items())),
    }


def verdict_for(model: Optional[Dict[str, Any]], sport: str,
                side: str) -> Optional[Dict[str, Any]]:
    """Most specific segment that can speak for this move.

    Sport-and-side first. If that is undecided for lack of data, fall back to
    the whole sport — but only to report a loss: a profitable sport must not
    lend "warto" to a side that has not earned it on its own.
    """
    if not model:
        return None
    segments = model.get("segments") or {}
    specific = segments.get(f"{sport}|{side}")
    broad = segments.get(f"{sport}|*")

    if specific and specific["verdict"] != VERDICT_UNKNOWN:
        return {**specific, "segment": f"{sport}|{side}"}
    if broad and broad["verdict"] == VERDICT_BAD:
        return {**broad, "segment": f"{sport}|*"}
    if specific:
        return {**specific, "segment": f"{sport}|{side}"}
    if broad:
        return {**broad, "segment": f"{sport}|*",
                "verdict": VERDICT_UNKNOWN,
                "reason": "brak historii dla tej strony"}
    return {"verdict": VERDICT_UNKNOWN, "reason": "brak historii dla tej dyscypliny",
            "segment": f"{sport}|{side}", "n": 0}


def load_model(path: str = MODEL_PATH) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _print(model: Dict[str, Any]) -> None:
    print(f"Rozstrzygnietych: {model['settled']}  "
          f"okres: {model['dateRange']}  podzial: {model['splitDate']}")
    o = model["overall"]
    print(f"Ogolem: ROI {o['roi']}%  po korekcie {o['roiRealistic']}%  -> {o['verdict']}\n")
    print(f"{'segment':24} {'n':>5} {'ROI':>7} {'realn.':>7} {'wcz.':>7} {'pozn.':>7}  werdykt")
    for key, s in model["segments"].items():
        print(f"{key:24} {s['n']:5} {s['roi'] if s['roi'] is not None else '-':>7} "
              f"{s['roiRealistic'] if s['roiRealistic'] is not None else '-':>7} "
              f"{s['roiEarly'] if s['roiEarly'] is not None else '-':>7} "
              f"{s['roiLate'] if s['roiLate'] is not None else '-':>7}  {s['verdict']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print-only", action="store_true")
    ap.add_argument("--output", default=MODEL_PATH)
    args = ap.parse_args(argv)

    import dropping_odds_accuracy as acc
    picks, _, _ = acc.collect_picks()
    model = build_model(picks)
    _print(model)

    if not args.print_only:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(model, fh, ensure_ascii=False, indent=2)
        print(f"\nZapisano model: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
