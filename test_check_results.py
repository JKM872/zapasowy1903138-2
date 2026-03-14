# pyright: reportPrivateUsage=false, reportMissingParameterType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
"""
Tests for check_results.py — result checker and accuracy report pipeline.

Covers:
 - Manifest loading and deduplication
 - Evaluation logic (won/lost/draw/pending/error + per-sport + ROI)
 - Predicted winner detection (team sports home/away, tennis)
 - Report HTML generation sanity checks
 - Summary save/load roundtrip
"""
import json
import os

from check_results import (
    load_manifests,
    evaluate,
    _predicted_winner,
    generate_report_html,
    save_summary,
)
from email_notifier import _save_mailed_manifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _match(url='https://example.com/m1', home='TeamA', away='TeamB',
           sport='football', home_odds=1.80, away_odds=2.10,
           focus_team=None, favorite=None, scoring_pick=None):
    m = {
        'match_url': url,
        'match_date': '2026-03-14',
        'match_time': '20:00',
        'sport': sport,
        'home_team': home,
        'away_team': away,
        'home_odds': home_odds,
        'away_odds': away_odds,
        'qualifies': True,
    }
    if focus_team:
        m['focus_team'] = focus_team
    if favorite:
        m['favorite'] = favorite
    if scoring_pick:
        m['scoring_pick'] = scoring_pick
    return m


# ---------------------------------------------------------------------------
# _predicted_winner
# ---------------------------------------------------------------------------

class TestPredictedWinner:
    def test_default_home(self):
        assert _predicted_winner(_match()) == 'home'

    def test_away_focus(self):
        assert _predicted_winner(_match(focus_team='away')) == 'away'

    def test_tennis_scoring_pick_1(self):
        assert _predicted_winner(_match(sport='tennis', scoring_pick='1')) == 'home'

    def test_tennis_scoring_pick_2(self):
        assert _predicted_winner(_match(sport='tennis', scoring_pick='2')) == 'away'

    def test_tennis_favorite_A(self):
        assert _predicted_winner(_match(sport='tennis', favorite='A')) == 'home'

    def test_tennis_favorite_B(self):
        assert _predicted_winner(_match(sport='tennis', favorite='B')) == 'away'


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

class TestEvaluate:
    def test_all_won(self):
        matches = [_match(url=f'http://m{i}') for i in range(3)]
        results = {
            f'http://m{i}': {'status': 'finished', 'score_home': 2, 'score_away': 1, 'winner': 'home'}
            for i in range(3)
        }
        stats = evaluate(matches, results)
        assert stats['total'] == 3
        assert stats['won'] == 3
        assert stats['lost'] == 0
        assert stats['accuracy'] == 100.0

    def test_all_lost(self):
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'finished', 'score_home': 0, 'score_away': 3, 'winner': 'away'}}
        stats = evaluate(matches, results)
        assert stats['won'] == 0
        assert stats['lost'] == 1
        assert stats['accuracy'] == 0.0

    def test_draw_excluded_from_accuracy(self):
        matches = [_match(url='http://m1'), _match(url='http://m2')]
        results = {
            'http://m1': {'status': 'finished', 'score_home': 2, 'score_away': 0, 'winner': 'home'},
            'http://m2': {'status': 'finished', 'score_home': 1, 'score_away': 1, 'winner': 'draw'},
        }
        stats = evaluate(matches, results)
        assert stats['won'] == 1
        assert stats['draw'] == 1
        assert stats['accuracy'] == 100.0  # draw excluded from denominator

    def test_pending_counted(self):
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'not_finished'}}
        stats = evaluate(matches, results)
        assert stats['pending'] == 1
        assert stats['finished'] == 0

    def test_error_counted(self):
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'error', 'error': 'timeout'}}
        stats = evaluate(matches, results)
        assert stats['errors'] == 1

    def test_per_sport_breakdown(self):
        matches = [
            _match(url='http://f1', sport='football'),
            _match(url='http://b1', sport='basketball'),
        ]
        results = {
            'http://f1': {'status': 'finished', 'score_home': 3, 'score_away': 0, 'winner': 'home'},
            'http://b1': {'status': 'finished', 'score_home': 80, 'score_away': 90, 'winner': 'away'},
        }
        stats = evaluate(matches, results)
        assert stats['by_sport']['football']['won'] == 1
        assert stats['by_sport']['basketball']['lost'] == 1

    def test_roi_positive_when_won(self):
        matches = [_match(url='http://m1', home_odds=2.0)]
        results = {'http://m1': {'status': 'finished', 'score_home': 1, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate(matches, results)
        assert stats['roi_pln'] == 100.0  # (2.0 * 100 - 100)
        assert stats['roi_pct'] == 100.0

    def test_roi_negative_when_lost(self):
        matches = [_match(url='http://m1', home_odds=1.50)]
        results = {'http://m1': {'status': 'finished', 'score_home': 0, 'score_away': 2, 'winner': 'away'}}
        stats = evaluate(matches, results)
        assert stats['roi_pln'] == -100.0

    def test_away_focus_won(self):
        matches = [_match(url='http://m1', focus_team='away', away_odds=2.50)]
        results = {'http://m1': {'status': 'finished', 'score_home': 0, 'score_away': 1, 'winner': 'away'}}
        stats = evaluate(matches, results)
        assert stats['won'] == 1
        assert stats['roi_pln'] == 150.0  # (2.50 * 100 - 100)

    def test_missing_url_in_results(self):
        matches = [_match(url='http://missing')]
        results = {}  # no results at all
        stats = evaluate(matches, results)
        assert stats['errors'] == 1

    def test_empty_matches(self):
        stats = evaluate([], {})
        assert stats['total'] == 0
        assert stats['accuracy'] == 0.0


# ---------------------------------------------------------------------------
# _save_mailed_manifest (from email_notifier)
# ---------------------------------------------------------------------------

class TestManifestSave:
    def test_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        matches = [_match()]
        path = _save_mailed_manifest(matches, '2026-03-14', tag='test')
        assert os.path.exists(path)
        with open(path, 'r') as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]['home_team'] == 'TeamA'

    def test_deduplicates_on_url(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        m = _match()
        _save_mailed_manifest([m], '2026-03-14', tag='dup')
        _save_mailed_manifest([m], '2026-03-14', tag='dup')  # same URL
        path = f'outputs/mailed_manifest_2026-03-14_dup.json'
        with open(path, 'r') as f:
            data = json.load(f)
        assert len(data) == 1  # not doubled

    def test_merges_different_urls(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        _save_mailed_manifest([_match(url='http://a')], '2026-03-14', tag='merge')
        _save_mailed_manifest([_match(url='http://b')], '2026-03-14', tag='merge')
        path = f'outputs/mailed_manifest_2026-03-14_merge.json'
        with open(path, 'r') as f:
            data = json.load(f)
        assert len(data) == 2

    def test_nan_converted_to_null(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        m = _match()
        m['home_odds'] = float('nan')
        _save_mailed_manifest([m], '2026-03-14', tag='nan')
        path = f'outputs/mailed_manifest_2026-03-14_nan.json'
        with open(path, 'r') as f:
            data = json.load(f)
        assert data[0]['home_odds'] is None


# ---------------------------------------------------------------------------
# load_manifests
# ---------------------------------------------------------------------------

class TestLoadManifests:
    def test_loads_multiple_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        for tag in ['football_form', 'football_normal']:
            with open(f'outputs/mailed_manifest_2026-03-14_{tag}.json', 'w') as f:
                json.dump([_match(url=f'http://{tag}')], f)
        result = load_manifests('2026-03-14')
        assert len(result) == 2

    def test_dedup_across_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        m = _match(url='http://same')
        for tag in ['a', 'b']:
            with open(f'outputs/mailed_manifest_2026-03-14_{tag}.json', 'w') as f:
                json.dump([m], f)
        result = load_manifests('2026-03-14')
        assert len(result) == 1

    def test_empty_date(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        result = load_manifests('1999-01-01')
        assert result == []


# ---------------------------------------------------------------------------
# generate_report_html
# ---------------------------------------------------------------------------

class TestReportHtml:
    def test_contains_key_sections(self):
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'finished', 'score_home': 2, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate(matches, results)
        html = generate_report_html(stats, '2026-03-14')
        assert 'RAPORT SKUTECZNOŚCI' in html
        assert '2026-03-14' in html
        assert 'TeamA vs TeamB' in html
        assert '✅' in html

    def test_pending_shown(self):
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'not_finished'}}
        stats = evaluate(matches, results)
        html = generate_report_html(stats, '2026-03-14')
        assert '⏳' in html
        assert 'PENDING' in html


# ---------------------------------------------------------------------------
# save_summary
# ---------------------------------------------------------------------------

class TestSaveSummary:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'finished', 'score_home': 1, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate(matches, results)
        path = save_summary(stats, '2026-03-14')
        assert os.path.exists(path)
        with open(path, 'r') as f:
            data = json.load(f)
        assert data['won'] == 1
        assert data['match_count'] == 1
        assert len(data['matches']) == 1

    def test_idempotent_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'finished', 'score_home': 1, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate(matches, results)
        save_summary(stats, '2026-03-14')
        save_summary(stats, '2026-03-14')  # second call overwrites without error
        with open('outputs/results_summary_2026-03-14.json', 'r') as f:
            data = json.load(f)
        assert data['match_count'] == 1
