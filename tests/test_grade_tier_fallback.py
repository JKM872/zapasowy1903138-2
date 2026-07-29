"""A sport with no top-tier pick gets the lower tier, not silence.

Football had zero Grade A/B picks out of 26 qualifying rows on 2026-07-29, so a
premium-only filter simply sent nothing for it. The fallback is per sport: a
sport that does have A/B is unaffected, and the subject always names the tier
that actually went out so a weaker card cannot pass for a premium one.
"""

import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from email_notifier import (_select_grade_tier,  # noqa: E402
                            send_split_emails_by_sport)


def _df(*grades_by_sport):
    rows = []
    for i, (sport, grade) in enumerate(grades_by_sport):
        rows.append({
            'sport': sport,
            'home_team': f'Home{i}', 'away_team': f'Away{i}',
            'qualifies': True, 'form_advantage': False,
            'prediction_grade': grade,
            'home_odds': 2.0, 'away_odds': 2.2,
            'match_time': f'2026-07-29 1{i % 9}:00',
            'scoring_pick': '1', 'scoring_prob': 70.0,
        })
    return pd.DataFrame(rows)


def _csv(tmp_path, df):
    path = tmp_path / 'matches.csv'
    df.to_csv(path, index=False, encoding='utf-8')
    return str(path)


class TestSelectGradeTier:
    def test_prefers_the_primary_tier(self):
        df = _df(('football', 'A'), ('football', 'C'))
        chosen, label = _select_grade_tier(df, {'A', 'B'}, {'C', 'D'})

        assert list(chosen['prediction_grade']) == ['A']
        assert label == 'A/B'

    def test_drops_to_the_fallback_when_the_top_tier_is_empty(self):
        df = _df(('football', 'C'), ('football', 'D'), ('football', 'F'))
        chosen, label = _select_grade_tier(df, {'A', 'B'}, {'C', 'D'})

        assert sorted(chosen['prediction_grade']) == ['C', 'D']
        assert label == 'C/D'

    def test_no_fallback_configured_means_nothing_is_sent(self):
        df = _df(('football', 'C'))
        chosen, label = _select_grade_tier(df, {'A', 'B'}, None)

        assert len(chosen) == 0
        assert label == ''

    def test_grades_outside_both_tiers_are_never_selected(self):
        df = _df(('football', 'F'))
        chosen, _ = _select_grade_tier(df, {'A', 'B'}, {'C', 'D'})
        assert len(chosen) == 0

    def test_missing_grade_counts_as_the_worst(self):
        df = _df(('football', None))
        chosen, _ = _select_grade_tier(df, {'A', 'B'}, {'C', 'D'})
        assert len(chosen) == 0

    def test_lowercase_grade_is_accepted(self):
        df = _df(('football', 'a'))
        chosen, label = _select_grade_tier(df, {'A', 'B'}, {'C', 'D'})
        assert len(chosen) == 1
        assert label == 'A/B'


class TestSplitEmailsUseTheFallbackPerSport:
    @pytest.fixture
    def server(self):
        with patch('email_notifier.smtplib.SMTP') as smtp:
            mock = MagicMock()
            smtp.return_value.__enter__ = MagicMock(return_value=mock)
            smtp.return_value.__exit__ = MagicMock(return_value=False)
            yield mock

    @staticmethod
    def _subjects(server):
        return [str(c[0][0]['Subject'])
                for c in server.send_message.call_args_list]

    def _send(self, tmp_path, df, **kw):
        return send_split_emails_by_sport(
            csv_file=_csv(tmp_path, df), to_email='a@b.com',
            from_email='a@b.com', password='x', date='2026-07-29',
            grade_filter={'A', 'B'}, **kw)

    def test_each_sport_gets_its_own_best_tier(self, server, tmp_path: Any):
        df = _df(('tennis', 'A'), ('tennis', 'C'),
                 ('football', 'C'), ('football', 'D'))

        count = self._send(tmp_path, df, fallback_grades={'C', 'D'})

        assert count == 2
        subjects = self._subjects(server)
        tennis = [s for s in subjects if 'Tenis' in s]
        football = [s for s in subjects if 'nożna' in s]
        assert 'Grade A/B' in tennis[0]
        assert '1 meczów' in tennis[0], 'only the A row, not the C one'
        assert 'Grade C/D' in football[0]
        assert '2 meczów' in football[0]

    def test_without_a_fallback_a_sport_lacking_the_top_tier_is_skipped(
            self, server, tmp_path: Any):
        df = _df(('tennis', 'A'), ('football', 'C'))

        count = self._send(tmp_path, df)

        assert count == 1
        assert 'Tenis' in self._subjects(server)[0]

    def test_fallback_does_not_dilute_a_sport_that_has_the_top_tier(
            self, server, tmp_path: Any):
        df = _df(('tennis', 'A'), ('tennis', 'D'))

        self._send(tmp_path, df, fallback_grades={'C', 'D'})

        subject = self._subjects(server)[0]
        assert 'Grade A/B' in subject
        assert '1 meczów' in subject

    def test_nothing_anywhere_sends_nothing(self, server, tmp_path: Any):
        df = _df(('tennis', 'F'), ('football', 'F'))

        assert self._send(tmp_path, df, fallback_grades={'C', 'D'}) == 0
        assert server.send_message.call_count == 0


class TestSingleEmailUsesTheFallback:
    """The table-tennis path sends one mail, not one per sport."""

    @pytest.fixture
    def server(self):
        with patch('email_notifier.smtplib.SMTP') as smtp:
            mock = MagicMock()
            smtp.return_value.__enter__ = MagicMock(return_value=mock)
            smtp.return_value.__exit__ = MagicMock(return_value=False)
            yield mock

    def _send(self, tmp_path, df, **kw):
        from email_notifier import send_email_notification
        return send_email_notification(
            csv_file=_csv(tmp_path, df), to_email='a@b.com',
            from_email='a@b.com', password='x', subject='🏓 Table Tennis',
            skip_no_odds=False, min_odds_threshold=0.0,
            grade_filter={'A', 'B'}, **kw)

    def test_top_tier_is_used_when_present(self, server, tmp_path: Any):
        df = _df(('table_tennis', 'A'), ('table_tennis', 'C'))

        with patch('email_notifier.create_html_email',
                   return_value='<html>ok</html>') as html:
            self._send(tmp_path, df, fallback_grades={'C', 'D'})

        grades = [m['prediction_grade'] for m in html.call_args[0][0]]
        assert grades == ['A']

    def test_falls_back_when_no_top_tier(self, server, tmp_path: Any):
        df = _df(('table_tennis', 'C'), ('table_tennis', 'D'))

        with patch('email_notifier.create_html_email',
                   return_value='<html>ok</html>') as html:
            self._send(tmp_path, df, fallback_grades={'C', 'D'})

        grades = sorted(m['prediction_grade'] for m in html.call_args[0][0])
        assert grades == ['C', 'D']

    def test_subject_names_the_tier_that_went_out(self, server, tmp_path: Any):
        df = _df(('table_tennis', 'C'))

        with patch('email_notifier.create_html_email',
                   return_value='<html>ok</html>'):
            self._send(tmp_path, df, fallback_grades={'C', 'D'})

        subject = str(server.send_message.call_args[0][0]['Subject'])
        assert 'C/D' in subject
        assert 'A/B' not in subject
