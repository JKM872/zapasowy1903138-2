"""
Tests for ai_prediction_engine — Ultra PRO AI prediction layer.
Covers: helpers, factor analysis, risk, consensus, verdicts, guardrails,
        full generate_ai_prediction for football and tennis.
"""
# pyright: reportPrivateUsage=false

import math
import pytest
from typing import Dict, Any
from ai_prediction_engine import (
    AIPrediction,
    generate_ai_prediction,
    _sf,
    _pick_label,
    _confidence_tier,
    _consensus_label,
    _value_label,
    _dq_label,
    _form_trend,
    _form_score,
    _form_consistency,
    _extract_source_prediction,
    _compute_consensus,
    _build_factors,
    _compute_risk,
    _generate_verdict,
    _extract_arguments,
    _check_guardrails,
)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def football_row() -> Dict[str, Any]:
    """A fully-enriched football match row."""
    return {
        'sport': 'football',
        'home_team': 'Liverpool',
        'away_team': 'Everton',
        'focus_team': 'home',
        'match_time': '20:00',
        'match_url': 'https://www.livesport.com/pl/pilka-nozna/test/',
        # H2H
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 1,
        'h2h_count': 5,
        'h2h_win_rate': 60,
        # Form
        'home_form': ['W', 'W', 'D', 'W', 'L'],
        'away_form': ['L', 'D', 'L', 'W', 'L'],
        'home_form_home': ['W', 'W', 'W', 'D'],
        'away_form_away': ['L', 'L', 'D', 'L'],
        # Forebet
        'forebet_prediction': '1',
        'forebet_probability': 72,
        'forebet_exact_score': '2-0',
        # SofaScore
        'sofascore_home_win_prob': 65,
        'sofascore_draw_prob': 20,
        'sofascore_away_win_prob': 15,
        'sofascore_total_votes': 4500,
        # Odds
        'home_odds': 1.55,
        'draw_odds': 4.10,
        'away_odds': 5.80,
        # Gemini
        'gemini_prediction': 'Liverpool Win',
        'gemini_confidence': 82,
        'gemini_recommendation': 'HIGH',
        'gemini_reasoning': 'Liverpool dominate at home.',
        # Scoring engine
        'scoring_pick': '1',
        'scoring_prob': 65,
        'scoring_ev': 0.08,
        'scoring_edge': 6.5,
        'scoring_kelly': 2.1,
        'scoring_confidence': 72,
        'scoring_data_quality': 0.85,
        'scoring_prob_home': 65,
        'scoring_prob_draw': 20,
        'scoring_prob_away': 15,
    }


@pytest.fixture
def tennis_row() -> Dict[str, Any]:
    """A fully-enriched tennis match row."""
    return {
        'sport': 'tennis',
        'home_team': 'Djokovic',
        'away_team': 'Nadal',
        'focus_team': 'home',
        'match_url': 'https://www.livesport.com/pl/tenis/test/',
        # H2H
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 2,
        'h2h_count': 5,
        'h2h_win_rate': 60,
        # Form
        'home_form': ['W', 'W', 'W', 'W', 'L'],
        'away_form': ['W', 'L', 'W', 'L', 'W'],
        # Forebet
        'forebet_prediction': '1',
        'forebet_probability': 62,
        # SofaScore
        'sofascore_home_win_prob': 55,
        'sofascore_draw_prob': 0,
        'sofascore_away_win_prob': 45,
        'sofascore_total_votes': 2000,
        # Odds
        'home_odds': 1.70,
        'draw_odds': 0,
        'away_odds': 2.10,
        # Gemini
        'gemini_prediction': 'Djokovic win',
        'gemini_confidence': 70,
        'gemini_recommendation': 'MEDIUM',
        'gemini_reasoning': 'Close matchup.',
        # Scoring engine
        'scoring_pick': 'A',
        'scoring_prob': 58,
        'scoring_ev': 0.03,
        'scoring_edge': 4.2,
        'scoring_kelly': 1.0,
        'scoring_confidence': 60,
        'scoring_data_quality': 0.75,
        'scoring_prob_a': 58,
        'scoring_prob_b': 42,
        # Tennis-specific
        'surface': 'Hard',
        'ranking_a': 1,
        'ranking_b': 3,
    }


@pytest.fixture
def minimal_row() -> Dict[str, Any]:
    """A minimal match row with almost no data."""
    return {
        'sport': 'football',
        'home_team': 'Team A',
        'away_team': 'Team B',
        'focus_team': 'home',
    }


# =========================================================================
# Helper unit tests
# =========================================================================

class TestSafeFloat:
    def test_normal(self):
        assert _sf(3.14) == 3.14

    def test_none(self):
        assert _sf(None) == 0.0

    def test_nan(self):
        assert _sf(float('nan')) == 0.0

    def test_inf(self):
        assert _sf(float('inf')) == 0.0

    def test_string_number(self):
        assert _sf('42') == 42.0

    def test_invalid_string(self):
        assert _sf('abc', 5.0) == 5.0


class TestPickLabel:
    def test_football_home(self):
        assert _pick_label('1', 'football') == 'Home Win'

    def test_football_draw(self):
        assert _pick_label('X', 'football') == 'Draw'

    def test_football_away(self):
        assert _pick_label('2', 'football') == 'Away Win'

    def test_tennis_a(self):
        assert _pick_label('A', 'tennis') == 'Player A'

    def test_tennis_b(self):
        assert _pick_label('B', 'tennis') == 'Player B'


class TestConfidenceTier:
    def test_very_high(self):
        assert _confidence_tier(90) == "VERY HIGH"

    def test_high(self):
        assert _confidence_tier(75) == "HIGH"

    def test_medium(self):
        assert _confidence_tier(60) == "MEDIUM"

    def test_low(self):
        assert _confidence_tier(42) == "LOW"

    def test_very_low(self):
        assert _confidence_tier(20) == "VERY LOW"

    def test_boundary_85(self):
        assert _confidence_tier(85) == "VERY HIGH"

    def test_boundary_70(self):
        assert _confidence_tier(70) == "HIGH"


class TestConsensusLabel:
    def test_strong(self):
        assert _consensus_label(4, 5) == "STRONG"

    def test_moderate(self):
        assert _consensus_label(3, 5) == "MODERATE"

    def test_weak(self):
        assert _consensus_label(2, 5) == "WEAK"

    def test_divided(self):
        assert _consensus_label(1, 5) == "DIVIDED"

    def test_zero_total(self):
        assert _consensus_label(0, 0) == "UNKNOWN"


class TestValueLabel:
    def test_excellent(self):
        assert _value_label(0.20, 12) == "EXCELLENT"

    def test_good(self):
        assert _value_label(0.06, 6) == "GOOD"

    def test_fair(self):
        assert _value_label(0.01, 1) == "FAIR"

    def test_none(self):
        assert _value_label(-0.05, -2) == "NONE"


class TestDqLabel:
    def test_excellent(self):
        assert _dq_label(0.9) == "EXCELLENT"

    def test_good(self):
        assert _dq_label(0.65) == "GOOD"

    def test_fair(self):
        assert _dq_label(0.45) == "FAIR"

    def test_poor(self):
        assert _dq_label(0.2) == "POOR"


# =========================================================================
# Form helpers
# =========================================================================

class TestFormTrend:
    def test_improving(self):
        score, label = _form_trend(['W', 'W', 'W', 'L', 'L', 'L'])
        assert label == "Improving"
        assert score > 0

    def test_declining(self):
        score, label = _form_trend(['L', 'L', 'L', 'W', 'W', 'W'])
        assert label == "Declining"
        assert score < 0

    def test_stable(self):
        _, label = _form_trend(['W', 'D', 'W', 'W', 'D'])
        assert label == "Stable"

    def test_none_input(self):
        score, label = _form_trend(None)
        assert score == 0.0
        assert label == "Unknown"

    def test_single_item(self):
        score, _label = _form_trend(['W'])
        assert score == 0.0


class TestFormScore:
    def test_all_wins(self):
        s = _form_score(['W', 'W', 'W', 'W', 'W'])
        assert s > 0.9

    def test_all_losses(self):
        s = _form_score(['L', 'L', 'L', 'L', 'L'])
        assert s < 0.1

    def test_mixed(self):
        s = _form_score(['W', 'L', 'W', 'L'])
        assert 0.3 < s < 0.7

    def test_none(self):
        assert _form_score(None) == 0.5


class TestFormConsistency:
    def test_all_same(self):
        c = _form_consistency(['W', 'W', 'W', 'W', 'W'])
        assert c > 0.8

    def test_volatile(self):
        c = _form_consistency(['W', 'L', 'W', 'L', 'W'])
        assert c < 0.6

    def test_empty(self):
        assert _form_consistency([]) == 0.5


# =========================================================================
# Source extraction & consensus
# =========================================================================

class TestSourceExtraction:
    def test_all_sources(self, football_row: Dict[str, Any]) -> None:
        preds = _extract_source_prediction(football_row, 'football')
        assert 'forebet' in preds
        assert 'scoring' in preds
        assert 'gemini' in preds
        assert 'sofascore' in preds
        assert 'h2h' in preds
        assert preds['forebet'] == '1'
        assert preds['scoring'] == '1'

    def test_tennis_sources(self, tennis_row: Dict[str, Any]) -> None:
        preds = _extract_source_prediction(tennis_row, 'tennis')
        assert preds.get('sofascore') == 'A'
        assert preds.get('h2h') == 'A'

    def test_empty_row(self, minimal_row: Dict[str, Any]) -> None:
        preds = _extract_source_prediction(minimal_row, 'football')
        assert len(preds) == 0


class TestConsensus:
    def test_full_agreement(self):
        preds = {'a': '1', 'b': '1', 'c': '1'}
        agree, total = _compute_consensus(preds, '1')
        assert agree == 3
        assert total == 3

    def test_partial_agreement(self):
        preds = {'a': '1', 'b': '2', 'c': '1'}
        agree, total = _compute_consensus(preds, '1')
        assert agree == 2
        assert total == 3

    def test_no_agreement(self):
        preds = {'a': '2', 'b': 'X'}
        agree, _total = _compute_consensus(preds, '1')
        assert agree == 0


# =========================================================================
# Factors
# =========================================================================

class TestBuildFactors:
    def test_football_factor_count(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        # H2H, Form, Venue Form, Market Odds, Forebet, SofaScore, Gemini = 7
        assert len(factors) == 7

    def test_tennis_has_surface_factor(self, tennis_row: Dict[str, Any]) -> None:
        factors = _build_factors(tennis_row, 'tennis')
        names = [f['name'] for f in factors]
        assert 'Surface & Rankings' in names
        # Tennis: no Venue Form but has Surface
        assert 'Venue Form' not in names

    def test_factor_has_required_keys(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        for f in factors:
            assert 'name' in f
            assert 'value' in f
            assert 'weight' in f
            assert 'impact' in f
            assert 'quality' in f
            assert 'description' in f

    def test_h2h_factor_description(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        h2h = next(f for f in factors if f['name'] == 'Head-to-Head')
        assert 'Liverpool' in h2h['description']
        assert h2h['quality'] == 1.0  # 5/5 h2h games

    def test_csv_string_form_parsed(self, football_row: Dict[str, Any]) -> None:
        """BUG #2 regression: CSV dash-separated form must be parsed, not iterated char-by-char."""
        row = dict(football_row)
        row['home_form'] = 'W-W-D-W-L'
        row['away_form'] = 'L-D-L-W-L'
        row['home_form_home'] = 'W-W-W-D'
        row['away_form_away'] = 'L-L-D-L'
        factors = _build_factors(row, 'football')
        form = next(f for f in factors if f['name'] == 'Recent Form')
        venue = next(f for f in factors if f['name'] == 'Venue Form')
        # With list input, quality=1.0 because both sides have data
        assert form['quality'] == 1.0
        assert venue['quality'] == 1.0
        # Form descriptions should contain team names and trend labels
        assert 'Liverpool' in form['description']
        assert 'Everton' in form['description']
        # Venue description must have reasonable percentages (not 50% default)
        assert 'Home at home:' in venue['description']
        assert '50%' not in venue['description']  # 50% would mean it fell back to default

    def test_csv_stringified_list_form(self, football_row: Dict[str, Any]) -> None:
        """CSV stringified list format also works."""
        row = dict(football_row)
        row['home_form'] = "['W', 'W', 'D', 'W', 'L']"
        row['away_form'] = "['L', 'D', 'L', 'W', 'L']"
        factors = _build_factors(row, 'football')
        form = next(f for f in factors if f['name'] == 'Recent Form')
        assert form['quality'] == 1.0
        assert 'Liverpool' in form['description']


# =========================================================================
# Risk
# =========================================================================

class TestComputeRisk:
    def test_low_risk_with_consensus(self, football_row: Dict[str, Any]) -> None:
        preds = {'a': '1', 'b': '1', 'c': '1', 'd': '1'}
        factors = _build_factors(football_row, 'football')
        score, level, _flags = _compute_risk(football_row, preds, '1', 0.9, factors)
        assert level == 'LOW'
        assert score < 5

    def test_high_risk_with_conflict(self, minimal_row: Dict[str, Any]) -> None:
        preds = {'a': '2', 'b': 'X', 'c': '2', 'd': '2', 'e': '1'}
        factors = _build_factors(minimal_row, 'football')
        score, _level, flags = _compute_risk(minimal_row, preds, '1', 0.2, factors)
        assert score >= 5
        assert len(flags) > 0

    def test_risk_never_exceeds_10(self, minimal_row: Dict[str, Any]) -> None:
        preds = {'a': '2', 'b': 'X', 'c': '2'}
        # Extreme: very low quality, all conflicts, volatile form
        row: Dict[str, Any] = {**minimal_row, 'home_form': ['W', 'L', 'W', 'L', 'W'], 'away_form': ['L', 'W', 'L', 'W', 'L'],
               'home_odds': 2.0, 'away_odds': 2.05}
        factors = _build_factors(row, 'football')
        score, _, _ = _compute_risk(row, preds, '1', 0.1, factors)
        assert score <= 10


# =========================================================================
# Verdict
# =========================================================================

class TestVerdict:
    def test_high_confidence_verdict(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        verdict, short = _generate_verdict(
            football_row, '1', 'Home Win', 80, 'STRONG', 'LOW', factors, 0.08, 6.5, 'football',
        )
        assert 'Liverpool' in verdict
        assert 'Strong' in short

    def test_low_confidence_verdict(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        _, short = _generate_verdict(
            football_row, '1', 'Home Win', 40, 'WEAK', 'HIGH', factors, -0.05, -2, 'football',
        )
        assert 'caution' in short.lower()


# =========================================================================
# Arguments
# =========================================================================

class TestArguments:
    def test_extracts_for_and_against(self, football_row: Dict[str, Any]) -> None:
        factors = _build_factors(football_row, 'football')
        args_for, _args_against = _extract_arguments(factors, football_row)
        # With rich data, should have some positive factors
        assert len(args_for) > 0

    def test_empty_factors(self):
        args_for, args_against = _extract_arguments([], {})
        assert args_for == []
        assert args_against == []


# =========================================================================
# Guardrails
# =========================================================================

class TestGuardrails:
    def test_no_warnings_for_good_data(self):
        reasons = _check_guardrails(75, 0.8, 3, [], 4, 5)
        assert len(reasons) == 0

    def test_low_data_quality(self):
        reasons = _check_guardrails(60, 0.2, 3, [], 3, 5)
        assert any('data' in r.lower() for r in reasons)

    def test_high_risk(self):
        reasons = _check_guardrails(60, 0.6, 9, ['flag1'], 3, 5)
        assert any('risk' in r.lower() for r in reasons)

    def test_low_confidence(self):
        reasons = _check_guardrails(30, 0.6, 3, [], 3, 5)
        assert any('confidence' in r.lower() for r in reasons)

    def test_severe_disagreement(self):
        reasons = _check_guardrails(60, 0.6, 3, [], 1, 5)
        assert any('disagreement' in r.lower() for r in reasons)


# =========================================================================
# Integration: generate_ai_prediction
# =========================================================================

class TestGenerateAIPrediction:
    def test_football_full_data(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        assert isinstance(pred, AIPrediction)
        assert pred.pick == '1'
        assert pred.pick_label == 'Home Win'
        assert 5 <= pred.composite_confidence <= 99
        assert pred.confidence_tier in ('VERY HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY LOW')
        assert pred.prob_home > 0
        assert pred.prob_away > 0
        assert pred.consensus_total > 0
        assert pred.data_quality > 0

    def test_tennis_prediction(self, tennis_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(tennis_row)
        assert pred.pick in ('A', 'B')
        assert pred.prob_draw == 0.0
        assert 'Surface & Rankings' in [f['name'] for f in pred.factors]

    def test_minimal_row_no_crash(self, minimal_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(minimal_row)
        assert isinstance(pred, AIPrediction)
        assert pred.pick in ('1', '2', 'X')
        assert pred.data_quality_label in ('EXCELLENT', 'GOOD', 'FAIR', 'POOR')

    def test_to_dict_camel_case(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        d = pred.to_dict()
        assert 'pick' in d
        assert 'pickLabel' in d
        assert 'compositeConfidence' in d
        assert 'confidenceTier' in d
        assert 'probHome' in d
        assert 'consensus' in d
        assert isinstance(d['consensus'], dict)
        assert 'risk' in d
        assert isinstance(d['risk'], dict)
        assert 'factors' in d
        assert isinstance(d['factors'], list)
        assert 'verdict' in d
        assert 'shortVerdict' in d
        assert 'doNotBetReasons' in d

    def test_confidence_range(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        assert 5 <= pred.composite_confidence <= 99

    def test_risk_range(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        assert 0 <= pred.risk_score <= 10
        assert pred.risk_level in ('LOW', 'MEDIUM', 'HIGH')

    def test_verdicts_not_empty(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        assert len(pred.verdict) > 20
        assert len(pred.short_verdict) > 10

    def test_missing_scoring_engine_fallback(self):
        """When scoring engine is absent, prediction should still work."""
        row: Dict[str, Any] = {
            'sport': 'football',
            'home_team': 'A', 'away_team': 'B',
            'focus_team': 'home',
            'forebet_prediction': '1',
            'forebet_probability': 55,
            'home_form': ['W', 'W', 'L'],
            'away_form': ['L', 'D', 'L'],
        }
        pred = generate_ai_prediction(row)
        assert pred.pick == '1'
        assert pred.composite_confidence > 0

    def test_all_nan_values_handled(self):
        """NaN values from pandas should not crash."""
        row: Dict[str, Any] = {
            'sport': 'football',
            'home_team': 'X', 'away_team': 'Y',
            'focus_team': 'home',
            'scoring_prob': float('nan'),
            'scoring_ev': float('nan'),
            'scoring_edge': float('nan'),
            'forebet_probability': float('nan'),
            'gemini_confidence': float('nan'),
        }
        pred = generate_ai_prediction(row)
        assert isinstance(pred, AIPrediction)
        assert not math.isnan(pred.composite_confidence)


class TestAIPredictionDataclass:
    def test_to_dict_roundtrip(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        d = pred.to_dict()
        # All values should be JSON-serializable
        import json
        json_str = json.dumps(d)
        assert len(json_str) > 100

    def test_do_not_bet_empty_for_good_data(self, football_row: Dict[str, Any]) -> None:
        pred = generate_ai_prediction(football_row)
        # Good data should not trigger do-not-bet (unless risk is high)
        if pred.risk_score < 8 and pred.composite_confidence >= 35:
            assert len(pred.do_not_bet_reasons) == 0
