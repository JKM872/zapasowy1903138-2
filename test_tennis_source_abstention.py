"""Tests for per-source abstention in the tennis engine.

Two defects are pinned down here:

1. A source with no data used to contribute 0.5 at FULL weight instead of
   abstaining. Because the weighted average divided by the total of all
   weights, every missing source acted as a vote for an even split. Tennis has
   the thinnest coverage of all sports (H2H 33%, form 28%, Forebet/SofaScore
   4%), so most matches were being dragged toward 50/50 by absent data.

2. `surface_form` duplicated the overall form in 80% of real rows (Livesport
   exposes no per-match tournament info, so the scraper uses recent form as a
   proxy). Counting it as an independent source gave one signal 0.16 + 0.12 of
   the model.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tennis_scoring_engine import TennisScoringEngine  # noqa: E402


@pytest.fixture
def engine():
    return TennisScoringEngine()


def _match(**kw):
    m = {'home_team': 'Player A', 'away_team': 'Player B', 'sport': 'tennis'}
    m.update(kw)
    return m


class TestAbstention:
    def test_no_data_is_a_coin_flip(self, engine):
        s = engine.score_match(_match())
        assert s.cal_a == pytest.approx(0.5, abs=1e-6)
        assert s.breakdown['active_sources'] == []

    def test_only_odds_present_follows_the_market(self, engine):
        s = engine.score_match(_match(home_odds=1.25, away_odds=4.0))
        assert 'odds' in s.breakdown['active_sources']
        # With the market as the only evidence, the favourite must dominate;
        # previously six abstaining sources pulled this back toward 0.5.
        assert s.cal_a > 0.70

    def test_absent_sources_do_not_dilute(self, engine):
        # Same market, but now form agrees with it. The probability must not
        # drop below the odds-only case just because other sources are missing.
        odds_only = engine.score_match(_match(home_odds=1.25, away_odds=4.0))
        with_form = engine.score_match(_match(
            home_odds=1.25, away_odds=4.0,
            home_form=['W', 'W', 'W', 'W', 'W'], away_form=['L', 'L', 'L', 'L', 'L'],
        ))
        assert with_form.cal_a >= odds_only.cal_a

    def test_active_sources_are_reported(self, engine):
        s = engine.score_match(_match(
            home_odds=1.8, away_odds=2.1,
            home_form=['W', 'L'], away_form=['L', 'W'],
            ranking_a=10, ranking_b=50,
        ))
        active = set(s.breakdown['active_sources'])
        assert {'odds', 'form', 'ranking'} <= active
        assert 'fatigue' not in active
        assert 'sofascore' not in active

    def test_effective_weights_sum_to_one_over_active(self, engine):
        s = engine.score_match(_match(
            home_odds=1.8, away_odds=2.1, ranking_a=10, ranking_b=50))
        total = sum(v for k, v in s.breakdown.items()
                    if k.endswith('_effective_weight'))
        assert total == pytest.approx(1.0, abs=1e-3)

    def test_inactive_source_has_zero_effective_weight(self, engine):
        s = engine.score_match(_match(home_odds=1.8, away_odds=2.1))
        assert s.breakdown['fatigue_effective_weight'] == 0.0
        assert s.breakdown['odds_effective_weight'] > 0.0

    def test_h2h_abstains_without_meetings(self, engine):
        s = engine.score_match(_match(home_odds=1.8, away_odds=2.1))
        assert 'h2h' not in s.breakdown['active_sources']

    def test_h2h_counts_when_present(self, engine):
        s = engine.score_match(_match(
            home_odds=1.8, away_odds=2.1,
            home_wins_in_h2h_last5=3, away_wins_in_h2h_last5=1))
        assert 'h2h' in s.breakdown['active_sources']

    def test_probabilities_always_sum_to_one(self, engine):
        for kw in ({}, {'home_odds': 1.5, 'away_odds': 2.5},
                   {'ranking_a': 1, 'ranking_b': 200},
                   {'home_form': ['W'], 'away_form': ['L']}):
            s = engine.score_match(_match(**kw))
            assert s.cal_a + s.cal_b == pytest.approx(1.0, abs=1e-6)


class TestSurfaceFormDeduplication:
    def test_duplicate_surface_form_abstains(self, engine):
        form_a = ['W', 'W', 'L', 'W', 'L']
        form_b = ['L', 'L', 'W', 'L', 'W']
        s = engine.score_match(_match(
            home_form=form_a, away_form=form_b,
            surface_form_a=form_a, surface_form_b=form_b,   # identical copies
        ))
        active = s.breakdown['active_sources']
        assert 'form' in active
        assert 'surface_form' not in active, 'duplicated evidence counted twice'

    def test_genuine_surface_form_counts(self, engine):
        s = engine.score_match(_match(
            home_form=['W', 'W', 'L'], away_form=['L', 'L', 'W'],
            surface_form_a=['L', 'L', 'L'], surface_form_b=['W', 'W', 'W'],
        ))
        assert 'surface_form' in s.breakdown['active_sources']

    def test_absent_surface_form_abstains(self, engine):
        s = engine.score_match(_match(
            home_form=['W', 'W'], away_form=['L', 'L']))
        assert 'surface_form' not in s.breakdown['active_sources']

    def test_duplication_does_not_change_the_probability(self, engine):
        form_a, form_b = ['W', 'W', 'W'], ['L', 'L', 'L']
        plain = engine.score_match(_match(home_form=form_a, away_form=form_b))
        duped = engine.score_match(_match(
            home_form=form_a, away_form=form_b,
            surface_form_a=form_a, surface_form_b=form_b))
        assert plain.cal_a == pytest.approx(duped.cal_a, abs=1e-9)


class TestScraperProxyFlag:
    def test_surface_form_is_flagged_as_proxy(self):
        import inspect

        from livesport_h2h_scraper import _compute_surface_form
        src = inspect.getsource(_compute_surface_form)
        # The output must state that this is a proxy, so no downstream consumer
        # mistakes it for court-filtered form.
        assert "surface_form_is_proxy" in src
