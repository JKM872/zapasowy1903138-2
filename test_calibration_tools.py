"""Tests for the benchmarking/calibration tooling.

Covers the metric maths (Brier, log-loss), the baselines the model is judged
against, the settled-data exporter's key translation and outcome mapping, and
the guard rails that stop simulated weights being written to disk.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calibrate_weights as cw  # noqa: E402
import export_settled as es  # noqa: E402


class TestMetrics:
    def test_brier_perfect_prediction_is_zero(self):
        assert cw.brier([1.0, 0.0, 0.0], '1') == pytest.approx(0.0)

    def test_brier_worst_prediction_is_two(self):
        assert cw.brier([0.0, 0.0, 1.0], '1') == pytest.approx(2.0)

    def test_brier_uniform(self):
        # 3 * (1/3 - target)^2 summed = 2/3 for any single outcome
        assert cw.brier([1 / 3, 1 / 3, 1 / 3], 'X') == pytest.approx(2 / 3, abs=1e-6)

    def test_log_loss_perfect_is_zero(self):
        assert cw.log_loss([1.0, 0.0, 0.0], '1') == pytest.approx(0.0, abs=1e-9)

    def test_log_loss_uniform_is_log3(self):
        import math
        assert cw.log_loss([1 / 3, 1 / 3, 1 / 3], '2') == pytest.approx(math.log(3), abs=1e-6)

    def test_log_loss_of_zero_probability_is_finite(self):
        # Must not raise or return inf — a confident miss should be penalised
        # heavily but remain a usable number.
        val = cw.log_loss([0.0, 0.0, 1.0], '1')
        assert val > 10 and val != float('inf')

    def test_lower_brier_for_better_prediction(self):
        good = cw.brier([0.7, 0.2, 0.1], '1')
        bad = cw.brier([0.2, 0.2, 0.6], '1')
        assert good < bad


class TestEvaluation:
    def test_accuracy_counts_top_pick(self):
        ev = cw.Evaluation('t')
        ev.add([0.6, 0.3, 0.1], '1')   # hit
        ev.add([0.6, 0.3, 0.1], '2')   # miss
        s = ev.summary()
        assert s['n'] == 2
        assert s['accuracy'] == pytest.approx(0.5)

    def test_value_bet_pnl_uses_odds(self):
        ev = cw.Evaluation('t')
        ev.add([0.6, 0.3, 0.1], '1', ev=0.2, odds=2.0)   # win -> +1.0
        ev.add([0.6, 0.3, 0.1], '2', ev=0.2, odds=2.0)   # loss -> -1.0
        s = ev.summary()
        assert s['value_bets'] == 2
        assert s['net_units'] == pytest.approx(0.0)

    def test_no_bet_without_positive_ev(self):
        ev = cw.Evaluation('t')
        ev.add([0.6, 0.3, 0.1], '1', ev=-0.1, odds=2.0)
        assert ev.summary()['value_bets'] == 0

    def test_reliability_bins_track_observed_rate(self):
        ev = cw.Evaluation('t')
        for _ in range(4):
            ev.add([0.7, 0.2, 0.1], '1')    # all hit at ~0.7 confidence
        rel = ev.reliability()
        bucket = [b for b in rel if b['n'] == 4][0]
        assert bucket['predicted'] == pytest.approx(0.7, abs=1e-6)
        assert bucket['observed'] == pytest.approx(1.0)


class TestBaselines:
    def test_market_probs_remove_the_margin(self):
        probs = cw.market_probs({'home_odds': 2.0, 'draw_odds': 4.0, 'away_odds': 4.0})
        assert probs is not None
        assert sum(probs) == pytest.approx(1.0, abs=1e-9)

    def test_market_probs_none_without_odds(self):
        assert cw.market_probs({}) is None
        assert cw.market_probs({'home_odds': 1.0, 'away_odds': 0}) is None

    def test_market_favourite_gets_highest_probability(self):
        probs = cw.market_probs({'home_odds': 1.5, 'draw_odds': 4.0, 'away_odds': 6.0})
        assert probs[0] > probs[1] and probs[0] > probs[2]

    def test_prior_probs_sum_to_one(self):
        for sport in ('football', 'basketball', 'esports'):
            assert sum(cw.prior_probs({'sport': sport})) == pytest.approx(1.0, abs=1e-9)

    def test_prior_for_draw_less_sport_has_no_draw_mass(self):
        assert cw.prior_probs({'sport': 'esports'})[1] == pytest.approx(0.0)


class TestWeightNormalisation:
    def test_normalise_sums_to_one(self):
        out = cw._normalise({'a': 2.0, 'b': 2.0})
        assert sum(out.values()) == pytest.approx(1.0)
        assert out['a'] == pytest.approx(0.5)

    def test_normalise_handles_all_zero(self):
        out = cw._normalise({'a': 0.0, 'b': 0.0})
        assert all(v == 0.0 for v in out.values())


class TestSimulatedDataset:
    def test_rows_carry_a_valid_outcome(self):
        rows = cw.build_simulated_rows(20, seed=5)
        assert len(rows) == 20
        assert all(r['actual_result'] in ('1', 'X', '2') for r in rows)

    def test_generation_is_deterministic(self):
        a = cw.build_simulated_rows(10, seed=5)
        b = cw.build_simulated_rows(10, seed=5)
        assert [r['actual_result'] for r in a] == [r['actual_result'] for r in b]

    def test_evaluation_reports_every_baseline(self):
        res = cw.evaluate_dataset(cw.build_simulated_rows(30, seed=5))
        for key in ('model', 'market', 'prior', 'uniform'):
            assert res[key]['n'] > 0
            assert 0.0 <= res[key]['accuracy'] <= 1.0
            assert res[key]['brier'] >= 0.0


class TestExporterOutcomeMapping:
    @pytest.mark.parametrize('h,a,expected', [
        (2, 1, '1'), (1, 2, '2'), (1, 1, 'X'), (0, 0, 'X'),
    ])
    def test_outcome_from_scores(self, h, a, expected):
        assert es.outcome_from_scores(h, a) == expected

    def test_outcome_from_scores_rejects_garbage(self):
        assert es.outcome_from_scores(None, 1) is None
        assert es.outcome_from_scores('x', 'y') is None

    @pytest.mark.parametrize('winner,expected', [
        ('home', '1'), ('away', '2'), ('draw', 'X'), ('HOME', '1'), ('', None),
    ])
    def test_outcome_from_winner(self, winner, expected):
        assert es.outcome_from_winner(winner) == expected


class TestExporterKeyTranslation:
    def test_camel_case_is_translated(self):
        row = es.normalise_row({
            'homeTeam': 'Alpha', 'awayTeam': 'Beta', 'sport': 'football',
            'homeForm': ['W', 'L'], 'awayForm': ['L'],
            'matchUrl': 'http://x/1',
            'odds': {'home': 1.8, 'draw': 3.4, 'away': 4.0},
            'forebet': {'prediction': '1', 'probability': 55},
            'sofascore': {'home': 60, 'draw': 20, 'away': 20, 'votes': 400},
            'h2h': {'home': 3, 'away': 1, 'total': 5, 'winRate': 0.6},
        })
        assert row['home_team'] == 'Alpha'
        assert row['away_team'] == 'Beta'
        assert row['home_form'] == ['W', 'L']
        assert row['home_odds'] == 1.8
        assert row['draw_odds'] == 3.4
        assert row['forebet_prediction'] == '1'
        assert row['sofascore_home_win_prob'] == 60
        assert row['home_wins_in_h2h_last5'] == 3
        assert row['h2h_count'] == 5

    def test_snake_case_input_is_preserved(self):
        row = es.normalise_row({
            'home_team': 'A', 'away_team': 'B', 'home_odds': 2.0,
            'sport': 'TENNIS',
        })
        assert row['home_team'] == 'A'
        assert row['home_odds'] == 2.0
        assert row['sport'] == 'tennis'   # normalised to lowercase

    def test_translated_row_is_scoreable(self):
        from football_scoring_engine import FootballScoringEngine
        row = es.normalise_row({
            'homeTeam': 'Alpha', 'awayTeam': 'Beta', 'sport': 'football',
            'odds': {'home': 1.9, 'draw': 3.5, 'away': 3.8},
            'h2h': {'home': 4, 'away': 1, 'total': 5, 'winRate': 0.8},
        })
        scored = FootballScoringEngine().score_match(row)
        assert 0.0 < scored.cal_home < 1.0
        # The H2H aggregate must actually reach the engine.
        assert scored.features['h2h_count'] > 0


class TestExporterLocalJoin:
    def test_join_matches_features_with_outcomes(self, tmp_path, monkeypatch):
        results_dir = tmp_path / 'results'
        outputs_dir = tmp_path / 'outputs'
        results_dir.mkdir()
        outputs_dir.mkdir()

        (results_dir / 'matches_2026-01-01_football.json').write_text(json.dumps({
            'date': '2026-01-01', 'sport': 'football',
            'matches': [
                {'homeTeam': 'Alpha', 'awayTeam': 'Beta',
                 'matchUrl': 'http://x/1', 'sport': 'football',
                 'odds': {'home': 1.9, 'draw': 3.4, 'away': 4.1}},
                {'homeTeam': 'Gamma', 'awayTeam': 'Delta',
                 'matchUrl': 'http://x/2', 'sport': 'football'},
            ],
        }), encoding='utf-8')

        (outputs_dir / 'result_store.json').write_text(json.dumps({
            'http://x/1': {'status': 'finished', 'score_home': 2,
                           'score_away': 1, 'winner': 'home'},
            'http://x/2': {'status': 'not_finished'},
        }), encoding='utf-8')

        monkeypatch.chdir(tmp_path)
        rows = es.export_local('football')

        # Only the finished match may be exported.
        assert len(rows) == 1
        assert rows[0]['home_team'] == 'Alpha'
        assert rows[0]['actual_result'] == '1'
        assert rows[0]['final_score'] == '2-1'

    def test_missing_store_returns_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert es.export_local('football') == []

    def test_unfinished_matches_are_excluded(self, tmp_path, monkeypatch):
        (tmp_path / 'results').mkdir()
        (tmp_path / 'outputs').mkdir()
        (tmp_path / 'results' / 'matches_2026-01-01_football.json').write_text(
            json.dumps({'matches': [{'homeTeam': 'A', 'awayTeam': 'B',
                                     'matchUrl': 'u1'}]}), encoding='utf-8')
        (tmp_path / 'outputs' / 'result_store.json').write_text(
            json.dumps({'u1': {'status': 'no_score'}}), encoding='utf-8')
        monkeypatch.chdir(tmp_path)
        assert es.export_local('football') == []


class TestRealRowLoading:
    def test_only_settled_rows_are_kept(self, tmp_path):
        path = tmp_path / 'settled.json'
        path.write_text(json.dumps([
            {'home_team': 'A', 'away_team': 'B', 'actual_result': '1'},
            {'home_team': 'C', 'away_team': 'D'},                 # no outcome
            {'home_team': 'E', 'away_team': 'F', 'actual_result': 'pending'},
            {'home_team': 'G', 'away_team': 'H', 'actual_result': 'x'},  # lowercase
        ]), encoding='utf-8')
        rows = cw.load_real_rows(str(path))
        assert len(rows) == 2
        assert rows[1]['actual_result'] == 'X'   # normalised to uppercase

    def test_wrapped_payload_is_unwrapped(self, tmp_path):
        path = tmp_path / 'settled.json'
        path.write_text(json.dumps(
            {'matches': [{'home_team': 'A', 'actual_result': '2'}]}),
            encoding='utf-8')
        assert len(cw.load_real_rows(str(path))) == 1


class TestPerSportRouting:
    """Each sport must be judged with the engine that fits it."""

    def _row(self, sport, **kw):
        m = {
            'home_team': 'A', 'away_team': 'B', 'sport': sport,
            'actual_result': '1',
            'home_form': ['W', 'W', 'L'], 'away_form': ['L', 'L', 'W'],
        }
        m.update(kw)
        return m

    def test_tennis_goes_to_the_tennis_engine(self):
        from football_scoring_engine import FootballScoringEngine
        probs, _ev, _odds = cw._score_row(
            self._row('tennis', home_odds=1.6, away_odds=2.4),
            FootballScoringEngine())
        assert probs[1] == 0.0, 'tennis must never carry draw mass'
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)

    def test_football_keeps_its_draw(self):
        from football_scoring_engine import FootballScoringEngine
        probs, _ev, _odds = cw._score_row(
            self._row('football', home_odds=1.9, draw_odds=3.4, away_odds=4.0),
            FootballScoringEngine())
        assert probs[1] > 0.0
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)

    def test_draw_less_team_sports_have_no_draw(self):
        from football_scoring_engine import FootballScoringEngine
        engine = FootballScoringEngine()
        for sport in ('basketball', 'volleyball', 'baseball', 'esports'):
            probs, _ev, _odds = cw._score_row(
                self._row(sport, home_odds=1.8, away_odds=2.1), engine)
            assert probs[1] == 0.0, sport
            assert sum(probs) == pytest.approx(1.0, abs=1e-6)


class TestPerSportEvaluation:
    def _rows(self, sport, n, outcome='1'):
        return [{
            'home_team': f'A{i}', 'away_team': f'B{i}', 'sport': sport,
            'actual_result': outcome,
            'home_odds': 1.8, 'draw_odds': 3.4, 'away_odds': 2.2,
            'home_form': ['W', 'W'], 'away_form': ['L', 'L'],
        } for i in range(n)]

    def test_groups_by_sport(self):
        rows = self._rows('football', 5) + self._rows('basketball', 3)
        res = cw.evaluate_per_sport(rows)
        assert set(res) == {'football', 'basketball'}
        assert res['football']['n_rows'] == 5
        assert res['basketball']['n_rows'] == 3

    def test_small_samples_are_flagged_unreliable(self):
        res = cw.evaluate_per_sport(self._rows('football', 4), min_rows=30)
        assert res['football']['reliable'] is False

    def test_large_samples_are_reliable(self):
        res = cw.evaluate_per_sport(self._rows('football', 40), min_rows=30)
        assert res['football']['reliable'] is True

    def test_each_sport_gets_its_own_baselines(self):
        res = cw.evaluate_per_sport(self._rows('football', 5))
        f = res['football']
        for key in ('model', 'market', 'prior', 'uniform'):
            assert f[key]['n'] > 0

    def test_missing_sport_defaults_to_football(self):
        rows = [{'home_team': 'A', 'away_team': 'B', 'actual_result': '1',
                 'home_odds': 1.8, 'away_odds': 2.2}]
        assert set(cw.evaluate_per_sport(rows)) == {'football'}

    def test_sport_without_odds_reports_no_market(self):
        rows = [{'home_team': 'A', 'away_team': 'B', 'sport': 'baseball',
                 'actual_result': '1', 'home_form': ['W'], 'away_form': ['L']}
                for _ in range(3)]
        res = cw.evaluate_per_sport(rows)
        assert res['baseball']['market']['n'] == 0
        assert res['baseball']['model']['n'] == 3

    def test_report_prints_without_error(self, capsys):
        res = cw.evaluate_per_sport(
            self._rows('football', 3) + self._rows('tennis', 2))
        cw.print_per_sport(res, min_rows=30)
        out = capsys.readouterr().out
        assert 'PER-SPORT BREAKDOWN' in out
        assert 'football' in out and 'tennis' in out
        assert 'noise' in out          # both samples are below min_rows


# ---------------------------------------------------------------------------
# Source coverage and the guards it feeds
# ---------------------------------------------------------------------------

def _settled(sport='football', **extra):
    """A settled row carrying nothing but H2H, so every optional source is absent."""
    row = {
        'sport': sport,
        'home_team': 'Alpha', 'away_team': 'Beta',
        'actual_result': '1',
        'home_wins_in_h2h_last5': 4, 'away_wins_in_h2h_last5': 1,
        'h2h_matches_count': 5,
    }
    row.update(extra)
    return row


class TestSourceCoverage:
    def test_absent_sources_are_reported_as_zero(self):
        cov = cw.source_coverage([_settled(), _settled()])

        assert cov['odds'] == 0
        assert cov['gemini'] == 0
        assert cov['availability'] == 0

    def test_present_source_is_counted(self):
        cov = cw.source_coverage([
            _settled(home_odds=1.9, draw_odds=3.4, away_odds=4.2),
            _settled(),
        ])

        assert cov['odds'] == 1

    def test_h2h_is_detected(self):
        assert cw.source_coverage([_settled()])['h2h'] == 1

    def test_empty_input(self):
        cov = cw.source_coverage([])
        assert set(cov) == set(cw._ABSTAINING_SOURCES)
        assert all(v == 0 for v in cov.values())

    def test_malformed_rows_do_not_raise(self):
        cov = cw.source_coverage([{}, None, {'sport': 'football'}])
        assert isinstance(cov, dict)


class TestPinAbsentSources:
    def test_absent_source_is_zeroed_and_rest_renormalised(self):
        pinned = cw.pin_absent_sources({'odds': 0.5, 'h2h': 0.25, 'form': 0.25},
                                       {'odds'})

        assert pinned['odds'] == 0.0
        assert sum(pinned.values()) == pytest.approx(1.0)
        # The survivors keep their ratio to each other.
        assert pinned['h2h'] == pytest.approx(pinned['form'])

    def test_nothing_absent_is_a_plain_renormalisation(self):
        pinned = cw.pin_absent_sources({'odds': 0.6, 'h2h': 0.6}, set())

        assert pinned['odds'] == pytest.approx(0.5)
        assert pinned['h2h'] == pytest.approx(0.5)

    def test_pinning_everything_falls_back_to_the_input(self):
        """Zeroing every source would leave no model at all."""
        original = {'odds': 0.5, 'h2h': 0.5}
        assert cw.pin_absent_sources(original, {'odds', 'h2h'}) == original

    def test_pinning_does_not_change_predictions(self):
        """The engine averages over contributing sources, so rescaling is inert.

        This is what makes the honest artifact free: it only removes numbers
        that describe nothing.
        """
        from football_scoring_engine import FootballScoringEngine

        row = _settled()
        raw = dict(FootballScoringEngine.DEFAULT_WEIGHTS)
        absent = {k for k, n in cw.source_coverage([row]).items() if n == 0}

        before = cw._engine_with(raw).score_match(row)
        after = cw._engine_with(cw.pin_absent_sources(raw, absent)).score_match(row)

        assert after.cal_home == pytest.approx(before.cal_home, abs=1e-9)
        assert after.cal_away == pytest.approx(before.cal_away, abs=1e-9)


class TestEngineWith:
    def test_explicit_weights_override_a_committed_per_sport_set(self, tmp_path):
        """Otherwise every candidate after the first calibration is a no-op.

        `weights_for_sport` prefers the per-sport entry loaded from disk, so
        without clearing it the tuned weights would be set and then bypassed —
        and the sport could never be improved again.
        """
        engine = cw._engine_with({'odds': 1.0})

        assert engine.sport_weights == {}
        assert engine.weights_for_sport('football')['odds'] == 1.0

    def test_no_weights_keeps_the_committed_calibration(self):
        from football_scoring_engine import FootballScoringEngine

        engine = cw._engine_with(None)
        reference = FootballScoringEngine()
        assert engine.sport_weights == reference.sport_weights

    def test_evaluation_actually_responds_to_weights(self):
        """A guard against the metrics being blind to the thing being tuned."""
        from football_scoring_engine import FootballScoringEngine

        def only(source):
            w = {k: 0.0 for k in FootballScoringEngine.DEFAULT_WEIGHTS}
            w[source] = 1.0
            return w

        rows = [_settled(home_odds=1.2, draw_odds=6.0, away_odds=12.0,
                         actual_result='2')]

        all_odds = cw.evaluate_dataset(rows, weights=only('odds'))
        all_h2h = cw.evaluate_dataset(rows, weights=only('h2h'))

        assert all_odds['model']['brier'] != all_h2h['model']['brier']


class TestCalibrationRowFloor:
    def test_floor_is_stricter_than_the_reporting_threshold(self):
        assert cw.MIN_CALIBRATION_ROWS > 30

    def test_sport_below_the_floor_is_skipped(self):
        rows = [_settled() for _ in range(40)]

        accepted, report = cw.optimise_per_sport(
            rows, iterations=2, seed=1, test_frac=0.3,
            min_rows=cw.MIN_CALIBRATION_ROWS)

        assert accepted == {}
        assert report['football']['status'] == 'too_few_rows'
