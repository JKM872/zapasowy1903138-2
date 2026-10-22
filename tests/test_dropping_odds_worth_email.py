"""The "worth it" mail: only verdict "warto", each event once, nothing when empty."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dropping_odds_worth_email as m


def ev(mid, verdict, roi=10.0, n=200, outcome='1'):
    return {'matchId': mid, 'outcome': outcome, 'sport': 'hockey',
            'homeTeam': f'H{mid}', 'awayTeam': f'A{mid}', 'league': 'L',
            'eventTime': '18:00', 'openOdds': 2.5, 'currentOdds': 2.0, 'dropPct': 20.0,
            'verdict': {'verdict': verdict, 'n': n, 'hitRate': 60.0,
                        'roiRealistic': roi}}


def test_only_worth_it_is_selected():
    out = m.select_new_worth([ev(1, 'warto'), ev(2, 'nie_warto'), ev(3, 'za_malo_danych')], set())
    assert [e['matchId'] for e in out] == [1]


def test_already_sent_events_are_not_repeated():
    out = m.select_new_worth([ev(1, 'warto'), ev(2, 'warto')], {'1|1'})
    assert [e['matchId'] for e in out] == [2]


def test_strongest_evidence_comes_first():
    out = m.select_new_worth([ev(1, 'warto', roi=7.1), ev(2, 'warto', roi=14.9)], set())
    assert [e['matchId'] for e in out] == [2, 1]


def test_the_ledger_round_trips(tmp_path):
    path = str(tmp_path / 'ledger.json')
    assert m.load_ledger(path) == set()
    m.save_ledger(path, {'1|1', '2|2'})
    assert m.load_ledger(path) == {'1|1', '2|2'}


def test_nothing_new_sends_nothing(monkeypatch, tmp_path):
    import dropping_odds_feed
    monkeypatch.setattr(dropping_odds_feed, 'load_dropping_odds',
                        lambda date=None: {'date': '2026-10-21', 'events': [ev(1, 'nie_warto')],
                                           'model': None})
    monkeypatch.setattr(m, 'OUTPUTS_DIR', str(tmp_path))
    monkeypatch.setattr(m, 'send', lambda *a, **k: (_ for _ in ()).throw(AssertionError('sent')))
    assert m.main(['--to', 'a@b', '--from-email', 'c@d', '--password', 'x']) == 0


def test_a_failed_send_is_not_recorded(monkeypatch, tmp_path):
    import dropping_odds_feed
    monkeypatch.setattr(dropping_odds_feed, 'load_dropping_odds',
                        lambda date=None: {'date': '2026-10-21', 'events': [ev(1, 'warto')],
                                           'model': None})
    monkeypatch.setattr(m, 'ledger_path', lambda d, o=None: str(tmp_path / 'l.json'))

    def boom(*a, **k):
        raise RuntimeError('smtp down')
    monkeypatch.setattr(m, 'send', boom)
    try:
        m.main(['--to', 'a@b', '--from-email', 'c@d', '--password', 'x'])
    except RuntimeError:
        pass
    assert m.load_ledger(str(tmp_path / 'l.json')) == set(), 'retry next run'


def test_html_escapes_team_names():
    e = ev(1, 'warto')
    e['homeTeam'] = '<script>x</script>'
    assert '<script>' not in m.build_html([e], '2026-10-21', None)
