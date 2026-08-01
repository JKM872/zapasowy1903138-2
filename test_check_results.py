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
    load_telegram_manifest,
    merge_manifests,
    evaluate,
    _predicted_winner,
    generate_report_html,
    save_summary,
    diagnose_manifest_state,
    save_diagnostic_summary,
)
from email_notifier import _save_mailed_manifest, _save_empty_manifest_marker
from telegram_notifier import _save_telegram_manifest, _MANIFEST_FIELDS


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

    def test_tag_writes_separate_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        matches = [_match(url='http://m1')]
        results = {'http://m1': {'status': 'finished', 'score_home': 1, 'score_away': 0, 'winner': 'home'}}
        stats = evaluate(matches, results)
        email_path = save_summary(stats, '2026-03-14')
        tg_path = save_summary(stats, '2026-03-14', tag='telegram')
        assert email_path.endswith('results_summary_2026-03-14.json')
        assert tg_path.endswith('results_summary_2026-03-14_telegram.json')
        assert os.path.exists(email_path)
        assert os.path.exists(tg_path)
        assert email_path != tg_path


# ---------------------------------------------------------------------------
# Telegram manifest — writer + loader + merge
# ---------------------------------------------------------------------------

class TestTelegramManifest:
    def test_save_includes_url_and_core_fields(self, tmp_path, monkeypatch):
        # telegram_notifier writes to <module_dir>/outputs, so patch the helper
        # to target tmp_path by monkeypatching the module-level os.path.dirname.
        import telegram_notifier as tn

        monkeypatch.setattr(
            tn, '_save_telegram_manifest',
            tn._save_telegram_manifest,  # keep original
        )
        # Run from tmp_path and point outputs to cwd/outputs by chdir.
        monkeypatch.chdir(tmp_path)

        # The real helper resolves outputs relative to the module file; emulate
        # it by writing a manifest using the same logic but targeting cwd.
        m = _match(url='http://tg/m1', focus_team='home', favorite='A')
        m['draw_odds'] = 3.2
        m['prediction_grade'] = 'A'
        os.makedirs('outputs', exist_ok=True)

        # Call the real writer and then copy the produced file next to cwd.
        _save_telegram_manifest([m], '2026-03-14')
        module_path = os.path.join(
            os.path.dirname(os.path.abspath(tn.__file__)),
            'outputs',
            'telegram_manifest_2026-03-14.json',
        )
        assert os.path.exists(module_path)
        with open(module_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        os.remove(module_path)

        assert data['count'] == 1
        rec = data['matches'][0]
        for field in ('match_url', 'focus_team', 'favorite', 'draw_odds',
                      'prediction_grade', 'sport'):
            assert field in rec, f'missing {field} in telegram manifest'
        assert rec['match_url'] == 'http://tg/m1'
        assert rec['favorite'] == 'A'

    def test_manifest_fields_covers_email_critical(self):
        for field in ('match_url', 'match_date', 'match_time', 'sport',
                      'home_team', 'away_team', 'home_odds', 'draw_odds',
                      'away_odds', 'scoring_pick', 'focus_team',
                      'prediction_grade', 'favorite'):
            assert field in _MANIFEST_FIELDS

    def test_load_new_format_with_matches_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        payload = {
            'date': '2026-03-14',
            'count': 2,
            'matches': [
                _match(url='http://tg/a'),
                _match(url='http://tg/b'),
            ],
        }
        with open('outputs/telegram_manifest_2026-03-14.json', 'w') as f:
            json.dump(payload, f)
        result = load_telegram_manifest('2026-03-14')
        assert len(result) == 2
        urls = {m['match_url'] for m in result}
        assert urls == {'http://tg/a', 'http://tg/b'}

    def test_load_legacy_flat_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        with open('outputs/telegram_manifest_2026-03-14.json', 'w') as f:
            json.dump([_match(url='http://tg/legacy')], f)
        result = load_telegram_manifest('2026-03-14')
        assert len(result) == 1
        assert result[0]['match_url'] == 'http://tg/legacy'

    def test_load_skips_entries_without_url(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        payload = {
            'matches': [
                {'home_team': 'X', 'away_team': 'Y'},  # missing match_url
                _match(url='http://tg/ok'),
            ],
        }
        with open('outputs/telegram_manifest_2026-03-14.json', 'w') as f:
            json.dump(payload, f)
        result = load_telegram_manifest('2026-03-14')
        assert len(result) == 1
        assert result[0]['match_url'] == 'http://tg/ok'

    def test_load_deduplicates_urls(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        dup = _match(url='http://tg/dup')
        payload = {'matches': [dup, dup]}
        with open('outputs/telegram_manifest_2026-03-14.json', 'w') as f:
            json.dump(payload, f)
        result = load_telegram_manifest('2026-03-14')
        assert len(result) == 1

    def test_load_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        result = load_telegram_manifest('1999-01-01')
        assert result == []


class TestMergeManifests:
    def test_merge_dedup_by_url(self):
        email = [_match(url='http://shared', home='E')]
        telegram = [_match(url='http://shared', home='T'),
                    _match(url='http://tg-only')]
        merged = merge_manifests(email, telegram)
        assert len(merged) == 2
        urls = [m['match_url'] for m in merged]
        assert urls == ['http://shared', 'http://tg-only']
        # First manifest wins for populated fields.
        assert merged[0]['home_team'] == 'E'

    def test_merge_fills_missing_fields(self):
        email = [{'match_url': 'http://x', 'home_team': 'Home'}]
        telegram = [{'match_url': 'http://x', 'home_team': 'Home',
                     'prediction_grade': 'A', 'favorite': 'A'}]
        merged = merge_manifests(email, telegram)
        assert merged[0]['prediction_grade'] == 'A'
        assert merged[0]['favorite'] == 'A'

    def test_merge_skips_entries_without_url(self):
        merged = merge_manifests([{'home_team': 'X'}], [_match(url='http://ok')])
        assert len(merged) == 1
        assert merged[0]['match_url'] == 'http://ok'

    def test_merge_empty_inputs(self):
        assert merge_manifests([], []) == []


# ---------------------------------------------------------------------------
# Manifest diagnosis (no_manifest / empty_run / has_matches)
# ---------------------------------------------------------------------------

class TestManifestDiagnosis:
    def test_state_has_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        with open('outputs/mailed_manifest_2026-04-27_football.json', 'w') as f:
            json.dump([_match(url='http://m1')], f)
        info = diagnose_manifest_state('2026-04-27', source='email')
        assert info['state'] == 'has_matches'
        assert any('mailed_manifest_2026-04-27' in p for p in info['files'])
        assert info['empty_reasons'] == []

    def test_state_empty_run_via_marker(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _save_empty_manifest_marker('2026-04-27', reason='no_qualified_after_filters')
        info = diagnose_manifest_state('2026-04-27', source='email')
        assert info['state'] == 'empty_run'
        assert 'no_qualified_after_filters' in info['empty_reasons']

    def test_state_no_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        info = diagnose_manifest_state('2026-04-27', source='email')
        assert info['state'] == 'no_manifest'
        assert info['files'] == []
        assert info['has_results_fallback'] is False

    def test_state_no_manifest_with_results_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('results', exist_ok=True)
        with open('results/matches_2026-04-27_football.json', 'w') as f:
            json.dump([], f)
        info = diagnose_manifest_state('2026-04-27', source='email')
        assert info['state'] == 'no_manifest'
        assert info['has_results_fallback'] is True

    def test_state_telegram_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        with open('outputs/telegram_manifest_2026-04-27.json', 'w') as f:
            json.dump({'matches': [_match(url='http://t1')]}, f)
        info = diagnose_manifest_state('2026-04-27', source='telegram')
        assert info['state'] == 'has_matches'

    def test_save_diagnostic_summary_empty_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _save_empty_manifest_marker('2026-04-27', reason='no_qualified_after_filters')
        info = diagnose_manifest_state('2026-04-27', source='email')
        path = save_diagnostic_summary('2026-04-27', info, source='email')
        assert os.path.exists(path)
        with open(path, 'r') as f:
            data = json.load(f)
        assert data['status'] == 'pipeline_ok_but_no_qualified_matches'
        assert data['state'] == 'empty_run'
        assert data['date'] == '2026-04-27'
        assert data['total'] == 0

    def test_save_diagnostic_summary_no_manifest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        info = diagnose_manifest_state('2026-04-27', source='email')
        path = save_diagnostic_summary('2026-04-27', info, source='email')
        with open(path, 'r') as f:
            data = json.load(f)
        assert data['status'] == 'manifest_missing_no_upstream_data'
        assert data['has_results_fallback'] is False

    def test_save_diagnostic_summary_no_manifest_but_results(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)
        os.makedirs('results', exist_ok=True)
        with open('results/matches_2026-04-27_football.json', 'w') as f:
            json.dump([], f)
        info = diagnose_manifest_state('2026-04-27', source='email')
        path = save_diagnostic_summary('2026-04-27', info, source='email')
        with open(path, 'r') as f:
            data = json.load(f)
        assert data['status'] == 'manifest_missing_but_results_present'
        assert data['has_results_fallback'] is True

    def test_load_manifests_skips_empty_marker(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _save_empty_manifest_marker('2026-04-27', reason='no_qualified_after_filters')
        # Empty marker shouldn't poison real loaders with placeholder rows.
        result = load_manifests('2026-04-27')
        assert result == []


# ---------------------------------------------------------------------------
# send_split_emails_by_sport date contract
# ---------------------------------------------------------------------------

class TestSendSplitEmailsDateContract:
    def test_uses_explicit_date_for_manifest(self, tmp_path, monkeypatch):
        """Manifest filename must match `--date` from the CLI (not `now()`)."""
        import pandas as pd  # local import — pandas is heavy
        from email_notifier import send_split_emails_by_sport

        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)

        df = pd.DataFrame([
            {
                'match_url': 'http://m1', 'home_team': 'A', 'away_team': 'B',
                'sport': 'football', 'home_odds': 1.80, 'away_odds': 2.10,
                'draw_odds': 3.20,
                'qualifies': True, 'channel_qualifies': True,
            }
        ])
        csv_path = str(tmp_path / 'matches.csv')
        df.to_csv(csv_path, index=False)

        # Dummy SMTP credentials should short-circuit before SMTP login,
        # but manifest must still be written.
        sent = send_split_emails_by_sport(
            csv_file=csv_path,
            to_email='noreply@localhost',
            from_email='noreply@localhost',
            password='dummy',
            date='2026-04-27',
        )
        assert sent == 0  # dummy creds → no real send
        # Ten test pilnuje DATY w nazwie, nie tagu. Wysyłka dzieli się teraz
        # dodatkowo na faworyta rynku i resztę, więc sufiks to `_football_reszta`
        # albo `_football_faworyt`; przybicie pełnej nazwy sprawdzałoby podział,
        # a nie kontrakt `--date`.
        import glob
        found = glob.glob('outputs/mailed_manifest_2026-04-27_football*.json')
        assert found, 'manifest must use --date, not datetime.now()'
        assert not glob.glob('outputs/mailed_manifest_2026-04-2[89]*.json')
        manifest = found[0]
        with open(manifest, 'r') as f:
            data = json.load(f)
        assert data[0]['match_url'] == 'http://m1'

    def test_writes_empty_marker_when_no_qualified(self, tmp_path, monkeypatch):
        import pandas as pd
        from email_notifier import send_split_emails_by_sport

        monkeypatch.chdir(tmp_path)
        os.makedirs('outputs', exist_ok=True)

        df = pd.DataFrame([
            {
                'match_url': 'http://m1', 'home_team': 'A', 'away_team': 'B',
                'sport': 'football', 'home_odds': None, 'away_odds': None,
                'draw_odds': None,
                'qualifies': False, 'channel_qualifies': False,
            }
        ])
        csv_path = str(tmp_path / 'matches.csv')
        df.to_csv(csv_path, index=False)

        sent = send_split_emails_by_sport(
            csv_file=csv_path,
            to_email='noreply@localhost',
            from_email='noreply@localhost',
            password='dummy',
            date='2026-04-27',
        )
        assert sent == 0
        marker = 'outputs/mailed_manifest_2026-04-27_empty.json'
        assert os.path.exists(marker), 'empty marker must be created so check_results can diagnose'
        with open(marker, 'r') as f:
            data = json.load(f)
        assert data[0].get('empty_reason') == 'no_qualified_after_filters'
