"""Grading on a per-sport curve, and the pick meaning one thing.

Two faults visible in the 2026-07-29 table-tennis mail:

* The same pick was rendered as two opposing players. `scoring_pick='A'` means
  *player A = home* in the tennis engine, but the 1X2 normaliser read 'A' as
  *Away* and printed "Gracz 2 — Marek Blejchar" next to a "Tennis Engine" block
  that correctly said "Ivo Taichman" — with the wrong side's odds attached.
* Every no-odds pick was capped at Grade D/C. Scored against an absolute 100,
  a table-tennis row could reach at most 60: the market component (20) needs
  odds AiScore does not publish, and consensus (20) is measured over Forebet,
  SofaScore and the AI, of which table tennis has one. B was unreachable, so
  the grade was really reporting "has odds".
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prediction_data_contract as pdc  # noqa: E402
from email_notifier import (_canonical_pick_code,  # noqa: E402
                            _render_model_pick_section)


class TestPickCodeVocabulary:
    @pytest.mark.parametrize('raw,expected', [
        ('A', '1'), ('a', '1'), ('1', '1'),
        ('B', '2'), ('b', '2'), ('2', '2'),
    ])
    def test_tennis_reads_a_as_player_a(self, raw, expected):
        assert _canonical_pick_code(raw, is_tennis=True) == expected

    @pytest.mark.parametrize('raw,expected', [
        ('A', '2'), ('H', '1'), ('1', '1'), ('2', '2'), ('X', 'X'),
        ('1X', '1'), ('X2', '2'),
    ])
    def test_team_sports_keep_the_1x2_meaning(self, raw, expected):
        assert _canonical_pick_code(raw) == expected

    def test_tennis_has_no_draw(self):
        assert _canonical_pick_code('X', is_tennis=True) is None

    @pytest.mark.parametrize('raw', [None, '', 'none', 'nan', 'whatever'])
    def test_unusable_values_yield_nothing(self, raw):
        assert _canonical_pick_code(raw) is None
        assert _canonical_pick_code(raw, is_tennis=True) is None

    def test_player_b_pick_is_no_longer_dropped(self):
        """'B' used to fall through to None, so the line vanished entirely."""
        assert _canonical_pick_code('B', is_tennis=True) == '2'


class TestRenderedPickAgreesWithTheEngine:
    ROW = {'scoring_pick': 'A',
           'home_team': 'Ivo Taichman', 'away_team': 'Marek Blejchar'}

    def test_names_the_player_the_engine_picked(self):
        html = _render_model_pick_section(self.ROW, 2.00, None, 1.73, True)

        assert 'Ivo Taichman' in html
        assert 'Marek Blejchar' not in html

    def test_attaches_that_player_s_odds(self):
        """The mail showed '@ 1.73' — the opponent's price — for a home pick."""
        html = _render_model_pick_section(self.ROW, 2.00, None, 1.73, True)

        assert '2.00' in html
        assert '1.73' not in html

    def test_player_b_pick_renders(self):
        html = _render_model_pick_section(
            dict(self.ROW, scoring_pick='B'), 2.00, None, 1.73, True)

        assert 'Marek Blejchar' in html
        assert '1.73' in html

    def test_team_sport_away_pick_is_unaffected(self):
        html = _render_model_pick_section(
            {'scoring_pick': '2', 'home_team': 'Alpha', 'away_team': 'Beta'},
            2.00, 3.30, 1.73, False)

        assert 'Beta' in html
        assert '1.73' in html


class TestAttainableScale:
    def test_table_tennis_cannot_have_odds_or_forebet(self):
        assert pdc._attainable_quality('table_tennis') == pytest.approx(0.5)

    def test_sports_with_every_feed_are_scored_against_the_full_scale(self):
        for sport in ('football', 'basketball', 'tennis', 'hockey', ''):
            assert pdc._attainable_quality(sport) == 1.0


class TestGradeOnACurve:
    @staticmethod
    def _row(prob=95.0, **extra):
        row = {
            'sport': 'table_tennis',
            'home_team': 'Alpha', 'away_team': 'Beta',
            'scoring_pick': 'A',
            'scoring_prob': prob,
            'home_wins_in_h2h_last5': 5, 'away_wins_in_h2h_last5': 1,
            'h2h_count': 6,
            'sofascore_home_win_prob': 90, 'sofascore_away_win_prob': 10,
            'home_form': ['W', 'W', 'L'], 'away_form': ['L', 'L', 'W'],
        }
        row.update(extra)
        return row

    def test_a_strong_no_odds_table_tennis_pick_can_reach_a_or_b(self):
        row = pdc.enrich_match_with_contract(self._row())
        assert row['prediction_grade'] in ('A', 'B')

    def test_a_weak_no_odds_pick_still_grades_low(self):
        """The curve must not hand out top grades for free."""
        row = pdc.enrich_match_with_contract(self._row(prob=51.0))
        assert row['prediction_grade'] in ('C', 'D', 'F')

    def test_grade_tracks_probability_for_table_tennis(self):
        strong = pdc.enrich_match_with_contract(self._row(prob=95.0))
        weak = pdc.enrich_match_with_contract(self._row(prob=52.0))
        order = ['F', 'D', 'C', 'B', 'A']
        assert order.index(strong['prediction_grade']) > order.index(
            weak['prediction_grade'])

    def test_football_grading_is_untouched_without_a_market(self):
        """A football row missing odds keeps forfeiting those points."""
        row = pdc.enrich_match_with_contract({
            'sport': 'football',
            'home_team': 'Alpha', 'away_team': 'Beta',
            'scoring_pick': '1', 'scoring_prob': 95.0,
            'home_wins_in_h2h_last5': 5, 'away_wins_in_h2h_last5': 1,
            'h2h_count': 6,
        })
        assert row['prediction_grade'] in ('C', 'D', 'F')

    def test_grade_is_one_of_the_five_letters(self):
        row = pdc.enrich_match_with_contract(self._row())
        assert row['prediction_grade'] in ('A', 'B', 'C', 'D', 'F')

    def test_a_pick_contradicted_by_its_only_cross_check_is_not_top_grade(self):
        """Fan vote is all table tennis has; disagreeing with it must cost."""
        agreed = pdc.enrich_match_with_contract(self._row(prob=95.0))
        against = pdc.enrich_match_with_contract(self._row(
            prob=95.0, sofascore_home_win_prob=0, sofascore_away_win_prob=100))

        assert agreed['prediction_grade'] == 'A'
        assert against['prediction_grade'] not in ('A', 'B')


class TestConsensusScaleIsKeyedOnTheRow:
    def test_maximum_follows_the_number_of_voters(self):
        assert pdc._attainable_consensus(3) == 20.0
        assert pdc._attainable_consensus(2) == 12.0
        assert pdc._attainable_consensus(1) == 5.0
        assert pdc._attainable_consensus(0) == 0.0

    def test_voter_count_is_recorded(self):
        dq = pdc.compute_data_quality({
            'home_team': 'Alpha', 'away_team': 'Beta', 'scoring_pick': '1',
            'sofascore_home_win_prob': 80, 'sofascore_away_win_prob': 20,
        })

        assert dq.consensus_sources == 1
        assert dq.sources_agree == 1

    def test_full_feed_sports_keep_the_absolute_scale(self):
        """Guards the blast radius of the table-tennis curve.

        Measured on 2026-07-29, applying the curve everywhere moved tennis from
        41 A/B out of 42 down to 26, and football from C11/D10/F5 to C1/D3/F22.
        Those grades were never the reported problem and the main e-mail filters
        on them, so they must stay on the original scale.
        """
        dq = pdc.DataQualityReport()
        dq.h2h_available = True
        dq.h2h_count = 6
        dq.sofascore_available = True
        dq.odds_available = True
        dq.form_available = True
        dq.consensus_strength = 'moderate'
        dq.consensus_sources = 3
        dq.sources_agree = 2
        dq.market_model_gap = 19.0

        class _NoAbsences:
            availability_impact = 0.0

        for sport in ('tennis', 'football', 'basketball', 'hockey'):
            assert (pdc._compute_grade(dq, _NoAbsences(), 84.4, sport)
                    == pdc._compute_grade_absolute(dq, _NoAbsences(), 84.4)), sport

    def test_restricted_sports_use_the_curve(self):
        dq = pdc.DataQualityReport()
        dq.h2h_available = True
        dq.h2h_count = 6
        dq.sofascore_available = True
        dq.form_available = True
        dq.consensus_strength = 'weak'
        dq.consensus_sources = 1
        dq.sources_agree = 1

        class _NoAbsences:
            availability_impact = 0.0

        curved = pdc._compute_grade(dq, _NoAbsences(), 94.0, 'table_tennis')
        absolute = pdc._compute_grade_absolute(dq, _NoAbsences(), 94.0)

        assert curved == 'A'
        assert absolute == 'D', 'the fault being fixed'

    def test_football_with_a_market_and_one_voter_still_grades_well(self):
        """Keying the maximum on the sport punished this row twice, B -> C."""
        row = pdc.enrich_match_with_contract({
            'sport': 'football',
            'home_team': 'Alpha', 'away_team': 'Beta',
            'scoring_pick': '1', 'scoring_prob': 90.0,
            'home_wins_in_h2h_last5': 5, 'away_wins_in_h2h_last5': 1,
            'h2h_count': 6,
            'sofascore_home_win_prob': 100, 'sofascore_away_win_prob': 0,
            'home_form': ['W', 'W', 'W'], 'away_form': ['L', 'L', 'L'],
            'home_odds': 2.0, 'away_odds': 3.5,
        })

        assert row['prediction_grade'] in ('A', 'B')
