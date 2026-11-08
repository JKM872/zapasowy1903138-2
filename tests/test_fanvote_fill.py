"""tools.fanvote_fill: which rows are fetched, budget/max calls, store."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import fanvote_fill as fill  # noqa: E402

DAY = '2026-10-21'
NOW = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)


def r(home, away, ss=None, time='19:00'):
    d = {'homeTeam': home, 'awayTeam': away, 'time': time}
    if ss:
        d['sofascore'] = ss
    return d


def fake(calls):
    def f(home, away, sport, day):
        calls.append(home)
        if home == 'X':
            return None
        return {'found': True, 'homeProb': 70, 'awayProb': 20, 'votes': 300, 'url': 'u',
                'orientation': 'direct', 'eventId': 11, 'startTimestamp': 1792605600}
    return f


def test_missing_vote_fetched_verified_skipped_and_store():
    calls, store = [], {}
    rows = [r('A', 'B'), r('X', 'Y'),
            r('V', 'W', {'found': True, 'homeProb': 80, 'awayProb': 10, 'votes': 900, 'orientation': 'direct'}),
            {**r('P', 'Q'), 'kickoffUtc': '2026-10-21T05:00:00Z'}]
    st = fill.fill_votes(rows, 'football', DAY, NOW, store, log=lambda *_: None, fetch=fake(calls), workers=1)
    assert sorted(calls) == ['A', 'X']
    assert st['voteRequested'] == 2 and st['voteFound'] == 1
    assert rows[0]['sofascore']['votes'] == 300 and rows[0]['sofascoreEventId'] == 11
    assert rows[0]['kickoffUtc'].startswith('2026-')
    assert 'a|b' in store['football']
    rows2 = [r('A', 'B')]
    fill.fill_votes(rows2, 'football', DAY, NOW, store, log=lambda *_: None, fetch=fake(calls := []), workers=1)
    assert calls == [] and rows2[0]['sofascore']['votes'] == 300


def test_stale_rule():
    old = '2026-10-21T01:00:00Z'
    near = r('A', 'B', {'found': True, 'homeProb': 62, 'awayProb': 20, 'votes': 500, 'refreshedAt': old})
    far = r('C', 'D', {'found': True, 'homeProb': 90, 'awayProb': 5, 'votes': 500, 'refreshedAt': old})
    fresh = r('E', 'F', {'found': True, 'homeProb': 62, 'awayProb': 5, 'votes': 5,
                         'refreshedAt': '2026-10-21T05:00:00Z'})
    assert fill.needs_fetch(near, 'football', NOW)
    assert not fill.needs_fetch(far, 'football', NOW)
    assert not fill.needs_fetch(fresh, 'football', NOW)


def test_max_calls_and_budget_stop():
    calls = []
    rows = [r(f'T{i}', 'Z') for i in range(5)]
    st = fill.fill_votes(rows, 'football', DAY, NOW, {}, log=lambda *_: None, fetch=fake(calls),
                         max_calls=2, workers=1)
    assert len(calls) == 2 and st['budgetHit'] == 1
    calls = []
    st = fill.fill_votes([r('A', 'B')], 'football', DAY, NOW, {}, log=lambda *_: None, fetch=fake(calls),
                         budget_s=-1, workers=1)
    assert calls == [] and st['budgetHit'] == 1


def test_store_round_trip(tmp_path):
    p = fill.store_path(DAY, str(tmp_path))
    fill.save_store(p, {'football': {'a|b': {'votes': 3}}})
    assert fill.load_store(p) == {'football': {'a|b': {'votes': 3}}}
