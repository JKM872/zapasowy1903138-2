"""The dropping-odds verdict must be hard to earn.

On 4 826 settled moves, backing the side the price fell on lost 3.7% overall,
and 7 of 13 segments that looked profitable early lost money later. A lenient
gate would recommend those. These tests pin each condition separately.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dropping_odds_advisor as adv


def picks(n, hits, odds, date, sport='hockey', side='home'):
    return [{'sport': sport, 'side': side, 'odds': odds, 'date': date,
             'hit': i < hits} for i in range(n)]


def split(early, late):
    return early, late


class TestJudge:
    def test_profit_in_both_halves_after_haircut_is_worth_it(self):
        v = adv.judge(picks(60, 36, 2.0, '2026-08-01'), picks(60, 36, 2.0, '2026-10-01'))
        assert v['verdict'] == adv.VERDICT_GOOD

    def test_too_few_settled_is_unknown_even_if_profitable(self):
        v = adv.judge(picks(30, 25, 2.0, '2026-08-01'), picks(30, 25, 2.0, '2026-10-01'))
        assert v['verdict'] == adv.VERDICT_UNKNOWN

    def test_profit_that_vanishes_later_is_not_worth_it(self):
        """The pattern behind 7 of 13 early winners."""
        v = adv.judge(picks(60, 45, 2.0, '2026-08-01'), picks(60, 24, 2.0, '2026-10-01'))
        assert v['verdict'] != adv.VERDICT_GOOD

    def test_thin_edge_wiped_out_by_the_haircut_is_not_worth_it(self):
        # 52% at 2.00 is +4% at the scraped price, -1.2% five percent lower.
        v = adv.judge(picks(100, 52, 2.0, '2026-08-01'), picks(100, 52, 2.0, '2026-10-01'))
        assert v['roi'] > 0
        assert v['roiRealistic'] < 0
        assert v['verdict'] == adv.VERDICT_BAD

    def test_a_clear_loss_is_not_worth_it(self):
        v = adv.judge(picks(80, 30, 2.0, '2026-08-01'), picks(80, 30, 2.0, '2026-10-01'))
        assert v['verdict'] == adv.VERDICT_BAD

    def test_one_sided_history_cannot_earn_worth_it(self):
        v = adv.judge(picks(150, 100, 2.0, '2026-08-01'), [])
        assert v['verdict'] != adv.VERDICT_GOOD

    def test_numbers_are_reported_with_the_verdict(self):
        v = adv.judge(picks(60, 36, 2.0, '2026-08-01'), picks(60, 36, 2.0, '2026-10-01'))
        assert v['n'] == 120
        assert v['hitRate'] == 60.0
        assert v['roi'] == 20.0


class TestBuildModel:
    def test_segments_are_keyed_by_sport_and_side(self):
        rows = (picks(60, 36, 2.0, '2026-08-01') + picks(60, 36, 2.0, '2026-10-01')
                + picks(10, 1, 2.0, '2026-09-01', sport='rugby'))
        model = adv.build_model(rows)
        assert 'hockey|home' in model['segments']
        assert 'hockey|*' in model['segments']
        assert model['settled'] == 130

    def test_unpriced_rows_are_ignored(self):
        rows = picks(5, 5, 0.0, '2026-08-01')
        assert adv.build_model(rows)['settled'] == 0


class TestVerdictFor:
    MODEL = {'segments': {
        'hockey|home': {'verdict': adv.VERDICT_GOOD, 'n': 199},
        'hockey|*': {'verdict': adv.VERDICT_GOOD, 'n': 349},
        'handball|away': {'verdict': adv.VERDICT_UNKNOWN, 'n': 91},
        'handball|*': {'verdict': adv.VERDICT_BAD, 'n': 158},
        'volleyball|home': {'verdict': adv.VERDICT_UNKNOWN, 'n': 11},
        'volleyball|*': {'verdict': adv.VERDICT_GOOD, 'n': 400},
    }}

    def test_the_specific_segment_speaks_first(self):
        assert adv.verdict_for(self.MODEL, 'hockey', 'home')['segment'] == 'hockey|home'

    def test_a_losing_sport_speaks_for_an_undecided_side(self):
        v = adv.verdict_for(self.MODEL, 'handball', 'away')
        assert v['verdict'] == adv.VERDICT_BAD

    def test_a_winning_sport_does_not_lend_worth_it_to_an_undecided_side(self):
        v = adv.verdict_for(self.MODEL, 'volleyball', 'home')
        assert v['verdict'] == adv.VERDICT_UNKNOWN

    def test_an_unseen_sport_is_unknown(self):
        assert adv.verdict_for(self.MODEL, 'darts', 'home')['verdict'] == adv.VERDICT_UNKNOWN

    def test_no_model_gives_none(self):
        assert adv.verdict_for(None, 'hockey', 'home') is None
