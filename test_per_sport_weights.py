"""Tests for per-sport weight support in the scoring engine.

Sports differ in which inputs even exist — baseball has no odds at all, tennis
rarely has H2H or Forebet — so a single shared weight mix cannot be right
everywhere. This adds the mechanism (and its safety rails); the actual numbers
must come from calibration on settled results, never from guesswork, which is
why the override table ships empty.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from football_scoring_engine import FootballScoringEngine  # noqa: E402


def _write_calibration(tmp_path, payload):
    path = tmp_path / 'scoring_calibration.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


class TestDefaultsUnchanged:
    """The code alone must not hardcode any per-sport mix.

    These build the engine against a path that does not exist, so they describe
    the code's own defaults rather than whatever `outputs/scoring_calibration.json`
    currently holds. That file is a measured artifact committed by the Backtest
    workflow — asserting it is empty would make the tests fail the moment a real
    calibration lands, which is the opposite of what we want to guard.
    """

    @staticmethod
    def _uncalibrated(tmp_path):
        return FootballScoringEngine(
            calibration_path=str(tmp_path / 'no-calibration.json'))

    def test_no_overrides_by_default(self):
        assert FootballScoringEngine.SPORT_WEIGHT_OVERRIDES == {}

    def test_engine_starts_with_no_sport_weights(self, tmp_path):
        assert self._uncalibrated(tmp_path).sport_weights == {}

    def test_every_sport_uses_the_global_mix(self, tmp_path):
        engine = self._uncalibrated(tmp_path)
        for sport in ('football', 'tennis', 'baseball', 'esports', 'curling'):
            assert engine.weights_for_sport(sport) is engine.weights

    def test_none_sport_defaults_to_global(self, tmp_path):
        engine = self._uncalibrated(tmp_path)
        assert engine.weights_for_sport(None) is engine.weights


class TestShippedCalibration:
    """Whatever is committed must be loadable and sane.

    A malformed or lopsided calibration file would silently distort every
    prediction, so the shipped artifact is checked like any other input.
    """

    def test_shipped_file_if_present_is_usable(self):
        path = FootballScoringEngine.CALIBRATION_PATH
        if not os.path.isfile(path):
            pytest.skip('no calibration committed yet')

        engine = FootballScoringEngine()
        for sport, weights in engine.sport_weights.items():
            assert set(weights) == set(engine.DEFAULT_WEIGHTS), sport
            assert sum(weights.values()) == pytest.approx(1.0, abs=0.01), sport
            assert all(0.0 <= v <= 1.0 for v in weights.values()), sport


class TestCalibrationLoading:
    def test_global_weights_are_applied(self, tmp_path):
        path = _write_calibration(tmp_path, {'weights': {'odds': 0.40}})
        engine = FootballScoringEngine(calibration_path=path)
        assert engine.weights['odds'] == pytest.approx(0.40)

    def test_per_sport_weights_are_applied(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'weights': {'odds': 0.21},
            'per_sport': {'baseball': {'odds': 0.0, 'h2h': 0.30}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        baseball = engine.weights_for_sport('baseball')
        assert baseball['odds'] == 0.0
        assert baseball['h2h'] == pytest.approx(0.30)
        # Untouched keys inherit the global value.
        assert baseball['form'] == engine.weights['form']

    def test_other_sports_keep_globals(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'per_sport': {'baseball': {'odds': 0.0}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        assert engine.weights_for_sport('football') is engine.weights
        assert engine.weights_for_sport('baseball')['odds'] == 0.0

    def test_sport_key_is_case_insensitive(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'per_sport': {'BaseBall': {'odds': 0.0}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        assert engine.weights_for_sport('baseball')['odds'] == 0.0

    def test_missing_file_is_harmless(self, tmp_path):
        engine = FootballScoringEngine(calibration_path=str(tmp_path / 'nope.json'))
        assert engine.weights == FootballScoringEngine.DEFAULT_WEIGHTS

    def test_corrupt_file_is_harmless(self, tmp_path):
        path = tmp_path / 'bad.json'
        path.write_text('{not json at all', encoding='utf-8')
        engine = FootballScoringEngine(calibration_path=str(path))
        assert engine.weights == FootballScoringEngine.DEFAULT_WEIGHTS

    def test_non_numeric_values_are_ignored(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'weights': {'odds': 'lots'},
            'per_sport': {'tennis': {'h2h': None}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        assert engine.weights['odds'] == FootballScoringEngine.DEFAULT_WEIGHTS['odds']
        assert engine.weights_for_sport('tennis')['h2h'] == \
            FootballScoringEngine.DEFAULT_WEIGHTS['h2h']

    def test_unknown_weight_keys_are_ignored(self, tmp_path):
        path = _write_calibration(tmp_path, {'weights': {'astrology': 0.9}})
        engine = FootballScoringEngine(calibration_path=path)
        assert 'astrology' not in engine.weights

    def test_per_sport_not_a_dict_is_ignored(self, tmp_path):
        path = _write_calibration(tmp_path, {'per_sport': ['football']})
        engine = FootballScoringEngine(calibration_path=path)
        assert engine.sport_weights == {}


class TestScoringUsesSportWeights:
    def _match(self, sport):
        return {
            'home_team': 'A', 'away_team': 'B', 'sport': sport,
            'home_odds': 1.7, 'draw_odds': 3.5, 'away_odds': 4.5,
            'home_form': ['L', 'L', 'L'], 'away_form': ['W', 'W', 'W'],
        }

    def test_sport_override_changes_the_output(self, tmp_path):
        # Football keeps defaults; hockey leans entirely on form, which here
        # points the opposite way to the market.
        path = _write_calibration(tmp_path, {
            'per_sport': {'hockey': {'odds': 0.0, 'form': 0.80}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        football = engine.score_match(self._match('football'))
        hockey = engine.score_match(self._match('hockey'))
        assert hockey.cal_home < football.cal_home

    def test_probabilities_remain_valid_with_overrides(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'per_sport': {'football': {'odds': 0.9, 'h2h': 0.05}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        scored = engine.score_match(self._match('football'))
        total = scored.cal_home + scored.cal_draw + scored.cal_away
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_zeroed_weights_do_not_crash(self, tmp_path):
        path = _write_calibration(tmp_path, {
            'per_sport': {'football': {k: 0.0 for k in
                                       FootballScoringEngine.DEFAULT_WEIGHTS}},
        })
        engine = FootballScoringEngine(calibration_path=path)
        scored = engine.score_match(self._match('football'))
        assert 0.0 <= scored.cal_home <= 1.0


class TestPerSportOptimisation:
    def _rows(self, sport, n, seed=1):
        import calibrate_weights as cw
        rows = cw.build_simulated_rows(n, seed=seed)
        for r in rows:
            r['sport'] = sport
        return rows

    def test_small_sports_are_skipped(self):
        import calibrate_weights as cw
        weights, report = cw.optimise_per_sport(
            self._rows('football', 5), iterations=1, seed=1,
            test_frac=0.3, min_rows=30, simulated=True)
        assert weights == {}
        assert report['football']['status'] == 'too_few_rows'

    def test_report_records_each_sport(self):
        import calibrate_weights as cw
        rows = self._rows('football', 6) + self._rows('tennis', 4, seed=2)
        _weights, report = cw.optimise_per_sport(
            rows, iterations=1, seed=1, test_frac=0.3, min_rows=50,
            simulated=True)
        assert set(report) == {'football', 'tennis'}
        assert all(r['status'] == 'too_few_rows' for r in report.values())
