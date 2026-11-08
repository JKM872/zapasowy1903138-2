import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tools import top_picks as tp  # noqa: E402


def _pick(match, **kw):
    return {'time': '18:00', 'sport': 'football', 'match': match, 'league': 'L', 'pick': '1',
            'odds': 2.1, 'grade': 'A', 'score': 80, 'form': '', 'h2h': '', 'fanvote': '',
            'signals': '', **kw}


class _SMTP:
    sent = []
    fail = False

    def __init__(self, *a):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        if _SMTP.fail:
            raise OSError('smtp down')

    def sendmail(self, frm, to, msg):
        import email
        from email.header import decode_header, make_header
        m = email.message_from_string(msg)
        subj = str(make_header(decode_header(m['Subject'])))
        body = m.get_payload()[0].get_payload(decode=True).decode('utf-8')
        _SMTP.sent.append(subj + '\n' + body)


def _setup(tmp_path, monkeypatch, picks, sent=()):
    (tmp_path / 'results').mkdir()
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'results' / 'top_2026-11-01.json').write_text(json.dumps(picks), encoding='utf-8')
    if sent:
        (tmp_path / 'outputs' / 'top_mail_sent_2026-11-01.json').write_text(
            json.dumps({'sent': list(sent), 'statusMailSent': False}), encoding='utf-8')
    monkeypatch.setattr(tp, 'ROOT', str(tmp_path))
    monkeypatch.setattr(tp, 'run_analyst', lambda d, m: [])
    monkeypatch.setattr('smtplib.SMTP', _SMTP)
    for k in ('EMAIL_RECIPIENT', 'EMAIL_SENDER', 'EMAIL_PASSWORD'):
        monkeypatch.setenv(k, 'x@y')
    _SMTP.sent, _SMTP.fail = [], False


def test_only_new_picks_counted_and_ledger_updated(tmp_path, monkeypatch):
    a, b = _pick('A vs B'), _pick('C vs D')
    _setup(tmp_path, monkeypatch, [a, b], sent=[tp._key(a)])
    assert tp.mail_only('2026-11-01')
    assert len(_SMTP.sent) == 1 and 'nowe: 1' in _SMTP.sent[0]
    assert set(tp.load_ledger('2026-11-01')['sent']) == {tp._key(a), tp._key(b)}
    assert not tp.mail_only('2026-11-01')


def test_smtp_error_keeps_ledger(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [_pick('A vs B')])
    _SMTP.fail = True
    assert not tp.mail_only('2026-11-01')
    assert tp.load_ledger('2026-11-01')['sent'] == []


def test_force_email_and_withdrawn_marker(tmp_path, monkeypatch):
    a = _pick('A vs B')
    w = _pick('E vs F', withdrawn=True, withdrawReason='kontuzja')
    _setup(tmp_path, monkeypatch, [a, w], sent=[tp._key(a)])
    assert tp.mail_only('2026-11-01', force=True)
    body = _SMTP.sent[0]
    assert 'wysyłka ręczna' in body and '<s>' in body and 'Wycofany: kontuzja' in body
