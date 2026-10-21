import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import watchdog as W  # noqa: E402

TS = '2026-10-21T06:01:02.1234567Z '


def codes(issues):
    return sorted(i['code'] for i in issues)


def test_forebet_low_per_sport():
    log = (TS + '   📋 Forebet football 2026-10-21: 0 meczów (HTML=0, getrs.php dodało=0, ...\n'
           + TS + '   📋 Forebet basketball 2026-10-21: 3 meczów (HTML=3, ...\n'
           + TS + '   📋 Forebet hockey 2026-10-21: 80 meczów (HTML=80, ...\n'
           + TS + '   📋 Forebet tennis 2026-10-21: 19 meczów (HTML=19, ...\n')
    issues = W.parse_log(log, 'scrape_forebet.yml')
    assert [i['sport'] for i in issues] == ['football', 'basketball', 'tennis']
    assert all(i['level'] == W.ALERT for i in issues)


def test_forebet_ok():
    log = TS + '   📋 Forebet football 2026-10-21: 350 meczów (HTML=340, ...'
    assert W.parse_log(log, 'x') == []


def test_fanvote_zero_alert_and_threshold():
    log = TS + '   🗳️ Fan Vote: 0/45 z głosami | bez głosowania: 0'
    assert codes(W.parse_log(log, 'x')) == ['fanvote_zero']
    assert W.parse_log(TS + '   🗳️ Fan Vote: 0/10 z głosami', 'x') == []
    assert W.parse_log(TS + '   🗳️ Fan Vote: 5/45 z głosami', 'x') == []
    assert codes(W.parse_log('SofaScore Fan Vote: 0 found / 30 not_found', 'x')) == ['fanvote_zero']


def test_warn_rules_and_traceback():
    log = '\n'.join([
        TS + '   ⚠️ Przekaźnik SofaScore #1: dzienny limit Google wyczerpany',
        TS + 'Exception: Service invoked too many times for one day',
        TS + '   🚫 SofaScore zablokowany dla IP runnera (sonda 403)',
        TS + '   ⏳ Czas wyczerpany (5.90 h, limit z X)',
        TS + 'Traceback (most recent call last):',
    ])
    issues = W.parse_log(log, 'x')
    assert codes(issues) == ['budget', 'relay_quota', 'sofa_blocked', 'traceback']
    lv = {i['code']: i['level'] for i in issues}
    assert lv['traceback'] == W.ALERT and lv['relay_quota'] == W.WARN


def test_scheduled_today(tmp_path):
    p = tmp_path / 'w.yml'
    p.write_text("on:\n  schedule:\n    - cron: '0 6 * * *'\n", encoding='utf-8')
    day = '2026-10-21'
    assert W.scheduled_today(p, day, dt.datetime(2026, 10, 21, 9, 30))
    assert not W.scheduled_today(p, day, dt.datetime(2026, 10, 21, 6, 30))
    assert not W.scheduled_today(tmp_path / 'none.yml', day, dt.datetime(2026, 10, 21, 9))


def _fake_gh(runs, jobs, logs):
    def fake(args):
        if args[0] == 'run':
            return json.dumps(runs.get(args[args.index('--workflow') + 1], []))
        path = args[-1]
        if path.endswith('/logs'):
            return logs.get(int(path.split('/')[-2]), '')
        return json.dumps({'jobs': jobs})
    return fake


def test_run_end_to_end(monkeypatch, tmp_path):
    day = '2026-10-21'
    runs = {'scrape_forebet.yml': [{'databaseId': 1, 'createdAt': day + 'T06:00:00Z',
                                    'status': 'completed', 'conclusion': 'success', 'url': 'u'}]}
    jobs = [{'id': 11, 'name': 'scrape (basketball)', 'status': 'completed', 'conclusion': 'success',
             'html_url': 'h', 'steps': []},
            {'id': 12, 'name': 'scrape (football)', 'status': 'completed', 'conclusion': 'failure',
             'html_url': 'h', 'steps': [{'name': 'Run', 'conclusion': 'failure'}]}]
    logs = {11: TS + 'Forebet basketball 2026-10-21: 3 meczów (HTML=3,', 12: ''}
    monkeypatch.setattr(W, 'gh', _fake_gh(runs, jobs, logs))
    monkeypatch.setattr(W, 'ROOT', tmp_path)
    monkeypatch.setattr(W, 'scheduled_today', lambda p, d, n: p.name == 'scrape.yml')
    monkeypatch.setenv('SOFASCORE_RELAY', 'https://a,https://b')
    monkeypatch.setattr(W, 'probe_relays', lambda r: [
        {'relay': 1, 'status': 200, 'exhausted': False, 'ok': True},
        {'relay': 2, 'status': 200, 'exhausted': True, 'ok': False}])
    sent = []
    monkeypatch.setattr(W, 'send_email', lambda issues, d: sent.append(len(issues)))
    rep = W.run(day, 'o/r', email=True, now=dt.datetime(2026, 10, 21, 9, 30, tzinfo=dt.timezone.utc))
    assert codes(rep['issues']) == ['forebet_low', 'job_failed', 'no_run', 'relay_dead']
    assert sent == [4]
    assert json.loads((tmp_path / 'results' / f'watchdog_{day}.json').read_text(encoding='utf-8'))['counts']


def test_run_all_ok_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(W, 'gh', lambda a: '[]' if a[0] == 'run' else '{}')
    monkeypatch.setattr(W, 'ROOT', tmp_path)
    monkeypatch.delenv('SOFASCORE_RELAY', raising=False)
    sent = []
    monkeypatch.setattr(W, 'send_email', lambda i, d: sent.append(1))
    rep = W.run('2026-10-21', 'o/r', email=True)
    assert rep['issues'] == [] and sent == []


def test_probe_relays_detects_quota(monkeypatch):
    import requests

    class R:
        def __init__(self, t):
            self.status_code, self.text = 200, t
    monkeypatch.setattr(requests, 'get', lambda url, timeout: R(
        '<html>Usługa została wywołana zbyt wiele razy</html>' if 'bad' in url else '{"categories":[]}'))
    res = W.probe_relays(['https://ok', 'https://bad'])
    assert [r['ok'] for r in res] == [True, False] and res[1]['exhausted']


def test_html_table():
    html = W.build_html([W._issue(W.ALERT, 'wf', 'football', 'forebet_low', 'x<y')], '2026-10-21')
    assert 'Sugerowana akcja' in html and 'x&lt;y' in html
