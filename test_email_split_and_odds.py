# pyright: reportPrivateUsage=false
"""
Tests for:
  1. Per-sport odds threshold filtering (AND — both odds must be >= sport threshold)
  2. skip_no_odds filtering (skip matches without odds)
  3. send_split_emails_by_sport grouping logic (2 emails per sport)
  4. _passes_sport_odds_threshold helper unit tests
"""

import os
import pandas as pd
from typing import Any
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MATCHES: list[dict[str, Any]] = [
    # football, form_advantage=True, good odds (both >= 1.5)
    dict(sport='football', home_team='Barcelona', away_team='Real Madrid',
         qualifies=True, form_advantage=True,
         home_odds=1.75, away_odds=4.20, match_time='2026-03-08 20:00'),
    # football, form_advantage=False, good odds
    dict(sport='football', home_team='Arsenal', away_team='Chelsea',
         qualifies=True, form_advantage=False,
         home_odds=2.10, away_odds=3.40, match_time='2026-03-08 18:00'),
    # football, form_advantage=True, BOTH odds below football threshold (1.5)
    dict(sport='football', home_team='Bayern', away_team='Augsburg',
         qualifies=True, form_advantage=True,
         home_odds=1.10, away_odds=1.20, match_time='2026-03-08 15:30'),
    # football, qualifies but NO odds
    dict(sport='football', home_team='Dortmund', away_team='Mainz',
         qualifies=True, form_advantage=False,
         home_odds=None, away_odds=None, match_time='2026-03-08 15:30'),
    # basketball, form_advantage=True, good odds (both >= 1.3)
    dict(sport='basketball', home_team='Lakers', away_team='Celtics',
         qualifies=True, form_advantage=True,
         home_odds=1.90, away_odds=1.95, match_time='2026-03-08 02:00'),
    # basketball, form_advantage=False, good odds
    dict(sport='basketball', home_team='Warriors', away_team='Nets',
         qualifies=True, form_advantage=False,
         home_odds=1.55, away_odds=2.50, match_time='2026-03-08 01:00'),
    # tennis, form_advantage=False, one odds below 1.35 — AND rejects (both must be >= 1.35)
    dict(sport='tennis', home_team='Djokovic', away_team='Nadal',
         qualifies=True, form_advantage=False,
         home_odds=1.19, away_odds=5.00, match_time='2026-03-08 14:00'),
    # not qualifying — should never appear
    dict(sport='football', home_team='Wolves', away_team='Brighton',
         qualifies=False, form_advantage=False,
         home_odds=2.00, away_odds=3.50, match_time='2026-03-08 16:00'),
]


def _write_csv(tmp_path: Any, matches: list[dict[str, Any]] | None = None) -> str:
    """Write sample matches to a temp CSV and return path."""
    df = pd.DataFrame(matches or SAMPLE_MATCHES)
    csv_path = os.path.join(str(tmp_path), 'test_matches.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    return csv_path


def test_create_html_email_omits_top_picks_and_sorted_odds_sections() -> None:
    from email_notifier import create_html_email

    html = create_html_email([
        dict(
            home_team='Liverpool',
            away_team='Manchester United',
            match_time='2026-03-08 20:00',
            home_wins_in_h2h_last5=3,
            away_wins_in_h2h_last5=1,
            forebet_probability=75.5,
            gemini_reasoning='Test reasoning',
            gemini_recommendation='HIGH',
            gemini_confidence=90,
            home_odds=1.85,
            draw_odds=3.50,
            away_odds=4.20,
            focus_team='home',
            ai_prediction={
                'confidenceTier': 'VERY HIGH',
                'compositeConfidence': 98,
                'pick': '2',
                'pickLabel': 'Away Win',
            },
        )
    ], '2026-03-08', include_sorted_odds=True, odds_limit=5)

    assert 'TOP PICKS - Najlepsze Typy AI' not in html
    assert 'KURSY POSORTOWANE' not in html
    assert 'Liverpool' in html


# ---------------------------------------------------------------------------
# Tests: _passes_sport_odds_threshold helper
# ---------------------------------------------------------------------------

class TestPassesSportOddsThreshold:
    """Unit tests for the per-sport odds threshold helper."""

    def test_football_both_above(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        assert _passes_sport_odds_threshold('football', 1.75, 4.20) is True

    def test_football_both_below(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        assert _passes_sport_odds_threshold('football', 1.10, 1.20) is False

    def test_football_and_one_below(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # home below, away above → AND rejects (both must be >= 1.50)
        assert _passes_sport_odds_threshold('football', 1.10, 8.50) is False

    def test_basketball_lower_threshold(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # 1.35 >= 1.30 basketball threshold
        assert _passes_sport_odds_threshold('basketball', 1.35, 1.35) is True

    def test_basketball_below(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        assert _passes_sport_odds_threshold('basketball', 1.20, 1.20) is False

    def test_tennis_exactly_at_threshold(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # tennis threshold = 1.35, exactly at threshold = passes
        assert _passes_sport_odds_threshold('tennis', 1.35, 1.35) is True

    def test_handball_threshold(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # handball threshold = 1.45
        assert _passes_sport_odds_threshold('handball', 1.45, 1.10) is False
        assert _passes_sport_odds_threshold('handball', 1.10, 1.10) is False
        assert _passes_sport_odds_threshold('handball', 1.45, 1.45) is True

    def test_hockey_threshold(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # hockey threshold = 1.50
        assert _passes_sport_odds_threshold('hockey', 1.50, 1.00) is False
        assert _passes_sport_odds_threshold('hockey', 1.40, 1.40) is False
        assert _passes_sport_odds_threshold('hockey', 1.50, 1.50) is True

    def test_volleyball_threshold(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # volleyball threshold = 1.30
        assert _passes_sport_odds_threshold('volleyball', 1.30, 1.10) is False
        assert _passes_sport_odds_threshold('volleyball', 1.20, 1.20) is False
        assert _passes_sport_odds_threshold('volleyball', 1.30, 1.30) is True

    def test_unknown_sport_uses_fallback(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # unknown sport → fallback 1.35
        assert _passes_sport_odds_threshold('rugby', 1.40, 1.40) is True
        assert _passes_sport_odds_threshold('rugby', 1.30, 1.30) is False

    def test_both_none_rejected(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        assert _passes_sport_odds_threshold('football', None, None) is False

    def test_one_none_other_above(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        # home=None, away=2.0 >= 1.5 → AND rejects (None fails)
        assert _passes_sport_odds_threshold('football', None, 2.0) is False

    def test_nan_float_rejected(self) -> None:
        from email_notifier import _passes_sport_odds_threshold
        assert _passes_sport_odds_threshold('football', float('nan'), float('nan')) is False


# ---------------------------------------------------------------------------
# Tests: per-sport filtering in send_email_notification
# ---------------------------------------------------------------------------

class TestPerSportOddsClassic:
    """send_email_notification filters by per-sport thresholds (AND condition)."""

    @patch('email_notifier.smtplib.SMTP')
    def test_filters_both_odds_below_sport_threshold(self, mock_smtp: Any, tmp_path: Any) -> None:
        from email_notifier import send_email_notification
        csv = _write_csv(tmp_path)

        with patch('email_notifier.create_html_email', return_value='<html>ok</html>') as mock_html:
            send_email_notification(
                csv_file=csv, to_email='a@b.com', from_email='a@b.com',
                password='x', skip_no_odds=True,
            )
            matches_sent = mock_html.call_args[0][0]
            teams = {m['home_team'] for m in matches_sent}
            assert 'Bayern' not in teams, "Bayern (1.10/1.20, football threshold 1.5) both below"
            assert 'Dortmund' not in teams, "Dortmund (no odds) should be filtered"
            assert 'Barcelona' in teams
            assert 'Arsenal' in teams
            assert 'Lakers' in teams
            assert 'Warriors' in teams

    @patch('email_notifier.smtplib.SMTP')
    def test_and_condition_rejects_one_below(self, mock_smtp: Any, tmp_path: Any) -> None:
        from email_notifier import send_email_notification
        csv = _write_csv(tmp_path)

        with patch('email_notifier.create_html_email', return_value='<html>ok</html>') as mock_html:
            send_email_notification(
                csv_file=csv, to_email='a@b.com', from_email='a@b.com',
                password='x', skip_no_odds=True,
            )
            matches_sent = mock_html.call_args[0][0]
            teams = {m['home_team'] for m in matches_sent}
            # Djokovic: tennis 1.19/5.00, threshold=1.35, 1.19<1.35 → rejected by AND
            assert 'Djokovic' not in teams, "Djokovic should be rejected (home 1.19 < 1.35)"

    @patch('email_notifier.smtplib.SMTP')
    def test_no_matches_after_filter(self, mock_smtp: Any, tmp_path: Any) -> None:
        """If all matches are below sport threshold, no email should be sent."""
        from email_notifier import send_email_notification
        low = [dict(sport='football', home_team='A', away_team='B',
                    qualifies=True, form_advantage=False,
                    home_odds=1.05, away_odds=1.10, match_time='2026-03-08 12:00')]
        csv = _write_csv(tmp_path, low)

        send_email_notification(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x', skip_no_odds=True,
        )
        mock_smtp.return_value.__enter__.return_value.send_message.assert_not_called()

    @patch('email_notifier.smtplib.SMTP')
    def test_basketball_passes_with_lower_threshold(self, mock_smtp: Any, tmp_path: Any) -> None:
        """Basketball threshold 1.3 — odds 1.35 should pass (would fail football 1.5)."""
        from email_notifier import send_email_notification
        matches = [dict(sport='basketball', home_team='Team1', away_team='Team2',
                        qualifies=True, form_advantage=False,
                        home_odds=1.35, away_odds=1.35, match_time='2026-03-08 12:00')]
        csv = _write_csv(tmp_path, matches)

        with patch('email_notifier.create_html_email', return_value='<html>ok</html>') as mock_html:
            send_email_notification(
                csv_file=csv, to_email='a@b.com', from_email='a@b.com',
                password='x', skip_no_odds=True,
            )
            teams = {m['home_team'] for m in mock_html.call_args[0][0]}
            assert 'Team1' in teams

    @patch('email_notifier.smtplib.SMTP')
    def test_unknown_sport_uses_fallback(self, mock_smtp: Any, tmp_path: Any) -> None:
        """Unknown sport 'rugby' should use fallback threshold 1.35."""
        from email_notifier import send_email_notification
        matches = [
            dict(sport='rugby', home_team='PassTeam', away_team='X',
                 qualifies=True, form_advantage=False,
                 home_odds=1.40, away_odds=1.40, match_time='2026-03-08 12:00'),
            dict(sport='rugby', home_team='FailTeam', away_team='Y',
                 qualifies=True, form_advantage=False,
                 home_odds=1.20, away_odds=1.20, match_time='2026-03-08 13:00'),
        ]
        csv = _write_csv(tmp_path, matches)

        with patch('email_notifier.create_html_email', return_value='<html>ok</html>') as mock_html:
            send_email_notification(
                csv_file=csv, to_email='a@b.com', from_email='a@b.com',
                password='x', skip_no_odds=True,
            )
            teams = {m['home_team'] for m in mock_html.call_args[0][0]}
            assert 'PassTeam' in teams, "1.40 >= 1.35 fallback"
            assert 'FailTeam' not in teams, "1.20 < 1.35 fallback"


# ---------------------------------------------------------------------------
# Tests: send_split_emails_by_sport
# ---------------------------------------------------------------------------

class TestSplitEmailsBySport:
    """send_split_emails_by_sport groups by sport with per-sport thresholds."""

    @patch('email_notifier.smtplib.SMTP')
    def test_sends_correct_number_of_emails(self, mock_smtp: Any, tmp_path: Any) -> None:
        from email_notifier import send_split_emails_by_sport
        csv = _write_csv(tmp_path)

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )

        # One email per sport (form-advantage matches are no longer split into
        # their own message). After the per-sport odds filter — Bayern 1.10/1.20
        # dropped, Dortmund has no odds, Djokovic 1.19/5.00 dropped because both
        # prices must clear the threshold — two sports remain:
        #   football:   [Barcelona, Arsenal] → 1 email
        #   basketball: [Lakers, Warriors]   → 1 email
        assert count == 2
        assert mock_server.send_message.call_count == 2

    @patch('email_notifier.smtplib.SMTP')
    def test_subjects_contain_sport_and_type(self, mock_smtp: Any, tmp_path: Any) -> None:
        from email_notifier import send_split_emails_by_sport
        csv = _write_csv(tmp_path)

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )

        subjects: list[str] = []
        for c in mock_server.send_message.call_args_list:
            msg = c[0][0]
            subjects.append(str(msg['Subject']))

        # One basketball email covering both its matches
        bball = [s for s in subjects if 'Koszykówka' in s]
        assert len(bball) == 1
        # Djokovic tennis (1.19/5.00) should be filtered out by AND logic
        tennis_normal = [s for s in subjects if 'Tenis' in s]
        assert len(tennis_normal) == 0, "Tennis should be absent (Djokovic 1.19 < 1.35)"

    @patch('email_notifier.smtplib.SMTP')
    def test_empty_group_not_sent(self, mock_smtp: Any, tmp_path: Any) -> None:
        """If a sport has no form_advantage matches, only 1 email for that sport."""
        from email_notifier import send_split_emails_by_sport
        only_normal = [
            dict(sport='hockey', home_team='A', away_team='B',
                 qualifies=True, form_advantage=False,
                 home_odds=2.00, away_odds=3.00, match_time='2026-03-08 19:00'),
        ]
        csv = _write_csv(tmp_path, only_normal)

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )
        assert count == 1  # only normal group

    @patch('email_notifier.smtplib.SMTP')
    def test_all_filtered_returns_zero(self, mock_smtp: Any, tmp_path: Any) -> None:
        from email_notifier import send_split_emails_by_sport
        low = [dict(sport='football', home_team='X', away_team='Y',
                    qualifies=True, form_advantage=True,
                    home_odds=1.05, away_odds=1.10, match_time='2026-03-08 12:00')]
        csv = _write_csv(tmp_path, low)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )
        assert count == 0

    @patch('email_notifier.smtplib.SMTP')
    def test_odds_exactly_at_sport_threshold_passes(self, mock_smtp: Any, tmp_path: Any) -> None:
        """Odds exactly at sport threshold should pass."""
        from email_notifier import send_split_emails_by_sport
        edge = [dict(sport='tennis', home_team='Player1', away_team='Player2',
                     qualifies=True, form_advantage=False,
                     home_odds=1.35, away_odds=1.35, match_time='2026-03-08 10:00')]
        csv = _write_csv(tmp_path, edge)

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )
        assert count == 1

    @patch('email_notifier.smtplib.SMTP')
    def test_nan_string_odds_filtered(self, mock_smtp: Any, tmp_path: Any) -> None:
        """String 'NaN' odds should be treated as missing."""
        from email_notifier import send_split_emails_by_sport
        nans = [dict(sport='football', home_team='TeamA', away_team='TeamB',
                     qualifies=True, form_advantage=True,
                     home_odds='NaN', away_odds='NaN', match_time='2026-03-08 12:00')]
        csv = _write_csv(tmp_path, nans)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )
        assert count == 0

    @patch('email_notifier.smtplib.SMTP')
    def test_per_sport_different_thresholds(self, mock_smtp: Any, tmp_path: Any) -> None:
        """Match that passes basketball threshold (1.3) but would fail football (1.5)."""
        from email_notifier import send_split_emails_by_sport
        matches = [
            dict(sport='basketball', home_team='BballTeam', away_team='X',
                 qualifies=True, form_advantage=False,
                 home_odds=1.40, away_odds=1.40, match_time='2026-03-08 12:00'),
            dict(sport='football', home_team='FootTeam', away_team='Y',
                 qualifies=True, form_advantage=False,
                 home_odds=1.40, away_odds=1.40, match_time='2026-03-08 13:00'),
        ]
        csv = _write_csv(tmp_path, matches)

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        count = send_split_emails_by_sport(
            csv_file=csv, to_email='a@b.com', from_email='a@b.com',
            password='x',
        )
        # basketball 1.40 >= 1.30 → passes
        # football 1.40 < 1.50 → filtered
        assert count == 1
        msg = mock_server.send_message.call_args[0][0]
        assert 'Koszykówka' in str(msg['Subject'])
