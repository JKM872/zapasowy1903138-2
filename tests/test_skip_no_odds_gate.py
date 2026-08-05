"""`skip_no_odds` must still apply when the qualification gate ran.

The odds *threshold* filter is deliberately skipped once the gate has run, and it
sits a few lines below the "drop unpriced picks" filter. If the two were ever
folded together, table tennis would silently go back to mailing picks that cannot
be settled in money — which is the whole reason its ROI was unmeasurable.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_notifier as en


def frame():
    """Two gate-qualified table-tennis picks; only one carries a price."""
    return pd.DataFrame([
        {
            'home_team': 'Jirasek Martin', 'away_team': 'Flesar Milan',
            'sport': 'table_tennis', 'match_url': 'u/priced',
            'qualifies': True, 'email_qualifies': True, 'channel_qualifies': True,
            'prediction_grade': 'B', 'scoring_pick': 'home',
            'home_odds': 1.57, 'away_odds': 2.25,
        },
        {
            'home_team': 'Adrian Eliasz', 'away_team': 'Michal Skorski',
            'sport': 'table_tennis', 'match_url': 'u/unpriced',
            'qualifies': True, 'email_qualifies': True, 'channel_qualifies': True,
            'prediction_grade': 'B', 'scoring_pick': 'home',
            'home_odds': None, 'away_odds': None,
        },
    ])


def mailed_rows(tmp_path, monkeypatch, **kwargs):
    """Run the mailer against a CSV and return the manifest it wrote."""
    import json

    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / 'card.csv'
    frame().to_csv(csv_path, index=False, encoding='utf-8')

    # Block the network. The manifest is written before the send, which is what
    # these tests assert on, so a refused connection is fine.
    def _no_network(*a, **k):
        raise RuntimeError('network disabled in tests')

    monkeypatch.setattr(en.smtplib, 'SMTP', _no_network)
    monkeypatch.setattr(en.smtplib, 'SMTP_SSL', _no_network)

    try:
        en.send_email_notification(
            csv_file=str(csv_path),
            to_email='to@example.test',
            from_email='from@example.test',
            password='',
            date='2026-08-04',
            **kwargs,
        )
    except Exception:
        # Sending is expected to fail without SMTP; the manifest is written first.
        pass

    path = tmp_path / 'outputs' / 'mailed_manifest_2026-08-04.json'
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8'))


class TestSkipNoOdds:
    def test_unpriced_picks_are_dropped(self, tmp_path, monkeypatch):
        records = mailed_rows(tmp_path, monkeypatch, skip_no_odds=True,
                              min_odds_threshold=0.0)
        urls = {r.get('match_url') for r in records}
        assert 'u/unpriced' not in urls, \
            'a pick with no price cannot be settled in money'

    def test_the_priced_pick_survives(self, tmp_path, monkeypatch):
        records = mailed_rows(tmp_path, monkeypatch, skip_no_odds=True,
                              min_odds_threshold=0.0)
        priced = [r for r in records if r.get('match_url') == 'u/priced']
        assert priced, 'the priced pick has to go out'
        assert priced[0]['home_odds'] == pytest.approx(1.57)

    def test_without_the_flag_both_are_kept(self, tmp_path, monkeypatch):
        """Guards the flag itself: the filter must be what removes the pick."""
        records = mailed_rows(tmp_path, monkeypatch, skip_no_odds=False,
                              min_odds_threshold=0.0)
        urls = {r.get('match_url') for r in records}
        assert {'u/priced', 'u/unpriced'} <= urls
