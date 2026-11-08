import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import settle_events as se  # noqa: E402

DAY = '2026-10-20'
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def ev(st='finished', h=2, a=1, hn=None, an=None, wc=None, eid=11, home='Alpha', away='Beta'):
    hs, as_ = {'current': h}, {'current': a}
    if hn is not None:
        hs['normaltime'], as_['normaltime'] = hn, an
    return {'id': eid, 'status': {'type': st}, 'homeScore': hs, 'awayScore': as_, 'winnerCode': wc,
            'homeTeam': {'name': home}, 'awayTeam': {'name': away}}


def test_finished_home_win():
    r = se.settle_event(ev(), 'tennis')
    assert (r['status'], r['winner'], r['score']) == ('settled', 'home', '2-1')


def test_football_extra_time_uses_normal_time_draw():
    r = se.settle_event(ev(h=2, a=1, hn=1, an=1), 'football')
    assert (r['winner'], r['score'], r['normaltime']) == ('draw', '1-1', True)


def test_hockey_ot_win_is_won():
    r = se.settle_event(ev(h=3, a=2, hn=2, an=2), 'hockey')
    assert (r['winner'], r['score']) == ('home', '3-2')


def test_canceled_and_postponed_are_void():
    assert se.settle_event(ev('canceled'), 'football')['status'] == 'void'
    assert se.settle_event(ev('postponed'), 'tennis')['status'] == 'void'


def test_notstarted_is_skipped():
    assert se.settle_event(ev('notstarted'), 'football') is None


def test_reversed_event_swaps_score():
    r = se.settle_event(ev(h=3, a=0), 'basketball', 'reversed')
    assert (r['winner'], r['score']) == ('away', '0-3')


def _res(tmp_path, top=None, rows=None):
    res = tmp_path / 'results'
    res.mkdir()
    (res / f'top_{DAY}.json').write_text(json.dumps(top or []), encoding='utf-8')
    if rows is not None:
        (res / f'matches_{DAY}_tennis.json').write_text(json.dumps({'matches': rows}), encoding='utf-8')
    return str(res)


TOP = [{'sport': 'tennis', 'match': 'Alpha vs Beta', 'pick': 'Alpha', 'time': '10:00',
        'kickoffUtc': f'{DAY}T10:00:00Z'}]


def test_id_from_forebet_row_and_second_run_makes_no_call(tmp_path, monkeypatch):
    import top_feed
    monkeypatch.setattr(top_feed, 'STORE_PATH', str(tmp_path / 'none.json'))
    rows = [{'homeTeam': 'Alpha', 'awayTeam': 'Beta',
             'sofascore': {'orientation': 'direct', 'eventId': 77}}]
    res = _res(tmp_path, TOP, rows)
    calls = []

    def fetch(eid):
        calls.append(eid)
        return ev(eid=eid)

    def search(it):
        raise AssertionError('no search expected')

    st = se.run([DAY], res, NOW, fetch=fetch, search=search, log=lambda *_: None)
    assert st['settled'] == 1 and calls == [77]
    data = json.load(open(os.path.join(res, 'event_settled.json'), encoding='utf-8'))
    assert data[f'{DAY}|tennis|Alpha|Beta']['winner'] == 'home'
    se.run([DAY], res, NOW, fetch=fetch, search=search, log=lambda *_: None)
    assert calls == [77]


def test_listing_fallback_and_unmatched(tmp_path, monkeypatch):
    import top_feed
    monkeypatch.setattr(top_feed, 'STORE_PATH', str(tmp_path / 'none.json'))
    res = _res(tmp_path, TOP + [{'sport': 'tennis', 'match': 'Gamma vs Delta', 'pick': 'Gamma',
                                 'kickoffUtc': f'{DAY}T11:00:00Z'}])
    st = se.run([DAY], res, NOW, fetch=lambda e: ev(eid=e),
                search=lambda it: 5 if it['home'] == 'Alpha' else None, log=lambda *_: None)
    assert (st['settled'], st['unmatched']) == (1, 1)
