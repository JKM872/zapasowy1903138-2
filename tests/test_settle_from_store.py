"""Settling results that came back from ``outputs/result_store.json``.

The store keeps ``winner`` as ``'home'``/``'away'`` next to our own team names and
never held a ``winner_name``. Settling compared the pick against that missing
name, so every stored result was recorded as a loss: Jirasek Martin won 3-1, we
had backed Jirasek, and the report still printed LOST. These tests pin the
store's exact shape, because it is the shape that broke.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from result_resolver import settle_from_result, winning_competitor_name


def stored_result(winner='home', score_home=3, score_away=1,
                  home='Jirasek Martin', away='Flesar Milan'):
    """A record exactly as ``ResultStore.add_result`` writes it."""
    return {
        'status': 'finished',
        'score_home': score_home,
        'score_away': score_away,
        'winner': winner,
        'checked_at': '2026-08-03T21:48:15.707586',
        'sport': 'table_tennis',
        'home_team': home,
        'away_team': away,
        'date': '2026-08-03',
        'source': 'sofascore',
        'orientation_flipped': None,
    }


def pick(side='home', home='Jirasek Martin', away='Flesar Milan'):
    return {
        'home_team': home,
        'away_team': away,
        'predicted': side,
        'scoring_pick': side,
        'match_url': 'https://example.test/m/1',
    }


class TestStoredResultsSettle:
    def test_backing_the_winner_is_a_win(self):
        settled = settle_from_result(pick('home'), stored_result(winner='home'))
        assert settled['outcome'] == 'won'

    def test_backing_the_loser_is_a_loss(self):
        settled = settle_from_result(pick('away'), stored_result(winner='home'))
        assert settled['outcome'] == 'lost'

    def test_the_away_winner_is_credited(self):
        settled = settle_from_result(
            pick('away'), stored_result(winner='away', score_home=1, score_away=3))
        assert settled['outcome'] == 'won'

    def test_the_winner_name_is_reported(self):
        settled = settle_from_result(pick('home'), stored_result(winner='home'))
        assert settled['winner_name'] == 'Jirasek Martin'
        assert settled['actual'] == 'Jirasek Martin'

    def test_the_score_is_kept_in_our_orientation(self):
        settled = settle_from_result(pick('home'), stored_result())
        assert settled['score'] == '3-1'

    def test_a_missing_winner_name_no_longer_raises(self):
        """It used to reach for result['winner_name'] and raise KeyError."""
        settle_from_result(pick('home'), stored_result())


class TestUnjudgeableResults:
    def test_no_winner_information_stays_unsettled(self):
        result = stored_result()
        result['winner'] = None
        settled = settle_from_result(pick('home'), result)
        assert settled['outcome'] == 'pending', \
            'a loss we cannot justify is worse than an unsettled row'

    def test_the_reason_is_recorded(self):
        result = stored_result()
        result['winner'] = None
        assert 'winner name' in settle_from_result(pick('home'), result)['unsettled_reason']


class TestStoredDraws:
    def test_a_stored_draw_is_a_draw(self):
        """The store writes winner='draw' and carries no is_draw flag."""
        result = stored_result(winner='draw', score_home=2, score_away=2)
        settled = settle_from_result(pick('home'), result)
        assert settled['outcome'] == 'draw'


class TestWinningCompetitorName:
    @pytest.mark.parametrize('winner,expected', [
        ('home', 'Jirasek Martin'),
        ('away', 'Flesar Milan'),
        ('draw', None),
        (None, None),
    ])
    def test_it_reads_the_side_from_the_store(self, winner, expected):
        assert winning_competitor_name(stored_result(winner=winner)) == expected

    def test_an_explicit_name_wins_over_the_side(self):
        result = stored_result(winner='home')
        result['winner_name'] = 'Someone Else'
        assert winning_competitor_name(result) == 'Someone Else'

    def test_the_resolver_shape_is_still_understood(self):
        """Fresh resolver output names the sides home_name/away_name."""
        assert winning_competitor_name(
            {'winner': 'away', 'home_name': 'A', 'away_name': 'B'}) == 'B'
