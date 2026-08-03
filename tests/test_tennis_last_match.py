"""The fatigue signal must survive a renamed date class.

`last_match_a_date` / `last_match_b_date` were empty in every exported tennis
row, so the engine's fatigue factor (weight 0.07) never contributed. Surface form
kept working from the very same H2H rows, which ruled out the page or the row
selectors — the difference is that surface form never reads the date.

The date came from one hardcoded `span.h2h__date`, and the six call sites guarded
on `if d and s`, so a row whose date could not be read discarded the score,
opponent and result it had already parsed.
"""

import pytest
from bs4 import BeautifulSoup

from livesport_h2h_scraper import (_extract_last_matches_for_players,
                                   _extract_row_date, _needs_last_match,
                                   _store_last_match)


def row_html(date_markup, home, away, s1, s2):
    return f"""
    <a class="h2h__row">
      {date_markup}
      <span class="h2h__homeParticipant"><span class="h2h__participantInner">{home}</span></span>
      <span class="h2h__awayParticipant"><span class="h2h__participantInner">{away}</span></span>
      <span class="h2h__result"><span>{s1}</span><span>{s2}</span></span>
    </a>"""


def page(date_markup):
    return BeautifulSoup(f"""
    <div class="h2h__section">
      <div class="h2h__sectionHeader">Ostatnie mecze: Shapovalov D.</div>
      {row_html(date_markup, 'Shapovalov D.', 'Nadal R.', 2, 0)}
    </div>
    <div class="h2h__section">
      <div class="h2h__sectionHeader">Ostatnie mecze: Gea A.</div>
      {row_html(date_markup, 'Djokovic N.', 'Gea A.', 2, 1)}
    </div>
    """, 'html.parser')


class TestRowDate:
    def test_reads_the_classic_class(self):
        row = BeautifulSoup(row_html(
            '<span class="h2h__date">28.07.26</span>', 'A', 'B', 2, 0),
            'html.parser')
        assert _extract_row_date(row) == '28.07.26'

    @pytest.mark.parametrize('markup', [
        '<span class="h2h__date--renamed">28.07.26</span>',
        '<div data-testid="wcl-matchRow-date">28.07.26</div>',
        '<span class="matchRowDate">28.07.26</span>',
        '<span class="whatever">28.07.26</span>',
    ])
    def test_survives_a_renamed_class(self, markup):
        """A class rename must cost the field, not the whole feature."""
        row = BeautifulSoup(row_html(markup, 'A', 'B', 2, 0), 'html.parser')
        assert _extract_row_date(row) == '28.07.26'

    def test_four_digit_year_is_read(self):
        row = BeautifulSoup(row_html(
            '<span class="x">28.07.2026</span>', 'A', 'B', 2, 0), 'html.parser')
        assert _extract_row_date(row) == '28.07.2026'

    def test_no_date_anywhere_returns_none(self):
        row = BeautifulSoup(row_html('', 'A', 'B', 2, 0), 'html.parser')
        assert _extract_row_date(row) is None

    def test_a_score_is_not_mistaken_for_a_date(self):
        row = BeautifulSoup(row_html('', 'A', 'B', 2, 0), 'html.parser')
        assert _extract_row_date(row) is None


class TestStoreLastMatch:
    def test_stores_a_complete_row(self):
        out = {}
        assert _store_last_match(out, 'a', '28.07.26', '2-0', 'Nadal R.', 'W')
        assert out['last_match_a_date'] == '28.07.26'
        assert out['last_match_a_result'] == 'W'

    def test_keeps_the_result_when_the_date_is_missing(self):
        """This is the regression: the result used to be thrown away too."""
        out = {}
        assert _store_last_match(out, 'a', None, '2-0', 'Nadal R.', 'W')
        assert out['last_match_a_score'] == '2-0'
        assert out['last_match_a_result'] == 'W'
        assert 'last_match_a_date' not in out

    def test_refuses_a_row_without_a_score(self):
        out = {}
        assert not _store_last_match(out, 'a', '28.07.26', None, None, None)
        assert out == {}

    def test_does_not_downgrade_a_dated_row(self):
        out = {}
        _store_last_match(out, 'a', '28.07.26', '2-0', 'Nadal R.', 'W')
        _store_last_match(out, 'a', None, '0-2', 'Someone', 'L')
        assert out['last_match_a_score'] == '2-0'

    def test_a_dated_row_completes_an_undated_one(self):
        out = {}
        _store_last_match(out, 'a', None, '0-2', 'Someone', 'L')
        _store_last_match(out, 'a', '28.07.26', '2-0', 'Nadal R.', 'W')
        assert out['last_match_a_date'] == '28.07.26'
        assert out['last_match_a_score'] == '2-0'

    def test_needs_last_match_tracks_the_date(self):
        out = {}
        assert _needs_last_match(out, 'a')
        _store_last_match(out, 'a', None, '2-0', 'X', 'W')
        assert _needs_last_match(out, 'a'), 'bez daty wciąż szukamy'
        _store_last_match(out, 'a', '28.07.26', '2-0', 'X', 'W')
        assert not _needs_last_match(out, 'a')


class TestEndToEndExtraction:
    def test_classic_markup_fills_both_players(self):
        out = {}
        _extract_last_matches_for_players(
            page('<span class="h2h__date">28.07.26</span>'), None, '', out,
            'Shapovalov D.', 'Gea A.')
        assert out['last_match_a_date'] == '28.07.26'
        assert out['last_match_a_result'] == 'W'
        assert out['last_match_b_result'] == 'L'

    def test_renamed_date_class_still_fills_both_players(self):
        out = {}
        _extract_last_matches_for_players(
            page('<span class="matchRow__date">28.07.26</span>'), None, '', out,
            'Shapovalov D.', 'Gea A.')
        assert out['last_match_a_date'] == '28.07.26'
        assert out['last_match_b_date'] == '28.07.26'

    def test_no_date_still_yields_a_usable_result(self):
        out = {}
        _extract_last_matches_for_players(page(''), None, '', out,
                                          'Shapovalov D.', 'Gea A.')
        assert out['last_match_a_result'] == 'W'
        assert out['last_match_b_result'] == 'L'

    def test_the_engine_uses_what_we_extracted(self):
        from tennis_scoring_engine import TennisFeatureExtractor
        out = {'home_team': 'Shapovalov D.', 'away_team': 'Gea A.',
               'sport': 'tennis', 'home_odds': 1.5, 'away_odds': 2.6}
        _extract_last_matches_for_players(
            page('<span class="h2h__date">28.07.26</span>'), None, '', out,
            'Shapovalov D.', 'Gea A.')
        feats = TennisFeatureExtractor().extract(out)
        assert feats['fatigue_advantage'] != 0.0, 'zmęczenie musi wpływać'

    def test_missing_players_are_handled(self):
        out = {}
        _extract_last_matches_for_players(page(''), None, '', out, '', '')
        assert out == {}

    def test_empty_page_is_handled(self):
        out = {}
        _extract_last_matches_for_players(
            BeautifulSoup('<div></div>', 'html.parser'), None, '', out,
            'A', 'B')
        assert out == {}
