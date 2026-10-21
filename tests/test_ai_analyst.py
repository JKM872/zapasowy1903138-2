import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import ai_analyst as aa  # noqa: E402


def _cand(i):
    return {'sport': 'football', 'match': f'A{i} vs B{i}', 'pick': f'A{i}', 'odds': 2.1}


def _reply_for(prompt, verdict='GRAJ', conf=4, fence=False):
    data = json.loads(prompt[prompt.index('Kandydaci:\n') + len('Kandydaci:\n'):])
    out = json.dumps([{'key': c['key'], 'verdict': verdict, 'confidence': conf,
                       'reason': 'Forma sezonu dobra.', 'risks': ['kontuzje']} for c in data],
                     ensure_ascii=False)
    return f"Oto wynik:\n```json\n{out}\n```\nkoniec" if fence else out


def test_parse_fenced_and_garbage():
    assert aa.parse_json_list('```json\n[{"key": "x"}]\n```') == [{'key': 'x'}]
    assert aa.parse_json_list('blah [{"key": "y"}] trailing') == [{'key': 'y'}]
    assert aa.parse_json_list('totally not json') == []
    assert aa.parse_json_list(None) == []


def test_normalise_filters_and_clamps():
    out = aa._normalise([{'key': 'k', 'verdict': 'odpusc', 'confidence': 9, 'risks': 'x'},
                         {'key': 'k2', 'verdict': 'GRAJ'},
                         {'key': 'k', 'verdict': 'MAYBE'}], {'k'})
    assert out == [{'key': 'k', 'verdict': 'ODPUŚĆ', 'confidence': 5, 'reason': '', 'risks': ['x']}]


def test_batching(monkeypatch):
    calls = []

    def fake(prompt, **kw):
        calls.append(prompt)
        return _reply_for(prompt, fence=True)
    monkeypatch.setattr(aa, '_chat', fake)
    monkeypatch.setattr(aa, 'BATCH', 25)
    res = aa.analyse([_cand(i) for i in range(60)], '2026-10-21')
    assert len(calls) == 3
    assert len(res) == 60 and all(r['verdict'] == 'GRAJ' for r in res)
    assert res[0]['match'] == 'A0 vs B0'


def test_failure_returns_empty(monkeypatch):
    def boom(prompt, **kw):
        raise RuntimeError('net')
    monkeypatch.setattr(aa, '_chat', boom)
    assert aa.analyse([_cand(1)], 'd') == []
    monkeypatch.setattr(aa, '_chat', lambda p, **kw: None)
    assert aa.analyse([_cand(1)], 'd') == []
    assert aa.analyse([], 'd') == []


def test_final_model_4xx_skipped(monkeypatch):
    monkeypatch.setattr(aa, '_chat', lambda p, **kw: _reply_for(p))
    monkeypatch.setenv('AI_ANALYST_FINAL_MODEL', 'gemini-4-argon')
    monkeypatch.setenv('GEMINI_API_KEYS', 'k1')
    import requests

    class R:
        status_code = 403
    monkeypatch.setattr(requests, 'post', lambda *a, **k: R())
    res = aa.analyse([_cand(1), _cand(2)], 'd')
    assert len(res) == 2


def test_ordering_and_html():
    res = [{'key': '1', 'verdict': 'ODPUŚĆ', 'confidence': 5, 'match': 'X vs Y', 'pick': 'X',
            'odds': 2.0, 'reason': 'r', 'risks': []},
           {'key': '2', 'verdict': 'GRAJ', 'confidence': 2, 'match': 'C vs D', 'pick': 'C',
            'odds': 1.9, 'reason': 'r', 'risks': ['ryzyko']},
           {'key': '3', 'verdict': 'GRAJ', 'confidence': 5, 'match': 'E vs F', 'pick': 'E',
            'odds': 2.5, 'reason': 'r', 'risks': []},
           {'key': '4', 'verdict': 'OBSERWUJ', 'confidence': 3, 'match': 'G vs H', 'pick': 'G',
            'odds': 3.0, 'reason': 'r', 'risks': []}]
    assert [r['key'] for r in aa.ordered(res)] == ['3', '2', '4', '1']
    html = aa.html_section(res)
    assert '🧠 Analityk AI' in html and '#1e8e3e' in html and '#d93025' in html
    assert html.index('E vs F') < html.index('C vs D') < html.index('G vs H') < html.index('X vs Y')
    assert 'E @ 2.50' in html and '★★★★★' in html and 'ryzyko' in html
    assert aa.html_section([]) == ''


def test_emails_put_section_on_top(monkeypatch):
    sent = {}

    class S:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, f, t, msg): sent['msg'] = msg
    import smtplib
    monkeypatch.setattr(smtplib, 'SMTP', S)
    for k in ('EMAIL_RECIPIENT', 'EMAIL_SENDER', 'EMAIL_PASSWORD'):
        monkeypatch.setenv(k, 'x@y.z')
    res = [{'key': 'k', 'verdict': 'GRAJ', 'confidence': 4, 'match': 'Q vs W', 'pick': 'Q',
            'odds': 2.2, 'reason': 'ok', 'risks': []}]
    from tools import top_picks
    pick = {'time': '18:00', 'sport': 'football', 'match': 'Q vs W', 'league': 'L', 'pick': 'Q',
            'odds': 2.2, 'grade': 'A', 'score': 60, 'form': 'WWW', 'h2h': 'brak',
            'fanvote': 'brak', 'signals': '3/3 za'}
    top_picks.send_email([pick], '2026-10-21', analyst=res)
    import email
    body = email.message_from_string(sent['msg']).get_payload()[0].get_payload(decode=True).decode()
    assert body.index('Analityk AI') < body.index('TOP —')
