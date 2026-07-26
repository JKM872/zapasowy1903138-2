"""Tests for tennis form-badge extraction.

Pins down the bug where both players received an identical form list: when a
player's "Ostatnie mecze" section could not be identified, the extractor fell
back to scanning the whole page and returned the first five badges to whoever
asked. Measured on real data: 14.5% of tennis rows carrying form had both
lists identical, against 0.8% in football.

An identical pair is worse than no data at all — the engine computes
form_p = form_a / (form_a + form_b), so equal forms always yield exactly 0.5
and the form weight silently disappears while looking populated.
"""

import os
import sys

import pytest
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from livesport_h2h_scraper import (  # noqa: E402
    _badges_from_section,
    _extract_form_badges_for_both,
    _find_player_form_section,
)


def _badge(kind: str) -> str:
    cls = 'wcl-badgeform_xyz wcl-win_abc' if kind == 'W' else 'wcl-badgeform_xyz wcl-lose_abc'
    txt = 'Z' if kind == 'W' else 'P'
    return f'<div class="{cls}">{txt}</div>'


def _section(header: str, badges: str) -> str:
    return (
        '<div class="h2h__section">'
        f'<div data-testid="wcl-headerSection-text">{header}</div>'
        f'{"".join(_badge(b) for b in badges)}'
        '</div>'
    )


def _page(*sections: str) -> BeautifulSoup:
    return BeautifulSoup(f'<div>{"".join(sections)}</div>', 'html.parser')


class TestSectionResolution:
    def test_exact_name_match(self):
        soup = _page(
            _section('Ostatnie mecze: De Jong J.', 'WLW'),
            _section('Ostatnie mecze: Gaubas V.', 'LLL'),
        )
        sec = _find_player_form_section(soup, 'De Jong J.')
        assert sec is not None
        assert _badges_from_section(sec) == ['W', 'L', 'W']

    def test_h2h_section_is_never_used_as_form(self):
        soup = _page(
            _section('Pojedynki bezpośrednie', 'WWWWW'),
            _section('Ostatnie mecze: Gaubas V.', 'LL'),
        )
        assert _find_player_form_section(soup, 'Gaubas V.') is not None
        # The H2H block must not be picked for an unrelated player.
        assert _find_player_form_section(soup, 'Nieznany Zawodnik X') is None

    def test_exclude_prevents_reusing_a_section(self):
        soup = _page(_section('Ostatnie mecze: Kowalski A.', 'WL'))
        first = _find_player_form_section(soup, 'Kowalski A.')
        assert first is not None
        assert _find_player_form_section(soup, 'Kowalski A.', exclude=first) is None

    def test_unknown_player_returns_none(self):
        soup = _page(_section('Ostatnie mecze: Someone Else', 'WWW'))
        assert _find_player_form_section(soup, 'Zupelnie Inny') is None


class TestBadgeParsing:
    def test_win_and_loss_badges(self):
        soup = _page(_section('Ostatnie mecze: A Player', 'WLWLL'))
        sec = _find_player_form_section(soup, 'A Player')
        assert _badges_from_section(sec) == ['W', 'L', 'W', 'L', 'L']

    def test_capped_at_five(self):
        soup = _page(_section('Ostatnie mecze: A Player', 'WWWWWWWW'))
        sec = _find_player_form_section(soup, 'A Player')
        assert len(_badges_from_section(sec)) == 5

    def test_section_without_badges_is_empty(self):
        soup = _page(_section('Ostatnie mecze: A Player', ''))
        sec = _find_player_form_section(soup, 'A Player')
        assert _badges_from_section(sec) == []


class TestBothPlayersAreDisjoint:
    def test_normal_page_gives_each_player_their_own_form(self):
        soup = _page(
            _section('Ostatnie mecze: De Jong J.', 'WLW'),
            _section('Ostatnie mecze: Gaubas V.', 'LLL'),
        )
        a, b = _extract_form_badges_for_both(soup, 'De Jong J.', 'Gaubas V.')
        assert a == ['W', 'L', 'W']
        assert b == ['L', 'L', 'L']
        assert a != b

    def test_no_fallback_to_whole_page(self):
        # Neither player has a section: the old code returned the page's first
        # five badges to both. Now both must come back empty.
        soup = _page(_section('Ostatnie mecze: Ktos Inny', 'WWWWW'))
        a, b = _extract_form_badges_for_both(soup, 'Player One', 'Player Two')
        assert a == []
        assert b == []

    def test_single_section_is_not_shared(self):
        # Only player A has a section; B must not inherit it.
        soup = _page(_section('Ostatnie mecze: Player One', 'WWL'))
        a, b = _extract_form_badges_for_both(soup, 'Player One', 'Player Two')
        assert a == ['W', 'W', 'L']
        assert b == []

    def test_identical_forms_are_rejected(self):
        # Two sections that both resolve to the same badge pattern for the same
        # ambiguous surname — treat as unresolved rather than a fake tie.
        soup = _page(
            _section('Ostatnie mecze: Nadal R.', 'WLW'),
            _section('Ostatnie mecze: Nadal R.', 'WLW'),
        )
        a, b = _extract_form_badges_for_both(soup, 'Nadal R.', 'Nadal R.')
        assert a == [] and b == []

    def test_empty_page_is_safe(self):
        a, b = _extract_form_badges_for_both(BeautifulSoup('<div></div>', 'html.parser'),
                                             'A', 'B')
        assert a == [] and b == []

    def test_missing_player_names_are_safe(self):
        soup = _page(_section('Ostatnie mecze: X', 'WW'))
        a, b = _extract_form_badges_for_both(soup, '', '')
        assert a == [] and b == []


class TestEngineConsequence:
    """Show why an identical pair had to be eliminated."""

    def test_identical_forms_neutralise_the_form_factor(self):
        from tennis_scoring_engine import TennisScoringEngine
        engine = TennisScoringEngine()
        same = engine.score_match({
            'home_team': 'A', 'away_team': 'B', 'sport': 'tennis',
            'home_form': ['L', 'W', 'L', 'W', 'W'],
            'away_form': ['L', 'W', 'L', 'W', 'W'],
        })
        assert same.breakdown['form_estimate'] == pytest.approx(0.5, abs=1e-6)

    def test_real_difference_moves_the_form_factor(self):
        from tennis_scoring_engine import TennisScoringEngine
        engine = TennisScoringEngine()
        differing = engine.score_match({
            'home_team': 'A', 'away_team': 'B', 'sport': 'tennis',
            'home_form': ['W', 'W', 'W', 'W', 'W'],
            'away_form': ['L', 'L', 'L', 'L', 'L'],
        })
        assert differing.breakdown['form_estimate'] > 0.8
