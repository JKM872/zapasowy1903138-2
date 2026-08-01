"""Splitting the mail into market-favourite picks and everything else.

Measured on 18 786 settled matches carrying real prices, the two groups behave
nothing alike: 72.3% hit rate against 30.8% on the full sample, 73.0% against
36.5% over the last six weeks. Reporting one average over both described two
unlike things with one number.

What the split is not: a profit filter. Favourites returned -1.1% and underdogs
-3.4% on the full sample, and the order reverses out of sample (-5.7% against
-4.1%). These tests therefore pin the separation and the bookkeeping, and claim
nothing about which side earns.
"""

import pandas as pd
import pytest

import email_notifier as en
from email_notifier import (ROLE_FAVOURITE, ROLE_REST, classify_pick_role,
                            send_split_emails_by_sport)


class TestClassifyPickRole:
    def test_backing_the_shorter_price_is_the_favourite(self):
        assert classify_pick_role({
            'scoring_pick': '1', 'home_odds': 1.5, 'away_odds': 2.5,
        }) == ROLE_FAVOURITE

    def test_backing_the_longer_price_is_the_rest(self):
        assert classify_pick_role({
            'scoring_pick': '1', 'home_odds': 3.0, 'away_odds': 1.4,
        }) == ROLE_REST

    def test_away_pick_is_judged_on_its_own_price(self):
        assert classify_pick_role({
            'scoring_pick': '2', 'home_odds': 3.0, 'away_odds': 1.4,
        }) == ROLE_FAVOURITE

    def test_equal_prices_are_not_a_favourite(self):
        assert classify_pick_role({
            'scoring_pick': '1', 'home_odds': 2.0, 'away_odds': 2.0,
        }) == ROLE_REST

    def test_draw_pick_goes_to_the_rest(self):
        assert classify_pick_role({
            'scoring_pick': 'X', 'home_odds': 2.0, 'draw_odds': 3.2,
            'away_odds': 3.0,
        }) == ROLE_REST

    @pytest.mark.parametrize('match', [
        {'scoring_pick': '1', 'away_odds': 2.0},
        {'scoring_pick': '1', 'home_odds': 1.8},
        {'scoring_pick': '1', 'home_odds': 1.0, 'away_odds': 2.0},
        {'scoring_pick': '', 'home_odds': 1.5, 'away_odds': 2.5},
        {},
    ])
    def test_an_incomplete_comparison_is_never_a_favourite(self, match):
        """The favourite group must hold only fixtures where the test ran."""
        assert classify_pick_role(match) == ROLE_REST

    def test_the_two_groups_partition_every_input(self):
        rows = [
            {'scoring_pick': '1', 'home_odds': 1.5, 'away_odds': 2.5},
            {'scoring_pick': '2', 'home_odds': 1.5, 'away_odds': 2.5},
            {'scoring_pick': 'X', 'home_odds': 2.0, 'away_odds': 2.0},
            {},
        ]
        roles = [classify_pick_role(r) for r in rows]
        assert set(roles) <= {ROLE_FAVOURITE, ROLE_REST}
        assert len(roles) == len(rows)


def _csv(tmp_path, rows):
    path = tmp_path / 'qualified.csv'
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8')
    return str(path)


def _row(home, away, pick, home_odds, away_odds, sport='basketball'):
    return {
        'home_team': home, 'away_team': away, 'sport': sport,
        'match_url': f'https://example.test/{home}-{away}',
        'match_date': '2026-08-01', 'match_time': '18:00',
        'home_odds': home_odds, 'away_odds': away_odds, 'draw_odds': None,
        'scoring_pick': pick, 'scoring_prob': 61.0, 'scoring_ev': 0.05,
        'prediction_grade': 'B', 'qualifies': True, 'focus_team': 'home',
        'h2h_count': 4, 'win_rate': 0.62,
    }


class TestSplitProducesSeparateManifests:
    """Bookkeeping has to follow the split, or the report re-merges them."""

    @pytest.fixture(autouse=True)
    def _in_tmp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self.tmp = tmp_path
        self.saved: list = []
        real = en._save_mailed_manifest

        def spy(matches, date, tag=''):
            self.saved.append((tag, len(matches)))
            return real(matches, date, tag=tag)

        monkeypatch.setattr(en, '_save_mailed_manifest', spy)

    def _send(self, rows, **kwargs):
        # Dummy credentials stop before SMTP; manifests are written first, which
        # is exactly the seam under test.
        return send_split_emails_by_sport(
            csv_file=_csv(self.tmp, rows), to_email='to@example.test',
            from_email='noreply@localhost', password='dummy',
            date='2026-08-01', **kwargs)

    def test_favourites_and_rest_get_their_own_manifest(self):
        self._send([
            _row('Alpha', 'Beta', '1', 1.4, 3.0),
            _row('Gamma', 'Delta', '1', 3.2, 1.35),
        ])
        tags = dict(self.saved)
        assert tags.get('basketball_faworyt') == 1
        assert tags.get('basketball_reszta') == 1

    def test_no_combined_manifest_is_written_when_split(self):
        self._send([_row('Alpha', 'Beta', '1', 1.4, 3.0)])
        assert 'basketball' not in dict(self.saved)

    def test_a_group_with_no_matches_is_not_written(self):
        self._send([_row('Alpha', 'Beta', '1', 1.4, 3.0)])
        assert 'basketball_reszta' not in dict(self.saved)

    def test_every_match_lands_in_exactly_one_group(self):
        rows = [
            _row('A', 'B', '1', 1.4, 3.0),
            _row('C', 'D', '2', 1.4, 3.0),
            _row('E', 'F', '1', 3.0, 1.4),
        ]
        self._send(rows)
        assert sum(n for _, n in self.saved) == len(rows)

    def test_sports_stay_separate_within_the_split(self):
        # Kursy wyraźnie powyżej progów per sport: hokej odrzuca 1.4, więc
        # niższa cena badałaby filtr progowy, a nie podział na role.
        self._send([
            _row('A', 'B', '1', 1.9, 3.5, sport='basketball'),
            _row('C', 'D', '1', 1.9, 3.5, sport='hockey'),
        ])
        tags = dict(self.saved)
        assert tags.get('basketball_faworyt') == 1
        assert tags.get('hockey_faworyt') == 1

    def test_disabling_the_split_restores_one_manifest_per_sport(self):
        self._send([
            _row('A', 'B', '1', 1.4, 3.0),
            _row('C', 'D', '1', 3.0, 1.4),
        ], split_by_role=False)
        tags = dict(self.saved)
        assert tags.get('basketball') == 2
        assert 'basketball_faworyt' not in tags
