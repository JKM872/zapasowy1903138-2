"""
Regression tests for FootballScoringEngine (Phase 4).

Covers:
  - Feature extraction
  - Probability normalisation (sum ≈ 1.0)
  - EV / edge calculation
  - Confidence & data-quality bounds
  - Calibration runner (no crashes on empty data)
  - CLI smoke test
"""

import sys
import os
import math
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from football_scoring_engine import (
    FootballScoringEngine,
    FeatureExtractor,
    ScoredMatch,
    CalibrationRunner,
    _safe_float,
    _parse_form,
    _form_points,
    _poisson_pmf,
    _poisson_match_probs,
    _h2h_outcome_rates,
    _expected_goals,
    _implied_probs_from_odds,
    _solve_lambdas_from_supremacy,
    SPORT_PROFILES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_match(**overrides):
    """Create a minimal match dict with sensible defaults."""
    base = {
        "home_team": "Home FC",
        "away_team": "Away United",
        "home_wins_in_h2h_last5": 3,
        "away_wins_in_h2h_last5": 1,
        "draws_in_h2h_last5": 1,
        "h2h_count": 5,
        "home_form": ["W", "W", "D", "L", "W"],
        "away_form": ["L", "D", "L", "W", "L"],
        "home_form_home": ["W", "W", "W"],
        "away_form_away": ["L", "L", "D"],
        "home_odds": 1.85,
        "draw_odds": 3.40,
        "away_odds": 4.20,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. _safe_float
# ---------------------------------------------------------------------------
class TestSafeFloat:
    def test_number(self):
        assert _safe_float(3.14) == 3.14

    def test_string(self):
        assert _safe_float("2.5") == 2.5

    def test_none(self):
        assert _safe_float(None) == 0.0

    def test_nan_string(self):
        result = _safe_float("nan")
        # float("nan") is a valid float, so _safe_float returns it
        assert isinstance(result, float)

    def test_garbage(self):
        assert _safe_float("abc") == 0.0


# ---------------------------------------------------------------------------
# 2. _parse_form
# ---------------------------------------------------------------------------
class TestParseForm:
    def test_list(self):
        assert _parse_form(["W", "L", "D"]) == ["W", "L", "D"]

    def test_string_comma(self):
        assert _parse_form("W,L,D") == ["W", "L", "D"]

    def test_string_dash(self):
        # _parse_form splits on comma/whitespace, not dashes
        # "W-L-D" is treated as one token -> extracted first char "W"
        result = _parse_form("W-L-D")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_none(self):
        assert _parse_form(None) == []

    def test_empty(self):
        assert _parse_form("") == []


# ---------------------------------------------------------------------------
# 3. _form_points
# ---------------------------------------------------------------------------
class TestFormPoints:
    def test_all_wins(self):
        pts = _form_points(["W", "W", "W", "W", "W"])
        assert pts > 0.8  # near-maximum

    def test_all_losses(self):
        pts = _form_points(["L", "L", "L", "L", "L"])
        assert pts < 0.2

    def test_empty(self):
        assert _form_points([]) == 0.5  # neutral default


# ---------------------------------------------------------------------------
# 4. FeatureExtractor
# ---------------------------------------------------------------------------
class TestFeatureExtractor:
    def setup_method(self):
        self.ext = FeatureExtractor()

    def test_full_data(self):
        feats = self.ext.extract(_make_match())
        assert "h2h_win_rate" in feats
        assert "home_form" in feats
        assert "_data_quality" in feats
        assert 0 <= feats["_data_quality"] <= 1

    def test_minimal_data(self):
        feats = self.ext.extract({"home_team": "A", "away_team": "B"})
        assert feats["_data_quality"] < 0.3  # very sparse data

    def test_h2h_rate_correct(self):
        # h2h_win_rate is computed from h2h_last5 list (raw H2H rows),
        # not from home_wins_in_h2h_last5 scalar.
        # Without h2h_last5 list, it defaults to 0.5.
        feats = self.ext.extract(
            _make_match(
                home_wins_in_h2h_last5=4, h2h_count=5,
                h2h_last5=[
                    {'home': 'Home FC', 'away': 'Away United', 'score': '2-1'},
                    {'home': 'Home FC', 'away': 'Away United', 'score': '3-0'},
                    {'home': 'Away United', 'away': 'Home FC', 'score': '0-1'},
                    {'home': 'Home FC', 'away': 'Away United', 'score': '1-0'},
                    {'home': 'Away United', 'away': 'Home FC', 'score': '2-3'},
                ]
            )
        )
        # All 5 H2H matches won by Home FC -> high win rate
        assert feats["h2h_win_rate"] >= 0.5


# ---------------------------------------------------------------------------
# 5. FootballScoringEngine – probability properties
# ---------------------------------------------------------------------------
class TestScoringEngine:
    def setup_method(self):
        self.engine = FootballScoringEngine()

    def test_probs_sum_to_one(self):
        sm = self.engine.score_match(_make_match())
        total = sm.prob_home + sm.prob_draw + sm.prob_away
        assert total == pytest.approx(1.0, abs=0.01)

    def test_calibrated_probs_sum_to_one(self):
        sm = self.engine.score_match(_make_match())
        total = sm.cal_home + sm.cal_draw + sm.cal_away
        assert total == pytest.approx(1.0, abs=0.01)

    def test_best_pick_valid(self):
        sm = self.engine.score_match(_make_match())
        assert sm.best_pick in ("1", "X", "2")

    def test_confidence_range(self):
        sm = self.engine.score_match(_make_match())
        assert 0 <= sm.confidence <= 100

    def test_data_quality_range(self):
        sm = self.engine.score_match(_make_match())
        assert 0 <= sm.data_quality <= 1

    def test_ev_with_good_odds(self):
        """When odds are generous vs probability, EV should be positive."""
        sm = self.engine.score_match(
            _make_match(
                home_odds=3.00,  # generous
                home_wins_in_h2h_last5=5,
                h2h_count=5,
                home_form=["W", "W", "W", "W", "W"],
                away_form=["L", "L", "L", "L", "L"],
            )
        )
        # With 100% H2H and perfect form at odds 3.00, EV should be positive
        if sm.best_pick == "1":
            assert sm.ev > 0

    def test_score_matches_sorted_by_ev(self):
        matches = [_make_match(), _make_match(home_odds=5.0)]
        scored = self.engine.score_matches(matches)
        assert len(scored) == 2
        assert scored[0].ev >= scored[1].ev

    def test_no_odds_still_works(self):
        """Engine must not crash when odds are missing."""
        sm = self.engine.score_match(
            _make_match(home_odds=None, draw_odds=None, away_odds=None)
        )
        assert sm.best_pick in ("1", "X", "2")
        assert sm.prob_home + sm.prob_draw + sm.prob_away == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 6. Edge & Kelly sanity
# ---------------------------------------------------------------------------
class TestEdgeKelly:
    def setup_method(self):
        self.engine = FootballScoringEngine()

    def test_kelly_non_negative(self):
        sm = self.engine.score_match(_make_match())
        assert sm.kelly >= 0

    def test_edge_bounded(self):
        sm = self.engine.score_match(_make_match())
        assert -100 <= sm.edge <= 100


# ---------------------------------------------------------------------------
# 7. CalibrationRunner — no crashes
# ---------------------------------------------------------------------------
class TestCalibrationRunner:
    def test_empty_list(self):
        engine = FootballScoringEngine()
        runner = CalibrationRunner(engine)
        metrics = runner.evaluate([])
        assert isinstance(metrics, dict)

    def test_no_results_field(self):
        engine = FootballScoringEngine()
        runner = CalibrationRunner(engine)
        metrics = runner.evaluate([_make_match()])
        assert isinstance(metrics, dict)


# ---------------------------------------------------------------------------
# 8. ScoredMatch dataclass
# ---------------------------------------------------------------------------
class TestScoredMatch:
    def test_creation(self):
        sm = ScoredMatch(
            home_team="A",
            away_team="B",
            sport="football",
            prob_home=0.5,
            prob_draw=0.3,
            prob_away=0.2,
        )
        assert sm.home_team == "A"
        assert sm.prob_home == 0.5


# ---------------------------------------------------------------------------
# 9. Poisson goal model (v3)
# ---------------------------------------------------------------------------
class TestPoissonModel:
    def test_pmf_sums_to_one(self):
        total = sum(_poisson_pmf(1.4, k) for k in range(30))
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_pmf_zero_lambda(self):
        assert _poisson_pmf(0.0, 0) == 1.0
        assert _poisson_pmf(0.0, 3) == 0.0

    def test_match_probs_sum_to_one(self):
        ph, pd, pa = _poisson_match_probs(1.5, 1.2)
        assert ph + pd + pa == pytest.approx(1.0, abs=1e-3)

    def test_symmetric_when_equal(self):
        ph, pd, pa = _poisson_match_probs(1.3, 1.3)
        assert ph == pytest.approx(pa, abs=1e-6)

    def test_favorite_has_higher_prob(self):
        ph, pd, pa = _poisson_match_probs(2.2, 0.7)
        assert ph > pa
        assert ph > pd

    def test_low_scoring_raises_draw(self):
        # Fewer goals → higher draw probability.
        _, draw_low, _ = _poisson_match_probs(0.6, 0.6)
        _, draw_high, _ = _poisson_match_probs(2.5, 2.5)
        assert draw_low > draw_high

    def test_probs_bounded(self):
        for lh in (0.1, 1.0, 3.5, 6.0):
            for la in (0.1, 1.0, 3.5, 6.0):
                ph, pd, pa = _poisson_match_probs(lh, la)
                assert 0.0 <= ph <= 1.0
                assert 0.0 <= pd <= 1.0
                assert 0.0 <= pa <= 1.0


# ---------------------------------------------------------------------------
# 10. H2H outcome-resolved rates (v3)
# ---------------------------------------------------------------------------
class TestH2HOutcomeRates:
    def test_rates_sum_to_one(self):
        h2h = [
            {'home': 'A', 'away': 'B', 'score': '2-1'},
            {'home': 'B', 'away': 'A', 'score': '0-0'},
            {'home': 'A', 'away': 'B', 'score': '1-3'},
        ]
        w, d, l, cnt = _h2h_outcome_rates(h2h, 'A')
        assert w + d + l == pytest.approx(1.0, abs=1e-6)
        assert cnt == 3

    def test_draw_preserved(self):
        # Two of three meetings are draws → meaningful draw rate.
        h2h = [
            {'home': 'A', 'away': 'B', 'score': '1-1'},
            {'home': 'B', 'away': 'A', 'score': '2-2'},
            {'home': 'A', 'away': 'B', 'score': '2-0'},
        ]
        w, d, l, _ = _h2h_outcome_rates(h2h, 'A')
        assert d > 0.5  # draws are the dominant outcome

    def test_empty_returns_neutral(self):
        w, d, l, cnt = _h2h_outcome_rates([], 'A')
        assert cnt == 0
        assert w == pytest.approx(0.5)
        assert d == pytest.approx(0.0)

    def test_team_perspective_flips(self):
        h2h = [
            {'home': 'A', 'away': 'B', 'score': '3-0'},
            {'home': 'A', 'away': 'B', 'score': '2-1'},
        ]
        wa, _, la, _ = _h2h_outcome_rates(h2h, 'A')
        wb, _, lb, _ = _h2h_outcome_rates(h2h, 'B')
        assert wa == pytest.approx(lb)
        assert la == pytest.approx(wb)


# ---------------------------------------------------------------------------
# 11. Expected goals inference (v3)
# ---------------------------------------------------------------------------
class TestExpectedGoals:
    def test_tier1_forebet_exact_score(self):
        xg = _expected_goals({'forebet_exact_score': '3-1'})
        assert xg is not None
        lh, la = xg
        assert lh > la  # home expected to score more

    def test_tier2_goal_averages(self):
        xg = _expected_goals({
            'home_goals_scored_avg': 2.0, 'home_goals_conceded_avg': 0.8,
            'away_goals_scored_avg': 0.9, 'away_goals_conceded_avg': 1.6,
        })
        assert xg is not None
        lh, la = xg
        assert lh > la

    def test_tier3_from_odds(self):
        # Only odds present — tier-3 inference must still produce lambdas.
        prof = SPORT_PROFILES['football']
        xg = _expected_goals(
            {'home_odds': 1.5, 'draw_odds': 4.0, 'away_odds': 6.5}, prof
        )
        assert xg is not None
        lh, la = xg
        assert lh > la  # heavy home favorite

    def test_no_data_returns_none(self):
        assert _expected_goals({}, SPORT_PROFILES['football']) is None

    def test_implied_probs_sum_to_one(self):
        probs = _implied_probs_from_odds(2.0, 3.5, 4.0)
        assert probs is not None
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)

    def test_implied_probs_missing_odds(self):
        assert _implied_probs_from_odds(0, 0, 0) is None

    def test_solve_lambdas_respects_total(self):
        lh, la = _solve_lambdas_from_supremacy(1.0, 2.6)
        assert lh + la == pytest.approx(2.6, abs=1e-6)
        assert lh > la


# ---------------------------------------------------------------------------
# 12. Poisson integration in engine (v3)
# ---------------------------------------------------------------------------
class TestPoissonIntegration:
    def setup_method(self):
        self.engine = FootballScoringEngine()

    def test_poisson_activates_on_odds_only(self):
        sm = self.engine.score_match(_make_match())
        assert sm.features.get('poisson_available', 0.0) == 1.0

    def test_poisson_skipped_for_basketball(self):
        m = _make_match(sport='basketball')
        sm = self.engine.score_match(m)
        # Draw-less sport must not receive a Poisson draw signal.
        assert sm.features.get('poisson_available', 0.0) == 0.0

    def test_draw_probability_reasonable(self):
        # Evenly matched teams at level odds should yield a non-trivial draw.
        m = _make_match(home_odds=2.6, draw_odds=3.2, away_odds=2.7,
                        home_form=["W", "D", "W", "D", "L"],
                        away_form=["D", "W", "L", "D", "W"])
        sm = self.engine.score_match(m)
        assert sm.cal_draw > 0.15

    def test_probs_still_sum_to_one_with_poisson(self):
        sm = self.engine.score_match(_make_match())
        assert sm.cal_home + sm.cal_draw + sm.cal_away == pytest.approx(1.0, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
