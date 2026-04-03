"""
Tests for prediction upgrade modules (Phase 6+).

Covers:
  - prediction_data_contract: quality, availability, explanation, grade
  - qualification_gate: odds, fan-vote, future-only filters
  - result_store: persist/load results
  - weight_optimizer: basic construction and helpers
  - football_scoring_engine: new availability/consensus features
  - tennis_scoring_engine: new availability features
"""

import os
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prediction_data_contract import (
    compute_data_quality,
    compute_availability,
    compute_explanation,
    enrich_match_with_contract,
    DataQualityReport,
    AvailabilityReport,
    PredictionExplanation,
)
from qualification_gate import (
    qualify_match,
    apply_qualification_gate,
    _passes_odds_filter,  # pyright: ignore[reportPrivateUsage]
    _passes_fan_vote_filter,  # pyright: ignore[reportPrivateUsage]
    _is_future_match,  # pyright: ignore[reportPrivateUsage]
)
from result_store import ResultStore
from weight_optimizer import WeightOptimizer, CalibrationBucket, OptimizationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _team_match(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "sport": "football",
        "qualifies": True,
        "home_odds": 2.10,
        "draw_odds": 3.30,
        "away_odds": 3.60,
        "forebet_prediction": "1",
        "forebet_probability": 55,
        "sofascore_home_win_prob": 60,
        "sofascore_draw_prob": 15,
        "sofascore_away_win_prob": 25,
        "gemini_recommendation": "HIGH",
        "home_form": ["W", "W", "D", "L", "W"],
        "away_form": ["L", "D", "W", "L", "W"],
        "home_wins_in_h2h_last5": 3,
        "away_wins_in_h2h_last5": 1,
        "h2h_count": 5,
        "match_url": "https://www.livesport.cz/zapas/abc123",
    }
    base.update(overrides)
    return base


def _tennis_match(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "home_team": "Sinner J.",
        "away_team": "Alcaraz C.",
        "sport": "tennis",
        "qualifies": True,
        "home_odds": 1.75,
        "away_odds": 2.10,
        "ranking_a": 1,
        "ranking_b": 2,
        "form_a": ["W", "W", "W", "L", "W"],
        "form_b": ["W", "L", "W", "W", "W"],
        "surface": "hard",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# PREDICTION DATA CONTRACT
# ═══════════════════════════════════════════════════════════════════════════

class TestDataQuality:
    def test_full_data_high_quality(self):
        m = _team_match()
        dq = compute_data_quality(m)
        assert isinstance(dq, DataQualityReport)
        assert dq.quality_score >= 0.7

    def test_missing_data_low_quality(self):
        m = {"home_team": "A", "away_team": "B", "sport": "football"}
        dq = compute_data_quality(m)
        assert dq.quality_score < 0.3

    def test_sources_counted(self):
        m = _team_match()
        dq = compute_data_quality(m)
        assert dq.sources_available >= 3  # odds, forebet, sofascore at least

    def test_consensus_strong_when_aligned(self):
        m = _team_match(
            forebet_prediction="1",
            sofascore_home_win_prob=70,
            sofascore_away_win_prob=10,
            gemini_recommendation="HIGH",
        )
        dq = compute_data_quality(m)
        assert dq.consensus_strength in ("strong", "moderate")


class TestAvailability:
    def test_football_defaults(self):
        m = _team_match()
        avail = compute_availability(m, "football")
        assert isinstance(avail, AvailabilityReport)
        assert avail.fatigue_risk in ("low", "medium", "high")

    def test_tennis_defaults(self):
        m = _tennis_match()
        avail = compute_availability(m, "tennis")
        assert isinstance(avail, AvailabilityReport)


class TestExplanation:
    def test_has_primary_factors(self):
        m = _team_match()
        dq = compute_data_quality(m)
        avail = compute_availability(m, "football")
        expl = compute_explanation(m, dq, avail)
        assert isinstance(expl, PredictionExplanation)
        assert len(expl.primary_factors) >= 1

    def test_risk_factors_when_low_quality(self):
        m = {"home_team": "A", "away_team": "B", "sport": "football"}
        dq = compute_data_quality(m)
        avail = compute_availability(m, "football")
        expl = compute_explanation(m, dq, avail)
        assert any("Low data" in f or "data" in f.lower() for f in expl.risk_factors)


class TestEnrichContract:
    def test_enriches_all_fields(self):
        m = _team_match()
        enrich_match_with_contract(m)
        assert "data_quality" in m or "dataQuality" in m
        assert "prediction_grade" in m
        assert m["prediction_grade"] in ("A", "B", "C", "D", "F")

    def test_grade_reasonable_for_good_data(self):
        m = _team_match(
            forebet_prediction="1",
            forebet_probability=70,
            sofascore_home_win_prob=75,
            sofascore_away_win_prob=10,
            gemini_recommendation="HIGH",
            gemini_confidence=85,
        )
        enrich_match_with_contract(m)
        assert m["prediction_grade"] in ("A", "B", "C")


# ═══════════════════════════════════════════════════════════════════════════
# QUALIFICATION GATE
# ═══════════════════════════════════════════════════════════════════════════

class TestOddsFilter:
    def test_good_odds_pass(self):
        m = _team_match(home_odds=2.10, away_odds=2.50)
        assert _passes_odds_filter("football", m)

    def test_low_odds_fail(self):
        m = _team_match(home_odds=1.20, away_odds=1.30)
        assert not _passes_odds_filter("football", m)

    def test_missing_odds_fail(self):
        m = _team_match(home_odds=None, away_odds=None)
        assert not _passes_odds_filter("football", m)

    def test_tennis_threshold(self):
        m = _tennis_match(home_odds=1.40, away_odds=1.40)
        assert _passes_odds_filter("tennis", m)

    def test_tennis_below_threshold(self):
        m = _tennis_match(home_odds=1.10, away_odds=1.10)
        assert not _passes_odds_filter("tennis", m)


class TestFanVoteFilter:
    def test_high_dominant_passes(self):
        m = _team_match(sofascore_home_win_prob=75)
        assert _passes_fan_vote_filter("football", m)

    def test_low_dominant_fails_basketball(self):
        m: Dict[str, Any] = {"sofascore_home_win_prob": 40, "sofascore_away_win_prob": 35}
        assert not _passes_fan_vote_filter("basketball", m)

    def test_no_data_passes(self):
        m: Dict[str, Any] = {}
        assert _passes_fan_vote_filter("football", m)


class TestFutureMatchFilter:
    def test_future_match_passes(self):
        now = datetime(2025, 6, 15, 10, 0)
        m: Dict[str, Any] = {"match_time": "15.06.2025 14:00"}
        assert _is_future_match(m, now)

    def test_past_match_fails(self):
        now = datetime(2025, 6, 15, 16, 0)
        m: Dict[str, Any] = {"match_time": "15.06.2025 14:00"}
        assert not _is_future_match(m, now)

    def test_different_date_passes(self):
        now = datetime(2025, 6, 15, 16, 0)
        m: Dict[str, Any] = {"match_time": "16.06.2025 14:00"}
        assert _is_future_match(m, now)

    def test_no_time_passes(self):
        now = datetime(2025, 6, 15, 16, 0)
        m: Dict[str, Any] = {}
        assert _is_future_match(m, now)


class TestQualifyMatch:
    def test_qualifying_match_passes(self):
        m = _team_match(sofascore_home_win_prob=70, sofascore_draw_prob=10, sofascore_away_win_prob=20)
        now = datetime(2025, 6, 15, 10, 0)
        assert qualify_match(m, now)
        assert m["channel_qualifies"] is True
        assert m["channel_skip_reasons"] == []

    def test_no_base_qualification_fails(self):
        m = _team_match(qualifies=False)
        now = datetime(2025, 6, 15, 10, 0)
        assert not qualify_match(m, now)
        assert "base_qualification_failed" in m["channel_skip_reasons"]

    def test_missing_odds_fails(self):
        m = _team_match(home_odds=None, away_odds=None)
        now = datetime(2025, 6, 15, 10, 0)
        assert not qualify_match(m, now)
        assert "missing_odds" in m["channel_skip_reasons"]


class TestApplyGate:
    def test_counts_qualifying(self):
        rows = [
            _team_match(sofascore_home_win_prob=70, sofascore_draw_prob=10, sofascore_away_win_prob=20),
            _team_match(home_odds=None),
            _team_match(sofascore_home_win_prob=70, sofascore_draw_prob=10, sofascore_away_win_prob=20),
        ]
        now = datetime(2025, 6, 15, 10, 0)
        count = apply_qualification_gate(rows, "2025-06-15", now)
        assert count == 2


# ═══════════════════════════════════════════════════════════════════════════
# RESULT STORE
# ═══════════════════════════════════════════════════════════════════════════

class TestResultStore:
    def test_add_and_get(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name

        try:
            store = ResultStore(path=tmp)
            store.add_result("url1", {"winner": "home", "score_home": 2, "score_away": 1})
            result = store.get_result("url1")
            assert result is not None
            assert result["winner"] == "home"
        finally:
            os.unlink(tmp)

    def test_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name

        try:
            store1 = ResultStore(path=tmp)
            store1.add_result("url2", {"winner": "away", "score_home": 0, "score_away": 3})
            store1.save()

            store2 = ResultStore(path=tmp)
            result = store2.get_result("url2")
            assert result is not None
            assert result["winner"] == "away"
        finally:
            os.unlink(tmp)

    def test_get_all_finished(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name

        try:
            store = ResultStore(path=tmp)
            store.add_result("url3", {"winner": "home", "status": "finished"})
            store.add_result("url4", {"winner": "draw", "status": "finished"})
            finished = store.get_all_finished()
            assert len(finished) == 2
        finally:
            os.unlink(tmp)


# ═══════════════════════════════════════════════════════════════════════════
# WEIGHT OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestWeightOptimizer:
    def test_default_weights_football(self):
        opt = WeightOptimizer("football")
        w = opt._default_weights()  # pyright: ignore[reportPrivateUsage]
        assert "h2h" in w
        assert "odds" in w
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_default_weights_tennis(self):
        opt = WeightOptimizer("tennis")
        w = opt._default_weights()  # pyright: ignore[reportPrivateUsage]
        assert "h2h" in w
        assert "surface_form" in w
        assert abs(sum(w.values()) - 1.0) < 0.01

    def test_objective_score_accuracy(self):
        opt = WeightOptimizer("football")
        assert opt._objective_score(0.7, 0.3, 0.05, "accuracy") == 0.7  # pyright: ignore[reportPrivateUsage]

    def test_objective_score_brier(self):
        opt = WeightOptimizer("football")
        assert opt._objective_score(0.7, 0.3, 0.05, "brier") == -0.3  # pyright: ignore[reportPrivateUsage]

    def test_empty_result_no_data(self):
        opt = WeightOptimizer("football")
        result = opt.optimize_coordinate_descent()
        assert result.n_matches == 0

    def test_calibration_bucket(self):
        b = CalibrationBucket(predicted_low=0.6, predicted_high=0.7, count=10, actual_wins=7)
        assert b.midpoint == pytest.approx(0.65, abs=0.001)  # pyright: ignore[reportUnknownMemberType]
        assert b.actual_rate == 0.7
        assert b.calibration_error == pytest.approx(0.05, abs=0.01)  # pyright: ignore[reportUnknownMemberType]


class TestOptimizationResult:
    def test_to_dict(self):
        r = OptimizationResult(
            sport="football",
            baseline_weights={"h2h": 0.2},
            optimized_weights={"h2h": 0.25},
            baseline_accuracy=0.55,
            optimized_accuracy=0.60,
            baseline_brier=0.30,
            optimized_brier=0.28,
            baseline_roi=-0.05,
            optimized_roi=0.02,
            n_matches=100,
            improvement=0.05,
            timestamp="2025-06-15",
        )
        d = r.to_dict()
        assert d["sport"] == "football"
        assert d["improvement"] == 0.05


# ═══════════════════════════════════════════════════════════════════════════
# SCORING ENGINE REGRESSIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestFootballNewFeatures:
    """Verify football engine works with new availability/consensus features."""

    def test_weights_sum(self):
        from football_scoring_engine import FootballScoringEngine
        engine = FootballScoringEngine()
        assert abs(sum(engine.weights.values()) - 1.0) < 0.01

    def test_has_availability_weight(self):
        from football_scoring_engine import FootballScoringEngine
        engine = FootballScoringEngine()
        assert "availability" in engine.weights
        assert "consensus" in engine.weights

    def test_score_with_availability_data(self):
        from football_scoring_engine import FootballScoringEngine
        engine = FootballScoringEngine()
        m = _team_match()
        m["availability_impact"] = -0.1
        m["fatigue_risk"] = "medium"
        m["consensus_strength"] = "strong"
        sm = engine.score_match(m)  # pyright: ignore[reportUnknownMemberType]
        assert sm.prob_home + sm.prob_draw + sm.prob_away == pytest.approx(1.0, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_feature_extraction_includes_new_fields(self):
        from football_scoring_engine import FeatureExtractor
        ext = FeatureExtractor()
        feats = ext.extract(_team_match())  # pyright: ignore[reportUnknownMemberType]
        assert "availability_impact" in feats
        assert "consensus" in feats


class TestTennisNewFeatures:
    """Verify tennis engine works with new availability features."""

    def test_weights_sum(self):
        from tennis_scoring_engine import DEFAULT_WEIGHTS
        assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 0.01

    def test_has_availability_weight(self):
        from tennis_scoring_engine import DEFAULT_WEIGHTS
        assert "availability" in DEFAULT_WEIGHTS

    def test_score_with_retirement_flags(self):
        from tennis_scoring_engine import TennisScoringEngine
        engine = TennisScoringEngine()
        m = _tennis_match()
        m["retirement_a"] = 0
        m["retirement_b"] = 1
        sm = engine.score_match(m)
        assert sm.prob_a + sm.prob_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]
        # Player B has retirement flag → A should be favored more
        assert sm.best_pick == "A"

    def test_feature_extraction_has_avail(self):
        from tennis_scoring_engine import TennisFeatureExtractor
        ext = TennisFeatureExtractor()
        feats = ext.extract(_tennis_match())
        assert "avail_impact" in feats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
