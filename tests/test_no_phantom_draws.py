"""No sport may be handed a draw it cannot produce.

Found by recomputing the engines' output from first principles: table tennis had
no entry in SPORT_PROFILES, so it fell through to the football default and was
given a 19-24% draw probability. Two live paths fed it there — the settled-data
scorer used by the calibrator, and the dropping-odds mail — so the phantom draw
reached both the numbers the model is tuned on and the mail a reader sees.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calibrate_weights as cw  # noqa: E402
import dropping_odds_email as doe  # noqa: E402
from football_scoring_engine import (NO_DRAW_SPORTS,  # noqa: E402
                                     SPORT_PROFILES, FootballScoringEngine,
                                     sport_has_draw)

TWO_OUTCOME = ('tennis', 'table_tennis', 'basketball', 'baseball',
               'volleyball', 'esports')
DRAW_CAPABLE = ('football', 'hockey', 'handball', 'rugby')


def _row(sport):
    return {
        'home_team': 'A', 'away_team': 'B', 'sport': sport,
        'home_odds': 1.80, 'away_odds': 2.00, 'draw_odds': 3.40,
        'home_wins_in_h2h_last5': 4, 'away_wins_in_h2h_last5': 1,
        'h2h_count': 5,
        'home_form': ['W', 'W', 'W', 'L', 'W'],
        'away_form': ['L', 'L', 'W', 'L', 'D'],
    }


class TestProfiles:
    @pytest.mark.parametrize('sport', TWO_OUTCOME)
    def test_two_outcome_sports_have_a_profile(self, sport):
        """A missing profile silently means "football", draws included."""
        assert sport in SPORT_PROFILES
        assert sport in NO_DRAW_SPORTS
        assert sport_has_draw(sport) is False

    @pytest.mark.parametrize('sport', DRAW_CAPABLE)
    def test_draw_capable_sports_keep_their_draw(self, sport):
        assert sport_has_draw(sport) is True

    def test_table_tennis_mirrors_tennis(self):
        assert (SPORT_PROFILES['table_tennis']['min_draw_prob']
                == SPORT_PROFILES['tennis']['min_draw_prob'] == 0.0)


class TestEngineOutput:
    @pytest.mark.parametrize('sport', TWO_OUTCOME)
    def test_no_draw_mass_and_probabilities_sum_to_one(self, sport):
        scored = FootballScoringEngine().score_match(_row(sport))

        assert scored.cal_draw == pytest.approx(0.0, abs=1e-9), sport
        assert (scored.cal_home + scored.cal_draw + scored.cal_away
                == pytest.approx(1.0, abs=1e-6))

    @pytest.mark.parametrize('sport', DRAW_CAPABLE)
    def test_draw_sports_still_price_the_draw(self, sport):
        scored = FootballScoringEngine().score_match(_row(sport))
        assert scored.cal_draw > 0.0


class TestRouting:
    @pytest.mark.parametrize('sport', ('tennis', 'table_tennis'))
    def test_settled_scorer_uses_the_two_outcome_engine(self, sport):
        row = dict(_row(sport), actual_result='1')
        probs, _ev, _odds = cw._score_row(row, FootballScoringEngine())

        assert probs[1] == 0.0, 'no draw mass may reach the calibrator'
        assert sum(probs) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize('sport', ('tennis', 'table_tennis'))
    def test_dropping_odds_uses_the_two_outcome_engine(self, sport):
        out = doe._run_scoring_engine({
            'sport': sport, 'home_team': 'A', 'away_team': 'B',
            'enrichment': {'home_odds': 1.8, 'away_odds': 2.0,
                           'home_wins_in_h2h_last5': 4,
                           'away_wins_in_h2h_last5': 1, 'h2h_count': 5},
        })

        assert out['engine'] == 'tennis'
        assert out['prob_X'] == 0.0
        assert out['best_pick'] in ('1', '2')

    def test_football_dropping_odds_still_uses_the_football_engine(self):
        out = doe._run_scoring_engine({
            'sport': 'football', 'home_team': 'A', 'away_team': 'B',
            'enrichment': {'home_odds': 2.5, 'draw_odds': 3.3,
                           'away_odds': 3.0, 'h2h_count': 5,
                           'home_wins_in_h2h_last5': 3,
                           'away_wins_in_h2h_last5': 1},
        })

        assert out['engine'] == 'football'
        assert out['prob_X'] > 0.0
