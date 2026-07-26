"""Regression tests for the scoring-engine correctness fixes.

Each test pins down a bug found during the scoring audit:
  1. Draw-less sports (tennis, basketball, baseball, e-sports) must never be
     assigned a draw probability.
  2. e-sports must have its own profile instead of inheriting football's.
  3. Dropping Odds must route tennis to the tennis engine.
  4. Dropping Odds must pass the raw h2h_last5 list the engines read.
  5. availability_impact is an unsigned magnitude, not a signed edge.
  6. The H2H consensus vote must follow focus_team.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from football_scoring_engine import (  # noqa: E402
    NO_DRAW_SPORTS,
    SPORT_PROFILES,
    FootballScoringEngine,
    sport_has_draw,
)
from tennis_scoring_engine import TennisScoringEngine  # noqa: E402
import dropping_odds_email as doe  # noqa: E402


def _match(sport, **kw):
    m = {
        'home_team': 'Alpha', 'away_team': 'Beta', 'sport': sport,
        'home_odds': 1.80, 'away_odds': 2.10, 'draw_odds': 3.40,
    }
    m.update(kw)
    return m


class TestNoPhantomDraw:
    @pytest.mark.parametrize('sport', ['tennis', 'basketball', 'baseball', 'esports', 'volleyball'])
    def test_draw_probability_is_zero(self, sport):
        scored = FootballScoringEngine().score_match(_match(sport))
        assert scored.cal_draw == 0.0, f'{sport} got a phantom draw'
        assert scored.to_dict()['prob_X'] == 0.0

    @pytest.mark.parametrize('sport', ['tennis', 'basketball', 'baseball', 'esports'])
    def test_two_outcome_probs_still_sum_to_one(self, sport):
        d = FootballScoringEngine().score_match(_match(sport)).to_dict()
        assert d['prob_1'] + d['prob_2'] == pytest.approx(1.0, abs=1e-3)

    @pytest.mark.parametrize('sport', ['tennis', 'basketball', 'baseball', 'esports'])
    def test_draw_is_never_picked(self, sport):
        scored = FootballScoringEngine().score_match(_match(sport))
        assert scored.best_pick in ('1', '2')

    def test_football_keeps_its_draw(self):
        scored = FootballScoringEngine().score_match(_match('football'))
        assert scored.cal_draw > 0.05
        probs = [scored.cal_home, scored.cal_draw, scored.cal_away]
        assert sum(probs) == pytest.approx(1.0, abs=1e-3)

    @pytest.mark.parametrize('sport', ['handball', 'hockey'])
    def test_low_draw_sports_keep_a_draw(self, sport):
        assert FootballScoringEngine().score_match(_match(sport)).cal_draw > 0


class TestSportProfiles:
    def test_esports_has_its_own_profile(self):
        assert 'esports' in SPORT_PROFILES
        assert SPORT_PROFILES['esports']['min_draw_prob'] == 0.0

    def test_rugby_has_a_profile(self):
        assert 'rugby' in SPORT_PROFILES

    def test_no_draw_sports_set(self):
        assert {'tennis', 'basketball', 'baseball', 'esports'} <= NO_DRAW_SPORTS
        assert 'football' not in NO_DRAW_SPORTS

    def test_sport_has_draw_helper(self):
        assert sport_has_draw('football') is True
        assert sport_has_draw('esports') is False
        assert sport_has_draw(None) is True          # defaults to football
        assert sport_has_draw('UNKNOWN') is True     # unknown -> football


class TestDroppingOddsEngineRouting:
    def _event(self, sport):
        return {
            'home_team': 'Player One', 'away_team': 'Player Two', 'sport': sport,
            'focus_team': 'home',
            'enrichment': {
                'home_odds': 1.7, 'away_odds': 2.2,
                'home_form': ['W', 'W', 'L'], 'away_form': ['L', 'L', 'W'],
                'h2h_last5': [{'home': 'Player One', 'away': 'Player Two',
                               'score': '2:0', 'date': '01.05.26'}],
            },
        }

    def test_tennis_uses_tennis_engine(self):
        out = doe._run_scoring_engine(self._event('tennis'))
        assert out is not None
        assert out['engine'] == 'tennis'
        assert out['prob_X'] == 0.0
        assert out['best_pick'] in ('1', '2')

    def test_football_uses_football_engine(self):
        out = doe._run_scoring_engine(self._event('football'))
        assert out is not None
        assert out['engine'] == 'football'

    def test_esports_gets_no_draw(self):
        out = doe._run_scoring_engine(self._event('esports'))
        assert out is not None
        assert out['prob_X'] == 0.0


class TestH2HIsActuallyPassed:
    def test_h2h_last5_reaches_the_engine(self):
        h2h = [{'home': 'Alpha', 'away': 'Beta', 'score': '3:0'},
               {'home': 'Beta', 'away': 'Alpha', 'score': '0:1'}]
        payload = doe._build_scoring_input({
            'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'football',
            'enrichment': {'h2h_last5': h2h},
        })
        assert payload['h2h_last5'] == h2h

    def test_engine_reads_h2h_from_the_built_payload(self):
        payload = doe._build_scoring_input({
            'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'football',
            'enrichment': {
                'h2h_last5': [
                    {'home': 'Alpha', 'away': 'Beta', 'score': '3:0'},
                    {'home': 'Alpha', 'away': 'Beta', 'score': '2:0'},
                    {'home': 'Beta', 'away': 'Alpha', 'score': '0:1'},
                ],
            },
        })
        feats = FootballScoringEngine().extractor.extract(payload)
        # A dominant Alpha record must move the H2H feature off its 0.5 prior.
        assert feats['h2h_win_rate'] > 0.9
        assert feats['h2h_count'] > 0

    def test_form_and_venue_form_are_passed(self):
        payload = doe._build_scoring_input({
            'home_team': 'A', 'away_team': 'B', 'sport': 'football',
            'enrichment': {
                'home_form': ['W', 'W'], 'away_form': ['L'],
                'home_form_home': ['W'], 'away_form_away': ['L'],
            },
        })
        assert payload['home_form'] == ['W', 'W']
        assert payload['home_form_home'] == ['W']
        assert payload['away_form_away'] == ['L']


class TestAvailabilityImpactIsUnsigned:
    def _tennis_match(self, impact):
        return {
            'home_team': 'One', 'away_team': 'Two', 'sport': 'tennis',
            'home_odds': 1.5, 'away_odds': 2.6,
            'home_form': ['W', 'W', 'W'], 'away_form': ['L', 'L', 'L'],
            'availability': {'availability_impact': impact},
        }

    def test_impact_does_not_favour_player_a(self):
        engine = TennisScoringEngine()
        clean = engine.score_match(self._tennis_match(0.0))
        severe = engine.score_match(self._tennis_match(1.0))
        # More uncertainty must not make the favourite look stronger.
        assert severe.cal_a <= clean.cal_a

    def test_impact_shrinks_toward_even(self):
        engine = TennisScoringEngine()
        clean = engine.score_match(self._tennis_match(0.0))
        severe = engine.score_match(self._tennis_match(1.0))
        assert abs(severe.cal_a - 0.5) < abs(clean.cal_a - 0.5)

    def test_retirement_flag_still_carries_direction(self):
        engine = TennisScoringEngine()
        base = self._tennis_match(0.0)
        a_retired = dict(base, availability={'home_retirement_flag': True})
        b_retired = dict(base, availability={'away_retirement_flag': True})
        assert engine.score_match(a_retired).cal_a < engine.score_match(b_retired).cal_a


class TestTennisEngineSanity:
    def test_weights_normalised_even_if_they_do_not_sum_to_one(self):
        engine = TennisScoringEngine(weights={'h2h': 0.2, 'odds': 0.2})
        scored = engine.score_match({
            'home_team': 'A', 'away_team': 'B', 'sport': 'tennis',
            'home_odds': 2.0, 'away_odds': 2.0,
        })
        # Even odds and no other signal must stay balanced, not collapse to B.
        assert scored.cal_a == pytest.approx(0.5, abs=0.05)

    def test_no_data_is_even(self):
        scored = TennisScoringEngine().score_match(
            {'home_team': 'A', 'away_team': 'B', 'sport': 'tennis'})
        assert scored.cal_a == pytest.approx(0.5, abs=0.01)

    def test_symmetry_under_player_swap(self):
        engine = TennisScoringEngine()
        a = {'home_team': 'One', 'away_team': 'Two', 'sport': 'tennis',
             'home_odds': 1.5, 'away_odds': 2.6, 'ranking_a': 20, 'ranking_b': 80,
             'home_form': ['W', 'W', 'L'], 'away_form': ['L', 'L', 'W']}
        b = {'home_team': 'Two', 'away_team': 'One', 'sport': 'tennis',
             'home_odds': 2.6, 'away_odds': 1.5, 'ranking_a': 80, 'ranking_b': 20,
             'home_form': ['L', 'L', 'W'], 'away_form': ['W', 'W', 'L']}
        assert engine.score_match(a).cal_a == pytest.approx(
            engine.score_match(b).cal_b, abs=1e-6)


class TestConsensusFollowsFocus:
    def test_away_focus_flips_the_h2h_vote(self):
        feats = {'h2h_win_rate': 0.85, 'h2h_count': 1.0,
                 'home_form': 0.5, 'away_form': 0.5,
                 'odds_home': 0.4, 'odds_away': 0.4, 'odds_draw': 0.2}
        engine = FootballScoringEngine()
        home_focus = engine._compute_source_consensus(feats, '1', 'home')
        away_focus = engine._compute_source_consensus(feats, '2', 'away')
        # A strong focus-team H2H record must support that team's own outcome.
        assert home_focus > 0
        assert away_focus > 0


class TestAggregateH2HFallback:
    """Rows enriched via the SofaScore API carry only H2H totals, not a match
    list. The engine must still read them instead of staying neutral."""

    def _feats(self, **kw):
        m = {'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'football'}
        m.update(kw)
        return FootballScoringEngine().extractor.extract(m)

    def test_aggregate_counts_are_used(self):
        f = self._feats(home_wins_in_h2h_last5=8, away_wins_in_h2h_last5=2,
                        h2h_count=10)
        assert f['h2h_win_rate'] == pytest.approx(0.8, abs=1e-6)
        assert f['h2h_count'] > 0

    def test_away_focus_inverts_the_rate(self):
        f = self._feats(home_wins_in_h2h_last5=8, away_wins_in_h2h_last5=2,
                        h2h_count=10, focus_team='away')
        assert f['h2h_win_rate'] == pytest.approx(0.2, abs=1e-6)

    def test_draws_count_as_half(self):
        # 4 wins, 4 losses, 2 draws out of 10 -> (4 + 1) / 10 = 0.5
        f = self._feats(home_wins_in_h2h_last5=4, away_wins_in_h2h_last5=4,
                        h2h_count=10)
        assert f['h2h_win_rate'] == pytest.approx(0.5, abs=1e-6)

    def test_win_rate_fraction_fallback(self):
        f = self._feats(win_rate=0.7, h2h_count=5)
        assert f['h2h_win_rate'] == pytest.approx(0.7, abs=1e-6)

    def test_percentage_win_rate_is_tolerated(self):
        f = self._feats(win_rate=70, h2h_count=5)
        assert f['h2h_win_rate'] == pytest.approx(0.7, abs=1e-6)

    def test_no_h2h_data_stays_neutral(self):
        f = self._feats()
        assert f['h2h_win_rate'] == 0.5
        assert f['h2h_count'] == 0

    def test_match_list_takes_precedence_over_aggregates(self):
        f = self._feats(
            h2h_last5=[{'home': 'Alpha', 'away': 'Beta', 'score': '3:0'}],
            home_wins_in_h2h_last5=0, away_wins_in_h2h_last5=9, h2h_count=9,
        )
        # The explicit match list says Alpha won, so the aggregate is ignored.
        assert f['h2h_win_rate'] > 0.9

    def test_aggregates_change_the_prediction(self):
        engine = FootballScoringEngine()
        base = {'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'esports',
                'home_odds': 2.0, 'away_odds': 2.0}
        home_dominant = engine.score_match(
            dict(base, home_wins_in_h2h_last5=9, away_wins_in_h2h_last5=1, h2h_count=10))
        away_dominant = engine.score_match(
            dict(base, home_wins_in_h2h_last5=1, away_wins_in_h2h_last5=9, h2h_count=10))
        assert home_dominant.cal_home > away_dominant.cal_home
