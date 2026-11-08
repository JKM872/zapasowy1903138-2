import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import fan_favourites_email as fe  # noqa: E402

DAY = '2026-11-01'


def _p(i, sport, pct, votes=200, ko='2026-11-01T18:00:00Z', status='pick', **kw):
    return {'id': f'{sport}|{DAY}|H{i}|A{i}', 'sport': sport, 'date': DAY, 'kickoff': ko,
            'match': f'H{i} vs A{i}', 'team': f'A{i}', 'side': 'away', 'fanPct': pct, 'votes': votes,
            'status': status, 'odds': {'home': 3.0, 'draw': 3.2, 'away': 2.0},
            'bestPrice': {'price': 2.1, 'bookmaker': 'Pinnacle'}, 'limit': {'min': 1.5},
            'form': {'overall': 'WWL'}, 'h2h': {}, 'forebet': {}, 'grade': 'B', **kw}


def _board(tmp, picks):
    (tmp / 'results').mkdir(exist_ok=True)
    (tmp / 'outputs').mkdir(exist_ok=True)
    (tmp / 'results' / f'fanvote_{DAY}.json').write_text(json.dumps(
        {'day': DAY, 'thresholds': {'minVotes': 100},
         'sports': {'football': {'picks': [p for p in picks if p['sport'] == 'football'], 'watch': True,
                                 'stats': {'rows': 10, 'picks': 2}},
                    'hockey': {'picks': [p for p in picks if p['sport'] == 'hockey']}}}), encoding='utf-8')


def test_select_skips_ledger_and_started():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    b = {'sports': {'football': {'picks': [_p(1, 'football', 70), _p(2, 'football', 80, ko='2026-11-01T10:00:00Z'),
                                           _p(3, 'football', 65)]}}}
    out = fe.select_new(b, {f'football|{DAY}|H3|A3'}, now)
    assert [p['team'] for p in out] == ['A1']


def test_html_sorted_escaped_football_first():
    picks = [_p(1, 'hockey', 90), _p(2, 'hockey', 75), _p(3, 'football', 61, team='<b>X</b>')]
    h = fe.build_html(picks, [DAY], {})
    assert h.index('Piłka nożna') < h.index('Hokej')
    assert h.index('A1') < h.index('A2') and '&lt;b&gt;X&lt;/b&gt;' in h


def test_nothing_new_no_send_and_failed_send_keeps_ledger(tmp_path, monkeypatch):
    _board(tmp_path, [_p(1, 'football', 70, ko='2099-01-01T00:00:00Z')])
    calls = []
    monkeypatch.setattr(fe, 'send', lambda *a, **k: calls.append(a) or False)
    args = ['--day', DAY, '--days', '1', '--results', str(tmp_path / 'results'),
            '--outputs', str(tmp_path / 'outputs'), '--to', 't', '--from-email', 'f', '--password', 'p']
    assert fe.main(args) == 1 and len(calls) == 1
    assert fe.load_ledger(fe.ledger_path(DAY, str(tmp_path / 'outputs'))) == set()
    monkeypatch.setattr(fe, 'send', lambda *a, **k: calls.append(a) or True)
    assert fe.main(args) == 0
    assert fe.load_ledger(fe.ledger_path(DAY, str(tmp_path / 'outputs'))) == {f'football|{DAY}|H1|A1'}
    n = len(calls)
    assert fe.main(args) == 0 and len(calls) == n          # nothing new -> no send
    assert fe.main(args + ['--force']) == 0 and 'ręczna' in calls[-1][1]
