"""
Baseball Scoring Engine – 2-outcome moneyline probability model
================================================================

Purpose-built for baseball where:
 • Starting pitcher is the dominant factor (~35 % weight)
 • Traditional "last 5 form" is nearly meaningless because teams
   play 4-5 consecutive games against each other (series)
 • H2H is extended to 20 games with lighter decay
 • No draw outcome – only home win / away win

Feature weights (tunable via calibration JSON):
 1. Starter pitcher matchup quality   (0.35)
 2. Odds-implied probabilities        (0.25)
 3. Extended H2H (20-game window)     (0.10)
 4. Recent team form (softer decay)   (0.08)
 5. Forebet / external prediction     (0.10)
 6. Back-to-back / fatigue signal     (0.07)
 7. Gemini AI signal                  (0.05)

Usage (standalone):
    python baseball_scoring_engine.py --file results/matches_baseball_2026-04-05.json

Usage (programmatic):
    from baseball_scoring_engine import BaseballScoringEngine
    engine = BaseballScoringEngine()
    result = engine.score_match(match_dict)
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Union


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScoredBaseballMatch:
    """Output of the baseball scoring engine for a single game."""
    home_team: str
    away_team: str
    sport: str = "baseball"

    # 2-outcome probabilities (sum to 1.0)
    prob_home: float = 0.50
    prob_away: float = 0.50

    # Calibrated probabilities
    cal_home: float = 0.0
    cal_away: float = 0.0

    # Best pick
    best_pick: str = ''        # '1' (home) or '2' (away)
    best_prob: float = 0.0
    best_odds: float = 0.0

    # Value metrics
    ev: float = 0.0
    edge: float = 0.0          # our prob – implied prob (%)
    kelly: float = 0.0
    roi_estimate: float = 0.0

    # Confidence / quality
    confidence: float = 0.0    # 0-100
    data_quality: float = 0.0  # 0-1

    # Pitcher info
    pitcher_home: str = ''
    pitcher_away: str = ''
    pitcher_available: bool = False

    # Series context
    is_series_game: bool = False
    series_game_number: int = 0
    is_back_to_back: bool = False

    # Feature breakdown
    features: Dict[str, float] = field(default_factory=lambda: {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            'home_team': self.home_team,
            'away_team': self.away_team,
            'sport': self.sport,
            'prob_1': round(self.cal_home or self.prob_home, 4),
            'prob_2': round(self.cal_away or self.prob_away, 4),
            'best_pick': self.best_pick,
            'best_prob': round(self.best_prob, 4),
            'best_odds': self.best_odds,
            'ev': round(self.ev, 4),
            'edge': round(self.edge, 2),
            'kelly': round(self.kelly, 2),
            'confidence': round(self.confidence, 1),
            'data_quality': round(self.data_quality, 2),
            'pitcher_home': self.pitcher_home,
            'pitcher_away': self.pitcher_away,
            'pitcher_available': self.pitcher_available,
            'is_series_game': self.is_series_game,
            'is_back_to_back': self.is_back_to_back,
            'features': {k: round(v, 4) if isinstance(v, float) else v
                         for k, v in self.features.items()},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _parse_form(raw: Union[List[Any], str, None]) -> List[str]:
    """Normalize form data to list of 'W'/'L' (no draws in baseball)."""
    if isinstance(raw, list):
        return [str(x).upper()[:1] for x in raw if str(x).upper()[:1] in ('W', 'L')]
    if isinstance(raw, str):
        raw = raw.replace('[', '').replace(']', '').replace("'", '').replace('"', '')
        return [x.strip().upper()[:1] for x in re.split(r'[,\s]+', raw)
                if x.strip().upper()[:1] in ('W', 'L')]
    return []


def _form_points_baseball(form: List[str], decay: float = 0.95) -> float:
    """Time-weighted form score for baseball.
    Softer decay than football (0.95 vs 0.85) because daily games
    make short streaks less meaningful.
    Returns 0.0–1.0 (0.5 = neutral)."""
    if not form:
        return 0.5
    pts_map = {'W': 1.0, 'L': 0.0}
    weighted_sum = 0.0
    weight_total = 0.0
    for i, result in enumerate(form[:10]):  # look at last 10 games
        w = decay ** i
        weighted_sum += pts_map.get(result, 0.5) * w
        weight_total += w
    return weighted_sum / weight_total if weight_total > 0 else 0.5


def _h2h_win_rate_extended(h2h: List[Dict[str, Any]], team_name: str,
                            decay: float = 0.95,
                            max_games: int = 20) -> Tuple[float, int]:
    """Extended H2H win rate for baseball (20-game window, lighter decay).
    Returns (weighted_rate, count)."""
    if not h2h or not team_name:
        return 0.5, 0

    team_lower = team_name.lower().strip()
    w_sum = 0.0
    w_total = 0.0
    counted = 0

    for i, item in enumerate(h2h[:max_games]):
        score = item.get('score', '')
        sm = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score)
        if not sm:
            continue
        gh = int(sm.group(1))
        ga = int(sm.group(2))
        h_home = item.get('home', '').lower().strip()

        weight = decay ** i

        if gh > ga:
            winner = h_home
        elif ga > gh:
            winner = item.get('away', '').lower().strip()
        else:
            winner = None  # extremely rare in baseball (suspended)

        if winner is None:
            pts = 0.5
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


def _detect_series_context(h2h: List[Dict[str, Any]], home_team: str,
                            away_team: str) -> Dict[str, Any]:
    """Detect if teams are in a back-to-back series (same opponent
    in recent games)."""
    if not h2h:
        return {'is_series': False, 'game_number': 0, 'is_back_to_back': False}

    ht = home_team.lower().strip()
    at = away_team.lower().strip()
    consecutive = 0

    for item in h2h:
        h = item.get('home', '').lower().strip()
        a = item.get('away', '').lower().strip()
        pair_match = (
            (ht in h or h in ht) and (at in a or a in at)
        ) or (
            (ht in a or a in ht) and (at in h or h in at)
        )
        if pair_match:
            consecutive += 1
        else:
            break

    return {
        'is_series': consecutive >= 2,
        'game_number': consecutive + 1,  # this would be the next game
        'is_back_to_back': consecutive >= 1,
    }


def _pitcher_quality_signal(match: Dict[str, Any]) -> Tuple[float, float, bool]:
    """Extract pitcher quality signals.
    Returns (home_pitcher_score, away_pitcher_score, pitcher_available).

    Pitcher data fields expected in match dict:
      - pitcher_home: str (name)
      - pitcher_away: str (name)
      - pitcher_home_era: float (earned run average, lower = better)
      - pitcher_away_era: float
      - pitcher_home_whip: float (walks+hits per inning, lower = better)
      - pitcher_away_whip: float
      - pitcher_home_record_w: int
      - pitcher_home_record_l: int
      - pitcher_away_record_w: int
      - pitcher_away_record_l: int
    """
    p_home = match.get('pitcher_home', '')
    p_away = match.get('pitcher_away', '')

    if not p_home or not p_away:
        return 0.5, 0.5, False

    # ERA-based quality (lower ERA → better pitcher → higher score)
    # MLB average ERA ≈ 4.00; elite < 3.00; bad > 5.00
    era_h = _safe_float(match.get('pitcher_home_era'), 4.00)
    era_a = _safe_float(match.get('pitcher_away_era'), 4.00)

    # Clamp ERA to [1.5, 7.0] for normalisation
    era_h = max(1.5, min(7.0, era_h))
    era_a = max(1.5, min(7.0, era_a))

    # Invert: lower ERA → higher score (0–1)
    score_h_era = 1.0 - (era_h - 1.5) / 5.5
    score_a_era = 1.0 - (era_a - 1.5) / 5.5

    # WHIP-based quality (lower WHIP → better, avg ≈ 1.25)
    whip_h = _safe_float(match.get('pitcher_home_whip'), 1.25)
    whip_a = _safe_float(match.get('pitcher_away_whip'), 1.25)
    whip_h = max(0.7, min(2.0, whip_h))
    whip_a = max(0.7, min(2.0, whip_a))
    score_h_whip = 1.0 - (whip_h - 0.7) / 1.3
    score_a_whip = 1.0 - (whip_a - 0.7) / 1.3

    # Win record (win percentage of starter)
    hw = _safe_float(match.get('pitcher_home_record_w'))
    hl = _safe_float(match.get('pitcher_home_record_l'))
    aw = _safe_float(match.get('pitcher_away_record_w'))
    al = _safe_float(match.get('pitcher_away_record_l'))

    h_wp = hw / (hw + hl) if (hw + hl) > 0 else 0.5
    a_wp = aw / (aw + al) if (aw + al) > 0 else 0.5

    # Composite pitcher score: ERA 50 %, WHIP 30 %, W-L record 20 %
    home_score = score_h_era * 0.50 + score_h_whip * 0.30 + h_wp * 0.20
    away_score = score_a_era * 0.50 + score_a_whip * 0.30 + a_wp * 0.20

    return home_score, away_score, True


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

class BaseballFeatureExtractor:
    """Extract normalised features from a baseball match dict."""

    # Baseball home advantage is lower: ~54 % home win historically
    HOME_ADVANTAGE = 0.54

    def extract(self, m: Dict[str, Any]) -> Dict[str, float]:
        f: Dict[str, float] = {}
        available = 0
        total_features = 7

        # 1. Pitcher matchup (CRITICAL)
        h_pitch, a_pitch, p_avail = _pitcher_quality_signal(m)
        f['pitcher_home'] = h_pitch
        f['pitcher_away'] = a_pitch
        f['pitcher_available'] = 1.0 if p_avail else 0.0
        if p_avail:
            available += 1

        # 2. Extended H2H (20 games, softer decay)
        focus = m.get('focus_team', 'home')
        team = m.get('away_team', '') if focus == 'away' else m.get('home_team', '')
        h2h_list = m.get('h2h_last5', [])  # field name from scraper; we use up to 20
        h2h_wr, h2h_cnt = _h2h_win_rate_extended(h2h_list, team)
        f['h2h_win_rate'] = h2h_wr
        f['h2h_count'] = min(h2h_cnt / 20.0, 1.0)
        if h2h_cnt > 0:
            available += 1

        # 3. Series context
        series = _detect_series_context(
            h2h_list,
            m.get('home_team', ''),
            m.get('away_team', ''),
        )
        f['is_series'] = 1.0 if series['is_series'] else 0.0
        f['series_game_num'] = min(series['game_number'] / 5.0, 1.0)
        f['is_back_to_back'] = 1.0 if series['is_back_to_back'] else 0.0

        # 4. Team form (softer decay, 10-game window)
        home_form = _parse_form(m.get('home_form_overall', m.get('home_form', [])))
        away_form = _parse_form(m.get('away_form_overall', m.get('away_form', [])))
        f['home_form'] = _form_points_baseball(home_form)
        f['away_form'] = _form_points_baseball(away_form)
        if home_form:
            available += 1

        # 5. Forebet probability
        fb_prob = _safe_float(m.get('forebet_probability'))
        fb_pred = m.get('forebet_prediction', '')
        if fb_prob > 0 and fb_pred:
            f['forebet_prob'] = fb_prob / 100.0
            # Baseball Forebet uses '1' (home) or '2' (away)
            f['forebet_pred'] = {'1': 1.0, '2': 0.0}.get(str(fb_pred), 0.5)
            available += 1
        else:
            f['forebet_prob'] = 0.5
            f['forebet_pred'] = 0.5

        # 6. Market odds → implied probabilities (2-outcome, no draw)
        odds_h = _safe_float(m.get('home_odds'))
        odds_a = _safe_float(m.get('away_odds'))
        if odds_h > 1 and odds_a > 1:
            imp_h = 1.0 / odds_h
            imp_a = 1.0 / odds_a
            margin = imp_h + imp_a
            f['odds_home'] = imp_h / margin
            f['odds_away'] = imp_a / margin
            available += 1
        else:
            f['odds_home'] = 0.50
            f['odds_away'] = 0.50

        # 7. Gemini AI
        gem_conf = _safe_float(m.get('gemini_confidence'))
        gem_pred = m.get('gemini_prediction', '')
        gem_rec = m.get('gemini_recommendation', '')
        if gem_conf > 0 and gem_pred:
            f['gemini_conf'] = gem_conf / 100.0
            f['gemini_pred'] = {'1': 1.0, '2': 0.0}.get(str(gem_pred)[:1], 0.5)
            f['gemini_high'] = 1.0 if gem_rec == 'HIGH' else 0.0
            available += 1
        else:
            f['gemini_conf'] = 0.5
            f['gemini_pred'] = 0.5
            f['gemini_high'] = 0.0

        f['_data_quality'] = available / total_features
        return f


# ---------------------------------------------------------------------------
# Core scoring model
# ---------------------------------------------------------------------------

class BaseballScoringEngine:
    """
    Weighted-ensemble probability model for baseball moneyline (home/away).

    Key difference from FootballScoringEngine:
      • 2 outcomes only (no draw)
      • Pitcher matchup is the single heaviest signal
      • Form is severely down-weighted vs football
      • H2H window is 20 games with lighter decay
      • Series/back-to-back context adjusts fatigue
    """

    DEFAULT_WEIGHTS = {
        'pitcher':  0.35,
        'odds':     0.25,
        'h2h':      0.10,
        'form':     0.08,
        'forebet':  0.10,
        'fatigue':  0.07,
        'gemini':   0.05,
    }

    CALIBRATION_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'outputs', 'baseball_scoring_calibration.json',
    )

    def __init__(self, calibration_path: str | None = None):
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.extractor = BaseballFeatureExtractor()
        self._load_calibration(calibration_path or self.CALIBRATION_PATH)

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

    def score_match(self, match: Dict[str, Any]) -> ScoredBaseballMatch:
        """Score a single baseball game and return ScoredBaseballMatch."""
        feats = self.extractor.extract(match)
        w = self.weights

        sources_home: List[Tuple[float, float]] = []
        sources_away: List[Tuple[float, float]] = []

        # ── 1. Pitcher matchup (dominant signal) ──────────────────────
        ph = feats['pitcher_home']
        pa = feats['pitcher_away']
        if feats['pitcher_available'] > 0:
            # Pitcher advantage → probability shift
            diff = ph - pa  # positive = home pitcher better
            pitcher_home_p = 0.50 + diff * 0.35  # max ±35 pp shift
            pitcher_home_p = max(0.20, min(0.80, pitcher_home_p))
            sources_home.append((pitcher_home_p, w['pitcher']))
            sources_away.append((1.0 - pitcher_home_p, w['pitcher']))
        else:
            # No pitcher data — fall back to mild home advantage prior
            sources_home.append((0.54, w['pitcher'] * 0.3))
            sources_away.append((0.46, w['pitcher'] * 0.3))

        # ── 2. Odds-implied (strong anchor) ───────────────────────────
        sources_home.append((feats['odds_home'], w['odds']))
        sources_away.append((feats['odds_away'], w['odds']))

        # ── 3. Extended H2H ───────────────────────────────────────────
        h2h_wr = feats['h2h_win_rate']
        h2h_cnt = feats['h2h_count']
        focus = match.get('focus_team', 'home')
        if h2h_cnt > 0:
            # Dampen H2H when it's a same-series pair (less informative)
            series_dampen = 0.6 if feats['is_series'] > 0 else 1.0
            effective_w = w['h2h'] * series_dampen
            if focus == 'home':
                sources_home.append((h2h_wr, effective_w))
                sources_away.append((1.0 - h2h_wr, effective_w))
            else:
                sources_away.append((h2h_wr, effective_w))
                sources_home.append((1.0 - h2h_wr, effective_w))

        # ── 4. Team form (soft weight) ────────────────────────────────
        hf = feats['home_form']
        af = feats['away_form']
        form_diff = hf - af
        form_home = 0.50 + form_diff * 0.20
        form_home = max(0.30, min(0.70, form_home))
        sources_home.append((form_home, w['form']))
        sources_away.append((1.0 - form_home, w['form']))

        # ── 5. Forebet ────────────────────────────────────────────────
        fb = feats['forebet_prob']
        fp = feats['forebet_pred']
        if fb != 0.5:
            if fp > 0.7:   # home predicted
                sources_home.append((fb, w['forebet']))
                sources_away.append((1.0 - fb, w['forebet']))
            elif fp < 0.3:  # away predicted
                sources_away.append((fb, w['forebet']))
                sources_home.append((1.0 - fb, w['forebet']))
            else:
                sources_home.append((0.50, w['forebet']))
                sources_away.append((0.50, w['forebet']))

        # ── 6. Fatigue / back-to-back ─────────────────────────────────
        b2b = feats['is_back_to_back']
        series_num = feats['series_game_num']
        # Later games in a series → bullpen fatigue → slight regression to mean
        fatigue_shift = b2b * 0.03 + max(0, (series_num - 0.4)) * 0.02
        fatigue_home = 0.50 - fatigue_shift * 0.5  # regress toward 50/50
        fatigue_home = max(0.40, min(0.60, fatigue_home))
        sources_home.append((fatigue_home, w['fatigue']))
        sources_away.append((1.0 - fatigue_home, w['fatigue']))

        # ── 7. Gemini AI ──────────────────────────────────────────────
        gc = feats['gemini_conf']
        gp = feats['gemini_pred']
        gh = feats['gemini_high']
        gem_w = w['gemini'] * (1.0 + 0.3 * gh)
        if gc != 0.5:
            if gp > 0.7:
                sources_home.append((gc, gem_w))
                sources_away.append((1.0 - gc, gem_w))
            elif gp < 0.3:
                sources_away.append((gc, gem_w))
                sources_home.append((1.0 - gc, gem_w))
            else:
                sources_home.append((0.50, gem_w))
                sources_away.append((0.50, gem_w))

        # ── Weighted average ──────────────────────────────────────────
        def _wavg(pairs: List[Tuple[float, float]]) -> float:
            if not pairs:
                return 0.50
            wsum = sum(p * wt for p, wt in pairs)
            wtot = sum(wt for _, wt in pairs)
            return wsum / wtot if wtot > 0 else 0.50

        raw_home = _wavg(sources_home)
        raw_away = _wavg(sources_away)

        # Normalise to sum = 1.0
        total = raw_home + raw_away
        if total > 0:
            raw_home /= total
            raw_away /= total
        else:
            raw_home, raw_away = 0.50, 0.50

        # ── Build result ──────────────────────────────────────────────
        sm = ScoredBaseballMatch(
            home_team=match.get('home_team', '?'),
            away_team=match.get('away_team', '?'),
            prob_home=raw_home,
            prob_away=raw_away,
            cal_home=raw_home,
            cal_away=raw_away,
        )

        # Best pick
        if raw_home >= raw_away:
            sm.best_pick = '1'
            sm.best_prob = raw_home
            sm.best_odds = _safe_float(match.get('home_odds'))
        else:
            sm.best_pick = '2'
            sm.best_prob = raw_away
            sm.best_odds = _safe_float(match.get('away_odds'))

        # EV, edge, Kelly
        if sm.best_odds > 1:
            implied = 1.0 / sm.best_odds
            sm.edge = round((sm.best_prob - implied) * 100, 2)
            sm.ev = round(sm.best_prob * sm.best_odds - 1.0, 4)
            if sm.best_odds > 1:
                sm.kelly = round(
                    max(0, (sm.best_prob * (sm.best_odds - 1)
                            - (1 - sm.best_prob)) / (sm.best_odds - 1)) * 100,
                    2,
                )

        sm.roi_estimate = round(sm.ev * 100, 2) if sm.ev > 0 else 0.0

        # Confidence (0-100)
        dq = feats['_data_quality']
        base_conf = sm.best_prob * 100
        # Boost if pitcher data is present; penalise if missing
        pitcher_bonus = 10 if feats['pitcher_available'] > 0 else -15
        sm.confidence = round(
            max(0, min(100, base_conf * 0.7 + dq * 30 + pitcher_bonus)), 1
        )
        sm.data_quality = round(dq, 2)

        # Pitcher metadata
        sm.pitcher_home = match.get('pitcher_home', '')
        sm.pitcher_away = match.get('pitcher_away', '')
        sm.pitcher_available = feats['pitcher_available'] > 0

        # Series context
        series = _detect_series_context(
            match.get('h2h_last5', []),
            match.get('home_team', ''),
            match.get('away_team', ''),
        )
        sm.is_series_game = series['is_series']
        sm.series_game_number = series['game_number']
        sm.is_back_to_back = series['is_back_to_back']

        sm.features = feats
        return sm


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Baseball Scoring Engine')
    parser.add_argument('--file', required=True, help='JSON file with match data')
    args = parser.parse_args()

    with open(args.file, 'r', encoding='utf-8') as fh:
        raw_data: Any = json.load(fh)

    matches: List[Dict[str, Any]] = [raw_data] if isinstance(raw_data, dict) else raw_data

    engine = BaseballScoringEngine()

    print(f"\n⚾ Baseball Scoring Engine — {len(matches)} games\n")
    print(f"{'Home':<20} {'Away':<20} {'Pick':>4} {'Prob':>6} "
          f"{'Odds':>5} {'EV':>6} {'Edge':>6} {'Conf':>5} {'Pitcher?':>8}")
    print("─" * 100)

    for m in matches:
        result = engine.score_match(m)
        tag = "✅" if result.pitcher_available else "❌"
        print(f"{result.home_team:<20} {result.away_team:<20} "
              f"{result.best_pick:>4} {result.best_prob:>6.1%} "
              f"{result.best_odds:>5.2f} {result.ev:>6.3f} "
              f"{result.edge:>5.1f}% {result.confidence:>5.1f} "
              f"{tag:>8}")

    print()


if __name__ == '__main__':
    main()
