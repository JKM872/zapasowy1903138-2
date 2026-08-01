"""The form the engine used has to be the form the reader sees.

Previously the card showed five circles out of a longer run while the engine
scored six, so the mail and the prediction disagreed about which matches
mattered. Both now use a window of ten, and these tests pin that together —
plus the scorelines, which is what makes a winning run readable as "beat
somebody" rather than just green.
"""

import football_scoring_engine as fse
import pytest

from email_notifier import (FORM_ICONS_SHOWN, RECENT_MATCHES_SHOWN,
                            _render_recent_matches, create_html_email)


def recent(n, outcome='W', at_home=True):
    return [{'date': f'2026-07-{d:02d}', 'outcome': outcome, 'at_home': at_home,
             'score': '3-1', 'opponent': f'Rywal {d}'} for d in range(1, n + 1)]


class TestWindowsAgree:
    def test_email_shows_as_many_as_the_engine_scores(self):
        assert FORM_ICONS_SHOWN == fse.FORM_DECAY_WINDOW

    def test_engine_window_is_ten(self):
        assert fse.FORM_DECAY_WINDOW == 10

    def test_detail_list_matches_the_icon_row(self):
        assert RECENT_MATCHES_SHOWN == FORM_ICONS_SHOWN


class TestRenderRecentMatches:
    def test_empty_input_renders_nothing(self):
        assert _render_recent_matches([], 'Ostatnie') == ''
        assert _render_recent_matches(None, 'Ostatnie') == ''
        assert _render_recent_matches('WWL', 'Ostatnie') == ''

    def test_shows_date_opponent_and_score(self):
        html = _render_recent_matches(recent(1), 'Ostatnie mecze')
        assert '2026-07-01' in html
        assert 'Rywal 1' in html
        assert '3-1' in html

    def test_title_is_included(self):
        assert 'Ostatnie mecze Alpha' in _render_recent_matches(
            recent(2), 'Ostatnie mecze Alpha')

    def test_caps_at_the_limit(self):
        html = _render_recent_matches(recent(25), 'x')
        assert html.count('Rywal') == RECENT_MATCHES_SHOWN

    def test_respects_an_explicit_limit(self):
        html = _render_recent_matches(recent(10), 'x', limit=3)
        assert html.count('Rywal') == 3

    def test_venue_icon_differs_by_side(self):
        assert '🏠' in _render_recent_matches(recent(1, at_home=True), 'x')
        assert '✈️' in _render_recent_matches(recent(1, at_home=False), 'x')

    def test_loss_and_win_get_different_colours(self):
        win = _render_recent_matches(recent(1, 'W'), 'x')
        loss = _render_recent_matches(recent(1, 'L'), 'x')
        assert '#4CAF50' in win
        assert '#F44336' in loss

    def test_missing_score_falls_back_to_a_dash(self):
        html = _render_recent_matches(
            [{'date': '2026-07-01', 'outcome': 'W', 'at_home': True,
              'score': '', 'opponent': 'X'}], 'x')
        assert '—' in html

    def test_non_dict_entries_are_skipped(self):
        html = _render_recent_matches(['nonsense', recent(1)[0]], 'x')
        assert html.count('Rywal') == 1

    def test_all_junk_renders_nothing(self):
        assert _render_recent_matches(['a', 'b'], 'x') == ''


class TestCardShowsTenAndTheDetails:
    @pytest.fixture
    def match(self):
        return {
            'home_team': 'Alpha', 'away_team': 'Beta', 'sport': 'football',
            'match_url': 'https://example.test/match/1',
            'match_date': '2026-08-01', 'match_time': '18:00',
            'home_odds': 2.10, 'draw_odds': 3.40, 'away_odds': 3.20,
            'home_form_overall': list('WWLDWWLWDW'),
            'home_form_home': list('WWWLW'),
            'away_form_overall': list('LLDWLLDWLL'),
            'away_form_away': list('LLDWL'),
            'home_recent_matches': recent(10),
            'away_recent_matches': recent(10, 'L', at_home=False),
            'qualifies': True, 'focus_team': 'home',
            'scoring_pick': '1', 'scoring_prob': 58.0,
        }

    def test_renders_all_ten_icons_not_five(self, match):
        html = create_html_email([match], '2026-08-01', cards_only=True)
        # Ten results, all green/red/yellow circles, appear for the home side.
        assert html.count('🟢') + html.count('🔴') + html.count('🟡') >= 20

    def test_recent_match_details_reach_the_card(self, match):
        html = create_html_email([match], '2026-08-01', cards_only=True)
        assert 'Ostatnie mecze Alpha' in html
        assert 'Ostatnie mecze Beta' in html
        assert 'Rywal 7' in html

    def test_venue_form_still_labelled(self, match):
        html = create_html_email([match], '2026-08-01', cards_only=True)
        assert 'U siebie' in html
        assert 'Na wyjeździe' in html

    def test_card_survives_without_recent_matches(self, match):
        match.pop('home_recent_matches')
        match.pop('away_recent_matches')
        html = create_html_email([match], '2026-08-01', cards_only=True)
        assert 'Alpha' in html
        assert 'Ostatnie mecze Alpha' not in html

    def test_card_survives_without_any_form(self, match):
        for key in ('home_form_overall', 'home_form_home',
                    'away_form_overall', 'away_form_away',
                    'home_recent_matches', 'away_recent_matches'):
            match.pop(key, None)
        html = create_html_email([match], '2026-08-01', cards_only=True)
        assert 'Alpha' in html
        assert '—' in html
