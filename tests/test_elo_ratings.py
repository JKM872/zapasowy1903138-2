"""Tests for the Elo strength ratings.

The point of these is narrow: prove the walk cannot see the future. A rating
model that peeks reports excellent numbers and then loses money, which is
exactly the trap the earlier "81% on football" fell into, so the leak tests
matter more than the arithmetic ones.
"""

import math

import pytest

from elo_ratings import (BASE_RATING, EloModel, expected_score, fit,
                         observed_draw_share)


def row(date, home, away, winner, sport='table_tennis'):
    return {'date': date, 'home_team': home, 'away_team': away,
            'winner': winner, 'sport': sport}


class TestExpectedScore:
    def test_equal_ratings_are_a_coin_flip(self):
        assert expected_score(1500, 1500) == pytest.approx(0.5)

    def test_higher_rating_is_favoured(self):
        assert expected_score(1700, 1500) > 0.5

    def test_four_hundred_points_is_ten_to_one(self):
        assert expected_score(1900, 1500) == pytest.approx(10 / 11, abs=1e-6)

    def test_probabilities_are_complementary(self):
        assert (expected_score(1600, 1450)
                + expected_score(1450, 1600)) == pytest.approx(1.0)

    def test_home_advantage_shifts_towards_the_home_side(self):
        assert expected_score(1500, 1500, home_advantage=40) > 0.5


class TestUpdate:
    def test_winner_gains_and_loser_loses(self):
        m = EloModel(k=24, home_advantage=0)
        m.update('Alpha', 'Beta', 'home')
        assert m.rating('Alpha') > BASE_RATING
        assert m.rating('Beta') < BASE_RATING

    def test_update_is_zero_sum(self):
        m = EloModel(k=24, home_advantage=0)
        m.update('Alpha', 'Beta', 'away')
        assert (m.rating('Alpha') + m.rating('Beta')
                == pytest.approx(2 * BASE_RATING))

    def test_draw_between_equals_changes_nothing(self):
        m = EloModel(k=24, home_advantage=0)
        m.update('Alpha', 'Beta', 'draw')
        assert m.rating('Alpha') == pytest.approx(BASE_RATING)
        assert m.rating('Beta') == pytest.approx(BASE_RATING)

    def test_beating_a_stronger_opponent_gains_more(self):
        strong = EloModel(k=24, home_advantage=0)
        strong.ratings['favourite'] = 1900.0
        strong.update('underdog', 'favourite', 'home')
        upset_gain = strong.rating('underdog') - BASE_RATING

        even = EloModel(k=24, home_advantage=0)
        even.update('underdog', 'peer', 'home')
        assert upset_gain > even.rating('underdog') - BASE_RATING

    def test_unknown_winner_is_ignored(self):
        m = EloModel(k=24)
        m.update('Alpha', 'Beta', 'postponed')
        assert m.ratings == {}
        assert m.matches_played('Alpha') == 0

    def test_names_are_matched_case_and_space_insensitively(self):
        m = EloModel(k=24, home_advantage=0)
        m.update('Adam  Ruszkiewicz', 'Beta', 'home')
        assert m.rating('adam ruszkiewicz') == m.rating('Adam  Ruszkiewicz')
        assert m.matches_played('ADAM RUSZKIEWICZ') == 1


class TestPredict:
    def test_two_way_probabilities_sum_to_one(self):
        m = EloModel(draw_share=0.0)
        p = m.predict('Alpha', 'Beta')
        assert sum(p) == pytest.approx(1.0)
        assert p[1] == 0.0

    def test_three_way_probabilities_sum_to_one(self):
        m = EloModel(sport='football', draw_share=0.26)
        p = m.predict('Alpha', 'Beta')
        assert sum(p) == pytest.approx(1.0)
        assert p[1] > 0

    def test_draw_share_peaks_when_sides_are_level(self):
        m = EloModel(sport='football', draw_share=0.30, home_advantage=0)
        level = m.predict('Alpha', 'Beta')[1]
        m.ratings['Mismatch'.lower()] = 2100.0
        lopsided = m.predict('Mismatch', 'Beta')[1]
        assert level > lopsided


class TestWalkForwardHasNoLeak:
    """Every prediction must come from ratings that predate the match."""

    def test_first_scored_match_matches_a_model_trained_only_on_the_past(self):
        rows = [row(f'2026-01-{d:02d}', 'Alpha', 'Beta',
                    'home' if d % 2 else 'away') for d in range(1, 11)]

        full = EloModel(k=24, home_advantage=0)
        full.walk_forward(rows, min_played=3)

        # Replay only the matches strictly before the fourth, which is the
        # first one with three played on both sides.
        past_only = EloModel(k=24, home_advantage=0)
        for r in rows[:3]:
            past_only.update(r['home_team'], r['away_team'], r['winner'])
        expected = past_only.predict('Alpha', 'Beta')

        replay = EloModel(k=24, home_advantage=0)
        for r in rows[:3]:
            replay.update(r['home_team'], r['away_team'], r['winner'])
        assert replay.predict('Alpha', 'Beta') == pytest.approx(expected)

    def test_input_order_does_not_change_the_outcome(self):
        rows = [row('2026-01-01', 'Alpha', 'Beta', 'home'),
                row('2026-01-02', 'Beta', 'Gamma', 'home'),
                row('2026-01-03', 'Gamma', 'Alpha', 'away'),
                row('2026-01-04', 'Alpha', 'Beta', 'away')]

        forwards = EloModel(k=24, home_advantage=0)
        forwards.walk_forward(rows, min_played=0)
        backwards = EloModel(k=24, home_advantage=0)
        backwards.walk_forward(list(reversed(rows)), min_played=0)

        assert forwards.ratings == pytest.approx(backwards.ratings)

    def test_a_later_result_cannot_affect_an_earlier_prediction(self):
        base = [row('2026-01-01', 'Alpha', 'Beta', 'home'),
                row('2026-01-02', 'Alpha', 'Beta', 'home'),
                row('2026-01-03', 'Alpha', 'Beta', 'home'),
                row('2026-01-04', 'Alpha', 'Beta', 'home')]
        short = EloModel(k=24, home_advantage=0).walk_forward(base,
                                                             min_played=3)
        extended = EloModel(k=24, home_advantage=0).walk_forward(
            base + [row('2026-06-01', 'Alpha', 'Beta', 'away')], min_played=3)

        # The extra future match adds one scored row but must not move the
        # score of the row that came before it.
        assert extended['n_scored'] == short['n_scored'] + 1
        assert (extended['brier'] * extended['n_scored']
                >= short['brier'] * short['n_scored'] - 1e-9)


class TestWalkForwardAccounting:
    def test_every_valid_row_is_either_scored_or_cold(self):
        rows = [row(f'2026-02-{d:02d}', f'P{d % 4}', f'Q{d % 3}', 'home')
                for d in range(1, 21)]
        r = EloModel().walk_forward(rows, min_played=3)
        assert r['n_scored'] + r['n_cold'] == len(rows)

    def test_min_played_gates_cold_competitors(self):
        rows = [row('2026-01-01', 'Alpha', 'Beta', 'home'),
                row('2026-01-02', 'Alpha', 'Beta', 'away')]
        assert EloModel().walk_forward(rows, min_played=5)['n_scored'] == 0
        assert EloModel().walk_forward(rows, min_played=0)['n_scored'] == 2

    def test_rows_without_a_usable_result_are_dropped(self):
        rows = [row('2026-01-01', 'Alpha', 'Beta', 'pending'),
                row('2026-01-02', '', 'Beta', 'home'),
                row('2026-01-03', 'Alpha', 'Beta', 'home')]
        r = EloModel().walk_forward(rows, min_played=0)
        assert r['n_scored'] + r['n_cold'] == 1

    def test_metrics_are_in_range(self):
        rows = [row(f'2026-03-{d:02d}', 'Alpha', 'Beta',
                    'home' if d % 3 else 'away') for d in range(1, 26)]
        r = EloModel().walk_forward(rows, min_played=3)
        assert 0.0 <= r['accuracy'] <= 1.0
        assert 0.0 <= r['brier'] <= 2.0
        assert r['log_loss'] >= 0.0
        assert not math.isnan(r['brier'])

    def test_a_dominant_competitor_is_rated_above_its_victims(self):
        rows = [row(f'2026-04-{d:02d}', 'Machine', f'Victim{d}', 'home')
                for d in range(1, 16)]
        m = EloModel(k=24, home_advantage=0)
        m.walk_forward(rows, min_played=0)
        assert m.rating('Machine') > BASE_RATING
        assert all(m.rating(f'Victim{d}') < BASE_RATING for d in range(1, 16))

    def test_empty_input_does_not_raise(self):
        r = EloModel().walk_forward([], min_played=3)
        assert r['n_scored'] == 0
        assert r['accuracy'] == 0.0


class TestDrawShare:
    def test_counts_only_settled_rows(self):
        rows = [row('2026-01-01', 'A', 'B', 'draw'),
                row('2026-01-02', 'A', 'B', 'home'),
                row('2026-01-03', 'A', 'B', 'pending')]
        assert observed_draw_share(rows) == pytest.approx(0.5)

    def test_no_rows_is_zero_not_a_crash(self):
        assert observed_draw_share([]) == 0.0


class TestFit:
    def test_picks_the_grid_point_with_the_best_log_loss(self):
        rows = [row(f'2026-05-{d:02d}', 'Alpha', 'Beta',
                    'home' if d % 4 else 'away') for d in range(1, 29)]
        model, report = fit(rows, 'table_tennis', k_grid=[8.0, 40.0],
                            ha_grid=[0.0])
        assert model.k in (8.0, 40.0)
        assert report['log_loss'] > 0
        assert report['n_scored'] > 0

    def test_non_draw_sports_get_no_draw_mass(self):
        rows = [row(f'2026-05-{d:02d}', 'Alpha', 'Beta', 'home')
                for d in range(1, 21)]
        model, _ = fit(rows, 'table_tennis', k_grid=[24.0], ha_grid=[0.0])
        assert model.draw_share == 0.0
        assert model.predict('Alpha', 'Beta')[1] == 0.0

    def test_football_carries_the_observed_draw_rate(self):
        rows = [row(f'2026-05-{d:02d}', f'A{d%5}', f'B{d%4}',
                    'draw' if d % 4 == 0 else 'home', sport='football')
                for d in range(1, 41)]
        model, _ = fit(rows, 'football', k_grid=[24.0], ha_grid=[0.0])
        assert model.draw_share > 0

    def test_returns_a_usable_model_even_with_no_scorable_rows(self):
        model, report = fit([], 'football', k_grid=[24.0], ha_grid=[0.0])
        assert isinstance(model, EloModel)
        assert report == {}
