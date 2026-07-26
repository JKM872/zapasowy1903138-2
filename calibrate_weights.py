#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weight calibration & benchmarking for the scoring engines
==========================================================

Answers three questions the plain backtest could not:

1. **Is the model any good?**  Every run reports the model *against
   baselines*: the bookmaker's own implied probabilities (margin removed),
   a fixed league prior, and a uniform guess. A model that cannot beat the
   market on Brier/log-loss is not adding information, however good its
   absolute numbers look.

2. **Which weights are best?**  ``--optimise`` runs a random search plus
   coordinate refinement over the source weights, minimising log-loss on a
   held-out split (train/test) so the result is not just overfitting.

3. **Is it calibrated?**  Reliability bins compare predicted probability
   against observed frequency, so systematic over-confidence is visible.

Data sources
------------
``--real PATH``   JSON/CSV rows carrying ``actual_result`` ('1'/'X'/'2').
                  Use ``export_settled.py`` to produce this from Supabase.
``--simulate N``  Monte-Carlo rows with ground truth known by construction.
                  Useful for regression-testing the maths, but weights tuned
                  here reflect the simulator, not real football — the report
                  says so explicitly.

Usage
-----
    python calibrate_weights.py --simulate 1200
    python calibrate_weights.py --simulate 1200 --optimise --iterations 40
    python calibrate_weights.py --real outputs/settled_football.json --optimise
    python calibrate_weights.py --real ... --optimise --save
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from football_scoring_engine import (  # noqa: E402
    CalibrationRunner,
    FootballScoringEngine,
    SPORT_PROFILES,
    _implied_probs_from_odds,
    _safe_float,
)

OUTCOMES = ('1', 'X', '2')


# ---------------------------------------------------------------------------
# Scoring metrics
# ---------------------------------------------------------------------------

def _target_vector(actual: str) -> List[float]:
    return [1.0 if o == actual else 0.0 for o in OUTCOMES]


def brier(probs: List[float], actual: str) -> float:
    """Multiclass Brier score for one prediction (lower is better)."""
    return sum((p - t) ** 2 for p, t in zip(probs, _target_vector(actual)))


def log_loss(probs: List[float], actual: str) -> float:
    """Negative log-likelihood of the observed outcome (lower is better)."""
    idx = OUTCOMES.index(actual)
    return -math.log(max(1e-12, min(1.0, probs[idx])))


class Evaluation:
    """Accumulates metrics for one predictor over a dataset."""

    def __init__(self, label: str):
        self.label = label
        self.n = 0
        self.correct = 0
        self.brier_sum = 0.0
        self.logloss_sum = 0.0
        self.bets = 0
        self.pnl = 0.0
        # Reliability bins on the model's confidence in its own pick.
        self._bins = [(0.0, 0.35), (0.35, 0.45), (0.45, 0.55),
                      (0.55, 0.65), (0.65, 0.80), (0.80, 1.01)]
        self._bin_pred = [0.0] * len(self._bins)
        self._bin_hit = [0.0] * len(self._bins)
        self._bin_n = [0] * len(self._bins)

    def add(self, probs: List[float], actual: str, *,
            ev: float = 0.0, odds: float = 0.0) -> None:
        self.n += 1
        self.brier_sum += brier(probs, actual)
        self.logloss_sum += log_loss(probs, actual)

        pick_idx = max(range(3), key=lambda i: probs[i])
        pick = OUTCOMES[pick_idx]
        hit = pick == actual
        if hit:
            self.correct += 1

        p_pick = probs[pick_idx]
        for bi, (lo, hi) in enumerate(self._bins):
            if lo <= p_pick < hi:
                self._bin_pred[bi] += p_pick
                self._bin_hit[bi] += 1.0 if hit else 0.0
                self._bin_n[bi] += 1
                break

        # Flat-stake value betting: only stake when the model sees an edge.
        if ev > 0 and odds > 1:
            self.bets += 1
            self.pnl += (odds - 1.0) if hit else -1.0

    def summary(self) -> Dict[str, Any]:
        n = max(1, self.n)
        return {
            'label': self.label,
            'n': self.n,
            'accuracy': round(self.correct / n, 4),
            'brier': round(self.brier_sum / n, 4),
            'log_loss': round(self.logloss_sum / n, 4),
            'value_bets': self.bets,
            'roi': round(self.pnl / self.bets, 4) if self.bets else 0.0,
            'net_units': round(self.pnl, 2),
        }

    def reliability(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for bi, (lo, hi) in enumerate(self._bins):
            if self._bin_n[bi] == 0:
                continue
            out.append({
                'range': f'{lo:.2f}-{hi:.2f}',
                'n': self._bin_n[bi],
                'predicted': round(self._bin_pred[bi] / self._bin_n[bi], 3),
                'observed': round(self._bin_hit[bi] / self._bin_n[bi], 3),
            })
        return out


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def market_probs(row: Dict[str, Any]) -> Optional[List[float]]:
    """Bookmaker implied probabilities with the margin removed."""
    implied = _implied_probs_from_odds(
        _safe_float(row.get('home_odds')),
        _safe_float(row.get('draw_odds')),
        _safe_float(row.get('away_odds')),
    )
    return list(implied) if implied else None


def prior_probs(row: Dict[str, Any]) -> List[float]:
    """Fixed long-run base rates for the row's sport."""
    sport = (row.get('sport') or 'football').lower()
    p = SPORT_PROFILES.get(sport, SPORT_PROFILES['football'])
    h = p.get('home_advantage', 0.46)
    d = p.get('draw_rate', 0.26)
    a = p.get('away_rate', 0.28)
    total = h + d + a
    return [h / total, d / total, a / total]


# ---------------------------------------------------------------------------
# Dataset handling
# ---------------------------------------------------------------------------

def load_real_rows(path: str) -> List[Dict[str, Any]]:
    """Load rows that carry ``actual_result``."""
    if path.endswith('.csv'):
        import csv
        with open(path, 'r', encoding='utf-8-sig') as fh:
            rows = list(csv.DictReader(fh))
    else:
        with open(path, 'r', encoding='utf-8-sig') as fh:
            data = json.load(fh)
        if isinstance(data, list):
            rows = data
        else:
            rows = []
            for key in ('matches', 'results', 'predictions', 'data'):
                if isinstance(data.get(key), list):
                    rows = data[key]
                    break

    usable = [r for r in rows
              if str(r.get('actual_result', '')).strip().upper() in OUTCOMES]
    for r in usable:
        r['actual_result'] = str(r['actual_result']).strip().upper()
    return usable


def build_simulated_rows(n: int, seed: int = 42) -> List[Dict[str, Any]]:
    """Generate rows with a known outcome using the existing simulator."""
    from backtest_engine import _build_match_row, _sample_score

    rng = random.Random(seed)
    rows: List[Dict[str, Any]] = []
    for _ in range(n):
        lh = rng.uniform(0.6, 2.6)
        la = rng.uniform(0.5, 2.2)
        sh, sa = _sample_score(lh, la, rng)
        actual = '1' if sh > sa else ('X' if sh == sa else '2')
        row = _build_match_row(lh, la, rng, odds_noise=0.1)
        row['actual_result'] = actual
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Evaluation over a dataset
# ---------------------------------------------------------------------------

def _score_row(row: Dict[str, Any], engine: FootballScoringEngine,
               ) -> Tuple[List[float], float, float]:
    """Score one row with the engine matching its sport.

    Tennis has its own two-outcome engine; scoring it with the football one
    would inject a draw that cannot happen. Returns
    ``([p1, pX, p2], ev, best_odds)``.
    """
    sport = (row.get('sport') or 'football').lower()
    if sport == 'tennis':
        from tennis_scoring_engine import TennisScoringEngine

        st = TennisScoringEngine().score_match(row)
        return [st.cal_a, 0.0, st.cal_b], st.ev, st.best_odds

    sm = engine.score_match(row)
    return [sm.cal_home, sm.cal_draw, sm.cal_away], sm.ev, sm.best_odds


def evaluate_dataset(rows: List[Dict[str, Any]],
                     weights: Optional[Dict[str, float]] = None,
                     ) -> Dict[str, Any]:
    """Evaluate the engine and all baselines over *rows*."""
    engine = FootballScoringEngine()
    if weights:
        engine.weights = dict(weights)

    model = Evaluation('model')
    market = Evaluation('market (bookmaker)')
    prior = Evaluation('sport prior')
    uniform = Evaluation('uniform 1/3')

    for row in rows:
        actual = row['actual_result']
        probs, ev, odds = _score_row(row, engine)
        model.add(probs, actual, ev=ev, odds=odds)

        mp = market_probs(row)
        if mp:
            market.add(mp, actual)
        prior.add(prior_probs(row), actual)
        uniform.add([1 / 3, 1 / 3, 1 / 3], actual)

    return {
        'model': model.summary(),
        'market': market.summary(),
        'prior': prior.summary(),
        'uniform': uniform.summary(),
        'reliability': model.reliability(),
    }


def evaluate_per_sport(rows: List[Dict[str, Any]],
                       min_rows: int = 30) -> Dict[str, Any]:
    """Evaluate each sport separately.

    A single blended number hides the fact that the engine may beat the market
    in one sport and trail it badly in another — which is exactly what a
    per-sport weight set would have to fix. Sports below *min_rows* are
    reported but flagged, because their metrics are noise.
    """
    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        sport = (row.get('sport') or 'football').lower()
        by_sport.setdefault(sport, []).append(row)

    out: Dict[str, Any] = {}
    for sport, sport_rows in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        res = evaluate_dataset(sport_rows)
        res['n_rows'] = len(sport_rows)
        res['reliable'] = len(sport_rows) >= min_rows
        out[sport] = res
    return out


def _log_loss_of(rows: List[Dict[str, Any]], weights: Dict[str, float]) -> float:
    """Mean log-loss of the engine with *weights* over *rows*."""
    engine = FootballScoringEngine()
    engine.weights = dict(weights)
    total = 0.0
    for row in rows:
        sm = engine.score_match(row)
        total += log_loss([sm.cal_home, sm.cal_draw, sm.cal_away],
                          row['actual_result'])
    return total / max(1, len(rows))


# ---------------------------------------------------------------------------
# Weight optimisation
# ---------------------------------------------------------------------------

def _normalise(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def optimise_weights(train: List[Dict[str, Any]],
                     iterations: int = 40,
                     seed: int = 42,
                     verbose: bool = True) -> Tuple[Dict[str, float], float]:
    """Search for weights minimising log-loss on *train*.

    Random search seeded with the current defaults, followed by a coordinate
    refinement pass. Log-loss (not accuracy) is the objective because it is a
    proper scoring rule — it rewards honest probabilities rather than lucky
    top-picks.
    """
    rng = random.Random(seed)
    base = _normalise(FootballScoringEngine.DEFAULT_WEIGHTS.copy())
    best = dict(base)
    best_loss = _log_loss_of(train, best)
    if verbose:
        print(f"  baseline log-loss (default weights): {best_loss:.5f}")

    keys = sorted(base.keys())

    # Phase 1 — random perturbations around the incumbent.
    for i in range(iterations):
        candidate = {
            k: max(0.0, best[k] * rng.uniform(0.5, 1.5) + rng.uniform(-0.02, 0.02))
            for k in keys
        }
        candidate = _normalise(candidate)
        loss = _log_loss_of(train, candidate)
        if loss < best_loss:
            best, best_loss = candidate, loss
            if verbose:
                print(f"  [{i + 1}/{iterations}] improved log-loss: {loss:.5f}")

    # Phase 2 — coordinate refinement: nudge one source at a time.
    for k in keys:
        for factor in (0.6, 0.8, 1.25, 1.6):
            candidate = dict(best)
            candidate[k] = max(0.0, candidate[k] * factor)
            candidate = _normalise(candidate)
            loss = _log_loss_of(train, candidate)
            if loss < best_loss:
                best, best_loss = candidate, loss
                if verbose:
                    print(f"  refine {k} x{factor}: log-loss {loss:.5f}")

    return best, best_loss


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_per_sport(per_sport: Dict[str, Any], min_rows: int = 30) -> None:
    """One line per sport: does the model add anything over the market there?"""
    print(f"\n{'=' * 78}")
    print("  PER-SPORT BREAKDOWN — model vs bookmaker")
    print(f"{'=' * 78}")
    print(f"  {'sport':<13}{'n':>6}{'acc':>7}{'brier':>9}{'mkt brier':>11}"
          f"{'d.brier':>9}{'d.ll':>8}  verdict")
    print(f"  {'-' * 74}")

    for sport, res in per_sport.items():
        m, mk = res['model'], res['market']
        n = res['n_rows']
        if mk['n'] == 0:
            verdict = 'no odds -> cannot compare'
            d_b = d_l = float('nan')
        else:
            d_b = m['brier'] - mk['brier']
            d_l = m['log_loss'] - mk['log_loss']
            if d_b < 0 and d_l < 0:
                verdict = 'beats market'
            elif d_b > 0 and d_l > 0:
                verdict = 'WORSE than market'
            else:
                verdict = 'mixed'
        if not res['reliable']:
            verdict += f' (n<{min_rows}: noise)'
        d_b_s = f'{d_b:+.4f}' if d_b == d_b else '     -'
        d_l_s = f'{d_l:+.4f}' if d_l == d_l else '     -'
        print(f"  {sport:<13}{n:>6}{m['accuracy']:>7.3f}{m['brier']:>9.4f}"
              f"{mk['brier'] if mk['n'] else 0:>11.4f}{d_b_s:>9}{d_l_s:>8}  {verdict}")

    print("\n  A sport that trails the market is the case for its own weight set;\n"
          "  one that beats it should be left alone.")
    print(f"{'=' * 78}\n")


def print_report(title: str, res: Dict[str, Any]) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")
    print(f"  {'predictor':<22}{'n':>6}{'acc':>9}{'brier':>10}{'log-loss':>11}")
    print(f"  {'-' * 58}")
    for key in ('model', 'market', 'prior', 'uniform'):
        s = res[key]
        if s['n'] == 0:
            continue
        print(f"  {s['label']:<22}{s['n']:>6}{s['accuracy']:>9.3f}"
              f"{s['brier']:>10.4f}{s['log_loss']:>11.4f}")

    m, mk = res['model'], res['market']
    if mk['n'] > 0:
        d_brier = m['brier'] - mk['brier']
        d_ll = m['log_loss'] - mk['log_loss']
        verdict = ('model beats the market'
                   if d_brier < 0 and d_ll < 0 else
                   'model does NOT beat the market')
        print(f"\n  vs market: brier {d_brier:+.4f}, log-loss {d_ll:+.4f}"
              f"  ->  {verdict}")

    if m['value_bets']:
        print(f"\n  value bets: {m['value_bets']}  "
              f"ROI {m['roi'] * 100:+.1f}%  net {m['net_units']:+.1f}u")
        if 'SIMULATED' in title:
            print("  WARNING: this ROI is meaningless. The simulator prices odds\n"
                  "  from the true probabilities with random noise, so the noise\n"
                  "  itself manufactures 'value'. Only ROI on real settled\n"
                  "  matches says anything about profitability.")
    else:
        print("\n  value bets: none flagged (no positive-EV picks with odds)")

    rel = res.get('reliability') or []
    if rel:
        print(f"\n  reliability (is the stated confidence honest?)")
        print(f"   {'range':<14}{'n':>6}{'predicted':>12}{'observed':>11}{'gap':>9}")
        for b in rel:
            gap = b['observed'] - b['predicted']
            print(f"   {b['range']:<14}{b['n']:>6}{b['predicted']:>12.3f}"
                  f"{b['observed']:>11.3f}{gap:>+9.3f}")
    print(f"{'=' * 72}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description='Benchmark and calibrate the football scoring weights')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--real', metavar='PATH',
                     help='JSON/CSV with rows carrying actual_result')
    src.add_argument('--simulate', type=int, metavar='N',
                     help='Generate N simulated rows with known outcomes')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--optimise', action='store_true',
                    help='Search for better weights (train/test split)')
    ap.add_argument('--iterations', type=int, default=30,
                    help='Random-search iterations for --optimise')
    ap.add_argument('--test-frac', type=float, default=0.3,
                    help='Held-out fraction used to validate new weights')
    ap.add_argument('--save', action='store_true',
                    help='Persist optimised weights to outputs/scoring_calibration.json')
    ap.add_argument('--per-sport', action='store_true',
                    help='Report every sport separately instead of one blend')
    ap.add_argument('--optimise-per-sport', action='store_true',
                    help='Calibrate a separate weight set for each sport that '
                         'has enough settled rows')
    ap.add_argument('--min-rows', type=int, default=30,
                    help='Below this row count a sport is flagged as unreliable')
    ap.add_argument('--json', action='store_true', help='Emit JSON only')
    args = ap.parse_args()

    if args.real:
        rows = load_real_rows(args.real)
        source_label = f'real data: {os.path.basename(args.real)}'
        if not rows:
            print(f"No rows with actual_result ('1'/'X'/'2') found in {args.real}.")
            print("Export settled predictions first (see export_settled.py).")
            return 1
    else:
        rows = build_simulated_rows(args.simulate, seed=args.seed)
        source_label = f'SIMULATED data ({args.simulate} rows)'

    print(f"\nDataset: {source_label} — {len(rows)} usable rows")
    if args.simulate:
        print("NOTE: simulated rows come from a Poisson generator, not real\n"
              "      fixtures. Weights tuned here describe the simulator.")

    baseline = evaluate_dataset(rows)
    print_report(f'CURRENT WEIGHTS — {source_label}', baseline)

    result: Dict[str, Any] = {'source': source_label, 'baseline': baseline}

    if args.per_sport:
        per_sport = evaluate_per_sport(rows, min_rows=args.min_rows)
        print_per_sport(per_sport, min_rows=args.min_rows)
        result['per_sport'] = per_sport

    if args.optimise:
        rng = random.Random(args.seed)
        shuffled = list(rows)
        rng.shuffle(shuffled)
        cut = int(len(shuffled) * (1.0 - args.test_frac))
        train, test = shuffled[:cut], shuffled[cut:]
        print(f"Optimising on {len(train)} rows, validating on {len(test)} held out...")

        weights, train_loss = optimise_weights(
            train, iterations=args.iterations, seed=args.seed)

        default_test = evaluate_dataset(test)
        tuned_test = evaluate_dataset(test, weights=weights)

        print("\n  optimised weights:")
        for k in sorted(weights):
            delta = weights[k] - FootballScoringEngine.DEFAULT_WEIGHTS.get(k, 0.0)
            print(f"    {k:<14}{weights[k]:.4f}   ({delta:+.4f} vs default)")

        print_report('HELD-OUT TEST — default weights', default_test)
        print_report('HELD-OUT TEST — optimised weights', tuned_test)

        improved = (tuned_test['model']['log_loss'] < default_test['model']['log_loss']
                    and tuned_test['model']['brier'] <= default_test['model']['brier'])
        print(f"  Held-out verdict: "
              f"{'optimised weights generalise' if improved else 'NO reliable gain — keep defaults'}")

        result.update({
            'weights': weights,
            'train_log_loss': round(train_loss, 5),
            'test_default': default_test,
            'test_optimised': tuned_test,
            'generalises': improved,
        })

        if args.save:
            if not improved:
                print("\n  Refusing to save: the new weights did not beat the\n"
                      "  defaults on held-out data. Use real settled data or\n"
                      "  more rows before calibrating.")
            elif args.simulate:
                print("\n  Refusing to save weights tuned on SIMULATED data —\n"
                      "  that would calibrate the engine to the simulator.\n"
                      "  Re-run with --real once settled results are exported.")
            else:
                CalibrationRunner().save_calibration(
                    weights, tuned_test['model'])
                print(f"\n  Saved to {FootballScoringEngine.CALIBRATION_PATH}")

    if args.optimise_per_sport:
        per_sport_weights, report = optimise_per_sport(
            rows, iterations=args.iterations, seed=args.seed,
            test_frac=args.test_frac, min_rows=args.min_rows,
            simulated=bool(args.simulate),
        )
        result['per_sport_weights'] = per_sport_weights
        result['per_sport_optimisation'] = report

        if args.save and per_sport_weights:
            if args.simulate:
                print("\n  Refusing to save weights tuned on SIMULATED data.")
            else:
                _save_per_sport(per_sport_weights, report)

    if args.json:
        print(json.dumps(result, indent=2))
    return 0


def optimise_per_sport(rows: List[Dict[str, Any]], *, iterations: int,
                       seed: int, test_frac: float, min_rows: int,
                       simulated: bool = False,
                       ) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Any]]:
    """Calibrate one weight set per sport, keeping only those that generalise.

    Each sport is split into train/test independently. A tuned set is accepted
    only when it improves BOTH log-loss and Brier on that sport's held-out
    rows; otherwise the sport keeps the shared defaults. Sports with fewer than
    *min_rows* settled matches are skipped outright — tuning ten weights on a
    handful of games fits noise, not football.
    """
    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_sport.setdefault((row.get('sport') or 'football').lower(), []).append(row)

    accepted: Dict[str, Dict[str, float]] = {}
    report: Dict[str, Any] = {}

    print(f"\n{'=' * 72}")
    print("  PER-SPORT WEIGHT CALIBRATION")
    print(f"{'=' * 72}")

    for sport, sport_rows in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        if len(sport_rows) < min_rows:
            print(f"  {sport:<13} {len(sport_rows):>5} rows — skipped (need {min_rows})")
            report[sport] = {'n_rows': len(sport_rows), 'status': 'too_few_rows'}
            continue

        rng = random.Random(seed)
        shuffled = list(sport_rows)
        rng.shuffle(shuffled)
        cut = int(len(shuffled) * (1.0 - test_frac))
        train, test = shuffled[:cut], shuffled[cut:]
        if not train or not test:
            report[sport] = {'n_rows': len(sport_rows), 'status': 'split_too_small'}
            continue

        print(f"\n  {sport} — {len(train)} train / {len(test)} test")
        weights, _train_loss = optimise_weights(
            train, iterations=iterations, seed=seed, verbose=False)

        before = evaluate_dataset(test)
        after = evaluate_dataset(test, weights=weights)
        improved = (after['model']['log_loss'] < before['model']['log_loss']
                    and after['model']['brier'] <= before['model']['brier'])

        print(f"    default : brier {before['model']['brier']:.4f}  "
              f"ll {before['model']['log_loss']:.4f}")
        print(f"    tuned   : brier {after['model']['brier']:.4f}  "
              f"ll {after['model']['log_loss']:.4f}"
              f"   -> {'ACCEPTED' if improved else 'rejected'}")

        report[sport] = {
            'n_rows': len(sport_rows),
            'status': 'accepted' if improved else 'rejected',
            'test_default': before['model'],
            'test_tuned': after['model'],
        }
        if improved:
            accepted[sport] = weights

    if accepted:
        print(f"\n  Accepted per-sport weights for: {', '.join(sorted(accepted))}")
    else:
        print("\n  No sport gained a reliable improvement — keeping shared weights.")
    print(f"{'=' * 72}\n")

    return accepted, report


def _save_per_sport(per_sport: Dict[str, Dict[str, float]],
                    report: Dict[str, Any]) -> None:
    """Merge per-sport weights into the calibration file, keeping globals."""
    path = FootballScoringEngine.CALIBRATION_PATH
    existing: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    existing.setdefault('weights', dict(FootballScoringEngine.DEFAULT_WEIGHTS))
    existing['per_sport'] = {**existing.get('per_sport', {}), **per_sport}
    existing['per_sport_metrics'] = report
    from datetime import datetime
    existing['calibrated_at'] = datetime.now().isoformat()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(existing, fh, indent=2)
    print(f"  Saved per-sport weights to {path}")


if __name__ == '__main__':
    sys.exit(main())
