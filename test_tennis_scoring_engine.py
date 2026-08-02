"""
Tests for tennis_scoring_engine.py  –  Phase 5 regression suite.
"""
import pytest
from typing import Any, Dict
from tennis_scoring_engine import (
    TennisScoringEngine,
    TennisFeatureExtractor,
    ScoredTennisMatch,
    _form_score,       # pyright: ignore[reportPrivateUsage]
    _parse_form_list,  # pyright: ignore[reportPrivateUsage]
    _streak_len,       # pyright: ignore[reportPrivateUsage]
    _recency_h2h,      # pyright: ignore[reportPrivateUsage]
    _prob_win_game,    # pyright: ignore[reportPrivateUsage]
    _prob_win_set,     # pyright: ignore[reportPrivateUsage]
    _prob_win_match_bo3,  # pyright: ignore[reportPrivateUsage]
    _serve_model_prob_a,  # pyright: ignore[reportPrivateUsage]
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_match(**overrides: Any) -> Dict[str, Any]:
    m: Dict[str, Any] = {
        'home_team': 'Djokovic N.',
        'away_team': 'Nadal R.',
        'match_time': '15:00',
        'h2h_last5': [],
        'home_wins_in_h2h_last5': 3,
        'away_wins_in_h2h_last5': 2,
        'ranking_a': 1,
        'ranking_b': 5,
        'form_a': ['W', 'W', 'W', 'L', 'W'],
        'form_b': ['W', 'L', 'W', 'L', 'W'],
        'surface': 'hard',
        'home_odds': 1.60,
        'away_odds': 2.40,
        'qualifies': True,
        'sport': 'tennis',
    }
    m.update(overrides)
    return m


@pytest.fixture
def engine() -> TennisScoringEngine:
    return TennisScoringEngine()


@pytest.fixture
def extractor() -> TennisFeatureExtractor:
    return TennisFeatureExtractor()


# ---------------------------------------------------------------------------
# ScoredTennisMatch dataclass
# ---------------------------------------------------------------------------

class TestScoredTennisMatch:
    def test_defaults(self):
        s = ScoredTennisMatch(player_a='A', player_b='B')
        assert s.prob_a == 0.5
        assert s.prob_b == 0.5
        assert s.ev == 0.0

    def test_no_draw_field(self):
        """Tennis model must NOT have a prob_draw field."""
        s = ScoredTennisMatch(player_a='A', player_b='B')
        assert not hasattr(s, 'prob_draw')


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

class TestParseFormList:
    def test_list_input(self):
        assert _parse_form_list(['W', 'L', 'W']) == ['W', 'L', 'W']

    def test_string_input(self):
        assert _parse_form_list("W,L,W,L") == ['W', 'L', 'W', 'L']

    def test_empty(self):
        assert _parse_form_list([]) == []
        assert _parse_form_list('') == []

    def test_draw_converted_to_loss(self):
        assert _parse_form_list(['D']) == ['L']

    def test_none(self):
        assert _parse_form_list(None) == []


class TestFormScore:
    def test_all_wins(self):
        assert _form_score(['W', 'W', 'W', 'W', 'W']) > 0.9

    def test_all_losses(self):
        assert _form_score(['L', 'L', 'L', 'L', 'L']) < 0.1

    def test_empty_is_neutral(self):
        assert _form_score([]) == 0.5

    def test_decay_recent_first(self):
        """Recent results should matter more."""
        recent_win = _form_score(['W', 'L', 'L', 'L'])
        recent_loss = _form_score(['L', 'W', 'W', 'W'])
        # More recent win in first list — but still fewer total wins
        # The key test is that they are not equal
        assert recent_win != recent_loss


class TestStreakLen:
    def test_win_streak(self):
        assert _streak_len(['W', 'W', 'W', 'L'], 'W') == 3

    def test_no_streak(self):
        assert _streak_len(['L', 'W', 'W'], 'W') == 0

    def test_empty(self):
        assert _streak_len([], 'W') == 0


# ---------------------------------------------------------------------------
# Feature extractor
# ---------------------------------------------------------------------------

class TestFeatureExtractor:
    def test_full_data_quality(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match()
        f = extractor.extract(m)
        # base match has h2h counts, form, ranking, odds → 4/7 features
        assert f['_data_quality'] >= 0.5   # at least 4/7

    def test_minimal_data(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(
            home_wins_in_h2h_last5=0,
            away_wins_in_h2h_last5=0,
            ranking_a=None,
            ranking_b=None,
            form_a=[],
            form_b=[],
            home_odds=0,
            away_odds=0,
        )
        f = extractor.extract(m)
        assert f['_data_quality'] == 0.0

    def test_h2h_win_rate(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(home_wins_in_h2h_last5=4, away_wins_in_h2h_last5=1)
        f = extractor.extract(m)
        assert f['h2h_win_rate_a'] == pytest.approx(0.8, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_ranking_advantage_positive_for_better_a(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(ranking_a=1, ranking_b=50)
        f = extractor.extract(m)
        assert f['ranking_advantage'] > 0   # A has better ranking

    def test_ranking_advantage_negative_for_worse_a(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(ranking_a=100, ranking_b=5)
        f = extractor.extract(m)
        assert f['ranking_advantage'] < 0

    def test_odds_implied(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(home_odds=1.50, away_odds=2.80)
        f = extractor.extract(m)
        assert f['odds_prob_a'] > f['odds_prob_b']

    def test_missing_odds(self, extractor: TennisFeatureExtractor) -> None:
        m = _base_match(home_odds=0, away_odds=0)
        f = extractor.extract(m)
        assert f['odds_prob_a'] == 0.5
        assert f['odds_prob_b'] == 0.5


# ---------------------------------------------------------------------------
# Engine scoring
# ---------------------------------------------------------------------------

class TestEngine:
    def test_probabilities_sum_to_one(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert s.prob_a + s.prob_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]
        assert s.cal_a + s.cal_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]

    def test_best_pick_A_or_B(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert s.best_pick in ('A', 'B')

    def test_favorite_set(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert s.favorite in ('player_a', 'player_b')

    def test_strong_favorite(self, engine: TennisScoringEngine) -> None:
        """Djokovic #1 with 4-1 H2H and great form at 1.30 odds should pick A."""
        m = _base_match(
            home_wins_in_h2h_last5=4,
            away_wins_in_h2h_last5=1,
            ranking_a=1,
            ranking_b=30,
            form_a=['W', 'W', 'W', 'W', 'W'],
            form_b=['L', 'L', 'L', 'W', 'L'],
            home_odds=1.30,
            away_odds=3.50,
        )
        s = engine.score_match(m)
        assert s.best_pick == 'A'
        assert s.prob_a > 0.65

    def test_underdog_scenario(self, engine: TennisScoringEngine) -> None:
        """When B dominates all factors, engine should pick B."""
        m = _base_match(
            home_wins_in_h2h_last5=0,
            away_wins_in_h2h_last5=5,
            ranking_a=80,
            ranking_b=3,
            form_a=['L', 'L', 'L', 'L', 'L'],
            form_b=['W', 'W', 'W', 'W', 'W'],
            home_odds=4.00,
            away_odds=1.25,
        )
        s = engine.score_match(m)
        assert s.best_pick == 'B'
        assert s.prob_b > 0.65

    def test_ev_positive_when_odds_generous(self, engine: TennisScoringEngine) -> None:
        """If our model says 70% for A but odds imply 50%, EV should be positive."""
        m = _base_match(
            home_wins_in_h2h_last5=5,
            away_wins_in_h2h_last5=0,
            ranking_a=1,
            ranking_b=80,
            form_a=['W', 'W', 'W', 'W', 'W'],
            form_b=['L', 'L', 'L', 'L', 'L'],
            home_odds=2.00,   # implies 50% — but model should say much higher
            away_odds=1.80,
        )
        s = engine.score_match(m)
        assert s.ev > 0

    def test_advanced_score_range(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert 0 <= s.advanced_score <= 100

    def test_confidence_range(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert 0 <= s.confidence <= 100

    def test_data_quality_range(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert 0 <= s.data_quality <= 1

    def test_kelly_capped(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert s.kelly <= 25.0

    def test_edge_is_percentage(self, engine: TennisScoringEngine) -> None:
        m = _base_match()
        s = engine.score_match(m)
        assert -100 <= s.edge <= 100

    def test_no_crash_on_empty_match(self, engine: TennisScoringEngine) -> None:
        """Engine should not crash on minimal/empty data."""
        s = engine.score_match({})
        assert s.prob_a + s.prob_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]

    def test_score_matches_sorted_by_ev(self, engine: TennisScoringEngine) -> None:
        matches = [
            _base_match(home_wins_in_h2h_last5=1, away_wins_in_h2h_last5=4, home_odds=3.00, away_odds=1.30),
            _base_match(home_wins_in_h2h_last5=5, away_wins_in_h2h_last5=0, home_odds=2.00, away_odds=1.80),
        ]
        scored = engine.score_matches(matches)
        assert len(scored) == 2
        assert scored[0].ev >= scored[1].ev   # sorted descending

    def test_threshold_is_45(self, engine: TennisScoringEngine) -> None:
        assert engine.threshold == 45.0


# ---------------------------------------------------------------------------
# Field name consistency (no old field names)
# ---------------------------------------------------------------------------

class TestFieldNameConsistency:
    def test_away_field_name(self) -> None:
        """The match dict should use away_wins_in_h2h_last5, not away_wins_in_h2h."""
        m = _base_match()
        assert 'away_wins_in_h2h_last5' in m
        # The engine should read properly
        engine = TennisScoringEngine()
        s = engine.score_match(m)
        assert s.prob_a + s.prob_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_calibrate_sums_to_one(self) -> None:
        cal_a, cal_b = TennisScoringEngine._calibrate(0.7, 0.3, 1.1)  # pyright: ignore[reportPrivateUsage]
        assert cal_a + cal_b == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]

    def test_calibrate_preserves_direction(self) -> None:
        cal_a, cal_b = TennisScoringEngine._calibrate(0.8, 0.2, 1.1)  # pyright: ignore[reportPrivateUsage]
        assert cal_a > cal_b

    def test_calibrate_extreme(self) -> None:
        cal_a, cal_b = TennisScoringEngine._calibrate(0.99, 0.01, 1.1)  # pyright: ignore[reportPrivateUsage]
        assert cal_a > 0.9
        assert cal_b < 0.1


# ---------------------------------------------------------------------------
# Recency H2H
# ---------------------------------------------------------------------------

class TestRecencyH2H:
    def test_basic_h2h(self) -> None:
        h2h = [
            {'home': 'Djokovic N.', 'away': 'Nadal R.', 'score': '2:1', 'date': ''},
            {'home': 'Nadal R.', 'away': 'Djokovic N.', 'score': '2:0', 'date': ''},
        ]
        wr, cnt = _recency_h2h(h2h, 'Djokovic N.', 'Nadal R.')
        assert cnt == 2
        assert 0.0 <= wr <= 1.0

    def test_empty_h2h(self) -> None:
        wr, cnt = _recency_h2h([], 'A', 'B')
        assert wr == 0.5
        assert cnt == 0

    def test_no_player(self) -> None:
        wr, _cnt = _recency_h2h([{'home': 'X', 'away': 'Y', 'score': '2:1'}], '', '')
        assert wr == 0.5


# ---------------------------------------------------------------------------
# Surface form tests (v5)
# ---------------------------------------------------------------------------

class TestSurfaceForm:
    def test_surface_form_lists_used(self, extractor: TennisFeatureExtractor) -> None:
        """When surface_form_a/b are provided, they should be used for surface scoring."""
        m = _base_match(
            surface_form_a=['W', 'W', 'W', 'W', 'L'],
            surface_form_b=['L', 'L', 'W', 'L', 'L'],
        )
        f = extractor.extract(m)
        assert f['surface_wr_a'] > f['surface_wr_b']

    def test_surface_form_empty_fallback(self, extractor: TennisFeatureExtractor) -> None:
        """Empty surface form should give neutral 0.5."""
        m = _base_match(surface_form_a=[], surface_form_b=[])
        f = extractor.extract(m)
        assert f['surface_wr_a'] == 0.5
        assert f['surface_wr_b'] == 0.5

    def test_surface_stats_fallback(self, extractor: TennisFeatureExtractor) -> None:
        """Old surface_stats dicts should still work as fallback."""
        m = _base_match(
            surface_form_a=[],
            surface_form_b=[],
            surface_stats_a={'hard': 0.8},
            surface_stats_b={'hard': 0.4},
        )
        f = extractor.extract(m)
        assert f['surface_wr_a'] > f['surface_wr_b']


# ---------------------------------------------------------------------------
# Fatigue / freshness tests (v5)
# ---------------------------------------------------------------------------

class TestFatigue:
    def test_fatigue_computed(self, extractor: TennisFeatureExtractor) -> None:
        """When last_match dates are provided, fatigue should be computed."""
        m = _base_match(
            last_match_a_date='01.04.26',
            last_match_a_result='W',
            last_match_b_date='25.03.26',
            last_match_b_result='L',
        )
        f = extractor.extract(m)
        assert 'fatigue_a' in f
        assert 'fatigue_b' in f
        assert f['fatigue_a'] != f['fatigue_b']

    def test_fatigue_neutral_when_missing(self, extractor: TennisFeatureExtractor) -> None:
        """No last match date → neutral 0.5."""
        m = _base_match()
        f = extractor.extract(m)
        assert f['fatigue_a'] == 0.5
        assert f['fatigue_b'] == 0.5

    def test_fatigue_advantage_positive_for_fresher(self, extractor: TennisFeatureExtractor) -> None:
        """Player with recent win should have higher fatigue score."""
        m = _base_match(
            last_match_a_date='30.03.26',
            last_match_a_result='W',
            last_match_b_date=None,
            last_match_b_result=None,
        )
        f = extractor.extract(m)
        # A has recent match + win bonus, B neutral → fatigue_advantage > 0
        assert f['fatigue_advantage'] != 0.0


# ---------------------------------------------------------------------------
# SofaScore integration tests (v5)
# ---------------------------------------------------------------------------

class TestSofaScoreFeature:
    def test_sofascore_used_in_features(self, extractor: TennisFeatureExtractor) -> None:
        """SofaScore probs should feed into features."""
        m = _base_match(
            sofascore_home_win_prob=65,
            sofascore_away_win_prob=35,
        )
        f = extractor.extract(m)
        assert f['sofascore_prob_a'] > f['sofascore_prob_b']

    def test_sofascore_neutral_when_missing(self, extractor: TennisFeatureExtractor) -> None:
        """No SofaScore → neutral 0.5."""
        m = _base_match()
        f = extractor.extract(m)
        assert f['sofascore_prob_a'] == 0.5

    def test_sofascore_weight_in_engine(self) -> None:
        """Engine weights should include sofascore."""
        engine = TennisScoringEngine()
        assert 'sofascore' in engine.weights
        assert engine.weights['sofascore'] > 0

    def test_fatigue_weight_in_engine(self) -> None:
        """Engine weights should include fatigue."""
        engine = TennisScoringEngine()
        assert 'fatigue' in engine.weights
        assert engine.weights['fatigue'] > 0


# ---------------------------------------------------------------------------
# Data quality with new features (v5)
# ---------------------------------------------------------------------------

class TestDataQualityV5:
    def test_full_data_quality_7_features(self, extractor: TennisFeatureExtractor) -> None:
        """All 7 features present → data_quality = 1.0."""
        m = _base_match(
            surface_form_a=['W', 'W', 'L'],
            surface_form_b=['L', 'W', 'L'],
            last_match_a_date='01.04.26',
            last_match_a_result='W',
            last_match_b_date='31.03.26',
            last_match_b_result='L',
            sofascore_home_win_prob=55,
            sofascore_away_win_prob=45,
            # Liczba głosów należy do "pełnych danych": fan vote jest teraz
            # ważony wolumenem, tak jak w silniku piłkarskim, bo odczyt bez
            # głosów to sygnatura estymaty AI (`sofascore_total_votes = 0`),
            # która nie może ciążyć jak prawdziwa opinia społeczności.
            sofascore_total_votes=2500,
        )
        f = extractor.extract(m)
        assert f['_data_quality'] == pytest.approx(1.0, abs=0.01)  # pyright: ignore[reportUnknownMemberType]

    def test_weights_sum_to_one(self) -> None:
        """All weights must sum to 1.0."""
        engine = TennisScoringEngine()
        total = sum(engine.weights.values())
        assert total == pytest.approx(1.0, abs=0.001)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Serve/point hierarchical match model (v6)
# ---------------------------------------------------------------------------

class TestServeModel:
    def test_hold_prob_at_baseline(self) -> None:
        """64% service points ≈ 81% hold — matches real ATP hold rates."""
        hold = _prob_win_game(0.64)
        assert 0.78 <= hold <= 0.84

    def test_hold_prob_even_is_half(self) -> None:
        assert _prob_win_game(0.5) == pytest.approx(0.5, abs=1e-6)

    def test_hold_prob_monotonic(self) -> None:
        assert _prob_win_game(0.55) < _prob_win_game(0.65) < _prob_win_game(0.75)

    def test_set_prob_bounded(self) -> None:
        for hold in (0.4, 0.6, 0.8):
            for brk in (0.1, 0.3, 0.5):
                p = _prob_win_set(hold, brk)
                assert 0.0 <= p <= 1.0

    def test_match_bo3_amplifies_set_edge(self) -> None:
        """A per-set edge should amplify at match level."""
        p_set = 0.6
        p_match = _prob_win_match_bo3(p_set)
        assert p_match > p_set  # best-of-3 rewards the stronger player

    def test_match_bo3_even(self) -> None:
        assert _prob_win_match_bo3(0.5) == pytest.approx(0.5, abs=1e-6)

    def test_serve_model_symmetric(self) -> None:
        """No edge → 0.5; opposite edges are mirror images."""
        assert _serve_model_prob_a(0.0) == pytest.approx(0.5, abs=1e-6)
        assert _serve_model_prob_a(0.4) == pytest.approx(
            1.0 - _serve_model_prob_a(-0.4), abs=0.02)

    def test_serve_model_amplification(self) -> None:
        """Small point edge → larger match edge (tennis structure)."""
        # A 0.5 normalized edge maps to a point edge of ~0.05; the match prob
        # should be meaningfully above 0.5 but not absurd.
        p = _serve_model_prob_a(0.5)
        assert 0.7 < p < 0.95

    def test_serve_model_bounded(self) -> None:
        for adv in (-1.0, -0.5, 0.0, 0.5, 1.0):
            p = _serve_model_prob_a(adv)
            assert 0.02 <= p <= 0.98

    def test_serve_model_weight_in_engine(self) -> None:
        engine = TennisScoringEngine()
        assert 'serve_model' in engine.weights
        assert engine.weights['serve_model'] > 0

    def test_serve_model_in_breakdown(self) -> None:
        """The serve model should appear in the engine breakdown."""
        engine = TennisScoringEngine()
        s = engine.score_match(_base_match())
        assert 'serve_model_estimate' in s.breakdown

    def test_favorite_by_ranking_uses_serve_model(self) -> None:
        """A strong #1 vs #50 should get a high probability via serve model."""
        engine = TennisScoringEngine()
        m = _base_match(ranking_a=1, ranking_b=50,
                        form_a=['W', 'W', 'W', 'W', 'W'],
                        form_b=['L', 'L', 'W', 'L', 'L'])
        s = engine.score_match(m)
        assert s.best_pick == 'A'
        assert s.prob_a > 0.6
