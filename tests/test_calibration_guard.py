"""Calibration must refuse data whose outcomes carry no information.

The Supabase export handed us 1000 settled rows in which ``actual_result`` was
'1' for every single match, across seven sports — no draw and no away win
anywhere. Tuned against it the model looked excellent: football "accuracy" 81%,
basketball 94%, both "beating the market". The real settled picks over the same
period were running at 44.7% with a ROI of -24%. The optimiser had been rewarded
for predicting a constant, and the per-sport weights it produced were shipped.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calibrate_weights as cw  # noqa: E402
import probability_calibration as pc  # noqa: E402


def _rows(*outcomes):
    return [{'sport': 'football', 'home_team': 'A', 'away_team': 'B',
             'actual_result': o} for o in outcomes]


class TestLabelGuard:
    def test_single_class_is_rejected(self):
        ok, reason = cw.labels_are_usable(_rows(*(['1'] * 100)))

        assert ok is False
        assert 'jedna klasa' in reason

    def test_near_single_class_is_rejected(self):
        ok, _ = cw.labels_are_usable(_rows(*(['1'] * 199 + ['2'])))
        assert ok is False

    def test_a_real_spread_is_accepted(self):
        rows = _rows(*(['1'] * 45 + ['X'] * 25 + ['2'] * 30))
        ok, reason = cw.labels_are_usable(rows)

        assert ok is True
        assert '1' in reason

    def test_two_classes_are_enough(self):
        """Two-outcome sports never produce a draw."""
        ok, _ = cw.labels_are_usable(_rows(*(['1'] * 60 + ['2'] * 40)))
        assert ok is True

    def test_empty_input_is_rejected(self):
        ok, reason = cw.labels_are_usable([])
        assert ok is False
        assert 'brak' in reason

    def test_garbage_labels_are_rejected(self):
        ok, reason = cw.labels_are_usable(_rows('W', 'L', 'W', 'L'))
        assert ok is False
        assert 'etykiet' in reason

    def test_distribution_is_reported(self):
        dist = cw.outcome_distribution(_rows('1', '1', 'X', '2'))
        assert dist == {'1': 2, 'X': 1, '2': 1}


class TestCliRefuses:
    def _write(self, tmp_path, rows):
        path = tmp_path / 'settled.json'
        path.write_text(json.dumps(rows), encoding='utf-8')
        return str(path)

    def test_tuning_stops_on_degenerate_labels(self, tmp_path, capsys, monkeypatch):
        rows = [{'sport': 'football', 'home_team': f'H{i}', 'away_team': f'A{i}',
                 'actual_result': '1', 'home_odds': 2.0, 'draw_odds': 3.3,
                 'away_odds': 3.0} for i in range(80)]
        path = self._write(tmp_path, rows)
        monkeypatch.setattr(sys, 'argv',
                            ['calibrate_weights.py', '--real', path,
                             '--optimise-temperature'])

        code = cw.main()
        out = capsys.readouterr().out

        assert code == 2, 'a refusal must not look like success'
        assert 'WSTRZYMANA' in out

    def test_reporting_without_tuning_is_still_allowed(self, tmp_path, capsys,
                                                       monkeypatch):
        """Looking at bad data is fine; learning from it is not."""
        rows = [{'sport': 'football', 'home_team': f'H{i}', 'away_team': f'A{i}',
                 'actual_result': '1', 'home_odds': 2.0, 'draw_odds': 3.3,
                 'away_odds': 3.0} for i in range(40)]
        path = self._write(tmp_path, rows)
        monkeypatch.setattr(sys, 'argv', ['calibrate_weights.py', '--real', path])

        assert cw.main() == 0
        assert 'jedna klasa' in capsys.readouterr().out


class TestIsotonic:
    def test_monotone_curve_from_noisy_pairs(self):
        pairs = ([(0.4, 1)] * 20 + [(0.4, 0)] * 5
                 + [(0.8, 1)] * 15 + [(0.8, 0)] * 15)
        curve = pc.fit_isotonic(pairs)

        assert curve
        values = [y for _x, y in curve]
        assert values == sorted(values), 'more confident must never mean worse'

    def test_curve_maps_towards_observed_frequency(self):
        pairs = [(0.4, 1)] * 40 + [(0.4, 0)] * 10      # stated 40%, wins 80%
        curve = pc.fit_isotonic(pairs)

        assert pc.apply_isotonic(curve, 0.4) == pytest.approx(0.8, abs=0.05)

    def test_too_little_data_yields_no_curve(self):
        assert pc.fit_isotonic([(0.5, 1), (0.6, 0)]) == []

    def test_no_curve_is_the_identity(self):
        assert pc.apply_isotonic([], 0.42) == 0.42

    def test_triplet_keeps_the_sum_and_the_structural_zero(self):
        curve = [(0.5, 0.30), (1.0, 0.80)]
        out = pc.calibrate_triplet(curve, [0.45, 0.0, 0.55])

        assert sum(out) == pytest.approx(1.0)
        assert out[1] == 0.0, 'a sport with no draw must keep its zero'
        assert out[2] == pytest.approx(0.80, abs=1e-6)

    def test_triplet_without_a_curve_only_normalises(self):
        out = pc.calibrate_triplet([], [1.0, 1.0, 2.0])
        assert out == pytest.approx([0.25, 0.25, 0.5])

    def test_leading_outcome_is_the_one_corrected(self):
        curve = [(1.0, 0.9)]
        out = pc.calibrate_triplet(curve, [0.2, 0.3, 0.5])

        assert out[2] == pytest.approx(0.9)
        assert out[0] < out[1], 'the rest keep their relative order'

    def test_load_curves_ignores_malformed_entries(self):
        curves = pc.load_curves({'isotonic': {
            'football': [[0.5, 0.4], [1.0, 0.8]],
            'broken': 'nope',
            'out_of_range': [[0.5, 7.0]],
        }})

        assert 'football' in curves
        assert 'broken' not in curves
        assert 'out_of_range' not in curves

    def test_load_curves_on_empty_payload(self):
        assert pc.load_curves(None) == {}
        assert pc.load_curves({}) == {}


class TestEngineIntegration:
    def test_curve_changes_the_stated_probability(self, tmp_path):
        from football_scoring_engine import FootballScoringEngine

        row = {'home_team': 'A', 'away_team': 'B', 'sport': 'football',
               'home_odds': 2.5, 'draw_odds': 3.3, 'away_odds': 3.0,
               'home_wins_in_h2h_last5': 4, 'away_wins_in_h2h_last5': 1,
               'h2h_count': 5}

        plain = FootballScoringEngine(
            calibration_path=str(tmp_path / 'none.json'))
        curved = FootballScoringEngine(
            calibration_path=str(tmp_path / 'none.json'))
        curved.sport_isotonic = {'football': [(1.0, 0.95)]}

        before = plain.score_match(row)
        after = curved.score_match(row)

        assert max(after.cal_home, after.cal_draw, after.cal_away) == pytest.approx(
            0.95, abs=1e-6)
        assert (after.cal_home + after.cal_draw + after.cal_away
                == pytest.approx(1.0, abs=1e-6))
        assert before.cal_home != after.cal_home

    def test_temperature_override_is_read_from_the_file(self, tmp_path):
        from football_scoring_engine import FootballScoringEngine

        path = tmp_path / 'cal.json'
        path.write_text(json.dumps({'temperatures': {'football': 0.8}}),
                        encoding='utf-8')
        engine = FootballScoringEngine(calibration_path=str(path))

        assert engine.temperature_for_sport('football') == pytest.approx(0.8)

    @pytest.mark.parametrize('bad', [0.0, -1.0, 99.0, 'x', None])
    def test_absurd_temperatures_are_ignored(self, tmp_path, bad):
        from football_scoring_engine import FootballScoringEngine

        path = tmp_path / 'cal.json'
        path.write_text(json.dumps({'temperatures': {'football': bad}}),
                        encoding='utf-8')
        engine = FootballScoringEngine(calibration_path=str(path))

        assert engine.temperature_for_sport('football') == pytest.approx(1.50)


class TestShippedCalibrationIsClean:
    def test_no_weights_survive_from_the_degenerate_export(self):
        """Those sets were tuned to predict a constant."""
        from football_scoring_engine import FootballScoringEngine

        engine = FootballScoringEngine()
        assert engine.sport_weights == {}
        assert engine.sport_temperatures == {}
        assert engine.sport_isotonic == {}


class TestExportRefusesDegenerateLabels:
    """The corrupt table must not become a training set at the source either."""

    def test_single_class_export_is_refused(self):
        import export_settled as es

        ok, reason = es.labels_are_usable([{'actual_result': '1'}] * 100)
        assert ok is False
        assert 'jedna klasa' in reason

    def test_real_spread_passes(self):
        import export_settled as es

        rows = ([{'actual_result': '1'}] * 45 + [{'actual_result': 'X'}] * 25
                + [{'actual_result': '2'}] * 30)
        ok, _ = es.labels_are_usable(rows)
        assert ok is True

    def test_two_outcome_sports_pass(self):
        """Table tennis and tennis never produce a draw."""
        import export_settled as es

        rows = [{'actual_result': '1'}] * 109 + [{'actual_result': '2'}] * 133
        ok, _ = es.labels_are_usable(rows)
        assert ok is True

    def test_cli_refuses_and_signals_failure(self, tmp_path, monkeypatch, capsys):
        """Exit 1 is what makes the backtest fall through to the local source."""
        import export_settled as es

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(es, 'export_local',
                            lambda sport: [{'actual_result': '1',
                                            'home_team': 'A', 'away_team': 'B'}] * 50)
        monkeypatch.setattr(sys, 'argv',
                            ['export_settled.py', '--source', 'local'])

        assert es.main() == 1
        assert 'Odmawiam eksportu' in capsys.readouterr().out


class TestCurveMustBeACurve:
    def test_two_bins_are_rejected_as_a_ceiling(self):
        """The first real fit produced 'below 0.41 say 0.42, above say 0.50'."""
        assert cw.MIN_CURVE_BINS >= 3

    def test_coarse_curve_is_not_accepted(self, monkeypatch):
        monkeypatch.setattr('probability_calibration.fit_isotonic',
                            lambda pairs, **kw: [(0.41, 0.42), (1.0, 0.50)])
        rows = [{'sport': 'football', 'home_team': f'H{i}', 'away_team': f'A{i}',
                 'actual_result': '1' if i % 2 else '2',
                 'home_odds': 2.0, 'draw_odds': 3.3, 'away_odds': 3.0,
                 'h2h_count': 4, 'home_wins_in_h2h_last5': 3,
                 'away_wins_in_h2h_last5': 1} for i in range(120)]

        accepted, report = cw.optimise_isotonic(
            rows, seed=1, test_frac=0.3, min_rows=60)

        assert accepted == {}
        assert report['football']['status'] == 'too_coarse'
