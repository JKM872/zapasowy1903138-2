"""The report must say how many matches its ROI rests on.

On 2026-08-03 the mail showed "-44.0% / -220 PLN" directly beside "58% (33/57)".
The ROI was arithmetically right but covered only the five settled picks that
carried a price: table tennis, 124 of 143 sends, had no odds at all. Read as a
verdict on every pick it was alarming and wrong.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check_results import FLAT_STAKE_PLN, evaluate, generate_report_html


def row(url, home, away, sport, pick='home', home_odds=None, away_odds=None):
    return {
        'match_url': url,
        'home_team': home,
        'away_team': away,
        'sport': sport,
        'predicted': pick,
        'scoring_pick': pick,
        'home_odds': home_odds,
        'away_odds': away_odds,
        'match_date': '2026-08-03',
    }


def finished(home, away, winner, score_home, score_away):
    """A result in the shape the store hands back."""
    return {
        'status': 'finished',
        'score_home': score_home,
        'score_away': score_away,
        'winner': winner,
        'home_team': home,
        'away_team': away,
        'source': 'sofascore',
        'sport': 'table_tennis',
        'date': '2026-08-03',
    }


def priced_loss_and_unpriced_win():
    """One priced pick that lost, one unpriced pick that won."""
    matches = [
        row('u/priced', 'A', 'B', 'football', 'home', home_odds=2.0, away_odds=1.8),
        row('u/unpriced', 'C', 'D', 'table_tennis', 'home'),
    ]
    results = {
        'u/priced': finished('A', 'B', 'away', 0, 1),
        'u/unpriced': finished('C', 'D', 'home', 3, 1),
    }
    return evaluate(matches, results)


class TestRoiBasisIsStated:
    def test_both_picks_are_settled(self):
        stats = priced_loss_and_unpriced_win()
        assert stats['won'] == 1, 'the unpriced pick still won'
        assert stats['lost'] == 1

    def test_roi_counts_only_the_priced_pick(self):
        stats = priced_loss_and_unpriced_win()
        assert stats['roi_count'] == 1
        assert stats['roi_decided'] == 2
        assert stats['roi_pln'] == -FLAT_STAKE_PLN
        assert stats['roi_pct'] == -100.0

    def test_the_report_says_what_the_roi_covers(self):
        html = generate_report_html(priced_loss_and_unpriced_win(), '2026-08-03')
        assert 'liczone na 1 z 2 rozliczonych' in html, \
            'a bare -100% next to a win reads as a broken model'

    def test_no_priced_matches_says_so_instead_of_showing_zero(self):
        matches = [row('u/1', 'C', 'D', 'table_tennis', 'home')]
        results = {'u/1': finished('C', 'D', 'home', 3, 1)}
        stats = evaluate(matches, results)
        assert stats['roi_count'] == 0
        html = generate_report_html(stats, '2026-08-03')
        assert 'ROI niemierzalne' in html


class TestRoleBreakdownBasis:
    def test_each_group_states_its_priced_count(self):
        html = generate_report_html(priced_loss_and_unpriced_win(), '2026-08-03')
        # Either a priced count or an explicit "no prices" note, never a bare
        # percentage.
        assert ('kurs.' in html) or ('brak kursów' in html)
