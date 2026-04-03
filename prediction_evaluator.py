#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prediction Evaluator — Unified backtesting & accuracy measurement
=================================================================

Loads historical prediction data (results/ JSON + mailed manifests),
matches predictions with actual results from livesport, and computes
comprehensive metrics per sport, per confidence bucket, per source.

Metrics computed:
  - Accuracy, Precision, Recall (win/loss/draw)
  - Brier score (probability calibration)
  - ROI & Yield (flat stake)
  - Confidence calibration (predicted vs actual per bucket)
  - Per-source agreement rates
  - Per-sport breakdown

Usage:
  python prediction_evaluator.py --days 30
  python prediction_evaluator.py --all --export report.json
  python prediction_evaluator.py --date 2026-04-01
"""

import argparse
import glob
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    from result_store import ResultStore
    _result_store_ok = True
except ImportError:
    _result_store_ok = False


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EvalMatch:
    """A single prediction+result pair for evaluation."""
    match_id: str
    date: str
    sport: str
    home_team: str
    away_team: str
    match_url: str

    # Prediction side
    qualifies: bool
    focus_team: str  # 'home' or 'away'
    predicted_winner: str  # 'home' or 'away'
    confidence: float  # 0-100
    scoring_pick: Optional[str] = None
    scoring_prob: Optional[float] = None
    scoring_ev: Optional[float] = None
    scoring_edge: Optional[float] = None
    scoring_data_quality: Optional[float] = None

    # Odds
    home_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    away_odds: Optional[float] = None

    # Source predictions
    forebet_prediction: Optional[str] = None
    forebet_probability: Optional[float] = None
    sofascore_home: Optional[float] = None
    sofascore_away: Optional[float] = None
    gemini_recommendation: Optional[str] = None

    # Result side
    actual_winner: Optional[str] = None  # 'home', 'away', 'draw', None
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    is_settled: bool = False

    # Derived
    outcome: str = 'pending'  # 'won', 'lost', 'draw', 'pending'

    @property
    def predicted_odds(self) -> Optional[float]:
        if self.predicted_winner == 'home' and self.home_odds:
            return self.home_odds
        if self.predicted_winner == 'away' and self.away_odds:
            return self.away_odds
        return None

    @property
    def implied_prob(self) -> Optional[float]:
        odds = self.predicted_odds
        if odds and odds > 1.0:
            return 1.0 / odds
        return None


@dataclass
class SportMetrics:
    """Aggregated metrics for a sport or bucket."""
    label: str
    total: int = 0
    settled: int = 0
    won: int = 0
    lost: int = 0
    draws: int = 0
    pending: int = 0

    total_staked: float = 0.0
    total_profit: float = 0.0

    # Brier score components
    brier_sum: float = 0.0
    brier_count: int = 0

    # Confidence calibration
    conf_buckets: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # Source agreement
    source_agreement: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        decided = self.won + self.lost
        return (self.won / decided * 100) if decided > 0 else 0.0

    @property
    def win_rate(self) -> float:
        return (self.won / self.settled * 100) if self.settled > 0 else 0.0

    @property
    def roi_pct(self) -> float:
        return (self.total_profit / self.total_staked * 100) if self.total_staked > 0 else 0.0

    @property
    def yield_pct(self) -> float:
        decided = self.won + self.lost
        return (self.total_profit / (decided * 100) * 100) if decided > 0 else 0.0

    @property
    def brier_score(self) -> float:
        return (self.brier_sum / self.brier_count) if self.brier_count > 0 else 1.0

    @property
    def avg_odds(self) -> float:
        if self.won + self.lost == 0:
            return 0.0
        return self.total_staked / (self.won + self.lost) if (self.won + self.lost) > 0 else 0.0

    def to_dict(self) -> Dict:
        return {
            'label': self.label,
            'total': self.total,
            'settled': self.settled,
            'won': self.won,
            'lost': self.lost,
            'draws': self.draws,
            'pending': self.pending,
            'accuracy': round(self.accuracy, 2),
            'win_rate': round(self.win_rate, 2),
            'roi_pct': round(self.roi_pct, 2),
            'yield_pct': round(self.yield_pct, 2),
            'brier_score': round(self.brier_score, 4),
            'total_profit': round(self.total_profit, 2),
            'confidence_calibration': self.conf_buckets,
            'source_agreement': self.source_agreement,
        }


# ═══════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outputs')

SPORT_LIST = ['football', 'tennis', 'basketball', 'handball', 'volleyball', 'hockey']


def _load_results_json(date: str) -> Dict[str, List[Dict]]:
    """Load all results/matches_{date}_{sport}.json for a date.
    Returns {sport: [match_dict, ...]}."""
    out: Dict[str, List[Dict]] = {}
    for sport in SPORT_LIST:
        path = os.path.join(RESULTS_DIR, f'matches_{date}_{sport}.json')
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            matches = data.get('matches', [])
            if matches:
                out[sport] = matches
        except (json.JSONDecodeError, OSError):
            pass
    return out


def _load_manifest(date: str) -> List[Dict]:
    """Load mailed manifests for a date (from outputs/)."""
    pattern = os.path.join(OUTPUTS_DIR, f'mailed_manifest_{date}*.json')
    files = sorted(glob.glob(pattern))
    all_matches: List[Dict] = []
    seen: set = set()
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for m in data:
                url = m.get('match_url', '')
                if url and url not in seen:
                    all_matches.append(m)
                    seen.add(url)
        except (json.JSONDecodeError, OSError):
            pass
    return all_matches


def _get_available_dates(days: Optional[int] = None, start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> List[str]:
    """Return sorted list of dates with data in results/ directory."""
    dates: set = set()
    for fname in os.listdir(RESULTS_DIR) if os.path.isdir(RESULTS_DIR) else []:
        if fname.startswith('matches_') and fname.endswith('.json'):
            parts = fname.replace('matches_', '').split('_')
            if parts:
                dates.add(parts[0])

    sorted_dates = sorted(dates)

    if start_date:
        sorted_dates = [d for d in sorted_dates if d >= start_date]
    if end_date:
        sorted_dates = [d for d in sorted_dates if d <= end_date]
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        sorted_dates = [d for d in sorted_dates if d >= cutoff]

    return sorted_dates


def _determine_winner(match: Dict) -> Optional[str]:
    """Try to determine actual winner from a results/matches_*.json entry.
    Uses matchUrl to scrape or infer from stored data. For now, returns None
    (actual result checking requires Selenium — done via check_results.py).
    This function reads from results_summary files if available."""
    return None


def _predicted_winner_from_match(match: Dict, sport: str) -> str:
    """Determine who our pipeline predicted to win from a match dict."""
    if sport == 'tennis':
        scoring = match.get('scoring') or {}
        pick = scoring.get('pick', '')
        if pick:
            return 'home' if '1' in str(pick) or 'A' in str(pick).upper() else 'away'
        return 'home'

    focus = (match.get('focusTeam') or match.get('focus_team') or 'home').lower()
    return focus


def _extract_eval_match(match: Dict, sport: str, date: str) -> EvalMatch:
    """Convert a results/matches_*.json match dict into EvalMatch."""
    scoring = match.get('scoring') or {}
    odds = match.get('odds') or {}
    forebet = match.get('forebet') or {}
    sofascore = match.get('sofascore') or {}

    predicted = _predicted_winner_from_match(match, sport)
    confidence = match.get('confidence', 0) or 0

    return EvalMatch(
        match_id=str(match.get('id', '')),
        date=date,
        sport=sport,
        home_team=match.get('homeTeam', ''),
        away_team=match.get('awayTeam', ''),
        match_url=match.get('matchUrl', ''),
        qualifies=bool(match.get('qualifies', False)),
        focus_team=(match.get('focusTeam') or match.get('focus_team') or 'home').lower(),
        predicted_winner=predicted,
        confidence=float(confidence),
        scoring_pick=scoring.get('pick'),
        scoring_prob=_safe_float(scoring.get('prob')),
        scoring_ev=_safe_float(scoring.get('ev')),
        scoring_edge=_safe_float(scoring.get('edge')),
        scoring_data_quality=_safe_float(scoring.get('dataQuality')),
        home_odds=_safe_float(odds.get('home')),
        draw_odds=_safe_float(odds.get('draw')),
        away_odds=_safe_float(odds.get('away')),
        forebet_prediction=forebet.get('prediction'),
        forebet_probability=_safe_float(forebet.get('probability')),
        sofascore_home=_safe_float(sofascore.get('home')),
        sofascore_away=_safe_float(sofascore.get('away')),
        gemini_recommendation=None,  # Not stored in results JSON
    )


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
# RESULT MATCHING
# ═══════════════════════════════════════════════════════════════════════════

def load_result_summaries() -> Dict[str, Dict[str, Any]]:
    """Load all results_summary_*.json files.
    Returns {date: summary_dict}."""
    summaries: Dict[str, Dict] = {}
    pattern = os.path.join(OUTPUTS_DIR, 'results_summary_*.json')
    for fpath in glob.glob(pattern):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            date = data.get('date', '')
            if date:
                summaries[date] = data
        except (json.JSONDecodeError, OSError):
            pass
    return summaries


def _match_results_from_summary(
    eval_matches: List[EvalMatch],
    summary: Dict[str, Any]
) -> int:
    """Enrich EvalMatch list with actual results from a results_summary.
    Returns number of matches updated."""
    summary_details = summary.get('matches', [])
    # Build lookup by (home, away) for matching
    lookup: Dict[Tuple[str, str], Dict] = {}
    for detail in summary_details:
        key = (detail.get('home', '').strip().lower(),
               detail.get('away', '').strip().lower())
        lookup[key] = detail

    updated = 0
    for em in eval_matches:
        if em.is_settled:
            continue
        key = (em.home_team.strip().lower(), em.away_team.strip().lower())
        detail = lookup.get(key)
        if detail and detail.get('outcome') in ('won', 'lost', 'draw'):
            outcome = detail['outcome']
            em.outcome = outcome
            em.is_settled = True

            score_str = detail.get('score', '')
            if score_str and '-' in score_str:
                parts = score_str.split('-')
                try:
                    em.score_home = int(parts[0].strip())
                    em.score_away = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            if outcome == 'won':
                em.actual_winner = em.predicted_winner
            elif outcome == 'lost':
                em.actual_winner = 'away' if em.predicted_winner == 'home' else 'home'
            elif outcome == 'draw':
                em.actual_winner = 'draw'

            updated += 1

    return updated


# ═══════════════════════════════════════════════════════════════════════════
# METRICS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════

CONF_BUCKET_EDGES = [0, 50, 60, 70, 80, 90, 100]
STAKE = 100.0  # Flat stake for ROI calculation


def _conf_bucket_label(conf: float) -> str:
    for i in range(len(CONF_BUCKET_EDGES) - 1):
        lo = CONF_BUCKET_EDGES[i]
        hi = CONF_BUCKET_EDGES[i + 1]
        if lo <= conf < hi:
            return f'{lo}-{hi}'
    return f'{CONF_BUCKET_EDGES[-2]}-{CONF_BUCKET_EDGES[-1]}'


def compute_metrics(
    matches: List[EvalMatch],
    label: str = 'all',
    only_qualifying: bool = True
) -> SportMetrics:
    """Compute full metrics for a set of matches."""
    m = SportMetrics(label=label)

    for em in matches:
        if only_qualifying and not em.qualifies:
            continue

        m.total += 1

        if not em.is_settled:
            m.pending += 1
            continue

        m.settled += 1

        if em.outcome == 'won':
            m.won += 1
        elif em.outcome == 'lost':
            m.lost += 1
        elif em.outcome == 'draw':
            m.draws += 1

        # ROI
        odds = em.predicted_odds
        if odds and odds > 1.0:
            m.total_staked += STAKE
            if em.outcome == 'won':
                m.total_profit += STAKE * (odds - 1)
            elif em.outcome in ('lost', 'draw'):
                m.total_profit -= STAKE

        # Brier score
        if em.scoring_prob is not None and em.is_settled:
            prob = em.scoring_prob / 100.0  # Convert from 0-100 to 0-1
            actual = 1.0 if em.outcome == 'won' else 0.0
            m.brier_sum += (prob - actual) ** 2
            m.brier_count += 1

        # Confidence calibration buckets
        bucket = _conf_bucket_label(em.confidence)
        if bucket not in m.conf_buckets:
            m.conf_buckets[bucket] = {'count': 0, 'won': 0, 'avg_conf': 0.0,
                                       'conf_sum': 0.0}
        b = m.conf_buckets[bucket]
        b['count'] += 1
        b['conf_sum'] += em.confidence
        if em.outcome == 'won':
            b['won'] += 1

        # Source agreement tracking
        _track_source_agreement(em, m)

    # Finalize confidence calibration
    for bucket, b in m.conf_buckets.items():
        b['avg_conf'] = round(b['conf_sum'] / b['count'], 1) if b['count'] > 0 else 0
        b['actual_accuracy'] = round(b['won'] / b['count'] * 100, 1) if b['count'] > 0 else 0
        b['gap'] = round(b['actual_accuracy'] - b['avg_conf'], 1)
        del b['conf_sum']

    return m


def _track_source_agreement(em: EvalMatch, metrics: SportMetrics):
    """Track how often each source agreed with the final pick and was correct."""
    sources = {}

    # Forebet
    if em.forebet_prediction:
        fp = str(em.forebet_prediction)
        predicted_code = '1' if em.predicted_winner == 'home' else '2'
        agrees = fp == predicted_code
        sources['forebet'] = agrees

    # SofaScore
    if em.sofascore_home is not None and em.sofascore_away is not None:
        ss_pred = 'home' if em.sofascore_home > em.sofascore_away else 'away'
        agrees = ss_pred == em.predicted_winner
        sources['sofascore'] = agrees

    # Gemini
    if em.gemini_recommendation:
        agrees = em.gemini_recommendation in ('HIGH', 'LOCK')
        sources['gemini'] = agrees

    for source, agrees in sources.items():
        if source not in metrics.source_agreement:
            metrics.source_agreement[source] = {
                'total': 0, 'agrees': 0, 'agrees_and_correct': 0,
                'disagrees_and_correct': 0
            }
        sa = metrics.source_agreement[source]
        sa['total'] += 1
        if agrees:
            sa['agrees'] += 1
            if em.outcome == 'won':
                sa['agrees_and_correct'] += 1
        else:
            if em.outcome == 'won':
                sa['disagrees_and_correct'] += 1


# ═══════════════════════════════════════════════════════════════════════════
# MAIN EVALUATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

class PredictionEvaluator:
    """Main evaluator class — loads data, matches results, computes metrics."""

    def __init__(self, results_dir: str = RESULTS_DIR, outputs_dir: str = OUTPUTS_DIR):
        self.results_dir = results_dir
        self.outputs_dir = outputs_dir
        self.all_matches: List[EvalMatch] = []
        self.dates_loaded: List[str] = []

    def load(self, days: Optional[int] = None, start_date: Optional[str] = None,
             end_date: Optional[str] = None, single_date: Optional[str] = None) -> int:
        """Load prediction data from results/ JSON files.
        Returns total number of EvalMatch objects loaded."""
        if single_date:
            dates = [single_date]
        else:
            dates = _get_available_dates(days=days, start_date=start_date, end_date=end_date)

        self.dates_loaded = dates
        self.all_matches = []

        for date in dates:
            sports_data = _load_results_json(date)
            for sport, matches in sports_data.items():
                for match in matches:
                    em = _extract_eval_match(match, sport, date)
                    self.all_matches.append(em)

        return len(self.all_matches)

    def match_results(self) -> int:
        """Try to match predictions with actual results.
        Uses result_store first, then results_summary files."""
        total_updated = 0

        # 1. Result store (persistent, accumulated)
        if _result_store_ok:
            store = ResultStore()
            finished = store.get_all_finished()
            for em in self.all_matches:
                if em.is_settled or not em.match_url:
                    continue
                result = finished.get(em.match_url)
                if result:
                    winner = result.get('winner')
                    if winner in ('home', 'away', 'draw'):
                        em.actual_winner = winner
                        em.score_home = result.get('score_home')
                        em.score_away = result.get('score_away')
                        em.is_settled = True
                        if winner == 'draw':
                            em.outcome = 'draw'
                        elif winner == em.predicted_winner:
                            em.outcome = 'won'
                        else:
                            em.outcome = 'lost'
                        total_updated += 1

        # 2. Results summary files (from check_results.py)
        summaries = load_result_summaries()
        for date in self.dates_loaded:
            if date in summaries:
                date_matches = [m for m in self.all_matches if m.date == date]
                updated = _match_results_from_summary(date_matches, summaries[date])
                total_updated += updated

        return total_updated

    def get_matches(self, sport: Optional[str] = None,
                    only_qualifying: bool = True,
                    only_settled: bool = False,
                    min_confidence: float = 0.0) -> List[EvalMatch]:
        """Filter matches by criteria."""
        result = self.all_matches
        if sport:
            result = [m for m in result if m.sport == sport]
        if only_qualifying:
            result = [m for m in result if m.qualifies]
        if only_settled:
            result = [m for m in result if m.is_settled]
        if min_confidence > 0:
            result = [m for m in result if m.confidence >= min_confidence]
        return result

    def evaluate(self, sport: Optional[str] = None,
                 only_qualifying: bool = True) -> Dict[str, SportMetrics]:
        """Run full evaluation, returns metrics dict.

        Keys: 'overall', per sport name, per confidence bucket.
        """
        results: Dict[str, SportMetrics] = {}

        # Overall
        matches = self.get_matches(sport=sport, only_qualifying=only_qualifying)
        results['overall'] = compute_metrics(matches, 'overall', only_qualifying=False)

        # Per sport
        sports_seen = set(m.sport for m in matches)
        for s in sorted(sports_seen):
            sport_matches = [m for m in matches if m.sport == s]
            results[f'sport_{s}'] = compute_metrics(sport_matches, s, only_qualifying=False)

        # Per confidence bucket
        for i in range(len(CONF_BUCKET_EDGES) - 1):
            lo = CONF_BUCKET_EDGES[i]
            hi = CONF_BUCKET_EDGES[i + 1]
            label = f'conf_{lo}_{hi}'
            bucket_matches = [m for m in matches if lo <= m.confidence < hi]
            if bucket_matches:
                results[label] = compute_metrics(bucket_matches, label, only_qualifying=False)

        return results

    def summary_stats(self, sport: Optional[str] = None) -> Dict[str, Any]:
        """Quick summary without full metrics breakdown."""
        matches = self.get_matches(sport=sport, only_qualifying=True)
        total = len(matches)
        settled = sum(1 for m in matches if m.is_settled)
        won = sum(1 for m in matches if m.outcome == 'won')
        lost = sum(1 for m in matches if m.outcome == 'lost')
        draws = sum(1 for m in matches if m.outcome == 'draw')
        decided = won + lost
        accuracy = (won / decided * 100) if decided > 0 else 0.0

        return {
            'dates_range': f'{self.dates_loaded[0]} → {self.dates_loaded[-1]}' if self.dates_loaded else 'none',
            'dates_count': len(self.dates_loaded),
            'total_matches_loaded': len(self.all_matches),
            'qualifying': total,
            'settled': settled,
            'won': won,
            'lost': lost,
            'draws': draws,
            'pending': total - settled,
            'accuracy': round(accuracy, 2),
        }

    def export_report(self, path: str, sport: Optional[str] = None) -> str:
        """Export full evaluation report as JSON."""
        metrics = self.evaluate(sport=sport)
        report = {
            'generated_at': datetime.now().isoformat(),
            'dates_range': f'{self.dates_loaded[0]} → {self.dates_loaded[-1]}' if self.dates_loaded else 'none',
            'dates_count': len(self.dates_loaded),
            'total_loaded': len(self.all_matches),
            'metrics': {k: v.to_dict() for k, v in metrics.items()},
        }

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return path


# ═══════════════════════════════════════════════════════════════════════════
# WEIGHT OPTIMIZER (grid search on historical data)
# ═══════════════════════════════════════════════════════════════════════════

def optimize_weights_grid(
    evaluator: PredictionEvaluator,
    sport: str,
    weight_keys: List[str],
    engine_class: str = 'football',
    resolution: float = 0.05,
    metric: str = 'accuracy',
) -> Dict[str, Any]:
    """Run a grid search over weight combinations to find optimal weights.

    This re-scores each match with different weights and evaluates.
    Returns best weights, baseline metrics, and improved metrics.

    NOTE: This requires re-scoring which is expensive. For now it returns
    the framework — actual re-scoring integration will come in Phase 2
    when we wire up the scoring engines.
    """
    matches = evaluator.get_matches(sport=sport, only_qualifying=True, only_settled=True)

    if len(matches) < 20:
        return {
            'status': 'insufficient_data',
            'settled_count': len(matches),
            'min_required': 20,
        }

    # Baseline
    baseline = compute_metrics(matches, f'{sport}_baseline', only_qualifying=False)

    return {
        'status': 'ready',
        'sport': sport,
        'settled_count': len(matches),
        'baseline': baseline.to_dict(),
        'message': 'Grid search ready — wire up scoring engine re-scoring in Phase 2',
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRETTY PRINTER
# ═══════════════════════════════════════════════════════════════════════════

SPORT_EMOJI = {
    'football': '⚽', 'basketball': '🏀', 'handball': '🤾',
    'volleyball': '🏐', 'tennis': '🎾', 'hockey': '🏒',
}


def print_report(evaluator: PredictionEvaluator, sport: Optional[str] = None):
    """Print a formatted evaluation report to stdout."""
    summary = evaluator.summary_stats(sport=sport)
    metrics = evaluator.evaluate(sport=sport)

    print()
    print('=' * 70)
    print('  📊 PREDICTION EVALUATOR — BACKTEST REPORT')
    print('=' * 70)
    print(f"  Period: {summary['dates_range']}  ({summary['dates_count']} days)")
    print(f"  Total matches loaded: {summary['total_matches_loaded']}")
    print(f"  Qualifying: {summary['qualifying']}")
    print(f"  Settled: {summary['settled']}  |  Pending: {summary['pending']}")
    print()

    overall = metrics.get('overall')
    if overall and overall.settled > 0:
        print('─' * 70)
        print(f"  🎯 OVERALL  (settled: {overall.settled})")
        print(f"     Accuracy:  {overall.accuracy:.1f}%  ({overall.won}W / {overall.lost}L / {overall.draws}D)")
        print(f"     ROI:       {overall.roi_pct:+.1f}%  (profit: {overall.total_profit:+.0f} PLN)")
        print(f"     Brier:     {overall.brier_score:.4f}")
        print()

    # Per sport
    print('─' * 70)
    print('  📋 PER SPORT')
    print(f"  {'Sport':<14} {'Settled':>8} {'Won':>5} {'Lost':>5} {'Draw':>5} {'Acc%':>7} {'ROI%':>7} {'Brier':>7}")
    print('  ' + '─' * 62)

    for key, sm in sorted(metrics.items()):
        if not key.startswith('sport_'):
            continue
        sport_name = key.replace('sport_', '')
        emoji = SPORT_EMOJI.get(sport_name, '🏆')
        if sm.settled == 0:
            continue
        print(f"  {emoji} {sport_name:<11} {sm.settled:>8} {sm.won:>5} {sm.lost:>5} "
              f"{sm.draws:>5} {sm.accuracy:>6.1f}% {sm.roi_pct:>+6.1f}% {sm.brier_score:>7.4f}")

    print()

    # Confidence calibration
    if overall and overall.conf_buckets:
        print('─' * 70)
        print('  📈 CONFIDENCE CALIBRATION')
        print(f"  {'Bucket':<12} {'Count':>6} {'Won':>5} {'Actual%':>8} {'AvgConf':>8} {'Gap':>7}")
        print('  ' + '─' * 50)
        for bucket in sorted(overall.conf_buckets.keys()):
            b = overall.conf_buckets[bucket]
            count = b['count']
            won = b['won']
            actual = b['actual_accuracy']
            avg_conf = b['avg_conf']
            gap = b['gap']
            gap_icon = '✅' if abs(gap) < 10 else '⚠️' if abs(gap) < 20 else '❌'
            print(f"  {bucket:<12} {count:>6} {won:>5} {actual:>7.1f}% {avg_conf:>7.1f}% {gap:>+6.1f} {gap_icon}")
        print()

    # Source agreement
    if overall and overall.source_agreement:
        print('─' * 70)
        print('  🔗 SOURCE AGREEMENT')
        print(f"  {'Source':<14} {'Total':>6} {'Agrees':>7} {'AgreeRate':>9} {'AgreeCorr':>10} {'DisCorr':>8}")
        print('  ' + '─' * 56)
        for source, sa in sorted(overall.source_agreement.items()):
            agree_rate = (sa['agrees'] / sa['total'] * 100) if sa['total'] > 0 else 0
            print(f"  {source:<14} {sa['total']:>6} {sa['agrees']:>7} {agree_rate:>8.1f}% "
                  f"{sa['agrees_and_correct']:>10} {sa['disagrees_and_correct']:>8}")
        print()

    print('=' * 70)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='📊 Prediction Evaluator — Backtest & Accuracy Report')
    parser.add_argument('--days', type=int, help='Analyze last N days')
    parser.add_argument('--all', action='store_true', help='Analyze all available data')
    parser.add_argument('--date', help='Analyze specific date (YYYY-MM-DD)')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--sport', help='Filter by sport (football, tennis, ...)')
    parser.add_argument('--export', help='Export report to JSON file')
    parser.add_argument('--include-all', action='store_true',
                        help='Include non-qualifying matches')

    args = parser.parse_args()

    evaluator = PredictionEvaluator()

    # Load data
    if args.date:
        count = evaluator.load(single_date=args.date)
    elif args.all:
        count = evaluator.load()
    elif args.days:
        count = evaluator.load(days=args.days)
    elif args.start or args.end:
        count = evaluator.load(start_date=args.start, end_date=args.end)
    else:
        count = evaluator.load(days=30)

    print(f'📂 Loaded {count} matches from {len(evaluator.dates_loaded)} days')

    # Match with results
    matched = evaluator.match_results()
    print(f'🔗 Matched {matched} results from summaries')

    # Print report
    print_report(evaluator, sport=args.sport)

    # Export
    if args.export:
        path = evaluator.export_report(args.export, sport=args.sport)
        print(f'📁 Report exported to {path}')


if __name__ == '__main__':
    main()
