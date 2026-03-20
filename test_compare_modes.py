# pyright: reportPrivateUsage=false, reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
"""
Tests for compare_modes.py — home vs away cohort comparison.

Covers:
 - Date range generation
 - Cohort splitting by focus_team
 - Cohort statistics (accuracy, ROI, per-sport)
 - Report rendering
 - Summary loading integration
 - Full compare() pipeline
"""
import json
import os

import pytest

from compare_modes import (
    _dates_in_range,
    split_by_focus,
    _cohort_stats,
    render_report,
    load_summaries,
    compare,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _m(outcome='won', focus_team='home', sport='football',
       predicted='home', home_odds=1.80, away_odds=2.10):
    """Minimal match dict compatible with _cohort_stats."""
    return {
        'home': 'TeamA', 'away': 'TeamB',
        'sport': sport, 'predicted': predicted,
        'focus_team': focus_team,
        'home_odds': home_odds, 'away_odds': away_odds,
        'outcome': outcome,
    }


# ---------------------------------------------------------------------------
# _dates_in_range
# ---------------------------------------------------------------------------

class TestDatesInRange:
    def test_single_day(self):
        assert _dates_in_range('2026-03-01', '2026-03-01') == ['2026-03-01']

    def test_three_days(self):
        result = _dates_in_range('2026-03-01', '2026-03-03')
        assert result == ['2026-03-01', '2026-03-02', '2026-03-03']

    def test_end_before_start(self):
        assert _dates_in_range('2026-03-05', '2026-03-01') == []


# ---------------------------------------------------------------------------
# split_by_focus
# ---------------------------------------------------------------------------

class TestSplitByFocus:
    def test_empty(self):
        cohorts = split_by_focus([])
        assert cohorts == {'home': [], 'away': []}

    def test_mixed(self):
        matches = [
            _m(focus_team='home'),
            _m(focus_team='away'),
            _m(focus_team='home'),
        ]
        cohorts = split_by_focus(matches)
        assert len(cohorts['home']) == 2
        assert len(cohorts['away']) == 1

    def test_missing_focus_defaults_home(self):
        m = _m()
        del m['focus_team']
        cohorts = split_by_focus([m])
        assert len(cohorts['home']) == 1


# ---------------------------------------------------------------------------
# _cohort_stats
# ---------------------------------------------------------------------------

class TestCohortStats:
    def test_empty(self):
        s = _cohort_stats([])
        assert s['total'] == 0
        assert s['accuracy'] == 0.0
        assert s['roi_pln'] == 0.0

    def test_all_won(self):
        matches = [_m(outcome='won', home_odds=2.00)] * 3
        s = _cohort_stats(matches)
        assert s['won'] == 3
        assert s['lost'] == 0
        assert s['accuracy'] == 100.0
        assert s['roi_pln'] == 300.0  # 3 * (2.0*100 - 100)

    def test_all_lost(self):
        matches = [_m(outcome='lost')] * 2
        s = _cohort_stats(matches)
        assert s['won'] == 0
        assert s['lost'] == 2
        assert s['accuracy'] == 0.0
        assert s['roi_pln'] == -200.0

    def test_mixed_outcomes(self):
        matches = [
            _m(outcome='won', home_odds=1.80),
            _m(outcome='lost', home_odds=1.80),
            _m(outcome='draw'),
        ]
        s = _cohort_stats(matches)
        assert s['won'] == 1
        assert s['lost'] == 1
        assert s['draw'] == 1
        assert s['decided'] == 2
        assert s['accuracy'] == 50.0

    def test_away_predicted_uses_away_odds(self):
        m = _m(outcome='won', focus_team='away', predicted='away',
               home_odds=1.50, away_odds=3.00)
        s = _cohort_stats([m])
        # Won at 3.00 → profit = 3.0 * 100 - 100 = 200
        assert s['roi_pln'] == 200.0

    def test_pending_excluded_from_accuracy(self):
        matches = [
            _m(outcome='won', home_odds=2.00),
            _m(outcome='pending'),
        ]
        s = _cohort_stats(matches)
        assert s['decided'] == 1
        assert s['accuracy'] == 100.0
        assert s['pending'] == 1

    def test_per_sport(self):
        matches = [
            _m(outcome='won', sport='football'),
            _m(outcome='lost', sport='basketball'),
            _m(outcome='won', sport='football'),
        ]
        s = _cohort_stats(matches)
        assert s['by_sport']['football']['won'] == 2
        assert s['by_sport']['basketball']['lost'] == 1

    def test_missing_odds_skipped_in_roi(self):
        m = _m(outcome='won')
        m['home_odds'] = None
        s = _cohort_stats([m])
        assert s['won'] == 1
        assert s['roi_pln'] == 0.0  # no odds → no ROI contribution

    def test_nan_odds_skipped(self):
        m = _m(outcome='won')
        m['home_odds'] = float('nan')
        s = _cohort_stats([m])
        assert s['roi_pln'] == 0.0


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_contains_header(self):
        empty = _cohort_stats([])
        report = render_report(empty, empty, empty, '2026-03-01', '2026-03-07')
        assert 'HOME vs AWAY' in report
        assert '2026-03-01' in report
        assert '2026-03-07' in report

    def test_shows_accuracy(self):
        home = _cohort_stats([_m(outcome='won', home_odds=2.0)])
        away = _cohort_stats([_m(outcome='lost')])
        combined = _cohort_stats([_m(outcome='won', home_odds=2.0), _m(outcome='lost')])
        report = render_report(home, away, combined, '2026-03-01', '2026-03-01')
        assert '100.0%' in report  # home accuracy
        assert '0.0%' in report    # away accuracy

    def test_per_sport_section(self):
        home = _cohort_stats([_m(outcome='won', sport='tennis')])
        away = _cohort_stats([_m(outcome='lost', sport='tennis')])
        combined = _cohort_stats([
            _m(outcome='won', sport='tennis'),
            _m(outcome='lost', sport='tennis'),
        ])
        report = render_report(home, away, combined, '2026-03-01', '2026-03-01')
        assert 'PER SPORT' in report
        assert 'tennis' in report


# ---------------------------------------------------------------------------
# load_summaries (integration with file system)
# ---------------------------------------------------------------------------

class TestLoadSummaries:
    def test_loads_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        summary = {
            'won': 1, 'lost': 0,
            'matches': [
                {
                    'home': 'A', 'away': 'B', 'sport': 'football',
                    'predicted': 'home', 'focus_team': 'home',
                    'home_odds': 1.80, 'away_odds': 2.10,
                    'score': '2-1', 'outcome': 'won',
                },
            ],
        }
        with open('outputs/results_summary_2026-03-01.json', 'w') as f:
            json.dump(summary, f)

        matches = load_summaries('2026-03-01', '2026-03-01')
        assert len(matches) == 1
        assert matches[0]['focus_team'] == 'home'
        assert matches[0]['date'] == '2026-03-01'

    def test_empty_range(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert load_summaries('2099-01-01', '2099-01-01') == []


# ---------------------------------------------------------------------------
# compare (full pipeline)
# ---------------------------------------------------------------------------

class TestCompare:
    def test_no_data(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        h, a, c, report = compare('2099-01-01', '2099-01-01')
        assert h['total'] == 0
        assert 'Brak danych' in report

    def test_home_vs_away_split(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        summary = {
            'matches': [
                {
                    'home': 'A', 'away': 'B', 'sport': 'football',
                    'predicted': 'home', 'focus_team': 'home',
                    'home_odds': 2.00, 'away_odds': 3.00,
                    'score': '2-1', 'outcome': 'won',
                },
                {
                    'home': 'C', 'away': 'D', 'sport': 'football',
                    'predicted': 'away', 'focus_team': 'away',
                    'home_odds': 2.00, 'away_odds': 2.50,
                    'score': '1-2', 'outcome': 'won',
                },
                {
                    'home': 'E', 'away': 'F', 'sport': 'football',
                    'predicted': 'away', 'focus_team': 'away',
                    'home_odds': 1.60, 'away_odds': 2.80,
                    'score': '2-0', 'outcome': 'lost',
                },
            ],
        }
        with open('outputs/results_summary_2026-03-01.json', 'w') as f:
            json.dump(summary, f)

        home, away, combined, report = compare('2026-03-01', '2026-03-01')
        assert home['total'] == 1
        assert home['won'] == 1
        assert home['accuracy'] == 100.0

        assert away['total'] == 2
        assert away['won'] == 1
        assert away['lost'] == 1
        assert away['accuracy'] == 50.0

        assert combined['total'] == 3
        assert 'HOME vs AWAY' in report

    def test_fallback_to_manifests(self, tmp_path, monkeypatch):
        """When no summaries exist, falls back to manifest files (all pending)."""
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs')
        manifest = [
            {
                'match_url': 'https://example.com/m1',
                'sport': 'football', 'focus_team': 'home',
                'home_team': 'X', 'away_team': 'Y',
                'home_odds': 1.90, 'away_odds': 2.00,
            },
        ]
        with open('outputs/mailed_manifest_2026-03-01.json', 'w') as f:
            json.dump(manifest, f)

        home, away, combined, report = compare('2026-03-01', '2026-03-01')
        assert combined['total'] == 1
        assert combined['pending'] == 1


# ---------------------------------------------------------------------------
# check_results.evaluate — focus_team now in details
# ---------------------------------------------------------------------------

class TestEvaluateFocusTeam:
    """Verify that evaluate() passes focus_team through to details."""

    def test_focus_team_in_detail(self):
        from check_results import evaluate
        m = {
            'match_url': 'https://example.com/ft1',
            'sport': 'football',
            'home_team': 'A', 'away_team': 'B',
            'home_odds': 1.80, 'away_odds': 2.10,
            'focus_team': 'away',
        }
        results = {'https://example.com/ft1': {'status': 'finished', 'score_home': 0, 'score_away': 1, 'winner': 'away'}}
        stats = evaluate([m], results)
        detail = stats['details'][0]
        assert detail['focus_team'] == 'away'
        assert detail['outcome'] == 'won'

    def test_focus_team_defaults_home(self):
        from check_results import evaluate
        m = {
            'match_url': 'https://example.com/ft2',
            'sport': 'football',
            'home_team': 'A', 'away_team': 'B',
            'home_odds': 1.80, 'away_odds': 2.10,
        }
        results = {'https://example.com/ft2': {'status': 'finished', 'score_home': 2, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate([m], results)
        assert stats['details'][0]['focus_team'] == 'home'
