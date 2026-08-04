"""The mailed manifest must capture odds in either shape.

Rows reach the mailer two ways. Built in memory they carry flat ``home_odds``;
re-read from ``results/*.json`` they carry prices only under
``odds: {home, draw, away}``. The manifest read the flat keys alone, so every
table-tennis pick was stored as unpriced. On 2026-08-03, 28 of 99 qualifying
table-tennis rows held a SofaScore price and the manifest recorded none — which
is why the ROI in the report rested on a handful of matches and read -44%.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_notifier as en


def base_row(**over):
    row = {
        'match_url': 'https://example.test/m/1',
        'match_date': '2026-08-03',
        'sport': 'table_tennis',
        'home_team': 'Adrian Eliasz',
        'away_team': 'Michal Skorski',
        'scoring_pick': 'home',
        'qualifies': True,
    }
    row.update(over)
    return row


class TestManifestField:
    def test_flat_odds_are_used(self):
        row = base_row(home_odds=1.57, away_odds=2.25)
        assert en._manifest_field(row, 'home_odds') == 1.57
        assert en._manifest_field(row, 'away_odds') == 2.25

    def test_nested_odds_are_picked_up(self):
        row = base_row(odds={'home': 1.57, 'draw': None, 'away': 2.25})
        assert en._manifest_field(row, 'home_odds') == 1.57
        assert en._manifest_field(row, 'away_odds') == 2.25

    def test_flat_wins_when_both_are_present(self):
        row = base_row(home_odds=1.90, odds={'home': 1.57})
        assert en._manifest_field(row, 'home_odds') == 1.90

    def test_missing_odds_stay_none(self):
        assert en._manifest_field(base_row(), 'home_odds') is None

    def test_a_nested_draw_is_resolved(self):
        row = base_row(odds={'home': 2.1, 'draw': 3.4, 'away': 3.0})
        assert en._manifest_field(row, 'draw_odds') == 3.4

    def test_non_odds_fields_are_untouched_by_the_fallback(self):
        row = base_row(odds={'home': 1.5})
        assert en._manifest_field(row, 'home_team') == 'Adrian Eliasz'
        assert en._manifest_field(row, 'league') is None

    def test_a_non_dict_odds_value_is_survived(self):
        """Older rows sometimes carried a string here."""
        assert en._manifest_field(base_row(odds='1.57/2.25'), 'home_odds') is None


class TestSavedManifest:
    def test_nested_odds_reach_the_written_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        row = base_row(odds={'home': 1.57, 'draw': None, 'away': 2.25})

        path = en._save_mailed_manifest([row], '2026-08-03', tag='test')
        records = json.loads(open(path, encoding='utf-8').read())

        assert len(records) == 1
        assert records[0]['home_odds'] == pytest.approx(1.57)
        assert records[0]['away_odds'] == pytest.approx(2.25)

    def test_a_priced_pick_is_no_longer_reported_as_unpriced(self, tmp_path, monkeypatch):
        """This is the condition the ROI denominator tests."""
        monkeypatch.chdir(tmp_path)
        rows = [
            base_row(match_url='u/1', odds={'home': 1.57, 'away': 2.25}),
            base_row(match_url='u/2'),
        ]

        path = en._save_mailed_manifest(rows, '2026-08-03', tag='test')
        records = json.loads(open(path, encoding='utf-8').read())

        priced = [r for r in records if r.get('home_odds') is not None]
        assert len(priced) == 1, 'the priced pick has to survive into the manifest'
