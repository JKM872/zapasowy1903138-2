"""
🎾 TENNIS SCORING ENGINE v5
============================
Unified probability model for tennis — Player A / Player B semantics.
NO home/away bias.  Two-outcome only (no draw in tennis).

Factors (weights sum to 1.0):
  H2H recency-weighted   0.25
  Current form            0.20
  Surface form            0.15
  Ranking gap             0.12
  Odds-implied            0.10
  Fatigue / freshness     0.08
  SofaScore fan vote      0.10

Qualification threshold: 45/100 advanced_score  (configurable)

Hard skip (before scoring):
  - Missing last H2H date/score
  - Missing last match for either player
  - Odds < 1.35 on either side
  - Missing SofaScore fan vote (enforced in scrape_and_notify.py)

Outputs per match:
  prob_a, prob_b          calibrated win probabilities (sum ≈ 1)
  best_pick               'A' or 'B'
  ev, edge, kelly         value metrics (when odds available)
  confidence              0-100 composite
  data_quality            0-1
  breakdown               per-factor detail dict
"""

from __future__ import annotations
import math
import re
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast

# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScoredTennisMatch:
    """Full output of the tennis scoring engine for a single match."""
    player_a: str
    player_b: str

    # Raw probability estimates (sum to 1.0)
    prob_a: float = 0.5
    prob_b: float = 0.5

    # Calibrated probabilities
    cal_a: float = 0.5
    cal_b: float = 0.5

    # Best pick
    best_pick: str = ''        # 'A' or 'B'
    best_prob: float = 0.5
    best_odds: float = 0.0
    favorite: str = ''         # 'player_a' or 'player_b'

    # Value metrics
    ev: float = 0.0
    edge: float = 0.0
    kelly: float = 0.0

    # Confidence / quality
    advanced_score: float = 0.0   # 0-100 (replaces old advanced_score)
    confidence: float = 0.0       # 0-100
    data_quality: float = 0.0     # 0-1

    # Factor breakdown
    breakdown: Dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]
    features: Dict[str, Any] = field(default_factory=dict)  # pyright: ignore[reportUnknownVariableType]

    # Surface / ranking metadata (for display)
    surface: str = ''
    ranking_a: Optional[int] = None
    ranking_b: Optional[int] = None


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _sf(val: Any, default: float = 0.0) -> float:
    """Safe float."""
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (ValueError, TypeError):
        return default


def _parse_form_list(raw: Any) -> List[str]:
    """Normalise form data to list of 'W'/'L' (no draws in tennis)."""
    if isinstance(raw, list):
        raw_items: List[Any] = cast(List[Any], raw)
        out: List[str] = []
        for x in raw_items:
            c = str(x).upper()[:1]
            if c in ('W', 'L'):
                out.append(c)
            elif c == 'D':
                out.append('L')   # no draws in tennis
        return out
    if isinstance(raw, str):
        raw = raw.replace('[', '').replace(']', '').replace("'", '').replace('"', '')
        out_str: List[str] = []
        for token in re.split(r'[,\s\-;]+', raw):
            token = token.strip().upper()
            if not token:
                continue
            # A run like "WLWLW" is one token but five results. Taking only the
            # first character silently reduced a five-match form to a
            # one-match form, which reads as present and carries almost nothing.
            chars = list(token) if len(token) > 1 and all(
                c in 'WLD' for c in token) else [token[:1]]
            for c in chars:
                if c in ('W', 'L'):
                    out_str.append(c)
                elif c == 'D':
                    out_str.append('L')   # no draws in tennis
        return out_str
    return []


def _form_score(form: List[str], decay: float = 0.85) -> float:
    """Time-weighted form score, newest first.  Returns 0-1."""
    if not form:
        return 0.5
    pts_map = {'W': 1.0, 'L': 0.0}
    total_w, total_pts = 0.0, 0.0
    for i, r in enumerate(form[:10]):
        w = decay ** i
        total_w += w
        total_pts += w * pts_map.get(r, 0.5)
    return total_pts / total_w if total_w > 0 else 0.5


def _first_form(m: Dict[str, Any], *keys: str) -> List[str]:
    """First key that actually holds form letters, in preference order.

    ``m.get('form_a', m.get('home_form'))`` looked equivalent but is not: a key
    present and empty wins over a later key that has data, so one scraper
    writing ``form_a=[]`` silenced every other source.
    """
    for key in keys:
        parsed = _parse_form_list(m.get(key, []))
        if parsed:
            return parsed
    return []


def _streak_len(form: List[str], char: str = 'W') -> int:
    """Length of leading streak of `char` in form."""
    n = 0
    for r in form:
        if r == char:
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------------------
# NEW (v6): Hierarchical serve/point match model
# ---------------------------------------------------------------------------

def _prob_win_game(p: float) -> float:
    """Probability the server holds a game given per-point win prob ``p``.

    Closed-form solution of the standard tennis game Markov chain (first to 4
    points, win by 2, including deuce). Returns the probability the *server*
    wins the game.
    """
    p = max(0.01, min(0.99, p))
    q = 1.0 - p
    # Win to love/15/30 (reach 4 points before opponent gets 3, no deuce):
    #   P(40-0) + P(40-15) + P(40-30)
    p_no_deuce = (
        p ** 4                                  # 4-0
        + 4 * p ** 4 * q                        # 4-1
        + 10 * p ** 4 * q ** 2                   # 4-2
    )
    # Deuce reached at 3-3 (each won 3 of 6 points): C(6,3)=20
    p_deuce = 20 * p ** 3 * q ** 3
    denom = (p ** 2 + q ** 2)
    p_win_from_deuce = (p ** 2 / denom) if denom > 0 else 0.5
    return p_no_deuce + p_deuce * p_win_from_deuce


def _prob_win_set(pg_serve: float, pg_return: float) -> float:
    """Probability a player wins a set.

    ``pg_serve`` is the player's hold probability (win own service game),
    ``pg_return`` is the probability of breaking (winning a return game).
    Computes a 6-game, win-by-2 set with a tie-break at 6-6, assuming the
    player serves first (averaged out across game pairs).
    """
    pg_serve = max(0.01, min(0.99, pg_serve))
    pg_return = max(0.01, min(0.99, pg_return))

    # Per game-pair (one serve + one return) the player wins g of the two.
    # Approximate the set as a race to 6 games using the average per-game
    # win probability, with win-by-2 and a tie-break modelled at 6-6.
    from math import comb

    # Probability of winning a single game averaged over serve/return.
    pg = 0.5 * pg_serve + 0.5 * pg_return

    pg = max(0.01, min(0.99, pg))
    qg = 1.0 - pg

    # Win set 6-0..6-4 (reach 6 before opponent reaches 5):
    p_clean = 0.0
    for opp in range(0, 5):  # opponent games 0..4
        # last game is a win: arrange (5 wins among first 5+opp games) * win
        p_clean += comb(5 + opp, opp) * (pg ** 6) * (qg ** opp)
    # 7-5: reach 5-5 then win two straight game-pairs (simplified)
    p_5_5 = comb(10, 5) * (pg ** 5) * (qg ** 5)
    p_7_5 = p_5_5 * (pg ** 2)
    # 6-6 tie-break: model as per-point race; approximate with pg.
    p_tb = p_5_5 * (2 * pg * qg) * pg  # reach 6-6 then win TB (~pg)
    return min(0.999, p_clean + p_7_5 + p_tb)


def _prob_win_match_bo3(p_set: float) -> float:
    """Probability of winning a best-of-3 match given per-set win prob."""
    p_set = max(0.01, min(0.99, p_set))
    # Win in straight sets + win after splitting the first two.
    return p_set ** 2 + 2 * p_set ** 2 * (1 - p_set)


def _serve_model_prob_a(serve_adv_a: float) -> float:
    """Match win probability for A from a per-point serve advantage.

    ``serve_adv_a`` in [-1, 1] expresses A's overall point-level edge. We map
    it to per-point serve/return win probabilities around a 0.64 baseline
    (typical ATP service-point win rate), run the game→set→match hierarchy
    for both players, and normalise.
    """
    base = 0.64
    spread = 0.10 * serve_adv_a  # shift point-win rates by the edge
    # A serving / B serving point-win probabilities
    a_serve_pt = max(0.5, min(0.8, base + spread))
    b_serve_pt = max(0.5, min(0.8, base - spread))

    a_hold = _prob_win_game(a_serve_pt)
    b_hold = _prob_win_game(b_serve_pt)
    a_break = 1.0 - b_hold   # A wins a return game when B fails to hold
    a_set = _prob_win_set(a_hold, a_break)
    a_match = _prob_win_match_bo3(a_set)
    # symmetry guard
    return max(0.02, min(0.98, a_match))


def _recency_h2h(h2h_list: List[Dict[str, Any]], player_a: str, player_b: str) -> Tuple[float, int]:
    """
    Recency-weighted H2H win-rate for player A.
    Returns (win_rate_a, count).
    """
    if not h2h_list or not player_a:
        return 0.5, 0

    pa = player_a.lower().strip()
    _pb = (player_b or '').lower().strip()
    now = datetime.now()
    wins_a, total_w = 0.0, 0.0

    for entry in h2h_list[:10]:
        # determine weight by recency
        date_str = entry.get('date', '')
        w = 1.0
        if date_str:
            m = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', str(date_str))
            if m:
                d, mo, y = m.groups()
                yr = int(y)
                if yr < 100:
                    yr = 2000 + yr if yr <= 50 else 1900 + yr
                try:
                    dt = datetime(yr, int(mo), int(d))
                    age_days = (now - dt).days
                    if age_days < 180:
                        w = 2.0
                    elif age_days < 365:
                        w = 1.5
                    else:
                        w = max(0.5, 1.0 - age_days / 3650)
                except ValueError:
                    pass

        # determine who won
        home = (entry.get('home', '') or '').lower().strip()
        away = (entry.get('away', '') or '').lower().strip()
        score = entry.get('score', '')
        sm = re.search(r'(\d+)\s*[:\-]\s*(\d+)', str(score))
        if not sm:
            continue
        s1, s2 = int(sm.group(1)), int(sm.group(2))
        if s1 == s2:
            continue

        winner_is_home = s1 > s2

        a_is_home = (pa in home or home in pa) if pa and home else False
        a_is_away = (pa in away or away in pa) if pa and away else False

        if not a_is_home and not a_is_away:
            continue

        total_w += w
        if (a_is_home and winner_is_home) or (a_is_away and not winner_is_home):
            wins_a += w

    if total_w == 0:
        return 0.5, 0
    return wins_a / total_w, len(h2h_list)


# ---------------------------------------------------------------------------
# Feature Extractor
# ---------------------------------------------------------------------------

class TennisFeatureExtractor:
    """Extract normalised features from a single tennis match dict."""

    def extract(self, m: Dict[str, Any]) -> Dict[str, float]:
        f: Dict[str, float] = {}
        available = 0
        total_features = 7   # h2h, form, surface_form, ranking, odds, fatigue, sofascore

        player_a = m.get('home_team', '') or ''
        player_b = m.get('away_team', '') or ''

        # 1. H2H recency-weighted
        h2h_list: List[Dict[str, Any]] = m.get('h2h_last5', [])
        if h2h_list:
            wr, cnt = _recency_h2h(h2h_list, player_a, player_b)
            f['h2h_win_rate_a'] = wr
            f['h2h_count'] = min(cnt / 5.0, 1.0)
            available += 1
        else:
            # fallback to simple counts
            a_wins = _sf(m.get('home_wins_in_h2h_last5', m.get('home_wins_in_h2h', 0)))
            b_wins = _sf(m.get('away_wins_in_h2h_last5', m.get('away_wins_in_h2h', 0)))
            total = a_wins + b_wins
            f['h2h_win_rate_a'] = a_wins / total if total > 0 else 0.5
            f['h2h_count'] = min(total / 5.0, 1.0)
            if total > 0:
                available += 1

        # 2. Current form
        # `home_form_overall` is included because that is the field the rest of
        # the pipeline fills — the football extractor reads it, the email card
        # renders it, and team_form.FormProvider writes it. Reading only
        # `form_a`/`home_form` meant store-derived form never reached this
        # engine: measured Brier was 0.5000 with and without form, identical to
        # the base rate, because the numbers were sitting in a key nobody here
        # looked at.
        form_a = _first_form(m, 'form_a', 'home_form_overall', 'home_form')
        form_b = _first_form(m, 'form_b', 'away_form_overall', 'away_form')
        f['form_a'] = _form_score(form_a)
        f['form_b'] = _form_score(form_b)
        f['form_advantage'] = f['form_a'] - f['form_b']  # >0 = A better
        # Clamped: the divisor assumes a five-match form list, so a ten-match
        # winning run used to leave this at 2.0 and push a feature that is
        # documented as normalised outside [0, 1].
        f['streak_a'] = min(1.0, _streak_len(form_a, 'W') / 5.0)
        f['streak_b'] = min(1.0, _streak_len(form_b, 'W') / 5.0)
        if form_a or form_b:
            available += 1

        # 3. Surface form (from real surface_form_a/b or surface_stats_a/b)
        surface = m.get('surface', '')
        # Prefer new surface_form lists (last 5 matches on surface)
        sf_a = _parse_form_list(m.get('surface_form_a', []))
        sf_b = _parse_form_list(m.get('surface_form_b', []))
        if sf_a or sf_b:
            f['surface_wr_a'] = _form_score(sf_a) if sf_a else 0.5
            f['surface_wr_b'] = _form_score(sf_b) if sf_b else 0.5
            f['surface_advantage'] = f['surface_wr_a'] - f['surface_wr_b']
            available += 1
        else:
            # Fallback to old surface_stats dicts
            surface_stats_a = m.get('surface_stats_a')
            surface_stats_b = m.get('surface_stats_b')
            if surface and surface_stats_a and surface_stats_b:
                sa = _sf(surface_stats_a.get(surface, 0.5))
                sb = _sf(surface_stats_b.get(surface, 0.5))
                f['surface_wr_a'] = sa
                f['surface_wr_b'] = sb
                f['surface_advantage'] = sa - sb
                available += 1
            else:
                f['surface_wr_a'] = 0.5
                f['surface_wr_b'] = 0.5
                f['surface_advantage'] = 0.0

        # 4. Ranking gap
        rank_a = m.get('ranking_a')
        rank_b = m.get('ranking_b')
        if rank_a and rank_b:
            ra, rb = int(rank_a), int(rank_b)
            # normalise: negative gap = A has lower (better) ranking
            gap = rb - ra   # positive = A better
            # sigmoid-like mapping to [0, 1]
            f['ranking_advantage'] = gap / (abs(gap) + 20)  # smooth, bounded ±1
            f['ranking_a_norm'] = max(0, 1 - ra / 200)
            f['ranking_b_norm'] = max(0, 1 - rb / 200)
            available += 1
        else:
            f['ranking_advantage'] = 0.0
            f['ranking_a_norm'] = 0.5
            f['ranking_b_norm'] = 0.5

        # 5. Odds-implied probability
        odds_a = _sf(m.get('home_odds', 0))
        odds_b = _sf(m.get('away_odds', 0))
        if odds_a > 1 and odds_b > 1:
            raw_a = 1 / odds_a
            raw_b = 1 / odds_b
            total = raw_a + raw_b
            f['odds_prob_a'] = raw_a / total
            f['odds_prob_b'] = raw_b / total
            f['odds_a'] = odds_a
            f['odds_b'] = odds_b
            available += 1
        else:
            f['odds_prob_a'] = 0.5
            f['odds_prob_b'] = 0.5
            f['odds_a'] = 0.0
            f['odds_b'] = 0.0

        # 6. Fatigue / freshness (based on last match recency + result)
        f['fatigue_a'] = self._compute_fatigue(m.get('last_match_a_date'), m.get('last_match_a_result'))
        f['fatigue_b'] = self._compute_fatigue(m.get('last_match_b_date'), m.get('last_match_b_result'))
        f['fatigue_advantage'] = f['fatigue_a'] - f['fatigue_b']  # >0 = A fresher/better
        if m.get('last_match_a_date') or m.get('last_match_b_date'):
            available += 1

        # 7. SofaScore fan vote (crowd wisdom signal)
        ss_a = _sf(m.get('sofascore_home_win_prob', 0))
        ss_b = _sf(m.get('sofascore_away_win_prob', 0))
        if ss_a > 0 and ss_b > 0:
            ss_total = ss_a + ss_b
            f['sofascore_prob_a'] = ss_a / ss_total
            f['sofascore_prob_b'] = ss_b / ss_total
            available += 1
        else:
            f['sofascore_prob_a'] = 0.5
            f['sofascore_prob_b'] = 0.5

        f['_data_quality'] = available / total_features

        # 8. Retirement / walkover flags (from data contract or raw data)
        avail = m.get('availability', {})
        if isinstance(avail, dict):
            f['retirement_a'] = 1.0 if avail.get('home_retirement_flag') else 0.0
            f['retirement_b'] = 1.0 if avail.get('away_retirement_flag') else 0.0
            f['avail_impact'] = _sf(avail.get('availability_impact', 0))
        else:
            # Detect from raw last match data
            lm_a_score = str(m.get('last_match_a_score', '') or '').lower()
            lm_b_score = str(m.get('last_match_b_score', '') or '').lower()
            ret_markers = ['ret', 'w.o', 'walkover', 'retired']
            f['retirement_a'] = 1.0 if any(mk in lm_a_score for mk in ret_markers) else 0.0
            f['retirement_b'] = 1.0 if any(mk in lm_b_score for mk in ret_markers) else 0.0
            f['avail_impact'] = 0.0

        return f

    @staticmethod
    def _compute_fatigue(last_match_date: Optional[str], last_match_result: Optional[str]) -> float:
        """
        Compute freshness/fatigue score (0-1) from last match date and result.
        Higher = better condition.
        
        - 1-2 days ago: 0.4 (fatigued)
        - 3-5 days ago: 0.7 (good rhythm)
        - 6-10 days ago: 0.5 (moderate rest)
        - 11+ days ago: 0.35 (rusty)
        - Win bonus: +0.1, Loss penalty: -0.05
        """
        if not last_match_date:
            return 0.5  # neutral

        try:
            now = datetime.now()
            dm = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', str(last_match_date))
            if not dm:
                return 0.5
            d, mo, y = dm.groups()
            yr = int(y)
            if yr < 100:
                yr = 2000 + yr if yr <= 50 else 1900 + yr
            dt = datetime(yr, int(mo), int(d))
            age_days = (now - dt).days

            if age_days <= 0:
                score = 0.5
            elif age_days <= 2:
                score = 0.4   # fatigued
            elif age_days <= 5:
                score = 0.7   # rhythm
            elif age_days <= 10:
                score = 0.5   # moderate
            else:
                score = 0.35  # rusty

            # Result bonus
            if last_match_result == 'W':
                score += 0.1
            elif last_match_result == 'L':
                score -= 0.05

            return max(0.05, min(0.95, score))
        except (ValueError, TypeError):
            return 0.5


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    'h2h':          0.20,
    'form':         0.16,
    'surface_form': 0.12,
    'ranking':      0.11,
    'odds':         0.12,
    'fatigue':      0.07,
    'sofascore':    0.09,
    'availability': 0.05,
    'serve_model':  0.08,
}


class TennisScoringEngine:
    """
    Multi-factor probability model for tennis.
    Two-outcome only (A wins / B wins).
    Threshold for qualification: advanced_score ≥ 45.
    """

    CALIBRATION_FILE = 'outputs/tennis_calibration.json'
    THRESHOLD = 45.0

    def __init__(self, weights: Optional[Dict[str, float]] = None, threshold: Optional[float] = None):
        self.weights: Dict[str, float] = weights or dict(DEFAULT_WEIGHTS)
        self.threshold: float = threshold or self.THRESHOLD
        self.extractor = TennisFeatureExtractor()
        self._load_calibration()

    def _load_calibration(self) -> None:
        self.calibration: Dict[str, Any] = {}
        try:
            if os.path.exists(self.CALIBRATION_FILE):
                with open(self.CALIBRATION_FILE) as fh:
                    self.calibration = json.load(fh)
                    if 'weights' in self.calibration:
                        self.weights = self.calibration['weights']
        except Exception:
            pass

    # ------------------------------------------------------------------
    def score_match(self, match: Dict[str, Any]) -> ScoredTennisMatch:
        feats = self.extractor.extract(match)
        w = self.weights

        # --- Per-source probability estimate for A winning ---
        # `estimates` holds every source's view; `active` lists the sources that
        # actually have data. A source without data must ABSTAIN (be dropped
        # from the weighted average) rather than contribute 0.5 at full weight:
        # the latter drags the prediction toward an even split and makes a
        # data-poor match look deliberately balanced. Tennis is the sport with
        # the thinnest coverage (H2H 33%, form 28%, Forebet/SofaScore 4%), so
        # this used to affect most matches.
        estimates: Dict[str, float] = {}
        active: set = set()

        # H2H
        wr = feats['h2h_win_rate_a']
        estimates['h2h'] = wr
        if feats.get('h2h_count', 0) > 0:
            active.add('h2h')

        # Form
        fa, fb = feats['form_a'], feats['form_b']
        if fa + fb > 0:
            form_p = fa / (fa + fb)
        else:
            form_p = 0.5
        # add streak bonus ± 0.05
        form_p += (feats['streak_a'] - feats['streak_b']) * 0.05
        form_p = max(0.05, min(0.95, form_p))
        estimates['form'] = form_p
        # Same key order as the extractor above, and for the same reason. This
        # gate is what actually decides whether form counts: an inactive source
        # abstains and is dropped from the weighted average, so while these two
        # reads disagreed the form estimate was computed and then discarded.
        # That is why the engine returned exactly 0.5000 on a player with ten
        # straight wins against one with ten straight losses.
        form_a_raw = _first_form(match, 'form_a', 'home_form_overall', 'home_form')
        form_b_raw = _first_form(match, 'form_b', 'away_form_overall', 'away_form')
        if form_a_raw and form_b_raw:
            active.add('form')

        # Surface form
        sa = feats['surface_wr_a']
        sb = feats['surface_wr_b']
        if sa + sb > 0:
            surf_p = sa / (sa + sb)
        else:
            surf_p = 0.5
        estimates['surface_form'] = max(0.05, min(0.95, surf_p))
        # Surface form only counts as its own source when it differs from the
        # overall form. Livesport does not expose per-match tournament info, so
        # the scraper used to copy the overall form here — measured identical in
        # 80% of rows. Counting it again would give one signal 0.16 + 0.12 of
        # the model.
        _surf_a = _parse_form_list(match.get('surface_form_a', []))
        _surf_b = _parse_form_list(match.get('surface_form_b', []))
        # `surface_form_is_proxy is False` means the lists were genuinely
        # filtered by court type (SofaScore groundType). Such a measurement
        # counts as its own source even if it happens to equal the overall
        # form. A proxy that merely echoes the overall form does not.
        _surface_is_real = match.get('surface_form_is_proxy') is False
        if (_surf_a or _surf_b) and (
                _surface_is_real
                or not (_surf_a == form_a_raw and _surf_b == form_b_raw)):
            active.add('surface_form')

        # Ranking
        rank_adv = feats['ranking_advantage']  # [-1,+1], >0 = A better
        rank_p = 0.5 + rank_adv * 0.35         # maps roughly to [0.15, 0.85]
        estimates['ranking'] = max(0.05, min(0.95, rank_p))
        if match.get('ranking_a') and match.get('ranking_b'):
            active.add('ranking')

        # Odds
        estimates['odds'] = feats['odds_prob_a']
        if feats.get('odds_a', 0) > 1 and feats.get('odds_b', 0) > 1:
            active.add('odds')

        # Fatigue / freshness
        fat_a = feats.get('fatigue_a', 0.5)
        fat_b = feats.get('fatigue_b', 0.5)
        if fat_a + fat_b > 0:
            fatigue_p = fat_a / (fat_a + fat_b)
        else:
            fatigue_p = 0.5
        estimates['fatigue'] = max(0.05, min(0.95, fatigue_p))
        if match.get('last_match_a_date') and match.get('last_match_b_date'):
            active.add('fatigue')

        # SofaScore fan vote
        estimates['sofascore'] = feats.get('sofascore_prob_a', 0.5)
        if _sf(match.get('sofascore_home_win_prob')) > 0 and \
                _sf(match.get('sofascore_away_win_prob')) > 0:
            active.add('sofascore')

        # Availability / injury impact.
        # `availability_impact` from prediction_data_contract is an unsigned
        # MAGNITUDE (0 = clean, 1 = severe) describing how unreliable the
        # prediction is — it carries no direction. Treating it as a signed
        # value favoured player A the more uncertain the data was. A neutral
        # 0.5 is the correct starting point; only the retirement flags below
        # carry actual directional information.
        avail_p = 0.5
        # Retirement flag penalty
        ret_a = feats.get('retirement_a', 0)
        ret_b = feats.get('retirement_b', 0)
        if ret_a and not ret_b:
            avail_p = max(avail_p - 0.15, 0.05)
        elif ret_b and not ret_a:
            avail_p = min(avail_p + 0.15, 0.95)
        estimates['availability'] = max(0.05, min(0.95, avail_p))
        # Only a retirement/walkover flag carries direction here; the impact
        # magnitude alone is handled later by shrinking toward 50/50.
        if ret_a or ret_b:
            active.add('availability')

        # Serve/point hierarchical model (v6) — converts an aggregate
        # point-level edge into a best-of-3 match win probability via the
        # game→set→match Markov hierarchy. This captures tennis's structural
        # amplification: a small per-point edge yields a large match edge.
        # The point edge is sourced from ranking gap, surface form and overall
        # form — the factors most predictive of who wins points.
        # The surface term is only included when surface form is a real,
        # independent signal. Otherwise the duplicated overall form would leak
        # back in here and inflate the serve edge a second time.
        _surface_term = (feats.get('surface_advantage', 0.0)
                         if 'surface_form' in active else 0.0)
        serve_adv = (
            feats.get('ranking_advantage', 0.0) * 0.5
            + _surface_term * 0.3
            + feats.get('form_advantage', 0.0) * 0.2
        )
        estimates['serve_model'] = _serve_model_prob_a(max(-1.0, min(1.0, serve_adv)))
        # The serve model is derived from ranking/surface/form, so it only has
        # standing when at least one of those is real.
        if serve_adv != 0.0 and (active & {'ranking', 'surface_form', 'form'}):
            active.add('serve_model')

        # --- Weighted average over the sources that actually have data ---
        # Normalise by the weight sum of ACTIVE sources only. Dividing by the
        # full weight total would leave abstaining sources implicitly voting
        # for 0.5 and bias every data-poor match toward an even split.
        active_weights = {k: w[k] for k in w if k in active}
        if active_weights:
            w_total = sum(active_weights.values()) or 1.0
            prob_a = sum(estimates[k] * wt for k, wt in active_weights.items()) / w_total
        else:
            # Nothing known at all — an honest coin flip.
            prob_a = 0.5
        prob_a = max(0.02, min(0.98, prob_a))

        # Availability uncertainty shrinks the prediction toward 50/50: the
        # less we trust the squad/fitness picture, the less we should commit.
        avail_impact = feats.get('avail_impact', 0.0)
        if avail_impact > 0:
            shrink = max(0.0, min(0.30, avail_impact * 0.30))
            prob_a = prob_a * (1 - shrink) + 0.5 * shrink

        prob_b = 1.0 - prob_a

        # --- Temperature-scaled softmax calibration ---
        temp = self.calibration.get('temperature', 1.10)
        cal_a, cal_b = self._calibrate(prob_a, prob_b, temp)

        # --- Best pick ---
        if cal_a >= cal_b:
            best_pick = 'A'
            best_prob = cal_a
            best_odds = feats['odds_a']
            favorite = 'player_a'
        else:
            best_pick = 'B'
            best_prob = cal_b
            best_odds = feats['odds_b']
            favorite = 'player_b'

        # --- EV / edge / Kelly ---
        ev, edge, kelly = 0.0, 0.0, 0.0
        if best_odds > 1:
            implied = 1.0 / best_odds
            ev = best_prob * best_odds - 1.0
            edge = (best_prob - implied) * 100
            if best_prob > implied and best_odds > 1:
                kelly = max(0, (best_prob * best_odds - 1) / (best_odds - 1)) * 100
                kelly = min(kelly, 25.0)  # cap

        # --- Advanced score (0-100) ---
        # Based on how dominant the prediction is
        dominance = abs(cal_a - cal_b)  # 0 to ~0.96
        advanced_score = dominance * 100  # scale to 0-100
        # Boost for data richness — use weighted data quality that values
        # the most predictive features (odds, h2h, ranking) more than
        # form/surface which are often missing for tennis.
        dq = feats['_data_quality']
        # Weighted DQ: odds(0.30) + h2h(0.25) + ranking(0.20) + form(0.10)
        # + surface(0.05) + fatigue(0.05) + sofascore(0.05)
        _wdq_score = 0.0
        h2h_list_check: List[Dict[str, Any]] = match.get('h2h_last5', [])
        if feats.get('odds_a', 0) > 1:
            _wdq_score += 0.30
        if h2h_list_check:
            _wdq_score += 0.25
        if match.get('ranking_a') and match.get('ranking_b'):
            _wdq_score += 0.20
        form_a_check = _parse_form_list(match.get('form_a', match.get('home_form', [])))
        form_b_check = _parse_form_list(match.get('form_b', match.get('away_form', [])))
        if form_a_check or form_b_check:
            _wdq_score += 0.10
        if feats.get('surface_wr_a', 0.5) != 0.5 or feats.get('surface_wr_b', 0.5) != 0.5:
            _wdq_score += 0.05
        if match.get('last_match_a_date') or match.get('last_match_b_date'):
            _wdq_score += 0.05
        if feats.get('sofascore_prob_a', 0.5) != 0.5:
            _wdq_score += 0.05
        # Use the better of raw dq and weighted dq (never penalize more than before)
        effective_dq = max(dq, _wdq_score)
        advanced_score = advanced_score * (0.5 + 0.5 * effective_dq)
        advanced_score = min(100, max(0, advanced_score))

        _qualifies = advanced_score >= self.threshold

        # --- Confidence ---
        conf = (
            best_prob * 40
            + dq * 30
            + min(max(edge, 0), 20) / 20 * 20
            + (10 if ev > 0 else 0)
        )
        conf = min(100, max(0, conf))

        # --- Build breakdown ---
        breakdown: Dict[str, Any] = {}
        for k in w:
            is_active = k in active
            breakdown[f'{k}_estimate'] = round(estimates[k], 3)
            breakdown[f'{k}_weight'] = w[k]
            # Effective weight after abstentions, so the breakdown shows what
            # really drove the number rather than the nominal configuration.
            eff = (active_weights.get(k, 0.0) / sum(active_weights.values())
                   if active_weights and is_active else 0.0)
            breakdown[f'{k}_active'] = is_active
            breakdown[f'{k}_effective_weight'] = round(eff, 3)
            breakdown[f'{k}_contribution'] = round(estimates[k] * eff, 3)
        breakdown['active_sources'] = sorted(active)

        return ScoredTennisMatch(
            player_a=match.get('home_team', ''),
            player_b=match.get('away_team', ''),
            prob_a=round(prob_a, 4),
            prob_b=round(prob_b, 4),
            cal_a=round(cal_a, 4),
            cal_b=round(cal_b, 4),
            best_pick=best_pick,
            best_prob=round(best_prob, 4),
            best_odds=round(best_odds, 2) if best_odds else 0.0,
            favorite=favorite,
            ev=round(ev, 4),
            edge=round(edge, 2),
            kelly=round(kelly, 2),
            advanced_score=round(advanced_score, 1),
            confidence=round(conf, 1),
            data_quality=round(dq, 2),
            breakdown=breakdown,
            features=feats,
            surface=match.get('surface', ''),
            ranking_a=match.get('ranking_a'),
            ranking_b=match.get('ranking_b'),
        )

    # ------------------------------------------------------------------
    def score_matches(self, matches: List[Dict[str, Any]]) -> List[ScoredTennisMatch]:
        results = [self.score_match(m) for m in matches]
        results.sort(key=lambda x: x.ev, reverse=True)
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _calibrate(p_a: float, p_b: float, temp: float) -> Tuple[float, float]:
        """Temperature-scaled softmax on two logits."""
        logit_a = math.log(max(p_a, 1e-9) / max(1 - p_a, 1e-9))
        logit_b = math.log(max(p_b, 1e-9) / max(1 - p_b, 1e-9))
        scaled = [logit_a / temp, logit_b / temp]
        max_s = max(scaled)
        exps = [math.exp(s - max_s) for s in scaled]
        total = sum(exps)
        return exps[0] / total, exps[1] / total

    # ------------------------------------------------------------------
    def print_report(self, matches: List[Dict[str, Any]]):
        scored = self.score_matches(matches)
        print(f'\n{"="*80}')
        print(f'  TENNIS SCORING ENGINE – {len(scored)} matches')
        print(f'{"="*80}')
        value_bets = [s for s in scored if s.ev > 0]
        print(f'  Value bets:      {len(value_bets)}/{len(scored)}')
        if scored:
            print(f'  Avg confidence:  {sum(s.confidence for s in scored)/len(scored):.1f}/100')
            print(f'  Avg data qual:   {sum(s.data_quality for s in scored)/len(scored):.0%}')
        print()
        for s in scored[:20]:
            ev_marker = '✅' if s.ev > 0 else '  '
            qs = '🎾' if s.advanced_score >= self.threshold else '  '
            print(f'  {ev_marker}{qs} {s.player_a:>25} vs {s.player_b:<25}'
                  f'  pick={s.best_pick}  P={s.best_prob:.0%}'
                  f'  odds={s.best_odds:.2f}  EV={s.ev:+.3f}'
                  f'  edge={s.edge:+.1f}%  K={s.kelly:.1f}%'
                  f'  adv={s.advanced_score:.0f}  conf={s.confidence:.0f}'
                  f'  dq={s.data_quality:.0%}')
        print(f'\n{"="*80}\n')
        return scored


# ---------------------------------------------------------------------------
# Calibration runner (backtest)
# ---------------------------------------------------------------------------

class TennisCalibrationRunner:
    """Evaluate engine on historical matches with known results."""

    def __init__(self, engine: TennisScoringEngine):
        self.engine = engine

    def evaluate(self, matches: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not matches:
            return {'count': 0}

        correct, total, brier_sum = 0, 0, 0.0
        profit = 0.0

        for m in matches:
            result = m.get('result')  # 'A' or 'B'
            if result not in ('A', 'B'):
                continue
            sm = self.engine.score_match(m)
            total += 1

            actual = 1 if result == 'A' else 0
            brier_sum += (sm.cal_a - actual) ** 2

            if sm.best_pick == result:
                correct += 1

            if sm.ev > 0 and sm.best_odds > 1:
                if sm.best_pick == result:
                    profit += sm.best_odds - 1
                else:
                    profit -= 1

        metrics: Dict[str, Any] = {
            'count': total,
            'accuracy': correct / total if total else 0,
            'brier': brier_sum / total if total else 1.0,
            'roi': profit / total if total else 0,
            'net_pl': round(profit, 2),
        }
        return metrics

    def save_calibration(self, weights: Dict[str, float], metrics: Dict[str, Any]) -> None:
        os.makedirs('outputs', exist_ok=True)
        data: Dict[str, Any] = {
            'weights': weights,
            'metrics': metrics,
            'updated': datetime.now().isoformat(),
        }
        with open(TennisScoringEngine.CALIBRATION_FILE, 'w') as fh:
            json.dump(data, fh, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse, glob

    ap = argparse.ArgumentParser(description='Tennis Scoring Engine')
    ap.add_argument('--file', help='JSON file with matches to score')
    ap.add_argument('--backtest', action='store_true', help='Run backtest on historical data')
    ap.add_argument('--days', type=int, default=30, help='Backtest window (days)')
    args = ap.parse_args()

    engine = TennisScoringEngine()

    if args.file:
        with open(args.file) as fh:
            data = json.load(fh)
        matches: List[Dict[str, Any]] = data if isinstance(data, list) else data.get('matches', [])  # pyright: ignore[reportUnknownVariableType]
        engine.print_report(matches)

    elif args.backtest:
        files = sorted(glob.glob('outputs/*tennis*_predictions.json'))
        all_m: List[Dict[str, Any]] = []
        for fn in files[-args.days:]:
            with open(fn) as fh:
                data = json.load(fh)
            if isinstance(data, list):
                all_m.extend(data)  # pyright: ignore[reportUnknownArgumentType]
            elif 'matches' in data:
                all_m.extend(data['matches'])
        print(f'Loaded {len(all_m)} matches from {len(files)} files')
        runner = TennisCalibrationRunner(engine)
        metrics = runner.evaluate(all_m)
        print(f'Accuracy: {metrics["accuracy"]:.1%}  Brier: {metrics["brier"]:.3f}  '
              f'ROI: {metrics["roi"]:.1%}  Net P/L: {metrics["net_pl"]:.2f}u')
    else:
        print('Usage: --file <json> or --backtest [--days N]')
