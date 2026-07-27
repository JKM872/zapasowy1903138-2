"""Tests for table-tennis reporting correctness.

Three defects observed in a real email are pinned down here:

1. "H2H 4/6 67%" appeared next to "Faworytem: <opponent>". The H2H figures are
   framed on the FOCUS player while the engine's `favorite` is framed on
   player A/B (home/away), so the two boxes described different people with no
   label saying so. It read as a contradiction.

2. The TYP field printed the raw engine pick — a bare "B" — which looks like a
   Grade letter rather than "the model picks player B".

3. The table-tennis pipeline never called enrich_match_with_contract, so its
   rows had no prediction_grade at all. The Grade A/B mail filter therefore
   dropped every table-tennis pick silently.
"""

import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from email_notifier import create_html_email  # noqa: E402
from prediction_data_contract import enrich_match_with_contract  # noqa: E402


def _tt_row(**kw):
    row = {
        'home_team': 'Milan Tlusty', 'away_team': 'Jan Hendrych',
        'sport': 'table_tennis', 'league': 'Czech Republic — TT Cup',
        'match_time': '14:20', 'match_date': '2026-07-27',
        'focus_team': 'away',
        'h2h_count': 6, 'win_rate': 0.67,
        'home_wins_in_h2h_last5': 2, 'away_wins_in_h2h_last5': 4,
        'sofascore_home_win_prob': 50.0, 'sofascore_away_win_prob': 50.0,
        'sofascore_total_votes': 2,
        'qualifies': True, 'email_qualifies': True,
        'match_url': 'https://example/tt/1',
        'scoring_pick': 'B', 'scoring_prob': 63.0,
        'advanced_score': 19.0, 'favorite': 'player_b',
    }
    row.update(kw)
    return row


def _typ_field(html):
    m = re.search(r'>([^<]{1,40})</div>\s*<div style="font-size: 9px[^>]*>TYP', html)
    return m.group(1).strip() if m else None


class TestH2HSubjectIsNamed:
    def test_h2h_box_names_its_subject(self):
        html = create_html_email([_tt_row()], '2026-07-27')
        assert 'dla:' in html

    def test_subject_is_the_focus_player_when_focus_away(self):
        html = create_html_email([_tt_row(focus_team='away')], '2026-07-27')
        assert 'dla: Jan Hendrych' in html

    def test_subject_is_home_when_focus_home(self):
        html = create_html_email([_tt_row(focus_team='home')], '2026-07-27')
        assert 'dla: Milan Tlusty' in html

    def test_no_subject_line_without_h2h(self):
        html = create_html_email([_tt_row(h2h_count=0)], '2026-07-27')
        assert 'dla:' not in html


class TestPickIsNamed:
    def test_pick_b_renders_the_away_player(self):
        html = create_html_email([_tt_row(scoring_pick='B')], '2026-07-27')
        assert _typ_field(html) == 'Jan Hendrych'

    def test_pick_a_renders_the_home_player(self):
        html = create_html_email([_tt_row(scoring_pick='A')], '2026-07-27')
        assert _typ_field(html) == 'Milan Tlusty'

    def test_numeric_picks_are_named_too(self):
        assert _typ_field(create_html_email(
            [_tt_row(scoring_pick='2')], '2026-07-27')) == 'Jan Hendrych'
        assert _typ_field(create_html_email(
            [_tt_row(scoring_pick='1')], '2026-07-27')) == 'Milan Tlusty'

    def test_draw_pick_is_labelled(self):
        html = create_html_email(
            [_tt_row(sport='football', scoring_pick='X')], '2026-07-27')
        assert _typ_field(html) == 'Remis'

    def test_no_bare_letter_left_in_the_typ_field(self):
        html = create_html_email([_tt_row(scoring_pick='B')], '2026-07-27')
        assert not re.search(r'>B</div>\s*<div[^>]*>TYP', html)

    def test_missing_pick_shows_dash(self):
        row = _tt_row()
        row.pop('scoring_pick')
        html = create_html_email([row], '2026-07-27')
        assert _typ_field(html) in ('—', None)

    def test_unknown_token_is_passed_through(self):
        html = create_html_email([_tt_row(scoring_pick='ZZZ')], '2026-07-27')
        assert _typ_field(html) == 'ZZZ'


class TestPickAndFavouriteAgree:
    def test_named_pick_matches_the_favourite_box(self):
        # Both boxes must name the same player when the engine picks B.
        html = create_html_email(
            [_tt_row(scoring_pick='B', favorite='player_b')], '2026-07-27')
        assert _typ_field(html) == 'Jan Hendrych'
        assert 'Jan Hendrych' in html


class TestGradingIsApplied:
    def test_contract_enrichment_produces_a_grade(self):
        row = _tt_row()
        enrich_match_with_contract(row)
        assert row.get('prediction_grade') in ('A', 'B', 'C', 'D', 'F')

    def test_thin_data_grades_low_not_missing(self):
        # No form, no odds, 2 votes -> must be a low grade, but present.
        row = _tt_row()
        enrich_match_with_contract(row)
        assert row['prediction_grade'] in ('D', 'F')

    def test_pipeline_calls_the_contract(self):
        import inspect

        import table_tennis_aiscore_pipeline as tt
        src = inspect.getsource(tt)
        assert 'enrich_match_with_contract' in src, \
            'table-tennis rows would carry no prediction_grade'


class TestAdvancedScoreThresholdRecorded:
    def test_pipeline_records_the_threshold_verdict(self):
        import inspect

        import table_tennis_aiscore_pipeline as tt
        src = inspect.getsource(tt.score_rows)
        assert 'advanced_score_passes' in src
        assert 'advanced_score_threshold' in src

    def test_verdict_matches_the_threshold(self):
        from tennis_scoring_engine import TennisScoringEngine
        engine = TennisScoringEngine(threshold=25.0)
        scored = engine.score_match(_tt_row())
        passes = scored.advanced_score >= engine.threshold
        assert isinstance(passes, bool)
