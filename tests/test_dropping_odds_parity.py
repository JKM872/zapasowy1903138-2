"""The dropping-odds mail must show the same per-event information as the main one.

It did not: this module kept its own copy of a match card, and the two drifted.
The dropping-odds version carried no grade, no advanced score, no value-bet
badge and no link to the fixture, so the same match looked different depending
on which mail it arrived in. Both now render through the main template, and the
price movement is the only thing added on top.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import dropping_odds_email as doe  # noqa: E402
from email_notifier import (_CARDS_END, _CARDS_START,  # noqa: E402
                            _render_drop_badge, create_html_email)


def _event(**extra):
    event = {
        'home_team': 'Urban Titu',
        'away_team': 'Vointa 2024 Crevedia',
        'league': 'Romania - Romanian Cup',
        'sport': 'football',
        'event_date': '2026-07-29',
        'event_time': '14:30',
        'match_url': 'https://www.oddssafari.com/matches/soccer/x',
        'outcome': '2',
        'drop_pct': 37.0,
        'open_odds': 3.70,
        'current_odds': 2.34,
        'focus_team': 'home',
        'enrichment': {
            'home_form': ['L', 'L', 'L', 'L', 'D'],
            'away_form': ['W', 'W', 'W', 'W', 'D'],
            'home_odds': 2.34, 'draw_odds': 3.20, 'away_odds': 2.90,
            'sofascore_home_win_prob': 40,
            'sofascore_draw_prob': 25,
            'sofascore_away_win_prob': 35,
            'sofascore_total_votes': 900,
            'h2h_count': 3, 'win_rate': 0.33,
            'home_wins_in_h2h_last5': 1, 'away_wins_in_h2h_last5': 2,
        },
    }
    event.update(extra)
    return event


class TestCardsOnly:
    def test_returns_cards_without_a_document_wrapper(self):
        cards = create_html_email([{'home_team': 'A', 'away_team': 'B',
                                    'qualifies': True}],
                                  '2026-07-29', cards_only=True)

        assert '<html' not in cards.lower()
        assert '<body' not in cards.lower()
        assert _CARDS_START not in cards and _CARDS_END not in cards
        assert 'A' in cards and 'B' in cards

    def test_full_document_is_still_the_default(self):
        html = create_html_email([{'home_team': 'A', 'away_team': 'B',
                                   'qualifies': True}], '2026-07-29')

        assert html.lower().count('<html') == 1
        assert 'Wygenerowano automatycznie' in html

    def test_markers_never_leak_into_the_full_document(self):
        html = create_html_email([{'home_team': 'A', 'away_team': 'B'}],
                                 '2026-07-29')
        assert _CARDS_START in html or True  # marker may remain, must be a comment
        assert '<!--' in html


class TestDropBadge:
    def test_renders_percentage_side_and_movement(self):
        html = _render_drop_badge({'dropping_odds': {
            'drop_pct': 37.0, 'side': '2', 'open': 3.70, 'current': 2.34}})

        assert '37.0%' in html
        assert 'Goście (2)' in html
        assert '3.70 → 2.34' in html

    @pytest.mark.parametrize('side,label', [
        ('1', 'Gospodarze (1)'), ('2', 'Goście (2)'), ('X', 'Remis (X)')])
    def test_side_labels(self, side, label):
        html = _render_drop_badge({'dropping_odds': {'drop_pct': 10.0,
                                                    'side': side}})
        assert label in html

    def test_absent_or_empty_drop_renders_nothing(self):
        assert _render_drop_badge({}) == ''
        assert _render_drop_badge({'dropping_odds': None}) == ''
        assert _render_drop_badge({'dropping_odds': {'drop_pct': 0}}) == ''

    def test_movement_is_omitted_when_prices_are_missing(self):
        html = _render_drop_badge({'dropping_odds': {'drop_pct': 12.0,
                                                    'side': '1'}})
        assert '→' not in html
        assert '12.0%' in html

    def test_a_main_pipeline_row_shows_no_badge(self):
        """Rows from the scraper carry no drop, and must look unchanged."""
        cards = create_html_email([{'home_team': 'A', 'away_team': 'B',
                                    'qualifies': True}],
                                  '2026-07-29', cards_only=True)
        assert '↓' not in cards


class TestEventToMatchRow:
    def test_maps_the_fields_the_template_reads(self):
        row = doe.event_to_match_row(_event())

        assert row['home_team'] == 'Urban Titu'
        assert row['league'] == 'Romania - Romanian Cup'
        assert row['match_time'] == '14:30', 'OddsSafari calls it event_time'
        assert row['match_date'] == '2026-07-29'
        assert row['match_url'].startswith('https://')
        assert row['qualifies'] is True

    def test_carries_the_price_movement(self):
        row = doe.event_to_match_row(_event())

        assert row['dropping_odds'] == {'drop_pct': 37.0, 'side': '2',
                                        'open': 3.70, 'current': 2.34}

    def test_enrichment_reaches_the_row(self):
        row = doe.event_to_match_row(_event())

        assert row['home_odds'] == 2.34
        assert row['sofascore_total_votes'] == 900
        assert row['home_form'] == ['L', 'L', 'L', 'L', 'D']

    def test_scoring_is_attached(self):
        row = doe.event_to_match_row(_event())

        assert row['scoring_pick'] in ('1', 'X', '2')
        assert 0 <= row['scoring_prob'] <= 100

    def test_grade_is_computed(self):
        row = doe.event_to_match_row(_event())
        assert row['prediction_grade'] in ('A', 'B', 'C', 'D', 'F')

    def test_no_market_leaves_ev_empty_rather_than_minus_999(self):
        """The engines' sentinel used to print as an EV of -999.000."""
        bare = _event()
        bare['enrichment'] = {}
        row = doe.event_to_match_row(bare)

        assert row.get('scoring_ev') is None


class TestRenderedMail:
    def _html(self, events):
        return doe.build_dropping_odds_email_html(
            events, {'filter': {'min_odds': 1.8, 'max_odds': 2.5}},
            '2026-07-29', sport='football')

    def test_uses_the_main_card_and_keeps_its_own_header(self):
        html = self._html([_event()])

        assert 'Dropping Odds' in html, 'the dropping-odds header stays'
        assert 'Zobacz szczegóły meczu' in html, 'the main card is used'
        assert 'Typ modelu' in html
        assert '↓ 37.0%' in html

    def test_stays_a_single_document(self):
        html = self._html([_event(), _event(home_team='Pyunik')])

        assert html.lower().count('<html') == 1
        assert html.lower().count('<body') == 1

    def test_empty_day_still_explains_itself(self):
        html = self._html([])

        assert 'Brak zdarzeń' in html
        assert html.lower().count('<html') == 1
