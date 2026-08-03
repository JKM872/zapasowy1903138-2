"""
Football Scoring Engine – EV/ROI-optimised probability model
=============================================================

Multi-factor model that combines:
 1. H2H time-weighted win rate
 2. Recent form (overall + venue-specific)
 3. Home-advantage baseline
 4. Odds-implied probabilities (market consensus)
 5. External predictions (Forebet, SofaScore, Gemini AI)
 6. Quality-of-opposition adjustment

Output:  calibrated 1/X/2 probabilities → EV, edge, Kelly per outcome
Designed to run deterministically on GitHub Actions (no GPU, no network
calls at scoring time – only uses pre-scraped match data).

Usage (standalone backtest):
    python football_scoring_engine.py --file results/matches_2026-02-24.json
    python football_scoring_engine.py --backtest --days 30

Usage (programmatic):
    from football_scoring_engine import FootballScoringEngine
    engine = FootballScoringEngine()
    result = engine.score_match(match_dict)
    # result -> ScoredMatch(prob_home=0.52, prob_draw=0.24, prob_away=0.24, ...)
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScoredMatch:
    """Full output of the scoring engine for a single match."""
    home_team: str
    away_team: str
    sport: str

    # Raw probability estimates (sum to 1.0)
    prob_home: float
    prob_draw: float
    prob_away: float

    # Calibrated probabilities after isotonic/sigmoid pass
    cal_home: float = 0.0
    cal_draw: float = 0.0
    cal_away: float = 0.0

    # Best pick
    best_pick: str = ''        # '1', 'X', or '2'
    best_prob: float = 0.0
    best_odds: float = 0.0

    # Value metrics
    ev: float = 0.0            # expected value of best pick
    edge: float = 0.0          # our prob – implied prob (%)
    kelly: float = 0.0         # kelly fraction (%)
    roi_estimate: float = 0.0  # (ev / 1) as percentage

    # Confidence / quality
    confidence: float = 0.0    # 0-100
    data_quality: float = 0.0  # 0-1 (how many features were available)

    # Feature breakdown for transparency
    features: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'home_team': self.home_team,
            'away_team': self.away_team,
            'prob_1': round(self.cal_home, 4),
            'prob_X': round(self.cal_draw, 4),
            'prob_2': round(self.cal_away, 4),
            'best_pick': self.best_pick,
            'best_prob': round(self.best_prob, 4),
            'best_odds': self.best_odds,
            'ev': round(self.ev, 4),
            'edge': round(self.edge, 2),
            'kelly': round(self.kelly, 2),
            'confidence': round(self.confidence, 1),
            'data_quality': round(self.data_quality, 2),
            'features': {k: round(v, 4) if isinstance(v, float) else v
                         for k, v in self.features.items()},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_form(raw) -> List[str]:
    """Normalize form data to a list of 'W'/'D'/'L' strings."""
    if isinstance(raw, list):
        return [str(x).upper()[:1] for x in raw if str(x).upper()[:1] in ('W', 'D', 'L')]
    if isinstance(raw, str):
        raw = raw.replace('[', '').replace(']', '').replace("'", '').replace('"', '')
        return [x.strip().upper()[:1] for x in re.split(r'[,\s]+', raw)
                if x.strip().upper()[:1] in ('W', 'D', 'L')]
    return []


# How many past results the form score may look at. The 0.85 decay already
# fades old matches out (the tenth carries 0.23 of the newest), so this cap is
# only about how much history we are willing to consider at all. Module-level so
# tools/evaluate_form.py can measure one window against another instead of the
# value being an unexamined literal.
#
# Measured at 10 against the previous 6 on a held-out later window (2026-05-22
# onwards, form rebuilt from settled results only, tools/evaluate_form.py):
# lower Brier in every sport that reads form, higher in none. 6 -> 10 was
# football 0.6029 -> 0.6018, basketball 0.4511 -> 0.4440, hockey
# 0.4994 -> 0.4947, volleyball 0.4158 -> 0.4123, handball 0.4909 -> 0.4889,
# baseball 0.5371 -> 0.5245. Tennis is unchanged because TennisScoringEngine
# reads no form field at all — a gap, not a result.
#
# Baseball is the one sport where form of any length is worse than none
# (0.5245 against 0.5073), which is why the pipeline skips it; see
# FORM_EXCLUDED_SPORTS in scrape_and_notify.py.
FORM_DECAY_WINDOW = 10


def _form_points(form: List[str], decay: float = 0.85,
                 window: Optional[int] = None) -> float:
    """Time-weighted form score (3 pts W, 1 pt D, 0 pt L), newest first.
    Returns normalized value 0.0 – 1.0."""
    if not form:
        return 0.5  # neutral prior
    pts_map = {'W': 3.0, 'D': 1.0, 'L': 0.0}
    weighted_sum = 0.0
    weight_total = 0.0
    limit = FORM_DECAY_WINDOW if window is None else window
    for i, result in enumerate(form[:limit]):
        w = decay ** i
        weighted_sum += pts_map.get(result, 1.0) * w
        weight_total += 3.0 * w  # max possible
    return weighted_sum / weight_total if weight_total > 0 else 0.5


def _h2h_win_rate_weighted(h2h: List[Dict], team_name: str, decay: float = 0.90) -> Tuple[float, int]:
    """Time-weighted H2H win rate for *team_name* across matches.
    Returns (weighted_rate, count).  Matches are assumed sorted newest-first."""
    if not h2h or not team_name:
        return 0.5, 0

    team_lower = team_name.lower().strip()
    w_sum = 0.0
    w_total = 0.0
    counted = 0

    for i, item in enumerate(h2h):
        score = item.get('score', '')
        sm = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score)
        if not sm:
            continue
        gh = int(sm.group(1))
        ga = int(sm.group(2))
        h_home = item.get('home', '').lower().strip()
        h_away = item.get('away', '').lower().strip()

        weight = decay ** i

        if gh > ga:
            winner = h_home
        elif ga > gh:
            winner = h_away
        else:
            winner = None

        if winner is None:
            pts = 0.5  # draw counts as 0.5
        elif team_lower in winner or winner in team_lower:
            pts = 1.0
        else:
            pts = 0.0

        w_sum += pts * weight
        w_total += weight
        counted += 1

    if w_total == 0:
        return 0.5, 0
    return w_sum / w_total, counted


# ---------------------------------------------------------------------------
# NEW: Advanced helpers for v2 engine
# ---------------------------------------------------------------------------

def _form_momentum(form: List[str]) -> float:
    """Detect winning/losing streak momentum.
    
    Returns value in [-1, 1]:
    +1.0  = current win streak ≥ 3
    +0.6  = current win streak 2
    +0.3  = last match win, no streak
     0.0  = mixed / draw
    -0.3  = last match loss, no streak
    -0.6  = current loss streak 2
    -1.0  = current loss streak ≥ 3
    """
    if not form:
        return 0.0
    streak = 0
    streak_type = None
    for r in form:
        if r in ('W',):
            if streak_type == 'W':
                streak += 1
            elif streak_type is None:
                streak_type = 'W'
                streak = 1
            else:
                break
        elif r in ('L',):
            if streak_type == 'L':
                streak += 1
            elif streak_type is None:
                streak_type = 'L'
                streak = 1
            else:
                break
        else:
            # Draw breaks streak
            break
    if streak_type == 'W':
        return min(1.0, 0.3 * streak)
    if streak_type == 'L':
        return -min(1.0, 0.3 * streak)
    return 0.0


def _form_consistency(form: List[str]) -> float:
    """Measure how consistent the form is (0=erratic, 1=very consistent).
    
    Counts dominant-result share. A team with WWWWW or LLLLL is fully
    consistent (1.0). A team with WLWLW is highly variable (0.4).
    """
    if not form or len(form) < 3:
        return 0.5
    counts = {'W': 0, 'D': 0, 'L': 0}
    for r in form:
        if r in counts:
            counts[r] += 1
    total = sum(counts.values())
    if total == 0:
        return 0.5
    dominant = max(counts.values()) / total
    return dominant


def _h2h_goal_diff(h2h: List[Dict], team_name: str) -> float:
    """Average goal difference for *team_name* across H2H matches.
    Returns normalized value in [-1, 1] where +1 = +3 goals avg, -1 = -3 goals avg.
    """
    if not h2h or not team_name:
        return 0.0
    team_lower = team_name.lower().strip()
    diffs: List[int] = []
    for item in h2h:
        score = item.get('score', '')
        sm = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score)
        if not sm:
            continue
        gh = int(sm.group(1))
        ga = int(sm.group(2))
        h_home = item.get('home', '').lower().strip()
        h_away = item.get('away', '').lower().strip()
        if team_lower in h_home or h_home in team_lower:
            diffs.append(gh - ga)
        elif team_lower in h_away or h_away in team_lower:
            diffs.append(ga - gh)
    if not diffs:
        return 0.0
    avg = sum(diffs) / len(diffs)
    # Normalize: assume 3 goals avg diff is "max"
    return max(-1.0, min(1.0, avg / 3.0))


def _sofascore_confidence_factor(votes: float) -> float:
    """Discount SofaScore signal when sample size is small.
    
    Returns factor in [0, 1]:
    - 0 votes:    0.0 (don't trust)
    - 50 votes:   0.5
    - 200 votes:  0.8
    - 1000+ votes: 1.0 (full trust)
    """
    if votes <= 0:
        return 0.0
    # Smooth ramp using log scale
    return min(1.0, math.log10(votes + 1) / math.log10(1000))


def _market_efficiency_score(odds_h: float, odds_d: float, odds_a: float) -> float:
    """Estimate how 'efficient' (= competitive) the market is.
    
    Lower margin (overround close to 0%) means sharper market — odds carry
    more signal. Returns value in [0, 1] where 1 = very efficient.
    """
    if odds_h <= 1 or odds_a <= 1:
        return 0.0
    inv = 1.0 / odds_h + 1.0 / odds_a
    if odds_d > 1:
        inv += 1.0 / odds_d
    margin = inv - 1.0  # overround
    # Tight book = margin near 0; bookies usually 5-10%
    if margin <= 0.05:
        return 1.0
    if margin >= 0.20:
        return 0.0
    return 1.0 - (margin - 0.05) / 0.15


def _entropy(probs: List[float]) -> float:
    """Shannon entropy of a probability distribution (in nats, normalized to [0,1]).
    
    0 = total certainty (one outcome at 100%), 1 = max uncertainty (all equal).
    For 3-outcome distribution, max entropy = log(3) ≈ 1.0986.
    """
    h = 0.0
    for p in probs:
        if p > 1e-9:
            h -= p * math.log(p)
    return min(1.0, h / math.log(len(probs)))  # normalize to [0,1]


def _kl_divergence(p: List[float], q: List[float]) -> float:
    """KL divergence D(p || q): how different is dist p from dist q.
    
    Used for measuring how far our model has moved from the market prior.
    Returns value >= 0; 0 = identical distributions.
    """
    d = 0.0
    for pi, qi in zip(p, q):
        if pi > 1e-9 and qi > 1e-9:
            d += pi * math.log(pi / qi)
    return d


def _source_disagreement(estimates: List[Tuple[str, float]]) -> float:
    """Measure spread of source picks. Returns value in [0, 1] where:
    - 0.0 = all sources point same way
    - 1.0 = sources point completely opposite directions
    
    Each estimate is ('1'|'X'|'2', confidence_in_pick).
    """
    if len(estimates) < 2:
        return 0.0
    
    # Count weighted votes per outcome
    votes = {'1': 0.0, 'X': 0.0, '2': 0.0}
    total_w = 0.0
    for pick, conf in estimates:
        votes[pick] = votes.get(pick, 0.0) + conf
        total_w += conf
    
    if total_w == 0:
        return 0.0
    
    # Normalize to distribution and compute entropy
    probs = [v / total_w for v in votes.values()]
    return _entropy(probs)


def _bayesian_blend(prior: List[float], likelihood: List[float],
                     prior_weight: float = 0.4) -> List[float]:
    """Bayesian blending of a prior (e.g., market) with a model likelihood.
    
    Args:
        prior: e.g., market-implied probabilities [home, draw, away]
        likelihood: e.g., our model's probabilities
        prior_weight: how much to trust the prior (0..1)
    
    Returns posterior probabilities (sum to 1).
    """
    posterior = [
        (prior[i] * prior_weight + likelihood[i] * (1 - prior_weight))
        for i in range(len(prior))
    ]
    total = sum(posterior)
    return [p / total for p in posterior] if total > 0 else likelihood


# ---------------------------------------------------------------------------
# NEW (v3): Outcome-resolved H2H + Poisson goal model
# ---------------------------------------------------------------------------

def _h2h_outcome_rates(h2h: List[Dict], team_name: str,
                       decay: float = 0.90) -> Tuple[float, float, float, int]:
    """Time-weighted H2H outcome rates for *team_name*.

    Unlike ``_h2h_win_rate_weighted`` (which folds draws into the win rate at
    0.5), this resolves the three outcomes separately so the draw signal —
    a real, repeatedly-observed tendency between two specific teams — is not
    thrown away.

    Returns ``(win_rate, draw_rate, loss_rate, count)`` with rates summing to
    1.0 when at least one scored meeting is found. Matches are assumed to be
    ordered newest-first.
    """
    if not h2h or not team_name:
        return 0.5, 0.0, 0.5, 0

    team_lower = team_name.lower().strip()
    w_win = w_draw = w_loss = w_total = 0.0
    counted = 0

    for i, item in enumerate(h2h):
        score = item.get('score', '')
        sm = re.search(r'(\d+)\s*[:\-]\s*(\d+)', str(score))
        if not sm:
            continue
        gh = int(sm.group(1))
        ga = int(sm.group(2))
        h_home = (item.get('home', '') or '').lower().strip()
        h_away = (item.get('away', '') or '').lower().strip()

        weight = decay ** i
        w_total += weight
        counted += 1

        if gh == ga:
            w_draw += weight
            continue

        winner = h_home if gh > ga else h_away
        if team_lower and (team_lower in winner or winner in team_lower):
            w_win += weight
        else:
            w_loss += weight

    if w_total == 0:
        return 0.5, 0.0, 0.5, 0
    return w_win / w_total, w_draw / w_total, w_loss / w_total, counted


def _h2h_from_aggregates(m: Dict, focus: str) -> Tuple[float, int]:
    """Derive (win_rate, count) for the focus team from aggregate H2H fields.

    Used when no ``h2h_last5`` list is available but win/loss totals are —
    e.g. rows enriched through the SofaScore API, which reports only totals.
    Falls back to a pre-computed ``win_rate`` when the counts are absent.

    Returns ``(0.5, 0)`` when nothing usable is present.
    """
    home_wins = _safe_float(m.get('home_wins_in_h2h_last5',
                                  m.get('home_wins_in_h2h')), -1.0)
    away_wins = _safe_float(m.get('away_wins_in_h2h_last5',
                                  m.get('away_wins_in_h2h')), -1.0)
    total = _safe_float(m.get('h2h_count'), 0.0)

    if home_wins >= 0 and away_wins >= 0 and (home_wins + away_wins) > 0:
        decided = home_wins + away_wins
        focus_wins = away_wins if focus == 'away' else home_wins
        # Draws are the remainder of the sample and count as half, matching
        # _h2h_win_rate_weighted's convention.
        draws = max(0.0, total - decided)
        denom = decided + draws
        rate = (focus_wins + 0.5 * draws) / denom if denom > 0 else 0.5
        return max(0.0, min(1.0, rate)), int(max(total, decided))

    # `win_rate` is stored as a 0-1 fraction by the pipelines.
    wr = _safe_float(m.get('win_rate'), -1.0)
    if wr >= 0 and total > 0:
        if wr > 1.0:          # tolerate a percentage slipping through
            wr = wr / 100.0
        return max(0.0, min(1.0, wr)), int(total)

    return 0.5, 0


def _poisson_pmf(lmbda: float, k: int) -> float:
    """Poisson probability mass P(X = k) for rate lmbda."""
    if lmbda <= 0:
        return 1.0 if k == 0 else 0.0
    try:
        return math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def _poisson_match_probs(lambda_home: float, lambda_away: float,
                         max_goals: int = 8) -> Tuple[float, float, float]:
    """1/X/2 probabilities from an independent bivariate-Poisson goal model.

    Sums the joint probability grid P(home=i) * P(away=j) over all
    score lines up to ``max_goals`` per side. This is the standard
    goals-based approach to football outcome modelling and yields a
    naturally-calibrated draw probability (the diagonal of the grid).

    Returns ``(p_home, p_draw, p_away)`` summing to ~1.0.
    """
    lambda_home = max(0.05, min(6.0, lambda_home))
    lambda_away = max(0.05, min(6.0, lambda_away))

    home_pmf = [_poisson_pmf(lambda_home, i) for i in range(max_goals + 1)]
    away_pmf = [_poisson_pmf(lambda_away, j) for j in range(max_goals + 1)]

    p_home = p_draw = p_away = 0.0
    for i in range(max_goals + 1):
        ph = home_pmf[i]
        if ph <= 0:
            continue
        for j in range(max_goals + 1):
            p = ph * away_pmf[j]
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p

    total = p_home + p_draw + p_away
    if total <= 0:
        return 0.40, 0.27, 0.33
    return p_home / total, p_draw / total, p_away / total


def _parse_exact_score(raw) -> Optional[Tuple[float, float]]:
    """Parse a 'home-away' exact score string (e.g. '2-1', '2:1') to floats.

    Returns ``(home_goals, away_goals)`` or ``None`` when not parseable.
    """
    if raw is None:
        return None
    m = re.search(r'(\d+)\s*[:\-]\s*(\d+)', str(raw))
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _implied_probs_from_odds(odds_h: float, odds_d: float, odds_a: float
                             ) -> Optional[Tuple[float, float, float]]:
    """Margin-removed 1/X/2 implied probabilities from decimal odds.

    Returns ``None`` when home/away odds are missing/invalid.
    """
    if odds_h <= 1 or odds_a <= 1:
        return None
    inv_h = 1.0 / odds_h
    inv_a = 1.0 / odds_a
    inv_d = 1.0 / odds_d if odds_d > 1 else 0.0
    total = inv_h + inv_d + inv_a
    if total <= 0:
        return None
    return inv_h / total, inv_d / total, inv_a / total


def _solve_lambdas_from_supremacy(supremacy: float, total_goals: float,
                                  max_goals: int = 8) -> Tuple[float, float]:
    """Split an expected goal *total* into home/away rates given a *supremacy*.

    ``supremacy`` is the expected home-minus-away goal difference (can be
    negative). We keep ``lambda_home + lambda_away = total_goals`` and
    ``lambda_home - lambda_away = supremacy``, clamped to sane bounds.
    """
    total_goals = max(0.4, min(6.0, total_goals))
    lh = (total_goals + supremacy) / 2.0
    la = (total_goals - supremacy) / 2.0
    return max(0.15, lh), max(0.15, la)


def _expected_goals(m: Dict, profile: Optional[Dict[str, float]] = None
                    ) -> Optional[Tuple[float, float]]:
    """Derive expected goals (lambda_home, lambda_away) for the Poisson model.

    Priority of evidence (most direct first):
      1. Forebet predicted exact score — a direct goal expectation.
      2. Team scoring/conceding averages — classic attack-vs-defence xG proxy.
      3. Market odds + form + H2H — infer a *supremacy* (expected goal
         difference) and a *match total*, then split into the two rates.
         This tier almost always fires because odds/form are nearly always
         present, so the naturally-calibrated Poisson draw probability
         contributes to essentially every football match.

    Returns ``None`` only when even the fallback inputs are absent.
    """
    # --- Tier 1: Forebet exact score -------------------------------------
    es = _parse_exact_score(m.get('forebet_exact_score'))
    if es is not None:
        lh, la = es
        # Smooth toward league-average to avoid 0-goal lambdas dominating.
        return max(0.2, lh * 0.85 + 0.20), max(0.2, la * 0.85 + 0.18)

    # --- Tier 2: Team goal averages --------------------------------------
    hs = _safe_float(m.get('home_goals_scored_avg', m.get('home_avg_goals_scored')))
    hc = _safe_float(m.get('home_goals_conceded_avg', m.get('home_avg_goals_conceded')))
    as_ = _safe_float(m.get('away_goals_scored_avg', m.get('away_avg_goals_scored')))
    ac = _safe_float(m.get('away_goals_conceded_avg', m.get('away_avg_goals_conceded')))
    if hs > 0 and as_ > 0:
        # Home attack vs away defence, plus a mild home-scoring bump.
        lh = (hs + (ac if ac > 0 else hs)) / 2.0 * 1.10
        la = (as_ + (hc if hc > 0 else as_)) / 2.0 * 0.95
        return max(0.2, lh), max(0.2, la)

    # --- Tier 3: Infer from odds + form + H2H ----------------------------
    # Build a "supremacy" signal in [-1, 1] (positive favours home) from the
    # strongest always-available sources, then map to an expected goal diff.
    league_total = (profile or {}).get('avg_total_goals', 2.6)

    signals: List[Tuple[float, float]] = []  # (signal in [-1,1], weight)

    implied = _implied_probs_from_odds(
        _safe_float(m.get('home_odds')),
        _safe_float(m.get('draw_odds')),
        _safe_float(m.get('away_odds')),
    )
    if implied is not None:
        ih, _id, ia = implied
        # Home edge in win probability → supremacy proxy.
        signals.append((max(-1.0, min(1.0, (ih - ia) * 1.6)), 0.55))

    home_form = _parse_form(m.get('home_form_overall', m.get('home_form', [])))
    away_form = _parse_form(m.get('away_form_overall', m.get('away_form', [])))
    if home_form or away_form:
        fdiff = _form_points(home_form) - _form_points(away_form)  # [-1,1]
        signals.append((max(-1.0, min(1.0, fdiff * 1.5)), 0.30))

    focus = m.get('focus_team', 'home')
    team = m.get('away_team', '') if focus == 'away' else m.get('home_team', '')
    h2h_list = m.get('h2h_last5', [])
    if h2h_list:
        gd = _h2h_goal_diff(h2h_list, m.get('home_team', team))  # [-1,1] home frame
        signals.append((max(-1.0, min(1.0, gd)), 0.15))

    if not signals:
        return None

    w_sum = sum(wt for _, wt in signals)
    supremacy_norm = sum(s * wt for s, wt in signals) / w_sum if w_sum else 0.0

    # Map normalized supremacy to an expected goal difference. Calibrated via
    # Monte-Carlo backtest (backtest_engine.py): a multiplier of ~1.3 best
    # matches the true draw frequency — higher values sharpen the favourite
    # and hurt probability calibration (over-confident), lower values
    # under-separate. A dominant favourite (~1.0) projects to ~1.4 goal margin.
    goal_supremacy = supremacy_norm * 1.3
    # Add a small structural home-field goal bump.
    goal_supremacy += 0.10

    lh, la = _solve_lambdas_from_supremacy(goal_supremacy, league_total)
    return lh, la


# Sport-specific characteristics (long-run averages from public datasets)
SPORT_PROFILES: Dict[str, Dict[str, float]] = {
    'football': {
        'home_advantage': 0.46,
        'draw_rate': 0.26,
        'away_rate': 0.28,
        # Softening factor for model probabilities. Raised from 1.15 to 1.50
        # after calibration measurement (calibrate_weights.py): at 1.15 the
        # engine was systematically over-confident — buckets claiming 83%
        # landed 67%, and 72% landed 62%. A sweep over 1.15-2.40 put the
        # optimum at 1.5-1.7, confirmed on three independent seeds where 1.50
        # improved both log-loss and Brier every time without costing
        # accuracy. Values above ~2.0 start washing out real signal.
        'temperature': 1.50,
        'min_draw_prob': 0.18,  # never go below this
        'avg_total_goals': 2.7,  # long-run avg goals/match (Poisson tier-3)
    },
    'basketball': {
        'home_advantage': 0.60,  # higher home advantage in basketball
        'draw_rate': 0.0,        # overtime resolves ties — no draw exists
        'away_rate': 0.40,
        'temperature': 1.05,
        'min_draw_prob': 0.0,
    },
    'tennis': {
        'home_advantage': 0.52,
        'draw_rate': 0.0,
        'away_rate': 0.48,
        'temperature': 1.10,
        'min_draw_prob': 0.0,
    },
    # Table tennis had no profile at all, so it fell through to the football
    # default and was handed a ~19-24% draw probability for a sport that cannot
    # draw. That reached the calibration data (calibrate_weights routed only
    # 'tennis' to the two-outcome engine) and the dropping-odds mail.
    'table_tennis': {
        'home_advantage': 0.52,
        'draw_rate': 0.0,
        'away_rate': 0.48,
        'temperature': 1.10,
        'min_draw_prob': 0.0,
    },
    'volleyball': {
        'home_advantage': 0.58,
        'draw_rate': 0.0,        # sets always produce a winner
        'away_rate': 0.42,
        'temperature': 1.05,
        'min_draw_prob': 0.0,
    },
    'handball': {
        'home_advantage': 0.55,
        'draw_rate': 0.10,
        'away_rate': 0.35,
        'temperature': 1.10,
        'min_draw_prob': 0.05,
        'avg_total_goals': 53.0,
    },
    'hockey': {
        'home_advantage': 0.50,
        'draw_rate': 0.10,
        'away_rate': 0.40,
        'temperature': 1.10,
        'min_draw_prob': 0.05,
        'avg_total_goals': 5.5,
    },
    'baseball': {
        'home_advantage': 0.54,
        'draw_rate': 0.0,
        'away_rate': 0.46,
        'temperature': 1.10,
        'min_draw_prob': 0.0,
    },
    # e-sports (LoL, CS2, Dota): a match always resolves to a winner, so any
    # draw probability is phantom. Without this entry the engine fell back to
    # the football profile and assigned ~22% to a draw that cannot happen.
    'esports': {
        'home_advantage': 0.52,
        'draw_rate': 0.0,
        'away_rate': 0.48,
        'temperature': 1.10,
        'min_draw_prob': 0.0,
    },
    # Rugby union/league: draws exist but are rare (~1-2% of fixtures).
    'rugby': {
        'home_advantage': 0.55,
        'draw_rate': 0.02,
        'away_rate': 0.43,
        'temperature': 1.10,
        'min_draw_prob': 0.02,
    },
}


# Sports whose scoring must never produce a draw probability. Used to route
# picks and to keep the '1'/'X'/'2' triplet honest for two-outcome sports.
NO_DRAW_SPORTS = frozenset({
    sport for sport, prof in SPORT_PROFILES.items()
    if prof.get('min_draw_prob', 0.0) <= 0.0
})


def sport_has_draw(sport: Optional[str]) -> bool:
    """True when *sport* can end in a draw (per SPORT_PROFILES)."""
    key = (sport or 'football').lower()
    profile = SPORT_PROFILES.get(key, SPORT_PROFILES['football'])
    return profile.get('min_draw_prob', 0.0) > 0.0


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

class FeatureExtractor:
    """Extract normalised features from a single match dict
    (the format produced by livesport_h2h_scraper.py / CSV rows)."""

    # Base home advantage in football (long-term average ≈ 46 % home win)
    HOME_ADVANTAGE = 0.46

    def extract(self, m: Dict) -> Dict[str, float]:
        """Return dict of named features all normalised to [0, 1]."""
        f: Dict[str, float] = {}
        available = 0
        total_features = 11

        # 1. H2H time-weighted win rate for focus team
        focus = m.get('focus_team', 'home')
        team = m.get('away_team', '') if focus == 'away' else m.get('home_team', '')
        h2h_list = m.get('h2h_last5', [])
        h2h_wr, h2h_cnt = _h2h_win_rate_weighted(h2h_list, team)
        if h2h_cnt == 0:
            # Fall back to aggregate H2H counts. Sources such as the SofaScore
            # API return only totals (home_wins/away_wins/total) rather than a
            # match list, and without this the H2H factor stayed neutral for
            # every such row despite carrying real information.
            h2h_wr, h2h_cnt = _h2h_from_aggregates(m, focus)
        f['h2h_win_rate'] = h2h_wr
        f['h2h_count'] = min(h2h_cnt / 5.0, 1.0)
        if h2h_cnt > 0:
            available += 1
        
        # 1b. NEW: H2H goal difference (margin of victory matters)
        f['h2h_goal_diff'] = _h2h_goal_diff(h2h_list, team)

        # 1c. NEW (v3): Outcome-resolved H2H rates relative to the HOME team.
        # Resolves win/draw/loss separately so the draw tendency between
        # these two specific teams is preserved instead of folded into 0.5.
        home_team_name = m.get('home_team', '')
        hw, hd, hl, _hc = _h2h_outcome_rates(h2h_list, home_team_name)
        f['h2h_home_win_rate'] = hw
        f['h2h_draw_rate'] = hd
        f['h2h_away_win_rate'] = hl

        # 2. Overall form
        home_form = _parse_form(m.get('home_form_overall', m.get('home_form', [])))
        away_form = _parse_form(m.get('away_form_overall', m.get('away_form', [])))
        f['home_form'] = _form_points(home_form)
        f['away_form'] = _form_points(away_form)
        if home_form:
            available += 1
        if away_form:
            available += 1
        
        # 2b. NEW: Form momentum (current streak)
        f['home_momentum'] = _form_momentum(home_form)
        f['away_momentum'] = _form_momentum(away_form)
        
        # 2c. NEW: Form consistency (low variance = predictable)
        f['home_consistency'] = _form_consistency(home_form)
        f['away_consistency'] = _form_consistency(away_form)

        # 3. Venue-specific form
        home_form_home = _parse_form(m.get('home_form_home', []))
        away_form_away = _parse_form(m.get('away_form_away', []))
        f['home_venue_form'] = _form_points(home_form_home) if home_form_home else f['home_form']
        f['away_venue_form'] = _form_points(away_form_away) if away_form_away else f['away_form']
        if home_form_home:
            available += 1
        if away_form_away:
            available += 1

        # 4. Forebet probability
        fb_prob = _safe_float(m.get('forebet_probability'))
        fb_pred = m.get('forebet_prediction', '')
        if fb_prob > 0 and fb_pred:
            f['forebet_prob'] = fb_prob / 100.0
            f['forebet_pred'] = {'1': 1.0, 'X': 0.5, '2': 0.0}.get(str(fb_pred), 0.5)
            available += 1
        else:
            f['forebet_prob'] = 0.5
            f['forebet_pred'] = 0.5

        # 5. SofaScore community vote — discount by sample size (volume)
        ss_home = _safe_float(m.get('sofascore_home_win_prob', m.get('sofascore_home')))
        ss_draw = _safe_float(m.get('sofascore_draw_prob', m.get('sofascore_draw')))
        ss_away = _safe_float(m.get('sofascore_away_win_prob', m.get('sofascore_away')))
        ss_votes = _safe_float(m.get('sofascore_total_votes', m.get('sofascore_votes')))
        ss_total = ss_home + ss_draw + ss_away
        if ss_total > 0:
            f['ss_home'] = ss_home / ss_total
            f['ss_draw'] = ss_draw / ss_total
            f['ss_away'] = ss_away / ss_total
            f['ss_volume_factor'] = _sofascore_confidence_factor(ss_votes)
            available += 1
        else:
            f['ss_home'] = 0.33
            f['ss_draw'] = 0.34
            f['ss_away'] = 0.33
            f['ss_volume_factor'] = 0.0

        # 6. Market odds → implied probabilities (margin-removed)
        odds_h = _safe_float(m.get('home_odds'))
        odds_d = _safe_float(m.get('draw_odds'))
        odds_a = _safe_float(m.get('away_odds'))
        sport_lower = (m.get('sport') or 'football').lower()
        sport_allows_draw = SPORT_PROFILES.get(sport_lower, SPORT_PROFILES['football']).get('min_draw_prob', 0.0) > 0.01
        
        if odds_h > 1 and odds_a > 1:
            imp_h = 1.0 / odds_h
            imp_a = 1.0 / odds_a
            if odds_d > 1 and sport_allows_draw:
                imp_d = 1.0 / odds_d
            elif sport_allows_draw:
                imp_d = 0.25  # default football-ish prior when draw odds missing
            else:
                imp_d = 0.0  # sport has no draws
            margin = imp_h + imp_d + imp_a
            f['odds_home'] = imp_h / margin
            f['odds_draw'] = imp_d / margin
            f['odds_away'] = imp_a / margin
            # NEW: Market efficiency (sharper book = stronger signal)
            f['market_efficiency'] = _market_efficiency_score(odds_h, odds_d, odds_a)
            f['odds_available'] = 1.0
            available += 1
        else:
            # No market. The values below are a neutral fallback kept for any
            # consumer that reads them directly — but `odds_available` marks
            # them as NOT real market data, so the scoring model abstains
            # instead of spending the odds weight (0.21, the largest single
            # source) on an invented price. Baseball has no odds at all, so
            # every baseball row used to be driven by this placeholder.
            f['odds_home'] = 0.40 if sport_allows_draw else 0.55
            f['odds_draw'] = 0.27 if sport_allows_draw else 0.0
            f['odds_away'] = 0.33 if sport_allows_draw else 0.45
            f['market_efficiency'] = 0.0
            f['odds_available'] = 0.0

        # 7. AI confidence + pick (Gemini or Groq — same output contract).
        # The pick MUST come from an explicit 1/X/2 field. The old code derived
        # it from the first character of the prose prediction, so any sentence
        # ("Wisla is likely to win…") resolved to 0.5 and was fed into the
        # engine as a DRAW signal at full AI weight.
        gem_conf = _safe_float(m.get('gemini_confidence'))
        gem_pick = str(m.get('gemini_pick') or m.get('ai_pick') or '').strip().upper()
        gem_rec = m.get('gemini_recommendation', '')
        if gem_pick not in ('1', 'X', '2'):
            # Legacy rows stored a bare token in gemini_prediction; accept it
            # only when it really is just that token.
            legacy = str(m.get('gemini_prediction') or '').strip().upper()
            gem_pick = legacy if legacy in ('1', 'X', '2') else ''
        if gem_conf > 0 and gem_pick:
            f['gemini_conf'] = gem_conf / 100.0
            f['gemini_pred'] = {'1': 1.0, 'X': 0.5, '2': 0.0}[gem_pick]
            f['gemini_high'] = 1.0 if gem_rec == 'HIGH' else 0.0
            available += 1
        else:
            # No machine-readable pick -> abstain (0.5 conf makes the source
            # skip itself in score_match).
            f['gemini_conf'] = 0.5
            f['gemini_pred'] = 0.5
            f['gemini_high'] = 0.0

        # 8. Form advantage flag
        f['form_advantage'] = 1.0 if m.get('form_advantage') else 0.0

        # 9. Availability / injury impact (from data contract)
        avail = m.get('availability', {})
        if isinstance(avail, dict):
            f['availability_impact'] = _safe_float(avail.get('availability_impact'), 0.0)
            f['home_key_absences'] = min(_safe_float(avail.get('home_key_absences'), 0.0) / 5.0, 1.0)
            f['away_key_absences'] = min(_safe_float(avail.get('away_key_absences'), 0.0) / 5.0, 1.0)
            f['fatigue_risk'] = {'high': 1.0, 'moderate': 0.5, 'low': 0.0}.get(
                avail.get('fatigue_risk', 'low'), 0.0)
            if f['availability_impact'] > 0 or f['home_key_absences'] > 0 or f['away_key_absences'] > 0:
                available += 1
        else:
            f['availability_impact'] = 0.0
            f['home_key_absences'] = 0.0
            f['away_key_absences'] = 0.0
            f['fatigue_risk'] = 0.0

        # 10. Source consensus (from data contract)
        dq = m.get('data_quality', {})
        if isinstance(dq, dict):
            consensus_map = {'strong': 1.0, 'moderate': 0.6, 'weak': 0.3, 'none': 0.0}
            f['consensus'] = consensus_map.get(dq.get('consensus_strength', 'none'), 0.0)
            f['market_model_gap'] = max(-1.0, min(1.0,
                _safe_float(dq.get('market_model_gap'), 0.0) / 20.0))
        else:
            f['consensus'] = 0.0
            f['market_model_gap'] = 0.0

        # 11. NEW (v3): Poisson goal-expectation model.
        # When goal-level data exists (forebet exact score or scoring/conceding
        # averages), derive a full 1/X/2 distribution from an independent
        # Poisson grid. This is the most principled draw estimator available
        # and complements the heuristic form/odds sources.
        sport_lower_pg = (m.get('sport') or 'football').lower()
        profile_pg = SPORT_PROFILES.get(sport_lower_pg, SPORT_PROFILES['football'])
        # Only sports that actually produce draws should receive a Poisson
        # draw signal (football/handball/hockey). For draw-less sports the
        # model abstains so it never injects a phantom draw probability.
        sport_has_draws_pg = profile_pg.get('min_draw_prob', 0.0) > 0.01
        xg = _expected_goals(m, profile_pg) if sport_has_draws_pg else None
        if xg is not None:
            lh, la = xg
            ph, pd, pa = _poisson_match_probs(lh, la)
            f['poisson_home'] = ph
            f['poisson_draw'] = pd
            f['poisson_away'] = pa
            f['poisson_available'] = 1.0
            f['exp_goals_home'] = lh
            f['exp_goals_away'] = la
            available += 1
        else:
            f['poisson_home'] = 0.0
            f['poisson_draw'] = 0.0
            f['poisson_away'] = 0.0
            f['poisson_available'] = 0.0
            f['exp_goals_home'] = 0.0
            f['exp_goals_away'] = 0.0

        # Data quality metric
        f['_data_quality'] = available / total_features

        return f


# ---------------------------------------------------------------------------
# Core scoring model
# ---------------------------------------------------------------------------

class FootballScoringEngine:
    """
    Weighted-ensemble probability model for football 1/X/2.

    Design principles:
      • No ML training needed — uses expert-tuned weights that can be
        refined via historical calibration (CalibrationRunner).
      • Deterministic — same input → same output; safe for CI.
      • Transparent — every feature contribution is stored.
    """

    # Source weights (tunable via calibration file)
    DEFAULT_WEIGHTS = {
        'h2h':          0.16,
        'form':         0.12,
        'venue_form':   0.07,
        'forebet':      0.12,
        'sofascore':    0.07,
        'odds':         0.21,
        'gemini':       0.07,
        'availability': 0.05,
        'consensus':    0.05,
        'poisson':      0.08,
    }

    # Per-sport weight overrides, filled by calibration on settled results.
    # Empty by default: every sport uses DEFAULT_WEIGHTS until there is
    # evidence that a different mix scores better for it. Sports differ in
    # which sources even exist (baseball has no odds, tennis rarely has H2H),
    # so one shared mix cannot be right everywhere — but guessing a per-sport
    # mix without measurement would be worse than the shared one.
    SPORT_WEIGHT_OVERRIDES: Dict[str, Dict[str, float]] = {}

    # How much of the bookmaker's price to fold into the published probability,
    # per sport: 0.0 keeps the model's own number, 1.0 publishes the market's.
    #
    # This exists because filtering could not fix a losing ROI. Grade bands,
    # odds bands, favourite/underdog and EV thresholds were all measured and all
    # reversed sign out of sample. That is what happens when the model's
    # probabilities are worse than the price — in tennis the engine scored Brier
    # 0.5060 against the market's 0.4157 — because then "the model sees value"
    # mostly means "the model is wrong here", and filtering harder concentrates
    # the errors instead of removing them.
    #
    # Anchoring attacks the cause. A market-anchored estimate disagrees with the
    # price far less often, so far fewer picks clear the EV bar, and the ones
    # that do are genuine disagreements rather than noise. Measured on settled
    # rows with real prices, trained before 2026-06-15 and judged after it
    # (tools/market_blend.py):
    #
    #   basketball  w=0.75  ROI +5.8% earlier, +25.9% held out (best in BOTH
    #               windows, which is the bar every earlier candidate failed)
    #   tennis      w=0.93  best in BOTH windows: +3.5% earlier, +14.6% held out,
    #               against -5.9% and -5.3% at the previous 0.90
    #
    # The tennis figure was re-measured after export_settled.py started
    # unpacking the nested `tennis` block. Ranking (0.11 of the tennis weight
    # budget) and surface form (0.12) had been dropped from every exported row,
    # so the earlier verdict — "engine Brier 0.5060 against the market's 0.4157,
    # no weight is profitable" — described an engine missing a quarter of its
    # inputs. With them present the engine scores 0.3808 against the market's
    # 0.3813: level, not far behind.
    #
    # Sports absent here keep 0.0 on purpose: their held-out samples are 51-95
    # matches with prices, too few to justify changing what clients receive.
    # Values are overridable from outputs/scoring_calibration.json, so a sport
    # can be promoted the moment it has evidence.
    MARKET_ANCHOR: Dict[str, float] = {
        'basketball': 0.75,
        'tennis': 0.93,
    }
    MARKET_ANCHOR_DEFAULT: float = 0.0

    CALIBRATION_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'outputs', 'scoring_calibration.json',
    )

    def __init__(self, calibration_path: str | None = None):
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.sport_weights: Dict[str, Dict[str, float]] = {
            sport: dict(w) for sport, w in self.SPORT_WEIGHT_OVERRIDES.items()
        }
        # Measured temperature overrides, filled from the calibration file. The
        # profile values are informed guesses; these are fitted on settled
        # results, which is what makes a stated probability mean what it says.
        self.sport_temperatures: Dict[str, float] = {}
        # Monotone reliability curves, per sport. Temperature shifts the whole
        # distribution; these fit its shape, which is what the observed data
        # actually needed — stated 42% won 83%, stated 91% won 83%.
        self.sport_isotonic: Dict[str, list] = {}
        # How far each sport's published probability is pulled onto the
        # bookmaker's price. See MARKET_ANCHOR for why this exists.
        self.sport_market_anchor: Dict[str, float] = dict(self.MARKET_ANCHOR)
        self.extractor = FeatureExtractor()
        self._load_calibration(calibration_path or self.CALIBRATION_PATH)

    # ------------------------------------------------------------------
    def _load_calibration(self, path: str):
        """Load global and per-sport weights from the calibration file.

        Expected shape::

            {"weights": {...},
             "per_sport": {"football": {...}, "basketball": {...}}}

        Unknown keys are ignored and any malformed entry is skipped, so a bad
        calibration file can never break scoring.
        """
        if not os.path.isfile(path):
            return
        try:
            with open(path, 'r') as fh:
                data = json.load(fh)
        except Exception:
            return

        saved_w = data.get('weights', {})
        if isinstance(saved_w, dict):
            for k in self.weights:
                if k in saved_w:
                    try:
                        self.weights[k] = float(saved_w[k])
                    except (TypeError, ValueError):
                        pass

        per_sport = data.get('per_sport', {})
        if isinstance(per_sport, dict):
            for sport, weights in per_sport.items():
                if not isinstance(weights, dict):
                    continue
                merged = self.weights.copy()
                for k in merged:
                    if k in weights:
                        try:
                            merged[k] = float(weights[k])
                        except (TypeError, ValueError):
                            pass
                self.sport_weights[str(sport).lower()] = merged

        try:
            from probability_calibration import load_curves
            self.sport_isotonic.update(load_curves(data))
        except ImportError:
            pass

        anchors = data.get('market_anchor', {})
        if isinstance(anchors, dict):
            for sport, value in anchors.items():
                try:
                    a = float(value)
                except (TypeError, ValueError):
                    continue
                if 0.0 <= a <= 1.0:
                    self.sport_market_anchor[str(sport).lower()] = a

        temps = data.get('temperatures', {})
        if isinstance(temps, dict):
            for sport, value in temps.items():
                try:
                    t = float(value)
                except (TypeError, ValueError):
                    continue
                # A temperature at or below zero would invert the distribution;
                # anything beyond 5 flattens every pick to the prior.
                if 0.2 <= t <= 5.0:
                    self.sport_temperatures[str(sport).lower()] = t

    # ------------------------------------------------------------------
    def weights_for_sport(self, sport: Optional[str]) -> Dict[str, float]:
        """Return the weight set to use for *sport* (falls back to global)."""
        key = (sport or 'football').lower()
        return self.sport_weights.get(key, self.weights)

    # ------------------------------------------------------------------
    def temperature_for_sport(self, sport: Optional[str]) -> float:
        """Softmax temperature for *sport*: measured value if we have one.

        Above 1 the distribution softens, below 1 it sharpens. The fitted value
        is what corrects the overconfidence the reliability table exposed — the
        model said 90% and won 78%.
        """
        key = (sport or 'football').lower()
        if key in self.sport_temperatures:
            return self.sport_temperatures[key]
        profile = SPORT_PROFILES.get(key, SPORT_PROFILES['football'])
        return float(profile.get('temperature', 1.15))

    # ------------------------------------------------------------------
    def market_anchor_for_sport(self, sport: Optional[str]) -> float:
        """How far to pull *sport*'s published probability onto the price."""
        key = (sport or 'football').lower()
        value = self.sport_market_anchor.get(key, self.MARKET_ANCHOR_DEFAULT)
        # Outside [0, 1] the blend stops being a blend: below zero it pushes
        # away from the price, above one it overshoots past it.
        return max(0.0, min(1.0, float(value)))

    # ------------------------------------------------------------------
    def score_match(self, match: Dict) -> ScoredMatch:
        """Score a single match and return ScoredMatch."""
        feats = self.extractor.extract(match)

        # ---- Build 1/X/2 raw probability estimates per source ----------
        sources_home: List[Tuple[float, float]] = []  # (prob, weight)
        sources_draw: List[Tuple[float, float]] = []
        sources_away: List[Tuple[float, float]] = []

        # Weights may be sport-specific once calibration has evidence for it.
        w = self.weights_for_sport(match.get('sport'))

        # H2H — now boosted by goal differential (margin of victory) and
        # using outcome-resolved draw rates (v3) instead of a flat heuristic.
        h2h_wr = feats['h2h_win_rate']
        h2h_cnt = feats['h2h_count']
        h2h_gd = feats.get('h2h_goal_diff', 0.0)  # in [-1, 1]
        # Adjust win-rate by goal diff: dominant wins (e.g., 3-0) signal stronger
        h2h_wr_adj = max(0.0, min(1.0, h2h_wr + h2h_gd * 0.10))
        focus = match.get('focus_team', 'home')
        # Real draw rate observed in these teams' meetings (home-team frame).
        h2h_draw_rate = feats.get('h2h_draw_rate', 0.0)
        if h2h_cnt > 0:
            confidence_mult = min(1.0, h2h_cnt / 0.6)  # penalise <3 matches
            # Blend observed draw rate with a prior; shrink toward prior when
            # the sample is small so a single historical draw isn't overweighted.
            draw_signal = h2h_draw_rate * confidence_mult + 0.26 * (1 - confidence_mult)
            non_draw = max(0.02, 1.0 - draw_signal)
            if focus == 'home':
                win_p = (h2h_wr_adj * confidence_mult + (1 - confidence_mult) * 0.45) * non_draw
                sources_home.append((win_p, w['h2h']))
                sources_draw.append((draw_signal, w['h2h']))
                sources_away.append((max(0.02, non_draw - win_p), w['h2h']))
            else:
                win_p = (h2h_wr_adj * confidence_mult + (1 - confidence_mult) * 0.45) * non_draw
                sources_away.append((win_p, w['h2h']))
                sources_draw.append((draw_signal, w['h2h']))
                sources_home.append((max(0.02, non_draw - win_p), w['h2h']))

        # Form (overall) — now boosted by momentum
        hf = feats['home_form']
        af = feats['away_form']
        h_momentum = feats.get('home_momentum', 0.0)
        a_momentum = feats.get('away_momentum', 0.0)
        # Effective form combines points + recent momentum (streak)
        hf_eff = max(0.0, min(1.0, hf + h_momentum * 0.10))
        af_eff = max(0.0, min(1.0, af + a_momentum * 0.10))
        form_diff = hf_eff - af_eff
        sources_home.append((0.40 + form_diff * 0.30, w['form']))
        sources_draw.append((0.28 - abs(form_diff) * 0.10, w['form']))
        sources_away.append((0.32 - form_diff * 0.30, w['form']))

        # Venue form
        hvf = feats['home_venue_form']
        avf = feats['away_venue_form']
        vdiff = hvf - avf
        sources_home.append((0.42 + vdiff * 0.25, w['venue_form']))
        sources_draw.append((0.27 - abs(vdiff) * 0.08, w['venue_form']))
        sources_away.append((0.31 - vdiff * 0.25, w['venue_form']))

        # Forebet
        fb = feats['forebet_prob']
        fp = feats['forebet_pred']
        if fb != 0.5:
            if fp > 0.7:  # pred = home
                sources_home.append((fb, w['forebet']))
                sources_draw.append(((1 - fb) * 0.40, w['forebet']))
                sources_away.append(((1 - fb) * 0.60, w['forebet']))
            elif fp < 0.3:  # pred = away
                sources_away.append((fb, w['forebet']))
                sources_draw.append(((1 - fb) * 0.40, w['forebet']))
                sources_home.append(((1 - fb) * 0.60, w['forebet']))
            else:  # pred = draw
                sources_draw.append((fb, w['forebet']))
                sources_home.append(((1 - fb) * 0.55, w['forebet']))
                sources_away.append(((1 - fb) * 0.45, w['forebet']))

        # SofaScore — weight scaled by vote volume (small samples discounted)
        ss_volume = feats.get('ss_volume_factor', 0.5)
        ss_w = w['sofascore'] * ss_volume  # discount low-vote signals
        sources_home.append((feats['ss_home'], ss_w))
        sources_draw.append((feats['ss_draw'], ss_w))
        sources_away.append((feats['ss_away'], ss_w))

        # Odds-implied (strongest signal) — boost when market is efficient.
        # Abstain entirely when there is no market, the same way H2H, Forebet
        # and Gemini abstain; _wavg then redistributes the weight across the
        # sources that do carry information.
        has_market_data = feats.get('odds_available', 0.0) > 0
        if has_market_data:
            market_eff = feats.get('market_efficiency', 0.5)
            odds_w = w['odds'] * (0.7 + 0.3 * market_eff)  # 70-100% by efficiency
            sources_home.append((feats['odds_home'], odds_w))
            sources_draw.append((feats['odds_draw'], odds_w))
            sources_away.append((feats['odds_away'], odds_w))

        # Poisson goal model (v3) — principled draw estimator from expected
        # goals. Only contributes when goal-level data is available. The
        # weight is adaptive: the Poisson signal is most valuable when the
        # market is absent or loose (it then carries independent information),
        # and least valuable when a sharp market already prices the game.
        # Backtests (backtest_engine.py) show the gain concentrates in the
        # missing/noisy-odds regime, so we up-weight there and down-weight
        # when a tight book is present.
        if feats.get('poisson_available', 0.0) > 0:
            base_pois_w = w.get('poisson', 0.08)
            has_market = feats.get('odds_home', 0.0) > 0.05 and feats.get('market_efficiency', 0.0) > 0.0
            if has_market:
                # Sharp market (efficiency→1) shrinks Poisson toward 60%;
                # loose market (efficiency→0) keeps it near full weight.
                pois_w = base_pois_w * (1.0 - 0.4 * feats.get('market_efficiency', 0.5))
            else:
                # No usable market data — Poisson is a primary signal here.
                pois_w = base_pois_w * 1.8
            sources_home.append((feats['poisson_home'], pois_w))
            sources_draw.append((feats['poisson_draw'], pois_w))
            sources_away.append((feats['poisson_away'], pois_w))

        # Gemini
        gc = feats['gemini_conf']
        gp = feats['gemini_pred']
        gh = feats['gemini_high']
        gem_w = w['gemini'] * (1.0 + 0.3 * gh)  # boost if HIGH rec
        if gc != 0.5:
            if gp > 0.7:
                sources_home.append((gc, gem_w))
                sources_draw.append(((1 - gc) * 0.40, gem_w))
                sources_away.append(((1 - gc) * 0.60, gem_w))
            elif gp < 0.3:
                sources_away.append((gc, gem_w))
                sources_draw.append(((1 - gc) * 0.40, gem_w))
                sources_home.append(((1 - gc) * 0.60, gem_w))
            else:
                sources_draw.append((gc * 0.6, gem_w))
                sources_home.append((gc * 0.25, gem_w))
                sources_away.append((gc * 0.15, gem_w))

        # Availability / injury adjustment
        avail_impact = feats.get('availability_impact', 0.0)
        home_abs = feats.get('home_key_absences', 0.0)
        away_abs = feats.get('away_key_absences', 0.0)
        if avail_impact > 0 or home_abs > 0 or away_abs > 0:
            # Absences hurt the team: shift probability to opponent
            abs_diff = away_abs - home_abs  # positive = away more hurt → home favored
            avail_home = 0.40 + abs_diff * 0.15
            avail_away = 0.35 - abs_diff * 0.15
            avail_draw = 0.25
            sources_home.append((max(0.1, min(0.8, avail_home)), w.get('availability', 0.05)))
            sources_draw.append((max(0.1, min(0.5, avail_draw)), w.get('availability', 0.05)))
            sources_away.append((max(0.1, min(0.8, avail_away)), w.get('availability', 0.05)))

        # Consensus strength boost
        cons = feats.get('consensus', 0.0)
        mmg = feats.get('market_model_gap', 0.0)
        if cons > 0:
            # Strong consensus reinforces the predicted side
            cons_boost = cons * 0.15
            if focus == 'home':
                sources_home.append((0.45 + cons_boost + mmg * 0.1, w.get('consensus', 0.05)))
                sources_draw.append((0.25 - cons_boost * 0.3, w.get('consensus', 0.05)))
                sources_away.append((0.30 - cons_boost * 0.7, w.get('consensus', 0.05)))
            else:
                sources_away.append((0.40 + cons_boost + mmg * 0.1, w.get('consensus', 0.05)))
                sources_draw.append((0.25 - cons_boost * 0.3, w.get('consensus', 0.05)))
                sources_home.append((0.35 - cons_boost * 0.7, w.get('consensus', 0.05)))

        # ---- Weighted average ------------------------------------------
        def _wavg(pairs: List[Tuple[float, float]]) -> float:
            if not pairs:
                return 0.33
            s = sum(p * wt for p, wt in pairs)
            w_sum = sum(wt for _, wt in pairs)
            return s / w_sum if w_sum > 0 else 0.33

        raw_h = _wavg(sources_home)
        raw_d = _wavg(sources_draw)
        raw_a = _wavg(sources_away)

        # ---- Sport-specific profile ------------------------------------
        sport = match.get('sport', 'football').lower()
        profile = SPORT_PROFILES.get(sport, SPORT_PROFILES['football'])
        has_draw = profile.get('min_draw_prob', 0.0) > 0.0

        # Clip & normalise. The draw floor must respect the sport: applying a
        # blanket 0.05 here used to inject a phantom draw into tennis,
        # basketball, baseball and e-sports before the profile was consulted.
        raw_h = max(0.02, raw_h)
        raw_d = max(0.05, raw_d) if has_draw else 0.0
        raw_a = max(0.02, raw_a)
        total = raw_h + raw_d + raw_a
        raw_h, raw_d, raw_a = raw_h / total, raw_d / total, raw_a / total
        
        # ---- Bayesian blending with market prior -----------------------
        # When market is sharp and our data is thin, anchor to market.
        # When data is rich, trust our model more.
        market_prior = [feats['odds_home'], feats['odds_draw'], feats['odds_away']]
        market_eff = feats.get('market_efficiency', 0.5)
        dq = feats['_data_quality']
        # Prior weight: 50% when we have weak data + sharp market;
        # 15% when we have strong data + loose market
        prior_weight = max(0.10, min(0.55, 0.30 + 0.25 * market_eff - 0.20 * dq))
        
        # Only blend against a REAL market. The old check (`> 0.05`) passed
        # for the placeholder too, so odds-less matches were anchored to a
        # made-up prior.
        if has_market_data:
            blended = _bayesian_blend(
                market_prior, [raw_h, raw_d, raw_a], prior_weight=prior_weight
            )
            raw_h, raw_d, raw_a = blended
        
        # ---- Sport-specific draw floor ---------------------------------
        # Some sports (basketball, tennis, baseball) almost never have draws;
        # our model would learn that, but explicit floor catches edge cases.
        min_draw = profile['min_draw_prob']
        if raw_d < min_draw:
            shortfall = min_draw - raw_d
            raw_d = min_draw
            # Take from the side with higher prob proportionally
            total_ha = raw_h + raw_a
            if total_ha > 0:
                raw_h = max(0.02, raw_h - shortfall * raw_h / total_ha)
                raw_a = max(0.02, raw_a - shortfall * raw_a / total_ha)
        
        # Re-normalize
        total = raw_h + raw_d + raw_a
        raw_h, raw_d, raw_a = raw_h / total, raw_d / total, raw_a / total

        # ---- Calibration pass (sport-specific temperature) -------------
        cal_h, cal_d, cal_a = self._calibrate(
            raw_h, raw_d, raw_a,
            temperature=self.temperature_for_sport(sport),
        )

        # ---- Anti-overconfidence regularization ------------------------
        # When data quality is low or sources strongly disagree, pull
        # extreme probabilities back toward the market prior.
        # Compute source disagreement for the dominant pick.
        disagreement = self._compute_disagreement(feats)
        # Regularization strength: high when disagreement is high or DQ is low
        reg_strength = max(0.0, min(0.4,
            0.15 * disagreement + 0.10 * (1.0 - dq)
        ))
        if reg_strength > 0 and has_market_data:
            cal_h = cal_h * (1 - reg_strength) + market_prior[0] * reg_strength
            cal_d = cal_d * (1 - reg_strength) + market_prior[1] * reg_strength
            cal_a = cal_a * (1 - reg_strength) + market_prior[2] * reg_strength
            # Re-normalize
            total = cal_h + cal_d + cal_a
            cal_h, cal_d, cal_a = cal_h / total, cal_d / total, cal_a / total

        # Two-outcome sports: the softmax calibration can leave a residual
        # draw mass. Zero it out and renormalise so the reported triplet is
        # honest (e.g. LoL showed "51% / 23% / 25%" for a draw-less game).
        if not has_draw and cal_d > 0:
            cal_d = 0.0
            total = cal_h + cal_a
            if total > 0:
                cal_h, cal_a = cal_h / total, cal_a / total

        # ---- Reliability curve, applied last ---------------------------
        # Deliberately after the regularisation and the draw-mass cleanup: the
        # curve is fitted on the engine's *final* output, so applying it any
        # earlier would train on one distribution and correct another. Placed
        # before the regulariser it was partly undone — a mapped 0.95 came out
        # as 0.877 after shrinking toward the market prior.
        curve = self.sport_isotonic.get(sport)
        if curve:
            from probability_calibration import calibrate_triplet
            cal_h, cal_d, cal_a = calibrate_triplet(curve, [cal_h, cal_d, cal_a])
            if not has_draw:
                cal_d = 0.0
                total = cal_h + cal_a
                if total > 0:
                    cal_h, cal_a = cal_h / total, cal_a / total

        # ---- Market anchor, per sport ----------------------------------
        # Applied after the reliability curve and before EV, because EV has to
        # be computed from the number we actually publish. Without a price there
        # is nothing to anchor to, so unpriced matches are untouched.
        anchor = self.market_anchor_for_sport(sport)
        if anchor > 0 and has_market_data:
            cal_h = cal_h * (1 - anchor) + market_prior[0] * anchor
            cal_d = cal_d * (1 - anchor) + market_prior[1] * anchor
            cal_a = cal_a * (1 - anchor) + market_prior[2] * anchor
            if not has_draw:
                cal_d = 0.0
            total = cal_h + cal_d + cal_a
            if total > 0:
                cal_h, cal_d, cal_a = cal_h / total, cal_d / total, cal_a / total

        # ---- EV / edge / Kelly for each outcome -----------------------
        odds_h = _safe_float(match.get('home_odds'))
        odds_d = _safe_float(match.get('draw_odds'))
        odds_a = _safe_float(match.get('away_odds'))

        outcomes = [
            ('1', cal_h, odds_h),
            ('2', cal_a, odds_a),
        ]
        if has_draw:
            outcomes.insert(1, ('X', cal_d, odds_d))

        # Default to the model's own most likely outcome. Previously this was
        # hardcoded to '1' with EV -999, and since the loop below `continue`s
        # over outcomes without odds, any match with no odds at all was
        # published as a home pick — even when the model gave the away side
        # 74%. That silently affected every sport (100% of baseball rows,
        # ~40-50% of football/handball/volleyball).
        best_pick, best_prob = max(
            ((label, prob) for label, prob, _ in outcomes),
            key=lambda pair: pair[1],
        )
        best_ev = -999.0
        best_edge = 0.0
        best_kelly = 0.0
        best_odds = 0.0
        has_priced_outcome = False

        for label, prob, odds_val in outcomes:
            if odds_val <= 1:
                continue
            if not has_priced_outcome:
                # First outcome with a real price becomes the incumbent, so a
                # priced outcome always wins over the unpriced default.
                has_priced_outcome = True
                best_ev = -999.0
            implied = 1.0 / odds_val
            ev = prob * odds_val - 1.0
            edge = (prob - implied) * 100
            # Fractional Kelly (1/4 Kelly) with 5% bankroll cap.
            # Full Kelly is too aggressive; 1/4 is the bankroll-safe variant
            # used by most pro bettors. Cap at 5% of bankroll per pick.
            full_kelly = max(0.0, (prob * odds_val - 1) / (odds_val - 1))
            kelly = min(0.05, full_kelly * 0.25) * 100  # in percent
            if ev > best_ev:
                best_ev = ev
                best_pick = label
                best_edge = edge
                best_kelly = kelly
                best_prob = prob
                best_odds = odds_val

        # Source consensus boost — when home_form, odds, forebet, sofascore
        # all point to the same outcome, confidence should be much higher.
        consensus_boost = self._compute_source_consensus(feats, best_pick, focus)
        
        # Disagreement penalty (already computed above as part of regularization)
        disagreement_pen = disagreement  # from earlier scope
        
        # Entropy: how peaked is our final distribution?
        # Low entropy = one outcome dominates (good); high entropy = uncertain.
        entropy = _entropy([cal_h, cal_d, cal_a])
        
        # KL divergence from market: how far did our model move from the
        # market prior? Used to flag outlier picks (potential value or risk).
        market_dist = [feats['odds_home'], feats['odds_draw'], feats['odds_away']]
        if has_market_data:
            kl_market = _kl_divergence([cal_h, cal_d, cal_a], market_dist)
        else:
            # Without a market there is nothing to diverge from, so the outlier
            # penalty must not fire on a placeholder comparison.
            kl_market = 0.0
        
        # Outlier flag: model strongly disagrees with market.
        # Could be value (good) or could be wrong (bad). Flagged for review.
        is_outlier = kl_market > 0.15  # threshold for "significant divergence"
        
        # Confidence score (0-100) — improved formula with uncertainty
        dq = feats['_data_quality']
        confidence = (
            best_prob * 30                       # how sure is the model
            + dq * 15                            # how much data was available
            + (min(best_edge, 15) / 15) * 12     # size of edge (capped)
            + (1 if best_ev > 0 else 0) * 8      # positive EV bonus
            + consensus_boost * 20               # source consensus (0-1)
            + (1.0 - entropy) * 10               # certainty (low entropy)
            - disagreement_pen * 15              # disagreement penalty
            - (10 if is_outlier else 0)          # outlier risk penalty
        )
        confidence = max(0, min(100, confidence))

        return ScoredMatch(
            home_team=match.get('home_team', ''),
            away_team=match.get('away_team', ''),
            sport=match.get('sport', 'football'),
            prob_home=raw_h,
            prob_draw=raw_d,
            prob_away=raw_a,
            cal_home=cal_h,
            cal_draw=cal_d,
            cal_away=cal_a,
            best_pick=best_pick,
            best_prob=best_prob,
            best_odds=best_odds,
            ev=best_ev,
            edge=best_edge,
            kelly=best_kelly,
            roi_estimate=best_ev * 100 if best_ev > 0 else 0,
            confidence=confidence,
            data_quality=dq,
            features=feats,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_disagreement(feats: Dict[str, float]) -> float:
        """Measure how strongly our sources disagree on the outcome.
        
        Returns value in [0, 1]:
        - 0.0 = all sources point same way
        - ~0.5 = mixed signals
        - 1.0 = sources contradict each other
        
        Used to regularize overconfident picks back toward the market prior
        when sources don't agree.
        """
        # Build per-source pick votes weighted by source confidence
        votes: List[Tuple[str, float]] = []
        
        # Form
        hf = feats.get('home_form', 0.5)
        af = feats.get('away_form', 0.5)
        if abs(hf - af) > 0.10:
            votes.append(('1' if hf > af else '2', abs(hf - af)))
        else:
            votes.append(('X', 0.20))
        
        # Odds
        oh = feats.get('odds_home', 0.33)
        oa = feats.get('odds_away', 0.33)
        odds_max = max(oh, oa, feats.get('odds_draw', 0.33))
        if oh == odds_max:
            votes.append(('1', odds_max))
        elif oa == odds_max:
            votes.append(('2', odds_max))
        else:
            votes.append(('X', odds_max))
        
        # Forebet
        if feats.get('forebet_prob', 0.5) > 0.5:
            fp = feats.get('forebet_pred', 0.5)
            if fp > 0.7:
                votes.append(('1', feats.get('forebet_prob', 0.5)))
            elif fp < 0.3:
                votes.append(('2', feats.get('forebet_prob', 0.5)))
            else:
                votes.append(('X', feats.get('forebet_prob', 0.5)))
        
        # SofaScore (only with volume)
        if feats.get('ss_volume_factor', 0) > 0.3:
            ssh = feats.get('ss_home', 0.33)
            ssa = feats.get('ss_away', 0.33)
            ssd = feats.get('ss_draw', 0.33)
            ss_max = max(ssh, ssd, ssa)
            if ssh == ss_max:
                votes.append(('1', ssh * feats.get('ss_volume_factor', 1.0)))
            elif ssa == ss_max:
                votes.append(('2', ssa * feats.get('ss_volume_factor', 1.0)))
            else:
                votes.append(('X', ssd * feats.get('ss_volume_factor', 1.0)))
        
        # H2H (only when meaningful sample)
        h2h_wr = feats.get('h2h_win_rate', 0.5)
        h2h_cnt = feats.get('h2h_count', 0)
        if h2h_cnt >= 0.4:  # at least 2 H2H matches
            if h2h_wr > 0.65:
                votes.append(('1', h2h_wr))
            elif h2h_wr < 0.35:
                votes.append(('2', 1.0 - h2h_wr))
            else:
                votes.append(('X', 0.30))
        
        return _source_disagreement(votes)
    
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_source_consensus(feats: Dict[str, float], pick: str,
                                  focus: str = 'home') -> float:
        """Compute how strongly all sources agree with the model's pick.
        
        Returns value in [0, 1] where 1.0 = all sources point to same outcome,
        0.0 = sources contradict each other.
        
        Considers: form differential, market odds, Forebet, SofaScore.
        """
        if pick not in ('1', 'X', '2'):
            return 0.5
        
        # Each source produces a "vote" (1=home, 2=away, X=draw, neutral=0.5)
        votes: List[str] = []
        
        # Form: who has better form?
        hf = feats.get('home_form', 0.5) + feats.get('home_momentum', 0) * 0.1
        af = feats.get('away_form', 0.5) + feats.get('away_momentum', 0) * 0.1
        if hf - af > 0.10:
            votes.append('1')
        elif af - hf > 0.10:
            votes.append('2')
        else:
            votes.append('X')
        
        # Odds: who is favorite?
        oh = feats.get('odds_home', 0.33)
        oa = feats.get('odds_away', 0.33)
        if oh > 0.45:
            votes.append('1')
        elif oa > 0.45:
            votes.append('2')
        else:
            votes.append('X')
        
        # Forebet
        fp = feats.get('forebet_pred', 0.5)
        fb_prob = feats.get('forebet_prob', 0.5)
        if fb_prob > 0.5:
            if fp > 0.7:
                votes.append('1')
            elif fp < 0.3:
                votes.append('2')
            else:
                votes.append('X')
        
        # SofaScore (only if has volume)
        if feats.get('ss_volume_factor', 0) > 0.3:
            ssh = feats.get('ss_home', 0.33)
            ssa = feats.get('ss_away', 0.33)
            ssd = feats.get('ss_draw', 0.33)
            if ssh > 0.5 and ssh > ssa:
                votes.append('1')
            elif ssa > 0.5 and ssa > ssh:
                votes.append('2')
            elif ssd > 0.4:
                votes.append('X')
        
        # H2H winner
        h2h_wr = feats.get('h2h_win_rate', 0.5)
        h2h_cnt = feats.get('h2h_count', 0)
        if h2h_cnt > 0.4:  # at least 2 H2H
            # h2h_win_rate is computed for the *focus* team, so the vote must
            # be flipped when the focus is the away side. This used to be
            # hardcoded to home, inverting the H2H vote for away-focus rows.
            focus_is_home = focus != 'away'
            if h2h_wr > 0.65:
                votes.append('1' if focus_is_home else '2')
            elif h2h_wr < 0.35:
                votes.append('2' if focus_is_home else '1')
        
        if not votes:
            return 0.5
        
        # Count agreement with the chosen pick
        agreeing = sum(1 for v in votes if v == pick)
        return agreeing / len(votes)
    
    # ------------------------------------------------------------------
    @staticmethod
    def _calibrate(h: float, d: float, a: float,
                   temperature: float = 1.15) -> Tuple[float, float, float]:
        """Light temperature-scaled softmax calibration.
        temperature > 1 → softer (more conservative);
        temperature < 1 → sharper (more aggressive)."""
        def _logit(p):
            p = max(1e-6, min(1 - 1e-6, p))
            return math.log(p / (1 - p))

        logits = [_logit(h), _logit(d), _logit(a)]
        scaled = [l / temperature for l in logits]
        max_s = max(scaled)
        exps = [math.exp(s - max_s) for s in scaled]
        total = sum(exps)
        return exps[0] / total, exps[1] / total, exps[2] / total

    # ------------------------------------------------------------------
    def score_matches(self, matches: List[Dict]) -> List[ScoredMatch]:
        """Score multiple matches, return sorted by EV descending."""
        results = [self.score_match(m) for m in matches]
        results.sort(key=lambda x: x.ev, reverse=True)
        return results

    # ------------------------------------------------------------------
    def print_report(self, matches: List[Dict]):
        """Print a formatted console report."""
        scored = self.score_matches(matches)
        print(f'\n{"="*80}')
        print(f'  FOOTBALL SCORING ENGINE – {len(scored)} matches')
        print(f'{"="*80}')

        value_bets = [s for s in scored if s.ev > 0]
        print(f'  Value bets found: {len(value_bets)}/{len(scored)}')
        print(f'  Avg confidence:   {sum(s.confidence for s in scored)/max(1,len(scored)):.1f}/100')
        print(f'  Avg data quality: {sum(s.data_quality for s in scored)/max(1,len(scored)):.0%}')
        print()

        for s in scored[:20]:
            ev_marker = '✅' if s.ev > 0 else '  '
            print(f'  {ev_marker} {s.home_team:>25} vs {s.away_team:<25}'
                  f'  pick={s.best_pick}  P={s.best_prob:.0%}'
                  f'  odds={s.best_odds:.2f}  EV={s.ev:+.3f}'
                  f'  edge={s.edge:+.1f}%  K={s.kelly:.1f}%'
                  f'  conf={s.confidence:.0f}  dq={s.data_quality:.0%}')

        print(f'\n{"="*80}\n')
        return scored


# ---------------------------------------------------------------------------
# Calibration runner (backtest-based weight optimisation)
# ---------------------------------------------------------------------------

class CalibrationRunner:
    """Run a rolling backtest to evaluate & optionally optimise source weights.

    Reads settled bets from Supabase or local JSON and measures
    accuracy / Brier score / ROI to tune weights.
    """

    def __init__(self, engine: FootballScoringEngine | None = None):
        self.engine = engine or FootballScoringEngine()

    def evaluate(self, matches_with_result: List[Dict]) -> Dict:
        """Evaluate model on matches that have actual_result (1/X/2).

        Each dict must contain:
          - all scraper fields (home_team, h2h_last5, etc.)
          - 'actual_result': '1', 'X', or '2'
          - 'home_odds', 'draw_odds', 'away_odds'
        """
        total = 0
        correct = 0
        brier_sum = 0.0
        ev_sum = 0.0         # sum of EVs across every bet placed
        roi_placed = 0       # how many bets we'd place (EV > 0)
        roi_won = 0.0        # profit from those bets (flat 1-unit)

        for m in matches_with_result:
            actual = m.get('actual_result', '').strip()
            if actual not in ('1', 'X', '2'):
                continue

            scored = self.engine.score_match(m)
            total += 1

            # Accuracy
            if scored.best_pick == actual:
                correct += 1

            # Brier score component
            p_vec = [scored.cal_home, scored.cal_draw, scored.cal_away]
            actual_vec = [1.0 if actual == '1' else 0.0,
                          1.0 if actual == 'X' else 0.0,
                          1.0 if actual == '2' else 0.0]
            brier_sum += sum((p - a) ** 2 for p, a in zip(p_vec, actual_vec))

            # ROI on value bets only
            if scored.ev > 0:
                roi_placed += 1
                if scored.best_pick == actual:
                    roi_won += scored.best_odds - 1.0  # net profit
                else:
                    roi_won -= 1.0  # lost stake

        accuracy = correct / total if total > 0 else 0.0
        brier = brier_sum / total if total > 0 else 1.0
        roi = roi_won / roi_placed if roi_placed > 0 else 0.0

        return {
            'total': total,
            'correct': correct,
            'accuracy': round(accuracy, 4),
            'brier_score': round(brier, 4),
            'value_bets_placed': roi_placed,
            'roi': round(roi * 100, 2),           # as percentage
            'net_profit_units': round(roi_won, 2),
        }

    def save_calibration(self, weights: Dict[str, float], metrics: Dict):
        path = self.engine.CALIBRATION_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            'weights': weights,
            'metrics': metrics,
            'calibrated_at': datetime.now().isoformat(),
        }
        with open(path, 'w') as fh:
            json.dump(data, fh, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_matches_from_file(path: str) -> List[Dict]:
    """Load matches from a results JSON file."""
    with open(path, 'r', encoding='utf-8-sig') as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if 'matches' in data:
            return data['matches']
        if 'results' in data:
            return data['results']
    return []


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Football Scoring Engine')
    parser.add_argument('--file', help='Path to matches JSON')
    parser.add_argument('--backtest', action='store_true', help='Run backtest on settled bets')
    parser.add_argument('--days', type=int, default=30, help='Backtest lookback days')
    args = parser.parse_args()

    engine = FootballScoringEngine()

    if args.file:
        matches = _load_matches_from_file(args.file)
        if not matches:
            print(f'No matches found in {args.file}')
            sys.exit(1)
        scored = engine.print_report(matches)
        # Save scored output
        out_path = args.file.replace('.json', '_scored.json')
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump([s.to_dict() for s in scored], fh, ensure_ascii=False, indent=2)
        print(f'Scored output saved to {out_path}')

    elif args.backtest:
        runner = CalibrationRunner(engine)
        results_dir = os.path.join(os.path.dirname(__file__), 'results')
        all_matches = []
        if os.path.isdir(results_dir):
            for fname in os.listdir(results_dir):
                if fname.endswith('.json') and 'football' in fname:
                    all_matches.extend(_load_matches_from_file(
                        os.path.join(results_dir, fname)))
        print(f'Loaded {len(all_matches)} matches for backtest')
        # Only keep matches with actual results
        settled = [m for m in all_matches if m.get('actual_result') in ('1', 'X', '2')]
        if settled:
            metrics = runner.evaluate(settled)
            print(f'\n📊 Backtest results ({metrics["total"]} settled matches):')
            print(f'   Accuracy:  {metrics["accuracy"]:.1%}')
            print(f'   Brier:     {metrics["brier_score"]:.4f}')
            print(f'   Value bets placed: {metrics["value_bets_placed"]}')
            print(f'   ROI:       {metrics["roi"]:+.1f}%')
            print(f'   Net P/L:   {metrics["net_profit_units"]:+.1f} units')
        else:
            print('No settled matches found for backtest (need actual_result field).')
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
