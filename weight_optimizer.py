#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weight Optimizer — Per-sport weight tuning & confidence calibration
===================================================================

Uses historical prediction data (via PredictionEvaluator & ResultStore)
to find optimal weights for each sport's scoring engine and calibrate
confidence thresholds.

Strategies:
  1. Coordinate descent over each weight while holding others fixed
  2. Grid search over weight space (coarse → fine)
  3. Isotonic / logistic calibration of confidence → actual accuracy

Outputs:
  - Per-sport JSON weight files consumed by scoring engines at startup
  - Calibration curves and reliability stats
  - Before/after comparison report

Usage:
  python weight_optimizer.py --sport football --days 60
  python weight_optimizer.py --sport tennis --all
  python weight_optimizer.py --calibrate --days 30
  python weight_optimizer.py --report
"""

import copy
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from prediction_evaluator import PredictionEvaluator, SportMetrics
    _evaluator_ok = True
except ImportError:
    _evaluator_ok = False

try:
    from football_scoring_engine import FootballScoringEngine
    _football_ok = True
except ImportError:
    _football_ok = False

try:
    from tennis_scoring_engine import TennisScoringEngine
    _tennis_ok = True
except ImportError:
    _tennis_ok = False


# ═══════════════════════════════════════════════════════════════════════════
# CALIBRATION OUTPUT PATHS
# ═══════════════════════════════════════════════════════════════════════════

OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
FOOTBALL_CAL = os.path.join(OUTPUTS_DIR, "football_calibration.json")
TENNIS_CAL = os.path.join(OUTPUTS_DIR, "tennis_calibration.json")
OPTIMIZER_REPORT = os.path.join(OUTPUTS_DIR, "optimizer_report.json")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OptimizationResult:
    sport: str
    baseline_weights: Dict[str, float]
    optimized_weights: Dict[str, float]
    baseline_accuracy: float
    optimized_accuracy: float
    baseline_brier: float
    optimized_brier: float
    baseline_roi: float
    optimized_roi: float
    n_matches: int
    improvement: float = 0.0
    calibration_temperature: float = 1.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sport": self.sport,
            "baseline_weights": self.baseline_weights,
            "optimized_weights": {k: round(v, 4) for k, v in self.optimized_weights.items()},
            "baseline_accuracy": round(self.baseline_accuracy, 4),
            "optimized_accuracy": round(self.optimized_accuracy, 4),
            "baseline_brier": round(self.baseline_brier, 4),
            "optimized_brier": round(self.optimized_brier, 4),
            "baseline_roi": round(self.baseline_roi, 4),
            "optimized_roi": round(self.optimized_roi, 4),
            "n_matches": self.n_matches,
            "improvement": round(self.improvement, 4),
            "calibration_temperature": round(self.calibration_temperature, 3),
            "timestamp": self.timestamp,
        }


@dataclass
class CalibrationBucket:
    predicted_low: float
    predicted_high: float
    count: int = 0
    actual_wins: int = 0

    @property
    def actual_rate(self) -> float:
        return self.actual_wins / self.count if self.count > 0 else 0.0

    @property
    def midpoint(self) -> float:
        return (self.predicted_low + self.predicted_high) / 2.0

    @property
    def calibration_error(self) -> float:
        return abs(self.actual_rate - self.midpoint) if self.count > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# WEIGHT OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class WeightOptimizer:
    """
    Optimizes scoring engine weights using historical prediction data.

    Works by re-scoring historical matches with candidate weight sets
    and measuring which weights produce the best accuracy / Brier / ROI.
    """

    def __init__(self, sport: str = "football"):
        self.sport = sport
        self.eval_matches: List[Dict[str, Any]] = []
        self.settled_matches: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # DATA LOADING
    # ------------------------------------------------------------------

    def load_data(self, days: int = 60, all_data: bool = False) -> int:
        """Load historical prediction+result data via PredictionEvaluator."""
        if not _evaluator_ok:
            print("[WeightOptimizer] PredictionEvaluator not available")
            return 0

        ev = PredictionEvaluator()
        if all_data:
            ev.load()  # no date filter = load all available
        else:
            ev.load(days=days)

        ev.match_results()

        # Filter to sport and settled only
        self.eval_matches = [
            m for m in ev.all_matches
            if m.sport == self.sport and m.is_settled
        ]
        self.settled_matches = self.eval_matches
        print(f"[WeightOptimizer] Loaded {len(self.settled_matches)} settled {self.sport} matches")
        return len(self.settled_matches)

    # ------------------------------------------------------------------
    # SCORING SIMULATION
    # ------------------------------------------------------------------

    def _simulate_weights(
        self, weights: Dict[str, float], matches: List[Dict[str, Any]]
    ) -> Tuple[float, float, float]:
        """
        Re-score matches with given weights, return (accuracy, brier, roi).

        This is a simplified simulation that re-computes the weighted average
        of source estimates using the candidate weights, then checks picks
        against actual outcomes.
        """
        if not matches:
            return 0.0, 1.0, 0.0

        correct = 0
        total = 0
        brier_sum = 0.0
        profit = 0.0

        for m in matches:
            if not m.is_settled:
                continue

            # Get source estimates from features
            estimates = self._extract_estimates(m)
            if not estimates:
                continue

            # Compute weighted probability
            w_total = sum(weights.get(k, 0) for k in estimates)
            if w_total == 0:
                continue

            prob_home = sum(estimates.get(k, 0.5) * weights.get(k, 0) for k in estimates)
            prob_home /= w_total
            prob_home = max(0.02, min(0.98, prob_home))

            # Pick
            pick = 'home' if prob_home >= 0.5 else 'away'
            pick_prob = prob_home if pick == 'home' else 1.0 - prob_home

            # Check result
            actual = m.actual_winner  # 'home', 'away', 'draw'
            total += 1

            won = (pick == actual)
            if won:
                correct += 1

            # Brier score (1 if correct outcome, 0 otherwise)
            actual_val = 1.0 if actual == 'home' else 0.0
            brier_sum += (prob_home - actual_val) ** 2

            # ROI (flat 1-unit stake)
            odds = m.home_odds if pick == 'home' else m.away_odds
            if odds and odds > 1.0 and won:
                profit += odds - 1.0
            elif odds:
                profit -= 1.0

        accuracy = correct / total if total > 0 else 0.0
        brier = brier_sum / total if total > 0 else 1.0
        roi = profit / total if total > 0 else 0.0

        return accuracy, brier, roi

    def _extract_estimates(self, m) -> Dict[str, float]:
        """Extract per-source probability estimates from an EvalMatch."""
        estimates = {}

        # H2H
        if hasattr(m, 'features') and m.features:
            feats = m.features
        else:
            feats = {}

        # Use stored data to reconstruct source estimates
        # H2H
        h2h_wr = feats.get('h2h_win_rate_a', feats.get('h2h_win_rate', None))
        if h2h_wr is not None:
            estimates['h2h'] = h2h_wr if h2h_wr <= 1.0 else h2h_wr / 100.0

        # Form — approximate from scoring data
        if m.scoring_prob is not None:
            estimates['form'] = m.scoring_prob

        # Odds
        if m.home_odds and m.home_odds > 1.0 and m.away_odds and m.away_odds > 1.0:
            total_inv = 1.0 / m.home_odds + 1.0 / m.away_odds
            if m.draw_odds and m.draw_odds > 1.0:
                total_inv += 1.0 / m.draw_odds
            estimates['odds'] = (1.0 / m.home_odds) / total_inv

        # Forebet
        if m.forebet_probability and m.forebet_probability > 0:
            fp = m.forebet_probability
            if fp > 1:
                fp = fp / 100.0
            # Forebet prediction direction
            if m.forebet_prediction == '1':
                estimates['forebet'] = fp
            elif m.forebet_prediction == '2':
                estimates['forebet'] = 1.0 - fp
            else:
                estimates['forebet'] = 0.5

        # SofaScore
        if m.sofascore_home is not None and m.sofascore_home > 0:
            ss_total = (m.sofascore_home or 0) + (m.sofascore_away or 0)
            if ss_total > 0:
                estimates['sofascore'] = m.sofascore_home / ss_total

        # Gemini
        gemini_map = {'LOCK': 0.85, 'HIGH': 0.72, 'MEDIUM': 0.58, 'LOW': 0.42, 'AVOID': 0.25}
        if m.gemini_recommendation:
            g_base = gemini_map.get(m.gemini_recommendation, 0.5)
            # Flip if focus is away
            if m.focus_team == 'away':
                g_base = 1.0 - g_base
            estimates['gemini'] = g_base

        return estimates

    # ------------------------------------------------------------------
    # COORDINATE DESCENT
    # ------------------------------------------------------------------

    def optimize_coordinate_descent(
        self,
        initial_weights: Optional[Dict[str, float]] = None,
        step: float = 0.02,
        min_weight: float = 0.02,
        max_weight: float = 0.40,
        max_iterations: int = 50,
        objective: str = "accuracy",  # "accuracy", "brier", "roi", "combined"
    ) -> OptimizationResult:
        """
        Coordinate descent: cycle through each weight, adjust up/down
        by `step`, keep change if objective improves.
        """
        if not self.settled_matches:
            return self._empty_result()

        if initial_weights is None:
            initial_weights = self._default_weights()

        weights = copy.deepcopy(initial_weights)
        keys = list(weights.keys())

        # Baseline
        b_acc, b_brier, b_roi = self._simulate_weights(weights, self.settled_matches)
        best_score = self._objective_score(b_acc, b_brier, b_roi, objective)

        improved = True
        iteration = 0
        while improved and iteration < max_iterations:
            improved = False
            iteration += 1
            for k in keys:
                for delta in [step, -step]:
                    candidate = copy.deepcopy(weights)
                    candidate[k] = max(min_weight, min(max_weight, candidate[k] + delta))

                    # Normalize to sum=1
                    total = sum(candidate.values())
                    if total > 0:
                        candidate = {kk: vv / total for kk, vv in candidate.items()}

                    c_acc, c_brier, c_roi = self._simulate_weights(candidate, self.settled_matches)
                    c_score = self._objective_score(c_acc, c_brier, c_roi, objective)

                    if c_score > best_score:
                        weights = candidate
                        best_score = c_score
                        improved = True

        # Final eval
        o_acc, o_brier, o_roi = self._simulate_weights(weights, self.settled_matches)

        result = OptimizationResult(
            sport=self.sport,
            baseline_weights=initial_weights,
            optimized_weights=weights,
            baseline_accuracy=b_acc,
            optimized_accuracy=o_acc,
            baseline_brier=b_brier,
            optimized_brier=o_brier,
            baseline_roi=b_roi,
            optimized_roi=o_roi,
            n_matches=len(self.settled_matches),
            improvement=o_acc - b_acc,
            timestamp=datetime.now().isoformat(),
        )
        return result

    # ------------------------------------------------------------------
    # GRID SEARCH
    # ------------------------------------------------------------------

    def optimize_grid_search(
        self,
        initial_weights: Optional[Dict[str, float]] = None,
        resolution: int = 5,  # number of steps per weight
        objective: str = "accuracy",
    ) -> OptimizationResult:
        """
        Coarse grid search over weight space.
        Only practical with ≤4 weights; for more, uses random sampling.
        """
        if not self.settled_matches:
            return self._empty_result()

        if initial_weights is None:
            initial_weights = self._default_weights()

        keys = list(initial_weights.keys())
        n_keys = len(keys)

        # For many weights, use random Latin hypercube sampling
        import random
        random.seed(42)

        best_weights = copy.deepcopy(initial_weights)
        b_acc, b_brier, b_roi = self._simulate_weights(best_weights, self.settled_matches)
        best_score = self._objective_score(b_acc, b_brier, b_roi, objective)

        n_samples = min(resolution ** min(n_keys, 4), 5000)
        print(f"[GridSearch] Sampling {n_samples} weight combinations for {n_keys} factors")

        for _ in range(n_samples):
            # Random weight vector
            raw = {k: random.uniform(0.02, 0.40) for k in keys}
            total = sum(raw.values())
            candidate = {k: v / total for k, v in raw.items()}

            c_acc, c_brier, c_roi = self._simulate_weights(candidate, self.settled_matches)
            c_score = self._objective_score(c_acc, c_brier, c_roi, objective)

            if c_score > best_score:
                best_weights = candidate
                best_score = c_score

        o_acc, o_brier, o_roi = self._simulate_weights(best_weights, self.settled_matches)

        return OptimizationResult(
            sport=self.sport,
            baseline_weights=initial_weights,
            optimized_weights=best_weights,
            baseline_accuracy=b_acc,
            optimized_accuracy=o_acc,
            baseline_brier=b_brier,
            optimized_brier=o_brier,
            baseline_roi=b_roi,
            optimized_roi=o_roi,
            n_matches=len(self.settled_matches),
            improvement=o_acc - b_acc,
            timestamp=datetime.now().isoformat(),
        )

    # ------------------------------------------------------------------
    # CONFIDENCE CALIBRATION
    # ------------------------------------------------------------------

    def calibrate_confidence(
        self, n_buckets: int = 10
    ) -> Tuple[List[CalibrationBucket], float]:
        """
        Measure confidence calibration: group predictions by predicted
        probability bucket, compute actual win rate per bucket.

        Returns (buckets, expected_calibration_error).
        """
        buckets = []
        step = 1.0 / n_buckets
        for i in range(n_buckets):
            lo = i * step
            hi = (i + 1) * step
            buckets.append(CalibrationBucket(predicted_low=lo, predicted_high=hi))

        for m in self.settled_matches:
            prob = m.scoring_prob or (m.confidence / 100.0 if m.confidence else None)
            if prob is None:
                continue

            # Clamp
            prob = max(0.001, min(0.999, prob))

            # Find bucket
            idx = min(int(prob / step), n_buckets - 1)
            buckets[idx].count += 1
            if m.outcome == 'won':
                buckets[idx].actual_wins += 1

        # ECE = weighted average of calibration errors
        total = sum(b.count for b in buckets)
        ece = 0.0
        if total > 0:
            ece = sum(b.calibration_error * b.count for b in buckets) / total

        return buckets, ece

    def find_optimal_temperature(
        self, temp_range: Tuple[float, float] = (0.5, 2.0), steps: int = 30
    ) -> float:
        """Find temperature that minimizes calibration error."""
        if not self.settled_matches:
            return 1.0

        best_temp = 1.0
        best_ece = float('inf')

        for i in range(steps + 1):
            temp = temp_range[0] + (temp_range[1] - temp_range[0]) * i / steps

            # Apply temperature scaling to all probabilities
            total_error = 0.0
            total_count = 0
            for m in self.settled_matches:
                prob = m.scoring_prob
                if prob is None or prob <= 0 or prob >= 1:
                    continue

                # Temperature scale via logit
                logit = math.log(prob / (1 - prob))
                scaled = 1.0 / (1.0 + math.exp(-logit / temp))

                actual = 1.0 if m.outcome == 'won' else 0.0
                total_error += (scaled - actual) ** 2
                total_count += 1

            if total_count > 0:
                ece = total_error / total_count
                if ece < best_ece:
                    best_ece = ece
                    best_temp = temp

        return best_temp

    # ------------------------------------------------------------------
    # SAVE / APPLY
    # ------------------------------------------------------------------

    def save_optimized(self, result: OptimizationResult) -> str:
        """Save optimized weights to the calibration file for the sport."""
        os.makedirs(OUTPUTS_DIR, exist_ok=True)

        cal_file = FOOTBALL_CAL if self.sport != 'tennis' else TENNIS_CAL
        cal_data = {}
        if os.path.exists(cal_file):
            try:
                with open(cal_file) as f:
                    cal_data = json.load(f)
            except Exception:
                pass

        cal_data['weights'] = {k: round(v, 4) for k, v in result.optimized_weights.items()}
        cal_data['temperature'] = result.calibration_temperature
        cal_data['optimized_at'] = result.timestamp
        cal_data['baseline_accuracy'] = result.baseline_accuracy
        cal_data['optimized_accuracy'] = result.optimized_accuracy
        cal_data['n_matches'] = result.n_matches

        with open(cal_file, 'w') as f:
            json.dump(cal_data, f, indent=2)

        print(f"[WeightOptimizer] Saved to {cal_file}")
        return cal_file

    def save_report(self, results: List[OptimizationResult]) -> str:
        """Save full optimization report."""
        os.makedirs(OUTPUTS_DIR, exist_ok=True)

        report = {
            "generated_at": datetime.now().isoformat(),
            "sports": [r.to_dict() for r in results],
        }

        with open(OPTIMIZER_REPORT, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"[WeightOptimizer] Report saved to {OPTIMIZER_REPORT}")
        return OPTIMIZER_REPORT

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _default_weights(self) -> Dict[str, float]:
        if self.sport == 'tennis' and _tennis_ok:
            from tennis_scoring_engine import DEFAULT_WEIGHTS as TENNIS_DEFAULTS
            return dict(TENNIS_DEFAULTS)
        elif _football_ok:
            return FootballScoringEngine.DEFAULT_WEIGHTS.copy()
        # Generic fallback
        return {
            'h2h': 0.20, 'form': 0.15, 'odds': 0.20,
            'forebet': 0.15, 'sofascore': 0.10, 'gemini': 0.10,
            'venue_form': 0.10,
        }

    def _objective_score(
        self, accuracy: float, brier: float, roi: float, objective: str
    ) -> float:
        """Higher is better."""
        if objective == "accuracy":
            return accuracy
        elif objective == "brier":
            return -brier  # lower brier is better
        elif objective == "roi":
            return roi
        elif objective == "combined":
            # Balanced: 50% accuracy, 30% -brier, 20% roi
            return accuracy * 0.5 + (-brier) * 0.3 + roi * 0.2
        return accuracy

    def _empty_result(self) -> OptimizationResult:
        return OptimizationResult(
            sport=self.sport,
            baseline_weights=self._default_weights(),
            optimized_weights=self._default_weights(),
            baseline_accuracy=0.0,
            optimized_accuracy=0.0,
            baseline_brier=1.0,
            optimized_brier=1.0,
            baseline_roi=0.0,
            optimized_roi=0.0,
            n_matches=0,
            timestamp=datetime.now().isoformat(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# PRINT REPORTS
# ═══════════════════════════════════════════════════════════════════════════

def print_calibration(buckets: List[CalibrationBucket], ece: float):
    print(f"\n{'='*70}")
    print(f"  CONFIDENCE CALIBRATION  (ECE = {ece:.4f})")
    print(f"{'='*70}")
    print(f"  {'Bucket':>12}  {'Count':>6}  {'Predicted':>10}  {'Actual':>10}  {'Error':>8}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*10}  {'-'*10}  {'-'*8}")
    for b in buckets:
        if b.count == 0:
            continue
        pred_str = f"{b.midpoint:.0%}"
        actual_str = f"{b.actual_rate:.0%}" if b.count > 0 else "N/A"
        err_str = f"{b.calibration_error:.3f}" if b.count > 0 else ""
        bar = "█" * int(b.count / max(1, max(bb.count for bb in buckets)) * 20)
        print(f"  {b.predicted_low:.0%}-{b.predicted_high:.0%}  {b.count:>6}  "
              f"{pred_str:>10}  {actual_str:>10}  {err_str:>8}  {bar}")
    print(f"{'='*70}\n")


def print_optimization_result(r: OptimizationResult):
    print(f"\n{'='*70}")
    print(f"  WEIGHT OPTIMIZATION — {r.sport.upper()}")
    print(f"{'='*70}")
    print(f"  Matches: {r.n_matches}")
    print(f"  {'':>20}  {'Baseline':>10}  {'Optimized':>10}  {'Change':>10}")
    print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(f"  {'Accuracy':>20}  {r.baseline_accuracy:>10.1%}  {r.optimized_accuracy:>10.1%}  "
          f"{r.improvement:>+10.1%}")
    print(f"  {'Brier Score':>20}  {r.baseline_brier:>10.4f}  {r.optimized_brier:>10.4f}  "
          f"{r.optimized_brier - r.baseline_brier:>+10.4f}")
    print(f"  {'ROI':>20}  {r.baseline_roi:>10.1%}  {r.optimized_roi:>10.1%}  "
          f"{r.optimized_roi - r.baseline_roi:>+10.1%}")

    print(f"\n  Weights:")
    print(f"  {'Factor':>20}  {'Before':>8}  {'After':>8}  {'Change':>8}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*8}")
    for k in r.baseline_weights:
        before = r.baseline_weights[k]
        after = r.optimized_weights.get(k, before)
        print(f"  {k:>20}  {before:>8.3f}  {after:>8.3f}  {after - before:>+8.3f}")

    if r.calibration_temperature != 1.0:
        print(f"\n  Calibration temperature: {r.calibration_temperature:.3f}")
    print(f"{'='*70}\n")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weight Optimizer")
    parser.add_argument("--sport", default="football",
                        choices=["football", "tennis", "basketball", "volleyball",
                                 "handball", "hockey"])
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--objective", default="combined",
                        choices=["accuracy", "brier", "roi", "combined"])
    parser.add_argument("--method", default="coordinate",
                        choices=["coordinate", "grid", "both"])
    parser.add_argument("--calibrate", action="store_true",
                        help="Also find optimal temperature")
    parser.add_argument("--save", action="store_true",
                        help="Save optimized weights to calibration file")
    parser.add_argument("--report", action="store_true",
                        help="Run all sports and generate report")
    args = parser.parse_args()

    if args.report:
        # Run all sports
        results = []
        for sport in ["football", "tennis"]:
            opt = WeightOptimizer(sport=sport)
            n = opt.load_data(days=args.days, all_data=args.all)
            if n < 20:
                print(f"[{sport}] Only {n} settled matches — skipping (need ≥20)")
                continue

            result = opt.optimize_coordinate_descent(objective=args.objective)

            if args.calibrate:
                temp = opt.find_optimal_temperature()
                result.calibration_temperature = temp

            print_optimization_result(result)

            buckets, ece = opt.calibrate_confidence()
            print_calibration(buckets, ece)

            if args.save:
                opt.save_optimized(result)

            results.append(result)

        if results:
            opt_any = WeightOptimizer()
            opt_any.save_report(results)
        return

    # Single sport
    opt = WeightOptimizer(sport=args.sport)
    n = opt.load_data(days=args.days, all_data=args.all)

    if n < 10:
        print(f"Only {n} settled matches for {args.sport} — need more data for meaningful optimization.")
        print("Run check_results.py to populate result_store.json with actual match outcomes.")
        return

    if args.method in ("coordinate", "both"):
        result = opt.optimize_coordinate_descent(objective=args.objective)
        if args.calibrate:
            result.calibration_temperature = opt.find_optimal_temperature()
        print_optimization_result(result)
        if args.save:
            opt.save_optimized(result)

    if args.method in ("grid", "both"):
        result = opt.optimize_grid_search(objective=args.objective)
        if args.calibrate:
            result.calibration_temperature = opt.find_optimal_temperature()
        print_optimization_result(result)
        if args.save:
            opt.save_optimized(result)

    # Always show calibration
    buckets, ece = opt.calibrate_confidence()
    print_calibration(buckets, ece)


if __name__ == "__main__":
    main()
