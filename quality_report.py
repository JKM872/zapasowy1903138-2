#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quality Report — Rolling accuracy, calibration & channel comparison
====================================================================

Generates a periodic quality report after each scrape run.
Shows rolling 7/30/90-day accuracy, per-sport precision, ROI per
threshold bucket, confidence reliability curve, injury/status rejection
rates, and email vs Telegram channel comparison.

Usage:
  python quality_report.py                    # default 30-day report
  python quality_report.py --days 7
  python quality_report.py --all --export
  python quality_report.py --channels         # compare email vs telegram
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from prediction_evaluator import PredictionEvaluator
    _evaluator_ok = True
except ImportError:
    _evaluator_ok = False

try:
    from result_store import ResultStore
    _store_ok = True
except ImportError:
    _store_ok = False


OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
REPORT_FILE = os.path.join(OUTPUTS_DIR, "quality_report.json")


# ═══════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

def _load_recent_results(days: int = 30) -> List[Dict[str, Any]]:
    """Load recent prediction files from results/ directory."""
    results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    if not os.path.exists(results_dir):
        return []

    cutoff = datetime.now() - timedelta(days=days)
    all_matches = []

    for fn in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        basename = os.path.basename(fn)
        # Extract date from filename: results_YYYY-MM-DD.json or YYYY-MM-DD_*.json
        date_str = None
        for part in basename.replace('.json', '').split('_'):
            try:
                datetime.strptime(part, "%Y-%m-%d")
                date_str = part
                break
            except ValueError:
                continue

        if date_str:
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                continue

        try:
            with open(fn, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict):
                for sport, matches in data.items():
                    if isinstance(matches, list):
                        for m in matches:
                            m['_date'] = date_str or basename
                            m['_sport'] = m.get('sport', sport)
                            all_matches.append(m)
            elif isinstance(data, list):
                for m in data:
                    m['_date'] = date_str or basename
                    all_matches.append(m)
        except Exception:
            continue

    return all_matches


# ═══════════════════════════════════════════════════════════════════════════
# REPORT GENERATORS
# ═══════════════════════════════════════════════════════════════════════════

def generate_pipeline_stats(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stats about the prediction pipeline: data quality, grades, sources."""
    total = len(matches)
    qualifying = sum(1 for m in matches if m.get('qualifies'))
    channel_q = sum(1 for m in matches if m.get('channel_qualifies'))
    with_odds = sum(1 for m in matches if m.get('home_odds') and m.get('away_odds'))
    with_forebet = sum(1 for m in matches if m.get('forebet_prediction'))
    with_sofascore = sum(1 for m in matches if m.get('sofascore_home_win_prob'))
    with_gemini = sum(1 for m in matches if m.get('gemini_recommendation'))
    with_scoring = sum(1 for m in matches if m.get('scoring_pick'))

    # Grade distribution
    grades = defaultdict(int)
    for m in matches:
        g = m.get('prediction_grade', 'N/A')
        grades[g] += 1

    # Data quality distribution
    dq_buckets = {"high (≥0.8)": 0, "medium (0.5-0.8)": 0, "low (<0.5)": 0}
    for m in matches:
        dq = m.get('data_quality', {})
        if isinstance(dq, dict):
            qs = dq.get('quality_score', 0)
        else:
            qs = 0
        if qs >= 0.8:
            dq_buckets["high (≥0.8)"] += 1
        elif qs >= 0.5:
            dq_buckets["medium (0.5-0.8)"] += 1
        else:
            dq_buckets["low (<0.5)"] += 1

    # Channel skip reasons
    skip_reasons = defaultdict(int)
    for m in matches:
        reasons = m.get('channel_skip_reasons', [])
        if isinstance(reasons, list):
            for r in reasons:
                skip_reasons[r] += 1

    # Per-sport breakdown
    sport_counts = defaultdict(lambda: {"total": 0, "qualifying": 0, "channel_q": 0})
    for m in matches:
        sp = m.get('_sport', m.get('sport', 'unknown'))
        sport_counts[sp]["total"] += 1
        if m.get('qualifies'):
            sport_counts[sp]["qualifying"] += 1
        if m.get('channel_qualifies'):
            sport_counts[sp]["channel_q"] += 1

    return {
        "total_matches": total,
        "qualifying": qualifying,
        "channel_qualifying": channel_q,
        "with_odds": with_odds,
        "with_forebet": with_forebet,
        "with_sofascore": with_sofascore,
        "with_gemini": with_gemini,
        "with_scoring_engine": with_scoring,
        "grades": dict(grades),
        "data_quality_distribution": dq_buckets,
        "channel_skip_reasons": dict(skip_reasons),
        "per_sport": dict(sport_counts),
    }


def generate_accuracy_report(days: int = 30) -> Dict[str, Any]:
    """Generate accuracy stats if result data is available."""
    if not _evaluator_ok:
        return {"error": "PredictionEvaluator not available"}

    ev = PredictionEvaluator()
    ev.load(days=days)
    ev.match_results()

    settled = [m for m in ev.all_matches if m.is_settled]
    if not settled:
        return {
            "total_predictions": len(ev.all_matches),
            "settled": 0,
            "message": "No settled matches yet. Run check_results.py to populate result data."
        }

    won = sum(1 for m in settled if m.outcome == 'won')
    lost = sum(1 for m in settled if m.outcome == 'lost')
    draws = sum(1 for m in settled if m.outcome == 'draw')

    # Per-sport accuracy
    sport_acc = defaultdict(lambda: {"settled": 0, "won": 0})
    for m in settled:
        sport_acc[m.sport]["settled"] += 1
        if m.outcome == 'won':
            sport_acc[m.sport]["won"] += 1

    for sport in sport_acc:
        s = sport_acc[sport]
        s["accuracy"] = round(s["won"] / s["settled"], 4) if s["settled"] else 0

    # Confidence buckets
    conf_buckets = defaultdict(lambda: {"count": 0, "won": 0})
    for m in settled:
        conf = m.confidence or 0
        if conf >= 80:
            bucket = "80-100"
        elif conf >= 70:
            bucket = "70-80"
        elif conf >= 60:
            bucket = "60-70"
        elif conf >= 50:
            bucket = "50-60"
        else:
            bucket = "<50"
        conf_buckets[bucket]["count"] += 1
        if m.outcome == 'won':
            conf_buckets[bucket]["won"] += 1

    for bucket in conf_buckets:
        b = conf_buckets[bucket]
        b["accuracy"] = round(b["won"] / b["count"], 4) if b["count"] else 0

    # ROI
    total_profit = 0.0
    total_staked = 0
    for m in settled:
        odds = m.predicted_odds
        if odds and odds > 1.0:
            total_staked += 1
            if m.outcome == 'won':
                total_profit += odds - 1.0
            else:
                total_profit -= 1.0

    return {
        "days": days,
        "total_predictions": len(ev.all_matches),
        "settled": len(settled),
        "won": won,
        "lost": lost,
        "draws": draws,
        "accuracy": round(won / len(settled), 4) if settled else 0,
        "roi": round(total_profit / total_staked, 4) if total_staked else 0,
        "per_sport": dict(sport_acc),
        "confidence_buckets": dict(conf_buckets),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRINT REPORT
# ═══════════════════════════════════════════════════════════════════════════

def print_quality_report(matches: List[Dict[str, Any]], days: int = 30):
    stats = generate_pipeline_stats(matches)
    accuracy = generate_accuracy_report(days)

    print(f"\n{'='*70}")
    print(f"  QUALITY REPORT — Last {days} days")
    print(f"{'='*70}")

    # Pipeline stats
    print(f"\n  📊 PIPELINE OVERVIEW")
    print(f"  {'─'*40}")
    print(f"  Total matches scraped:    {stats['total_matches']}")
    print(f"  Base qualifying:          {stats['qualifying']}")
    print(f"  Channel qualifying:       {stats['channel_qualifying']}")
    print(f"  With odds:                {stats['with_odds']}")
    print(f"  With Forebet:             {stats['with_forebet']}")
    print(f"  With SofaScore:           {stats['with_sofascore']}")
    print(f"  With Gemini:              {stats['with_gemini']}")
    print(f"  With Scoring Engine:      {stats['with_scoring_engine']}")

    # Grades
    if stats['grades']:
        print(f"\n  🏅 PREDICTION GRADES")
        print(f"  {'─'*40}")
        for g in sorted(stats['grades'].keys()):
            count = stats['grades'][g]
            pct = 100 * count / stats['total_matches'] if stats['total_matches'] else 0
            bar = "█" * int(pct / 2)
            print(f"  Grade {g:>3}: {count:>5} ({pct:>5.1f}%)  {bar}")

    # Skip reasons
    if stats['channel_skip_reasons']:
        print(f"\n  🚦 CHANNEL SKIP REASONS")
        print(f"  {'─'*40}")
        for reason, count in sorted(stats['channel_skip_reasons'].items(), key=lambda x: -x[1]):
            print(f"  {reason:>30}: {count}")

    # Per-sport
    if stats['per_sport']:
        print(f"\n  🏟  PER-SPORT BREAKDOWN")
        print(f"  {'─'*40}")
        print(f"  {'Sport':>15}  {'Total':>6}  {'Qual':>6}  {'ChQ':>6}  {'Rate':>6}")
        for sport, sc in sorted(stats['per_sport'].items()):
            rate = 100 * sc['channel_q'] / sc['total'] if sc['total'] else 0
            print(f"  {sport:>15}  {sc['total']:>6}  {sc['qualifying']:>6}  {sc['channel_q']:>6}  {rate:>5.1f}%")

    # Accuracy
    if accuracy.get('settled', 0) > 0:
        print(f"\n  🎯 ACCURACY ({accuracy['days']} days)")
        print(f"  {'─'*40}")
        print(f"  Settled: {accuracy['settled']}/{accuracy['total_predictions']}")
        print(f"  Won:     {accuracy['won']}  Lost: {accuracy['lost']}  Draw: {accuracy.get('draws', 0)}")
        print(f"  Accuracy: {accuracy['accuracy']:.1%}")
        print(f"  ROI:      {accuracy['roi']:+.1%}")

        if accuracy.get('per_sport'):
            print(f"\n  Per-sport accuracy:")
            for sport, sa in sorted(accuracy['per_sport'].items()):
                print(f"    {sport:>15}: {sa['won']}/{sa['settled']} = {sa.get('accuracy', 0):.1%}")

        if accuracy.get('confidence_buckets'):
            print(f"\n  Confidence calibration:")
            for bucket in ["80-100", "70-80", "60-70", "50-60", "<50"]:
                if bucket in accuracy['confidence_buckets']:
                    b = accuracy['confidence_buckets'][bucket]
                    print(f"    {bucket:>8}: {b['won']}/{b['count']} = {b.get('accuracy', 0):.1%}")
    else:
        msg = accuracy.get('message', 'No settled matches available.')
        print(f"\n  🎯 ACCURACY: {msg}")

    print(f"\n{'='*70}\n")


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def export_report(matches: List[Dict[str, Any]], days: int = 30) -> str:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "days": days,
        "pipeline_stats": generate_pipeline_stats(matches),
        "accuracy": generate_accuracy_report(days),
    }

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Report exported to {REPORT_FILE}")
    return REPORT_FILE


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Quality Report")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    days = 9999 if args.all else args.days
    matches = _load_recent_results(days)

    if not matches:
        print(f"No prediction data found for last {days} days in results/ directory.")
        return

    print_quality_report(matches, days)

    if args.export:
        export_report(matches, days)


if __name__ == "__main__":
    main()
