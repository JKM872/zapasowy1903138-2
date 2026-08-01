"""The accuracy report settles the two mail groups separately.

The mail now goes out split into market favourites and everything else, so a
single blended accuracy line would describe two populations that behave nothing
alike — measured 72.3% against 30.8% over 18 786 settled matches.
"""

import pytest

from check_results import _role_breakdown, generate_report_html


def detail(pick, home_odds, away_odds, outcome, predicted='home',
           sport='basketball'):
    return {'scoring_pick': pick, 'home_odds': home_odds,
            'away_odds': away_odds, 'outcome': outcome, 'predicted': predicted,
            'sport': sport, 'home_team': 'Alpha', 'away_team': 'Beta',
            'score': '2-1', 'actual': 'home'}


class TestRoleBreakdown:
    def test_favourite_and_rest_are_counted_apart(self):
        b = _role_breakdown([
            detail('1', 1.4, 3.0, 'won'),
            detail('1', 3.0, 1.4, 'lost'),
        ])
        assert b['faworyt']['total'] == 1
        assert b['faworyt']['won'] == 1
        assert b['reszta']['total'] == 1
        assert b['reszta']['lost'] == 1

    def test_accuracy_uses_decided_matches_only(self):
        b = _role_breakdown([
            detail('1', 1.4, 3.0, 'won'),
            detail('1', 1.5, 3.0, 'lost'),
            detail('1', 1.5, 3.0, 'pending'),
        ])
        assert b['faworyt']['total'] == 3
        assert b['faworyt']['accuracy'] == pytest.approx(50.0)

    def test_roi_counts_the_winning_price(self):
        b = _role_breakdown([detail('1', 2.0, 3.0, 'won')], stake=100)
        assert b['faworyt']['roi_pln'] == pytest.approx(100.0)
        assert b['faworyt']['roi_pct'] == pytest.approx(100.0)

    def test_roi_counts_the_loss_as_the_stake(self):
        b = _role_breakdown([detail('1', 2.0, 3.0, 'lost')], stake=100)
        assert b['faworyt']['roi_pln'] == pytest.approx(-100.0)
        assert b['faworyt']['roi_pct'] == pytest.approx(-100.0)

    def test_away_pick_is_priced_on_the_away_side(self):
        b = _role_breakdown(
            [detail('2', 3.0, 1.5, 'won', predicted='away')], stake=100)
        assert b['faworyt']['total'] == 1
        assert b['faworyt']['roi_pln'] == pytest.approx(50.0)

    def test_pending_matches_are_not_staked(self):
        b = _role_breakdown([detail('1', 2.0, 3.0, 'pending')])
        assert b['faworyt']['pending'] == 1
        assert b['faworyt']['staked'] == 0
        assert b['faworyt']['roi_pct'] == 0.0

    def test_void_is_recorded_and_not_staked(self):
        b = _role_breakdown([detail('1', 2.0, 3.0, 'void')])
        assert b['faworyt']['void'] == 1
        assert b['faworyt']['staked'] == 0

    def test_unusable_odds_do_not_break_roi(self):
        b = _role_breakdown([
            detail('1', 1.4, 3.0, 'won'),
            {'scoring_pick': '1', 'home_odds': None, 'away_odds': None,
             'outcome': 'won', 'predicted': 'home'},
            {'scoring_pick': '1', 'home_odds': 'x', 'away_odds': 'y',
             'outcome': 'lost', 'predicted': 'home'},
        ])
        assert b['faworyt']['won'] >= 1
        assert b['reszta']['total'] == 2

    def test_empty_input_yields_empty_buckets(self):
        b = _role_breakdown([])
        assert b['faworyt']['total'] == 0
        assert b['faworyt']['accuracy'] == 0.0

    def test_every_detail_lands_in_one_bucket(self):
        details = [detail('1', 1.4, 3.0, 'won'),
                   detail('1', 3.0, 1.4, 'lost'),
                   detail('X', 2.0, 2.0, 'draw'),
                   detail('', 0, 0, 'error')]
        b = _role_breakdown(details)
        assert b['faworyt']['total'] + b['reszta']['total'] == len(details)


class TestReportRendersTheSplit:
    def _stats(self, details):
        return {
            'total': len(details), 'finished': len(details),
            'won': sum(1 for d in details if d['outcome'] == 'won'),
            'lost': sum(1 for d in details if d['outcome'] == 'lost'),
            'draw': 0, 'pending': 0, 'void': 0, 'errors': 0,
            'accuracy': 50.0, 'roi_pln': 0.0, 'roi_pct': 0.0,
            'details': details,
            'by_sport': {'basketball': {'total': len(details), 'won': 1,
                                        'lost': 1, 'draw': 0, 'pending': 0,
                                        'void': 0, 'errors': 0}},
            'by_role': _role_breakdown(details),
        }

    def test_section_appears_when_both_groups_exist(self):
        html = generate_report_html(self._stats([
            detail('1', 1.4, 3.0, 'won'),
            detail('1', 3.0, 1.4, 'lost'),
        ]), '2026-08-01')
        assert 'Faworyt rynku vs reszta' in html
        assert 'Faworyt rynku (nasz kurs niższy)' in html
        assert 'Wyższy kurs niż przeciwnik' in html

    def test_section_says_it_is_not_a_profit_filter(self):
        """The measurement did not survive a later window; the mail must say so."""
        html = generate_report_html(self._stats([
            detail('1', 1.4, 3.0, 'won'),
        ]), '2026-08-01')
        assert 'segmentacja, nie filtr zysku' in html

    def test_empty_group_is_not_rendered(self):
        html = generate_report_html(self._stats([
            detail('1', 1.4, 3.0, 'won'),
        ]), '2026-08-01')
        assert 'Wyższy kurs niż przeciwnik' not in html

    def test_report_still_renders_without_role_data(self):
        stats = self._stats([detail('1', 1.4, 3.0, 'won')])
        stats.pop('by_role')
        html = generate_report_html(stats, '2026-08-01')
        assert 'Faworyt rynku vs reszta' not in html
        assert 'RAPORT' in html.upper()
