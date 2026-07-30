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

# A settled set whose outcomes are nearly all one class teaches nothing except
# that class. The Supabase export handed us 1000 rows in which `actual_result`
# was '1' for every single match across seven sports — no draw, no away win
# anywhere. Fitted against it the model looked excellent (football "accuracy"
# 81%, basketball 94%) while the real settled picks were running at 44.7%. Every
# calibration path now refuses such data instead of learning a constant.
MIN_CLASS_SHARE = 0.02

# A sport needs this many settled matches before it may get its own weights.
# Higher than the reporting threshold on purpose: ten weights tuned on ~30 rows
# fit noise. The first real run accepted baseball off 28 train / 12 test rows.
MIN_CALIBRATION_ROWS = 60


# ---------------------------------------------------------------------------
# Source coverage
# ---------------------------------------------------------------------------

# Sources the engine abstains from when the underlying data is missing, and the
# feature that tells us whether it contributed. Weights for sources that never
# appear in a sport's data are meaningless — tuning them fits nothing — so they
# are pinned to zero before the weights are stored.
#
# form, venue_form and sofascore are deliberately absent from this map: the
# engine always feeds them, so they always have coverage.
_ABSTAINING_SOURCES: Dict[str, Any] = {
    'h2h': lambda f: f.get('h2h_count', 0.0) > 0,
    'forebet': lambda f: f.get('forebet_prob', 0.5) != 0.5,
    'odds': lambda f: f.get('odds_available', 0.0) > 0,
    'poisson': lambda f: f.get('poisson_available', 0.0) > 0,
    'gemini': lambda f: f.get('gemini_conf', 0.5) != 0.5,
    'consensus': lambda f: f.get('consensus', 0.0) > 0,
    'availability': lambda f: (f.get('availability_impact', 0.0) > 0
                               or f.get('home_key_absences', 0.0) > 0
                               or f.get('away_key_absences', 0.0) > 0),
}


def outcome_distribution(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count how many settled rows carry each outcome."""
    dist: Dict[str, int] = {}
    for row in rows:
        key = str(row.get('actual_result') or '').strip().upper()
        dist[key] = dist.get(key, 0) + 1
    return dist


def labels_are_usable(rows: List[Dict[str, Any]],
                      min_share: float = MIN_CLASS_SHARE,
                      ) -> Tuple[bool, str]:
    """Whether *rows* carry a real spread of outcomes.

    Returns ``(ok, reason)``. Anything a model is tuned on must contain the
    outcomes it is meant to distinguish; a single-class label set makes every
    metric meaningless while looking like an improvement.
    """
    if not rows:
        return False, 'brak wierszy'

    dist = outcome_distribution(rows)
    present = {k: v for k, v in dist.items() if k in OUTCOMES}
    total = sum(present.values())
    if total == 0:
        return False, f'brak poprawnych etykiet (rozkład: {dist})'

    if len(present) < 2:
        only = next(iter(present))
        return False, (f"tylko jedna klasa wyników: '{only}' w {total} wierszach "
                       f'— dane nie nadają się do kalibracji')

    top_share = max(present.values()) / total
    if top_share > 1.0 - min_share:
        return False, (f'rozkład zdegenerowany: {present} '
                       f'(dominująca klasa {100 * top_share:.1f}%)')

    return True, f'rozkład wyników: {present}'


def source_coverage(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count, per source, how many rows actually carry it.

    Uses the engine's own feature extractor and the same predicates the engine
    uses to decide whether a source contributes, so coverage cannot drift from
    scoring behaviour.
    """
    extractor = FootballScoringEngine().extractor
    counts = {name: 0 for name in _ABSTAINING_SOURCES}
    for row in rows:
        try:
            feats = extractor.extract(row)
        except Exception:
            continue
        for name, present in _ABSTAINING_SOURCES.items():
            try:
                if present(feats):
                    counts[name] += 1
            except Exception:
                pass
    return counts


def pin_absent_sources(weights: Dict[str, float],
                       absent: Any) -> Dict[str, float]:
    """Zero the weights of sources with no data and renormalise the rest.

    Behaviour-neutral: the engine averages over contributing sources only, so
    rescaling the survivors changes no prediction. What it buys is an honest
    artifact — nobody reads ``odds=0.191`` for a sport that has no odds and
    concludes the market matters there.
    """
    pinned = {k: (0.0 if k in absent else float(v)) for k, v in weights.items()}
    total = sum(pinned.values())
    if total <= 0:
        return dict(weights)
    return {k: v / total for k, v in pinned.items()}


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
    # Both racket sports are two-outcome. Table tennis used to fall through to
    # the football engine, which gave it a ~19% draw probability that no
    # table-tennis match can produce — inflating its Brier and log-loss and
    # poisoning any weight calibrated on it.
    if sport in ('tennis', 'table_tennis'):
        from tennis_scoring_engine import TennisScoringEngine

        st = TennisScoringEngine().score_match(row)
        return [st.cal_a, 0.0, st.cal_b], st.ev, st.best_odds

    sm = engine.score_match(row)
    return [sm.cal_home, sm.cal_draw, sm.cal_away], sm.ev, sm.best_odds


def _engine_with(weights: Optional[Dict[str, float]]) -> FootballScoringEngine:
    """Engine that really uses *weights*, ignoring any committed calibration.

    ``weights_for_sport`` prefers a per-sport entry from
    ``outputs/scoring_calibration.json`` over the global mix. Once a sport has
    been calibrated once, leaving those entries in place would make every later
    candidate a silent no-op: the tuned weights would be set and then bypassed,
    so the sport could never improve again and every run would report
    'rejected' with numbers identical to the default. Clearing them is what
    makes the comparison mean what it says.
    """
    engine = FootballScoringEngine()
    if weights:
        engine.weights = dict(weights)
        engine.sport_weights = {}
    return engine


def evaluate_dataset(rows: List[Dict[str, Any]],
                     weights: Optional[Dict[str, float]] = None,
                     ) -> Dict[str, Any]:
    """Evaluate the engine and all baselines over *rows*."""
    engine = _engine_with(weights)

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
    engine = _engine_with(weights)
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
    ap.add_argument('--optimise-isotonic', action='store_true',
                    help='Fit a monotone reliability curve per sport so a '
                         'stated probability matches the observed hit rate')
    ap.add_argument('--optimise-temperature', action='store_true',
                    help='Fit the softmax temperature per sport so a stated '
                         'probability matches the observed hit rate')
    ap.add_argument('--min-calibration-rows', type=int,
                    default=MIN_CALIBRATION_ROWS,
                    help='A sport needs at least this many settled rows before '
                         'it may get its own weight set (stricter than '
                         '--min-rows, which only affects reporting)')
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

    # One gate for every calibration path. Tuning on a label set that holds a
    # single outcome produces numbers that look like success and mean nothing.
    labels_ok, labels_reason = labels_are_usable(rows)
    print(f"Etykiety: {labels_reason}")
    tuning_requested = (args.optimise or args.optimise_per_sport
                        or args.optimise_temperature or args.optimise_isotonic)
    if not labels_ok and tuning_requested:
        print('\n' + '=' * 72)
        print('  KALIBRACJA WSTRZYMANA — dane wynikowe są niewiarygodne')
        print('=' * 72)
        print(f'  {labels_reason}')
        print('  Model dopasowany do takiego zbioru wygląda świetnie i nie')
        print('  przewiduje niczego. Napraw źródło wyników i uruchom ponownie.')
        print('=' * 72)
        return 2

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
            test_frac=args.test_frac,
            min_rows=max(args.min_rows, args.min_calibration_rows),
            simulated=bool(args.simulate),
        )
        result['per_sport_weights'] = per_sport_weights
        result['per_sport_optimisation'] = report

        if args.save and per_sport_weights:
            if args.simulate:
                print("\n  Refusing to save weights tuned on SIMULATED data.")
            else:
                _save_per_sport(per_sport_weights, report)

    if args.optimise_temperature:
        temps, temp_report = optimise_temperature(
            rows, seed=args.seed, test_frac=args.test_frac,
            min_rows=max(args.min_rows, args.min_calibration_rows),
            simulated=bool(args.simulate),
        )
        result['temperatures'] = temps
        result['temperature_metrics'] = temp_report

        # Reliability is the point of this exercise: it says whether a stated
        # probability can be believed, which no accuracy number can.
        if temps:
            _print_reliability_shift(rows, temps)

        if args.save and temps:
            _save_temperatures(temps, temp_report)

    if args.optimise_isotonic:
        curves, iso_report = optimise_isotonic(
            rows, seed=args.seed, test_frac=args.test_frac,
            min_rows=max(args.min_rows, args.min_calibration_rows),
            simulated=bool(args.simulate),
        )
        result['isotonic'] = curves
        result['isotonic_metrics'] = iso_report

        if args.save and curves:
            _save_isotonic(curves, iso_report)

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
    rows; otherwise the sport keeps the shared defaults.

    Two guards decide whether a sport may be calibrated at all:

    *min_rows* — tuning ten weights needs more than a handful of games. The
    first real run accepted baseball off 28 train / 12 test rows, which is an
    anecdote, not evidence; hence MIN_CALIBRATION_ROWS above the reporting
    threshold.

    Source coverage — a weight is only meaningful if that source appears in the
    data. The same run handed baseball ``odds=0.191`` while not a single
    baseball row carried a price, so the number described nothing. Sources that
    are absent from a sport's rows are pinned to zero and the remaining mass is
    renormalised.
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

        coverage = source_coverage(sport_rows)
        absent = {name for name, n in coverage.items() if n == 0}
        if absent:
            print(f"    no data for: {', '.join(sorted(absent))}"
                  f" — pinned to zero")

        weights, _train_loss = optimise_weights(
            train, iterations=iterations, seed=seed, verbose=False)
        weights = pin_absent_sources(weights, absent)

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
            'source_coverage': coverage,
            'sources_without_data': sorted(absent),
        }
        if improved:
            accepted[sport] = weights

    if accepted:
        print(f"\n  Accepted per-sport weights for: {', '.join(sorted(accepted))}")
    else:
        print("\n  No sport gained a reliable improvement — keeping shared weights.")
    print(f"{'=' * 72}\n")

    return accepted, report


def _engine_with_temperature(sport: str, temperature: float
                             ) -> FootballScoringEngine:
    engine = FootballScoringEngine()
    engine.sport_temperatures = {sport: temperature}
    return engine


def _loss_at_temperature(rows: List[Dict[str, Any]], sport: str,
                         temperature: float) -> Tuple[float, float]:
    """Mean log-loss and Brier for *sport* at this temperature."""
    engine = _engine_with_temperature(sport, temperature)
    ll = br = 0.0
    n = 0
    for row in rows:
        probs, _ev, _odds = _score_row(row, engine)
        actual = row['actual_result']
        ll += log_loss(probs, actual)
        br += brier(probs, actual)
        n += 1
    if not n:
        return float('inf'), float('inf')
    return ll / n, br / n


def fit_temperature(train: List[Dict[str, Any]], sport: str,
                    grid: Optional[List[float]] = None) -> Tuple[float, float]:
    """Find the temperature minimising log-loss on *train*.

    A single parameter per sport, fitted by scanning a grid — the standard
    temperature-scaling recipe. One parameter cannot overfit the way ten weights
    can, which is why this is the safer half of calibration.

    Returns ``(temperature, train_log_loss)``.
    """
    if grid is None:
        # Wide enough that the optimum is interior rather than at an edge. The
        # first run settled on 0.60 for football and basketball, which was the
        # old lower bound — a boundary answer means the search was cut short,
        # not that the data preferred the edge.
        grid = [round(0.30 + 0.05 * i, 2)
                for i in range(int((3.0 - 0.30) / 0.05) + 1)]

    best_t, best_ll = 1.0, float('inf')
    for t in grid:
        ll, _brier = _loss_at_temperature(train, sport, t)
        if ll < best_ll:
            best_t, best_ll = t, ll
    return best_t, best_ll


def optimise_temperature(rows: List[Dict[str, Any]], *, seed: int,
                         test_frac: float, min_rows: int,
                         simulated: bool = False,
                         ) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Fit one temperature per sport, keeping only those that generalise.

    Accepted only when BOTH log-loss and Brier improve on that sport's held-out
    rows, the same bar the weight calibration has to clear. Sports scored by a
    different engine (tennis, table tennis) are skipped: their probabilities do
    not pass through this temperature.
    """
    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        sport = (row.get('sport') or 'football').lower()
        if sport in ('tennis', 'table_tennis'):
            continue
        by_sport.setdefault(sport, []).append(row)

    accepted: Dict[str, float] = {}
    report: Dict[str, Any] = {}

    print(f"\n{'=' * 72}")
    print('  PROBABILITY CALIBRATION (temperature per sport)')
    print(f"{'=' * 72}")

    if simulated:
        print('  Refusing to fit on SIMULATED data.')
        return {}, {'status': 'simulated'}

    for sport, sport_rows in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        if len(sport_rows) < min_rows:
            print(f'  {sport:<13} {len(sport_rows):>5} rows — skipped '
                  f'(need {min_rows})')
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

        current = FootballScoringEngine().temperature_for_sport(sport)
        fitted, _train_ll = fit_temperature(train, sport)

        before_ll, before_br = _loss_at_temperature(test, sport, current)
        after_ll, after_br = _loss_at_temperature(test, sport, fitted)
        improved = after_ll < before_ll and after_br <= before_br

        print(f'\n  {sport} — {len(train)} train / {len(test)} test')
        print(f'    obecna T={current:<5} : ll {before_ll:.4f}  brier {before_br:.4f}')
        print(f'    dopasowana T={fitted:<5}: ll {after_ll:.4f}  brier {after_br:.4f}'
              f'   -> {"ACCEPTED" if improved else "rejected"}')

        report[sport] = {
            'n_rows': len(sport_rows),
            'status': 'accepted' if improved else 'rejected',
            'temperature_current': current,
            'temperature_fitted': fitted,
            'test_log_loss_before': round(before_ll, 5),
            'test_log_loss_after': round(after_ll, 5),
            'test_brier_before': round(before_br, 5),
            'test_brier_after': round(after_br, 5),
        }
        if improved:
            accepted[sport] = fitted

    if accepted:
        print('\n  Accepted temperatures: '
              + ', '.join(f'{s}={t}' for s, t in sorted(accepted.items())))
    else:
        print('\n  No sport improved — keeping the profile temperatures.')
    print(f"{'=' * 72}\n")
    return accepted, report


def _reliability_with(rows: List[Dict[str, Any]],
                      temperatures: Optional[Dict[str, float]] = None,
                      ) -> Dict[str, Any]:
    """Evaluate *rows*, optionally forcing fitted temperatures.

    Without the override the 'after' table is built by an engine reading the
    calibration file, which has not been written yet — so it silently reports
    the 'before' numbers under an 'after' heading.
    """
    engine = FootballScoringEngine()
    if temperatures:
        engine.sport_temperatures = dict(temperatures)

    model = Evaluation('model')
    value_bets = 0
    for row in rows:
        probs, ev, odds = _score_row(row, engine)
        model.add(probs, row['actual_result'], ev=ev, odds=odds)
        if ev is not None and ev > 0 and odds:
            value_bets += 1
    summary = model.summary()
    return {'reliability': model.reliability(), 'model': summary,
            'value_bets': value_bets}


def _print_reliability_shift(rows: List[Dict[str, Any]],
                             temperatures: Dict[str, float]) -> None:
    """Show whether a stated probability became more believable."""
    before = _reliability_with(rows, None)
    after = _reliability_with(rows, temperatures)

    print('  RZETELNOŚĆ — czy obiecane % odpowiada zaobserwowanym')
    print(f"    {'przedział':<12} {'n':>5}  {'obiecane':>9} "
          f"{'obserw.':>8} {'luka przed':>11} {'luka po':>9}")
    b_by_range = {b['range']: b for b in before['reliability']}
    for band in after['reliability']:
        b = b_by_range.get(band['range'])
        gap_after = band['observed'] - band['predicted']
        gap_before = (b['observed'] - b['predicted']) if b else float('nan')
        print(f"    {band['range']:<12} {band['n']:>5}  "
              f"{band['predicted']:>9.3f} {band['observed']:>8.3f} "
              f"{gap_before:>+11.3f} {gap_after:>+9.3f}")

    mae_before = _mean_abs_gap(before['reliability'])
    mae_after = _mean_abs_gap(after['reliability'])
    print(f"    średnia |luka|: {mae_before:.3f} -> {mae_after:.3f}")
    print(f"    brier: {before['model']['brier']:.4f} -> "
          f"{after['model']['brier']:.4f}")
    print(f"    log-loss: {before['model']['log_loss']:.4f} -> "
          f"{after['model']['log_loss']:.4f}")
    # A value screen that fires on almost everything is not a screen. Before
    # calibration it flagged 244 of 293 priced games.
    print(f"    typy z EV>0: {before['value_bets']} -> {after['value_bets']}"
          f" (z {sum(1 for r in rows if market_probs(r))} wycenionych)")


def _mean_abs_gap(bands: List[Dict[str, Any]]) -> float:
    gaps = [abs(b['observed'] - b['predicted']) * b['n'] for b in bands]
    total = sum(b['n'] for b in bands)
    return (sum(gaps) / total) if total else float('nan')


def _engine_with_curve(sport: str, curve) -> FootballScoringEngine:
    engine = FootballScoringEngine()
    engine.sport_isotonic = {sport: curve} if curve else {}
    return engine


def _metrics_with_curve(rows: List[Dict[str, Any]], sport: str, curve,
                        ) -> Dict[str, float]:
    """Log-loss, Brier, mean reliability gap and positive-EV count."""
    engine = _engine_with_curve(sport, curve)
    model = Evaluation('model')
    value_bets = priced = 0
    for row in rows:
        probs, ev, odds = _score_row(row, engine)
        model.add(probs, row['actual_result'], ev=ev, odds=odds)
        if odds:
            priced += 1
            if ev is not None and ev > 0:
                value_bets += 1
    summary = model.summary()
    return {
        'log_loss': summary['log_loss'],
        'brier': summary['brier'],
        'gap': _mean_abs_gap(model.reliability()),
        'value_bets': value_bets,
        'priced': priced,
    }


def optimise_isotonic(rows: List[Dict[str, Any]], *, seed: int,
                      test_frac: float, min_rows: int,
                      simulated: bool = False,
                      ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fit a reliability curve per sport, keeping only those that generalise.

    Accepted only when log-loss, Brier AND the mean reliability gap all improve
    on held-out rows. The gap is the one that matters for betting: it says
    whether a stated 70% really wins 70% of the time, which is the number the
    EV calculation is built on.
    """
    from probability_calibration import fit_isotonic

    by_sport: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        sport = (row.get('sport') or 'football').lower()
        if sport in ('tennis', 'table_tennis'):
            continue                      # scored by the two-outcome engine
        by_sport.setdefault(sport, []).append(row)

    accepted: Dict[str, Any] = {}
    report: Dict[str, Any] = {}

    print(f"\n{'=' * 72}")
    print('  RELIABILITY CURVES (isotonic, per sport)')
    print(f"{'=' * 72}")

    if simulated:
        print('  Refusing to fit on SIMULATED data.')
        return {}, {'status': 'simulated'}

    for sport, sport_rows in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        if len(sport_rows) < min_rows:
            print(f'  {sport:<13} {len(sport_rows):>5} rows — skipped '
                  f'(need {min_rows})')
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

        # Learn from what the engine claims on the training rows.
        engine = FootballScoringEngine()
        pairs = []
        for row in train:
            probs, _ev, _odds = _score_row(row, engine)
            lead = max(range(len(probs)), key=lambda i: probs[i])
            won = OUTCOMES[lead] == row['actual_result']
            pairs.append((probs[lead], 1.0 if won else 0.0))

        curve = fit_isotonic(pairs)
        if not curve:
            print(f'  {sport:<13} zbyt mało danych na krzywą')
            report[sport] = {'n_rows': len(sport_rows), 'status': 'no_curve'}
            continue

        before = _metrics_with_curve(test, sport, None)
        after = _metrics_with_curve(test, sport, curve)
        improved = (after['log_loss'] < before['log_loss']
                    and after['brier'] <= before['brier']
                    and after['gap'] <= before['gap'])

        print(f'\n  {sport} — {len(train)} train / {len(test)} test, '
              f'{len(curve)} przedziałów')
        print(f"    przed : ll {before['log_loss']:.4f}  brier {before['brier']:.4f}"
              f"  luka {before['gap']:.3f}  EV>0 {before['value_bets']}/{before['priced']}")
        print(f"    po    : ll {after['log_loss']:.4f}  brier {after['brier']:.4f}"
              f"  luka {after['gap']:.3f}  EV>0 {after['value_bets']}/{after['priced']}"
              f"   -> {'ACCEPTED' if improved else 'rejected'}")

        report[sport] = {
            'n_rows': len(sport_rows),
            'status': 'accepted' if improved else 'rejected',
            'bins': len(curve),
            'test_before': before,
            'test_after': after,
        }
        if improved:
            accepted[sport] = [[x, y] for x, y in curve]

    if accepted:
        print('\n  Accepted curves: ' + ', '.join(sorted(accepted)))
    else:
        print('\n  No sport improved on held-out data — nothing saved.')
    print(f"{'=' * 72}\n")
    return accepted, report


def _save_isotonic(curves: Dict[str, Any], report: Dict[str, Any]) -> None:
    path = FootballScoringEngine.CALIBRATION_PATH
    existing: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    existing['isotonic'] = {**existing.get('isotonic', {}), **curves}
    existing['isotonic_metrics'] = report
    from datetime import datetime
    existing['calibrated_at'] = datetime.now().isoformat()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(existing, fh, indent=2)
    print(f'  Saved reliability curves to {path}')


def _save_temperatures(temperatures: Dict[str, float],
                       report: Dict[str, Any]) -> None:
    """Merge fitted temperatures into the calibration file."""
    path = FootballScoringEngine.CALIBRATION_PATH
    existing: Dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    existing['temperatures'] = {**existing.get('temperatures', {}), **temperatures}
    existing['temperature_metrics'] = report
    from datetime import datetime
    existing['calibrated_at'] = datetime.now().isoformat()

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(existing, fh, indent=2)
    print(f'  Saved temperatures to {path}')


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
