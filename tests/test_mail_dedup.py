import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import email_notifier  # noqa: E402

try:
    import undetected_chromedriver  # noqa: F401
except Exception:  # Python 3.12+ bez distutils — scraper nie jest tu potrzebny
    import types
    _uc = types.ModuleType('undetected_chromedriver')
    _uc.Chrome = type('Chrome', (), {'quit': lambda self: None})
    _uc.ChromeOptions = type('ChromeOptions', (), {})
    sys.modules['undetected_chromedriver'] = _uc
import forebet_pipeline as fp  # noqa: E402
import scrape_and_notify as san  # noqa: E402


class FakeSMTP:
    sent = []
    fail = False

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError('smtp down')
        FakeSMTP.sent.append(msg)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(email_notifier.smtplib, 'SMTP', FakeSMTP)
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    rows = [
        {'home_team': 'A', 'away_team': 'B', 'qualifies': True, 'email_qualifies': True,
         'home_odds': 1.8, 'away_odds': 2.1, 'sport': 'football', 'prediction_grade': 'A',
         'match_time': '18:00'},
        {'home_team': 'C', 'away_team': 'D', 'qualifies': True, 'email_qualifies': True,
         'home_odds': 1.9, 'away_odds': 2.0, 'sport': 'football', 'prediction_grade': 'B',
         'match_time': '19:00'},
    ]
    csv = tmp_path / 'f.csv'
    pd.DataFrame(rows).to_csv(csv, index=False)
    return str(csv)


def _send(csv, **kw):
    return email_notifier.send_email_notification(
        csv_file=csv, to_email='t@x', from_email='f@x', password='p',
        subject='s', date='2026-10-31', grade_filter={'A', 'B'},
        manifest_tag='forebet_football_AB', **kw)


def test_exclude_keys_and_sent_keys(env):
    keys = []
    assert _send(env, exclude_keys={'a|b'}, sent_keys_out=keys) is True
    assert keys == ['c|d']
    assert os.path.exists('outputs/mailed_manifest_2026-10-31_forebet_football_AB.json')


def test_all_excluded_sends_nothing(env):
    assert _send(env, exclude_keys={'a|b', 'c|d'}) is False
    assert FakeSMTP.sent == []


def test_smtp_error_returns_false(env):
    FakeSMTP.fail = True
    keys = []
    assert _send(env, sent_keys_out=keys) is False
    assert keys == []


def test_ledger_round_trip(tmp_path):
    p = fp.mail_ledger_path('football', '2026-10-31', str(tmp_path))
    assert fp.load_mail_ledger(p) == {}
    fp.save_mail_ledger(p, {'AB': ['a|b']})
    assert fp.load_mail_ledger(p) == {'AB': ['a|b']}


def test_second_run_sends_nothing(env):
    keys = []
    assert _send(env, sent_keys_out=keys) is True
    assert _send(env, exclude_keys=set(keys)) is False
    assert len(FakeSMTP.sent) == 1


def test_empty_result_keeps_existing_file(tmp_path):
    p = tmp_path / 'm.json'
    p.write_text(json.dumps({'matches': [{'x': 1}]}), encoding='utf-8')
    assert san.should_keep_existing_results(str(p), 0) is True
    assert san.should_keep_existing_results(str(p), 3) is False
    assert san.should_keep_existing_results(str(tmp_path / 'none.json'), 0) is False
