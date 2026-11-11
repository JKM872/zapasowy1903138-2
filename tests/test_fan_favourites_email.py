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


def test_one_section_per_sport_with_counts_toc_and_order():
    picks = [_p(1, 'hockey', 90, ko='2026-11-01T20:00:00Z'), _p(2, 'hockey', 75, ko='2026-11-01T17:00:00Z'),
             _p(3, 'football', 70, ko='2026-11-01T18:00:00Z'), _p(4, 'football', 85, ko='2026-11-01T18:00:00Z'),
             _p(5, 'football', 95, ko='2026-11-01T19:00:00Z')]
    h = fe.build_html(picks, [DAY], {})
    assert h.count("<h3 id='sport-") == 2
    assert 'Piłka nożna — 3 typów' in h and 'Hokej — 2 typów' in h
    assert "href='#sport-football'" in h and "href='#sport-hockey'" in h
    assert 'Koszykówka' not in h and 'sport-basketball' not in h
    fb, hk = h.index("id='sport-football'"), h.index("id='sport-hockey'")
    assert fb < h.index('A4') < h.index('A3') < h.index('A5') < hk
    assert hk < h.index('A2') < h.index('A1')


def test_one_mail_per_sport_ordered_no_empty_no_resend(tmp_path, monkeypatch):
    picks = [_p(1, 'football', 70, ko='2099-01-01T18:00:00Z'), _p(2, 'football', 85, ko='2099-01-01T18:00:00Z'),
             _p(3, 'football', 95, ko='2099-01-01T19:00:00Z'), _p(4, 'hockey', 75, ko='2099-01-01T17:00:00Z')]
    _board(tmp_path, picks)
    calls = []
    monkeypatch.setattr(fe, 'send', lambda *a, **k: calls.append(a) or True)
    args = ['--day', DAY, '--days', '1', '--results', str(tmp_path / 'results'),
            '--outputs', str(tmp_path / 'outputs'), '--to', 't', '--from-email', 'f', '--password', 'p']
    assert fe.main(args) == 0
    subjects = [c[1] for c in calls]
    assert len(calls) == 2
    assert f'Piłka nożna (3) – {DAY}' in subjects[0] and f'Hokej (1) – {DAY}' in subjects[1]
    fb = calls[0][0]
    assert 'A4' not in fb and fb.index('A2') < fb.index('A1') < fb.index('A3')
    assert 'A4' in calls[1][0] and 'A1' not in calls[1][0]
    assert 'Koszykówka' not in ''.join(c[1] for c in calls)
    assert fe.main(args) == 0 and len(calls) == 2           # second run: nothing resent


def test_force_with_zero_picks_sends_one_mail(tmp_path, monkeypatch):
    _board(tmp_path, [])
    calls = []
    monkeypatch.setattr(fe, 'send', lambda *a, **k: calls.append(a) or True)
    args = ['--day', DAY, '--days', '1', '--results', str(tmp_path / 'results'),
            '--outputs', str(tmp_path / 'outputs'), '--to', 't', '--from-email', 'f', '--password', 'p']
    assert fe.main(args) == 0 and calls == []
    assert fe.main(args + ['--force']) == 0
    assert len(calls) == 1 and '(0)' in calls[0][1] and 'wysyłka ręczna' in calls[0][1]


def test_card_shows_form_h2h_last_h2h_and_last_matches():
    p = _p(1, 'football', 80, home='H1', away='A1',
           form={'overall': 'WWL', 'venue': 'WD', 'opponentOverall': 'LLD', 'opponentVenue': 'L'},
           h2h={'total': 3, 'line': 'H2H 3: A1 2-1', 'last': '2026-10-29 H1 1-0 A1',
                'lastDate': '29.10.26', 'lastScore': '1-0'},
           lastMatch={'team': {'date': '05.11.26', 'result': 'W', 'score': '2-1'},
                      'opponent': {'date': '04.11.26', 'result': 'L', 'score': '0-3'}})
    h = fe.build_html([p], [DAY], {})
    assert 'Forma A1' in h and 'Forma H1' in h and '>D<' in h
    assert 'H2H 3: A1 2-1' in h and '2026-10-29 H1 1-0 A1' in h
    assert 'Ostatni mecz A1: 05.11.26' in h and '2-1' in h
    assert 'Ostatni mecz H1: 04.11.26' in h and '0-3' in h


def test_card_falls_back_to_last_h2h_date_and_score():
    p = _p(1, 'football', 80, h2h={'total': 1, 'line': 'x', 'last': 'No previous meetings',
                                   'lastDate': '29.10.26', 'lastScore': '1-0'})
    assert 'Ostatni H2H: 29.10.26 1-0' in fe.build_html([p], [DAY], {})


def test_card_renders_cleanly_without_new_fields():
    p = _p(1, 'football', 80, form={}, h2h=None)
    h = fe.build_html([p], [DAY], {})
    assert 'Brak bezpośrednich meczów' in h and 'Ostatni H2H: —' in h
    assert 'Ostatni mecz A1: —' in h and 'Ostatni mecz H1: —' in h


def test_threshold_text_shows_1x2_60_with_form():
    h = fe.build_html([_p(1, 'football', 80)], [DAY], {})
    assert 'Progi: ≥ 70%' in h and '(1X2: piłka nożna, piłka ręczna) ≥ 60%' in h
    assert 'forma obu drużyn' in h
