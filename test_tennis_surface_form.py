"""Tests for real (court-filtered) tennis surface form.

Livesport's H2H rows carry no tournament info, so the scraper could only reuse
a player's recent matches as a "surface form" proxy — identical to the overall
form in 80% of real rows. SofaScore reports a ``groundType`` per event, so
genuine per-surface records are obtainable.

Verified live on 2026-07-27: Alcaraz clay ['W','L','W','W','W'] vs hard
['L','W','L','W','W'] — the surfaces really do differ, so this is a signal and
not a duplicate of the overall form.
"""

import os
import sys
from unittest.mock import patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sofascore_scraper as ss  # noqa: E402
from tennis_scoring_engine import TennisScoringEngine  # noqa: E402


class TestSurfaceNormalisation:
    @pytest.mark.parametrize('raw,expected', [
        ('Red clay', 'clay'),
        ('Clay', 'clay'),
        ('Grass', 'grass'),
        ('Hardcourt outdoor', 'hard'),
        ('Hardcourt indoor', 'hard'),
        ('Hard', 'hard'),
        ('Carpet indoor', 'carpet'),
    ])
    def test_known_ground_types(self, raw, expected):
        assert ss.normalize_surface(raw) == expected

    @pytest.mark.parametrize('raw', [None, '', 'Something else', 'unknown'])
    def test_unknown_returns_none(self, raw):
        assert ss.normalize_surface(raw) is None


def _event(team_id, surface, home_score, away_score, as_home=True, other=999):
    home = {'id': team_id if as_home else other}
    away = {'id': other if as_home else team_id}
    return {
        'homeTeam': home, 'awayTeam': away,
        'homeScore': {'current': home_score},
        'awayScore': {'current': away_score},
        'tournament': {'groundType': surface, 'name': 'Test'},
    }


def _events_payload(events):
    # API returns oldest-first; the helper reverses it.
    return {'events': events}


class TestSurfaceForm:
    def test_filters_by_surface(self):
        payload = _events_payload([
            _event(1, 'Red clay', 2, 0),          # clay win
            _event(1, 'Hardcourt outdoor', 0, 2),  # hard loss (ignored)
            _event(1, 'Red clay', 0, 2),           # clay loss
        ])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'clay') == ['L', 'W']

    def test_newest_first(self):
        payload = _events_payload([
            _event(1, 'Grass', 0, 2),   # older: loss
            _event(1, 'Grass', 2, 1),   # newer: win
        ])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'grass') == ['W', 'L']

    def test_away_side_result_is_read_correctly(self):
        payload = _events_payload([_event(1, 'Red clay', 0, 2, as_home=False)])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'clay') == ['W']

    def test_respects_limit(self):
        payload = _events_payload([_event(1, 'Red clay', 2, 0) for _ in range(9)])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert len(ss.get_team_surface_form(1, 'clay', limit=5)) == 5

    def test_accepts_raw_sofascore_label(self):
        payload = _events_payload([_event(1, 'Red clay', 2, 0)])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'Red clay') == ['W']

    def test_unknown_surface_returns_empty(self):
        with patch.object(ss, '_api_get_json', return_value=_events_payload([])):
            assert ss.get_team_surface_form(1, 'moon dust') == []

    def test_no_team_id_returns_empty(self):
        assert ss.get_team_surface_form(0, 'clay') == []

    def test_unplayed_events_are_skipped(self):
        payload = _events_payload([_event(1, 'Red clay', None, None)])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'clay') == []

    def test_draw_skipped_by_default(self):
        payload = _events_payload([_event(1, 'Red clay', 1, 1)])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'clay') == []

    def test_api_failure_is_safe(self):
        with patch.object(ss, '_api_get_json', return_value=None):
            assert ss.get_team_surface_form(1, 'clay') == []

    def test_events_of_other_players_ignored(self):
        payload = _events_payload([
            {'homeTeam': {'id': 7}, 'awayTeam': {'id': 8},
             'homeScore': {'current': 2}, 'awayScore': {'current': 0},
             'tournament': {'groundType': 'Red clay'}},
        ])
        with patch.object(ss, '_api_get_json', return_value=payload):
            assert ss.get_team_surface_form(1, 'clay') == []


class TestScraperIntegration:
    def test_real_form_replaces_the_proxy(self):
        import livesport_h2h_scraper as ls

        out = {'surface': 'clay', 'surface_form_a': ['W', 'W'],
               'surface_form_b': ['W', 'W'], 'surface_form_is_proxy': True}
        with patch.object(ls, 'logger'), \
             patch('sofascore_scraper.find_team_by_name',
                   side_effect=[{'id': 1}, {'id': 2}]), \
             patch('sofascore_scraper.get_team_surface_form',
                   side_effect=[['W', 'L', 'W'], ['L', 'L']]):
            ls._apply_real_surface_form(out, 'Player A', 'Player B')

        assert out['surface_form_a'] == ['W', 'L', 'W']
        assert out['surface_form_b'] == ['L', 'L']
        assert out['surface_form_is_proxy'] is False
        assert out['surface_form_source'] == 'sofascore'
        assert out['surface_stats_a'] == {'clay': pytest.approx(2 / 3)}

    def test_proxy_kept_when_only_one_side_resolves(self):
        import livesport_h2h_scraper as ls

        out = {'surface': 'clay', 'surface_form_a': ['W'],
               'surface_form_b': ['W'], 'surface_form_is_proxy': True}
        with patch('sofascore_scraper.find_team_by_name',
                   side_effect=[{'id': 1}, None]), \
             patch('sofascore_scraper.get_team_surface_form',
                   return_value=['L', 'L']):
            ls._apply_real_surface_form(out, 'Player A', 'Player B')

        # Comparing a real record against a proxy one would be misleading.
        assert out['surface_form_is_proxy'] is True

    def test_no_surface_means_no_lookup(self):
        import livesport_h2h_scraper as ls

        out = {'surface': None}
        with patch('sofascore_scraper.find_team_by_name') as mock_find:
            ls._apply_real_surface_form(out, 'A', 'B')
        mock_find.assert_not_called()


class TestEngineTreatsRealSurfaceAsASource:
    def _match(self, **kw):
        m = {'home_team': 'A', 'away_team': 'B', 'sport': 'tennis',
             'home_form': ['W', 'W', 'L'], 'away_form': ['L', 'L', 'W']}
        m.update(kw)
        return m

    def test_real_surface_form_counts_even_when_equal_to_overall(self):
        engine = TennisScoringEngine()
        scored = engine.score_match(self._match(
            surface_form_a=['W', 'W', 'L'], surface_form_b=['L', 'L', 'W'],
            surface_form_is_proxy=False))
        assert 'surface_form' in scored.breakdown['active_sources']

    def test_proxy_duplicate_still_abstains(self):
        engine = TennisScoringEngine()
        scored = engine.score_match(self._match(
            surface_form_a=['W', 'W', 'L'], surface_form_b=['L', 'L', 'W'],
            surface_form_is_proxy=True))
        assert 'surface_form' not in scored.breakdown['active_sources']

    def test_real_differing_surface_form_moves_the_probability(self):
        engine = TennisScoringEngine()
        neutral = engine.score_match(self._match())
        clay_bad = engine.score_match(self._match(
            surface_form_a=['L', 'L', 'L'], surface_form_b=['W', 'W', 'W'],
            surface_form_is_proxy=False))
        assert clay_bad.cal_a < neutral.cal_a
