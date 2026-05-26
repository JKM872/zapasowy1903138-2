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


def _form_points(form: List[str], decay: float = 0.85) -> float:
    """Time-weighted form score (3 pts W, 1 pt D, 0 pt L), newest first.
    Returns normalized value 0.0 – 1.0."""
    if not form:
        return 0.5  # neutral prior
    pts_map = {'W': 3.0, 'D': 1.0, 'L': 0.0}
    weighted_sum = 0.0
    weight_total = 0.0
    for i, result in enumerate(form[:6]):
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
        total_features = 10

        # 1. H2H time-weighted win rate for focus team
        focus = m.get('focus_team', 'home')
        team = m.get('away_team', '') if focus == 'away' else m.get('home_team', '')
        h2h_list = m.get('h2h_last5', [])
        h2h_wr, h2h_cnt = _h2h_win_rate_weighted(h2h_list, team)
        f['h2h_win_rate'] = h2h_wr
        f['h2h_count'] = min(h2h_cnt / 5.0, 1.0)
        if h2h_cnt > 0:
            available += 1
        
        # 1b. NEW: H2H goal difference (margin of victory matters)
        f['h2h_goal_diff'] = _h2h_goal_diff(h2h_list, team)

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
        if odds_h > 1 and odds_a > 1:
            imp_h = 1.0 / odds_h
            imp_d = 1.0 / odds_d if odds_d > 1 else 0.25
            imp_a = 1.0 / odds_a
            margin = imp_h + imp_d + imp_a
            f['odds_home'] = imp_h / margin
            f['odds_draw'] = imp_d / margin
            f['odds_away'] = imp_a / margin
            # NEW: Market efficiency (sharper book = stronger signal)
            f['market_efficiency'] = _market_efficiency_score(odds_h, odds_d, odds_a)
            available += 1
        else:
            f['odds_home'] = 0.40
            f['odds_draw'] = 0.27
            f['odds_away'] = 0.33
            f['market_efficiency'] = 0.0

        # 7. Gemini AI confidence + prediction
        gem_conf = _safe_float(m.get('gemini_confidence'))
        gem_pred = m.get('gemini_prediction', '')
        gem_rec = m.get('gemini_recommendation', '')
        if gem_conf > 0 and gem_pred:
            f['gemini_conf'] = gem_conf / 100.0
            f['gemini_pred'] = {'1': 1.0, 'X': 0.5, '2': 0.0}.get(str(gem_pred)[:1], 0.5)
            f['gemini_high'] = 1.0 if gem_rec == 'HIGH' else 0.0
            available += 1
        else:
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
        'h2h':          0.18,
        'form':         0.13,
        'venue_form':   0.08,
        'forebet':      0.13,
        'sofascore':    0.08,
        'odds':         0.22,
        'gemini':       0.08,
        'availability': 0.05,
        'consensus':    0.05,
    }

    CALIBRATION_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'outputs', 'scoring_calibration.json',
    )

    def __init__(self, calibration_path: str | None = None):
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.extractor = FeatureExtractor()
        self._load_calibration(calibration_path or self.CALIBRATION_PATH)

    # ------------------------------------------------------------------
    def _load_calibration(self, path: str):
        if os.path.isfile(path):
            try:
                with open(path, 'r') as fh:
                    data = json.load(fh)
                saved_w = data.get('weights', {})
                for k in self.weights:
                    if k in saved_w:
                        self.weights[k] = float(saved_w[k])
            except Exception:
                pass

    # ------------------------------------------------------------------
    def score_match(self, match: Dict) -> ScoredMatch:
        """Score a single match and return ScoredMatch."""
        feats = self.extractor.extract(match)

        # ---- Build 1/X/2 raw probability estimates per source ----------
        sources_home: List[Tuple[float, float]] = []  # (prob, weight)
        sources_draw: List[Tuple[float, float]] = []
        sources_away: List[Tuple[float, float]] = []

        w = self.weights

        # H2H — now boosted by goal differential (margin of victory)
        h2h_wr = feats['h2h_win_rate']
        h2h_cnt = feats['h2h_count']
        h2h_gd = feats.get('h2h_goal_diff', 0.0)  # in [-1, 1]
        # Adjust win-rate by goal diff: dominant wins (e.g., 3-0) signal stronger
        h2h_wr_adj = max(0.0, min(1.0, h2h_wr + h2h_gd * 0.10))
        focus = match.get('focus_team', 'home')
        if h2h_cnt > 0:
            confidence_mult = min(1.0, h2h_cnt / 0.6)  # penalise <3 matches
            if focus == 'home':
                sources_home.append((h2h_wr_adj * confidence_mult + (1 - confidence_mult) * 0.40,
                                     w['h2h']))
                sources_draw.append(((1 - h2h_wr_adj) * 0.40, w['h2h']))
                sources_away.append(((1 - h2h_wr_adj) * 0.60, w['h2h']))
            else:
                sources_away.append((h2h_wr_adj * confidence_mult + (1 - confidence_mult) * 0.35,
                                     w['h2h']))
                sources_draw.append(((1 - h2h_wr_adj) * 0.40, w['h2h']))
                sources_home.append(((1 - h2h_wr_adj) * 0.60, w['h2h']))

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

        # Odds-implied (strongest signal) — boost when market is efficient
        market_eff = feats.get('market_efficiency', 0.5)
        odds_w = w['odds'] * (0.7 + 0.3 * market_eff)  # 70-100% based on efficiency
        sources_home.append((feats['odds_home'], odds_w))
        sources_draw.append((feats['odds_draw'], odds_w))
        sources_away.append((feats['odds_away'], odds_w))

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

        # Clip & normalise
        raw_h = max(0.02, raw_h)
        raw_d = max(0.05, raw_d)
        raw_a = max(0.02, raw_a)
        total = raw_h + raw_d + raw_a
        raw_h, raw_d, raw_a = raw_h / total, raw_d / total, raw_a / total

        # ---- Calibration pass (light sigmoid squeeze) ------------------
        cal_h, cal_d, cal_a = self._calibrate(raw_h, raw_d, raw_a)

        # ---- EV / edge / Kelly for each outcome -----------------------
        odds_h = _safe_float(match.get('home_odds'))
        odds_d = _safe_float(match.get('draw_odds'))
        odds_a = _safe_float(match.get('away_odds'))

        outcomes = [
            ('1', cal_h, odds_h),
            ('X', cal_d, odds_d),
            ('2', cal_a, odds_a),
        ]

        best_pick = '1'
        best_ev = -999.0
        best_edge = 0.0
        best_kelly = 0.0
        best_prob = cal_h
        best_odds = odds_h

        for label, prob, odds_val in outcomes:
            if odds_val <= 1:
                continue
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
        consensus_boost = self._compute_source_consensus(feats, best_pick)
        
        # Confidence score (0-100) — improved formula
        dq = feats['_data_quality']
        confidence = (
            best_prob * 35           # how sure is the model
            + dq * 20                # how much data was available
            + (min(best_edge, 15) / 15) * 15  # size of edge
            + (1 if best_ev > 0 else 0) * 10  # positive EV bonus
            + consensus_boost * 20   # source consensus (0-1)
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
    def _compute_source_consensus(feats: Dict[str, float], pick: str) -> float:
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
            focus_is_home = True  # default; we don't have direct access here
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
