import json
import sys
import types

import pytest

try:
    import forebet_pipeline as fp
except ImportError:  # undetected_chromedriver needs distutils (removed in 3.12+)
    uc = types.ModuleType('undetected_chromedriver')
    uc.Chrome = type('Chrome', (), {'quit': lambda self: None})
    uc.ChromeOptions = type('ChromeOptions', (), {})
    sys.modules['undetected_chromedriver'] = uc
    try:
        import forebet_pipeline as fp
    except Exception as e:
        pytest.skip(f'forebet_pipeline not importable: {e}', allow_module_level=True)


def test_write_outputs_carries_explicit_kickoff(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row = {'home_team': 'A', 'away_team': 'B', 'match_time': '20:00', 'kickoff_utc': '2026-10-26T18:00:00Z'}
    try:
        fp.write_outputs([row], 'football', '2026-10-26')
    except TypeError:
        fp.write_outputs([row], 'football', '2026-10-26', str(tmp_path))
    found = [json.load(open(p, encoding='utf-8')) for p in tmp_path.rglob('*.json')]
    ms = [m for d in found if isinstance(d, dict) for m in d.get('matches') or []]
    assert ms and ms[0]['kickoffUtc'] == '2026-10-26T18:00:00Z' and ms[0]['kickoffSource'] == 'pinnacle'


def test_write_outputs_carries_dated_form(tmp_path, monkeypatch):
    import forebet_pipeline as fp
    monkeypatch.chdir(tmp_path)
    row = {'home_team': 'A', 'away_team': 'B', 'match_time': '20:00',
           'home_form_dated': [{'date': '05.11.26', 'result': 'W', 'score': '2-1'}]}
    try:
        fp.write_outputs([row], 'football', '2026-10-26')
    except TypeError:
        fp.write_outputs([row], 'football', '2026-10-26', str(tmp_path))
    found = [json.load(open(p, encoding='utf-8')) for p in tmp_path.rglob('*.json')]
    ms = [m for d in found if isinstance(d, dict) for m in d.get('matches') or []]
    assert ms[0]['form']['homeDated'] == [{'date': '05.11.26', 'result': 'W', 'score': '2-1'}]
    assert ms[0]['form']['awayDated'] == []
