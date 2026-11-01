"""SofaScore relays (SOFASCORE_RELAY) and the day-listing disk cache — no network."""
import json
import os
import sys
import time
import types
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sofascore_scraper as ss  # noqa: E402

A, B = 'https://a/exec', 'https://b/exec'
URL = 'https://www.sofascore.com/api/v1/event/1/votes'
HTML = '<!DOCTYPE html><html><body>Script function not found: doGet</body></html>'


class _R:
    def __init__(self, status, text):
        self.status_code, self.text = status, text

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def relays(monkeypatch):
    """answer(A=..., B=..., direct=...) installs a fake curl_requests.get; each
    value builds a fresh response (or exception) per call; returns the call log."""
    monkeypatch.setenv('SOFASCORE_RELAY', f'{A},{B}')
    for name, value in (('CURL_CFFI_AVAILABLE', True), ('_APP_CLIENT_ENABLED', True),
                        ('_sofascore_unreachable_for_run', False), ('_app_client_403_streak', 0),
                        ('_app_stats', {}), ('_dead_relays', set()), ('_relay_bad', {}),
                        ('_relay_turn', 0), ('_RELAY_BAD_LIMIT', 3)):
        monkeypatch.setattr(ss, name, value)
    monkeypatch.setattr(ss, '_get_sofascore_proxies', lambda: None)
    monkeypatch.setattr(ss.time, 'sleep', lambda s: None)
    calls = []

    def answer(**by):
        def get(url, **kw):
            who = 'A' if url.startswith(A) else 'B' if url.startswith(B) else 'direct'
            calls.append(who)
            res = by.get(who, lambda: _R(403, '{"error": {"code": 403}}'))()
            if isinstance(res, Exception):
                raise res
            return res
        monkeypatch.setattr(ss, 'curl_requests', types.SimpleNamespace(get=get))
        return calls
    return answer


def test_relay_with_non_json_200_is_dropped_after_three_bad_answers(relays, capsys):
    calls = relays(A=lambda: _R(200, HTML), B=lambda: _R(200, '{"vote": {"vote1": 10}}'))
    for _ in range(5):
        assert ss._app_client_response(URL).status_code == 200
    # Round robin: requests 1, 3 and 5 start at A; its 3rd bad answer drops it.
    assert calls == ['A', 'B', 'B', 'A', 'B', 'B', 'A', 'B']
    assert ss._dead_relays == {A}
    n = len(calls)
    for _ in range(3):
        ss._app_client_response(URL)
    assert calls[n:] == ['B', 'B', 'B']          # A's 4th turn goes straight to B
    out = capsys.readouterr().out
    assert out.count('Przekaźnik SofaScore #1: 3 złych odpowiedzi z rzędu — pomijam do końca runu') == 1
    assert ss._app_stats['relay_calls'] == len(calls)


def test_broken_relays_are_skipped_from_the_fourth_request(relays):
    calls = relays(A=lambda: _R(200, HTML), B=lambda: _R(502, 'Bad Gateway'),
                   direct=lambda: _R(200, '{"event": {"id": 1}}'))
    for _ in range(3):
        assert ss._app_client_response(URL).status_code == 200
    assert calls.count('A') == 3 and calls.count('B') == 3
    assert ss._dead_relays == {A, B}
    n = len(calls)
    assert ss._app_client_response(URL).status_code == 200
    assert calls[n:] == ['direct']


def test_good_answer_resets_the_streak_and_exceptions_count_as_bad(relays, monkeypatch):
    monkeypatch.setenv('SOFASCORE_RELAY', A)
    seq = iter([ConnectionError('reset'), _R(200, HTML), _R(200, '{"ok": 1}'),
                _R(503, ''), ConnectionError('reset'), _R(200, '{"ok": 1}'),
                _R(200, HTML), _R(200, HTML), ConnectionError('reset')])
    relays(A=lambda: next(seq))
    dead = []
    for _ in range(9):
        ss._app_client_response(URL)
        dead.append(A in ss._dead_relays)
    assert dead == [False] * 8 + [True]
    assert ss._app_stats['relay_err'] == 3


def test_good_relays_take_turns(relays):
    calls = relays(A=lambda: _R(200, '{"a": 1}'), B=lambda: _R(200, '{"b": 1}'))
    got = [ss._app_client_get(URL) for _ in range(4)]
    assert calls == ['A', 'B', 'A', 'B']
    assert got == [(200, {'a': 1}), (200, {'b': 1}), (200, {'a': 1}), (200, {'b': 1})]
    assert ss._app_stats['relay_calls'] == 4 and ss._app_stats['relay_ok'] == 4
    assert not ss._dead_relays


def test_exhausted_relay_is_dropped_at_once(relays, capsys):
    calls = relays(A=lambda: _R(200, '<html>Service invoked too many times for one day: urlfetch.</html>'),
                   B=lambda: _R(200, '{"ok": 1}'))
    assert ss._app_client_response(URL).status_code == 200
    assert calls == ['A', 'B'] and ss._dead_relays == {A}
    assert 'dzienny limit Google wyczerpany' in capsys.readouterr().out


def test_sofascore_403_through_a_working_relay_does_not_drop_it(relays):
    challenge = '{"error": {"code": 403, "reason": "challenge"}}'
    relays(A=lambda: _R(200, challenge), B=lambda: _R(200, challenge))
    for _ in range(5):
        assert ss._app_client_response(URL) is None
    assert not ss._dead_relays and ss._app_stats['relay_fail'] == 10


# ── day listing: SOFASCORE_LISTING_CACHE_DIR ──────────────────────────────────

DAY = '2026-10-31'
T0 = datetime(2026, 10, 31, 12, tzinfo=timezone.utc).timestamp()


def _ev(i, ts):
    return {'id': i, 'startTimestamp': ts, 'homeTeam': {'name': f'H{i}'}, 'awayTeam': {'name': f'A{i}'}}


@pytest.fixture
def listing(monkeypatch, tmp_path):
    """Fake _app_client_get: two categories with one event each. Returns
    (call log, answers by URL part, cache file of football on DAY)."""
    monkeypatch.setenv('SOFASCORE_LISTING_CACHE_DIR', str(tmp_path / 'sofa_listing'))
    monkeypatch.delenv('SOFASCORE_LISTING_TTL_S', raising=False)
    monkeypatch.setattr(ss, '_scheduled_cache', {})
    calls = []
    answers = {
        '/scheduled-tournaments/': (200, {'scheduled': [{'tournament': {'category': {'id': 7}}},
                                                        {'tournament': {'category': {'id': 9}}}],
                                          'hasNextPage': False}),
        '/category/7/': (200, {'events': [_ev(1, T0)]}),
        '/category/9/': (200, {'events': [_ev(2, T0 + 3600)]}),
    }

    def get(url, timeout=10):
        calls.append(url)
        return next((ans for part, ans in answers.items() if part in url), (None, None))
    monkeypatch.setattr(ss, '_app_client_get', get)
    return calls, answers, tmp_path / 'sofa_listing' / f'football_{DAY}.json'


def test_second_listing_build_reads_the_disk_and_makes_no_api_call(listing, monkeypatch):
    calls, _, path = listing
    first = ss._scheduled_events_via_categories('football', DAY)
    assert sorted(e['id'] for e in first['events']) == [1, 2] and len(calls) == 3
    assert path.exists()
    ss._scheduled_cache.clear()                     # next step of the job = new process
    n = len(calls)
    for name in ('CURL_CFFI_AVAILABLE', '_APP_CLIENT_ENABLED'):
        monkeypatch.setattr(ss, name, True)
    for name in ('_api_consecutive_403', '_sofascore_api_reachable'):
        monkeypatch.setattr(ss, name, getattr(ss, name))   # restored after the test
    again = ss._api_get_json(f'https://api.sofascore.com/api/v1/sport/football/scheduled-events/{DAY}')
    assert again == first and len(calls) == n


def test_expired_listing_file_is_rebuilt(listing, monkeypatch):
    calls, _, path = listing
    monkeypatch.setenv('SOFASCORE_LISTING_TTL_S', '600')
    ss._scheduled_events_via_categories('football', DAY)
    old = time.time() - 601
    os.utime(path, (old, old))
    ss._scheduled_cache.clear()
    n = len(calls)
    assert len(ss._scheduled_events_via_categories('football', DAY)['events']) == 2
    assert len(calls) == n + 3
    assert path.stat().st_mtime > old + 300            # written again


def test_missing_or_empty_listing_is_never_written(listing):
    calls, answers, path = listing
    answers['/scheduled-tournaments/'] = (None, None)  # relay gave nothing: no categories
    assert ss._scheduled_events_via_categories('football', DAY) is None
    answers['/scheduled-tournaments/'] = (200, {'scheduled': [{'tournament': {'category': {'id': 7}}}],
                                                'hasNextPage': False})
    answers['/category/7/'] = (200, {'events': []})
    assert ss._scheduled_events_via_categories('hockey', DAY) == {'events': []}
    assert not path.parent.exists() or os.listdir(path.parent) == []
    ss._scheduled_cache.clear()
    n = len(calls)
    ss._scheduled_events_via_categories('football', DAY)  # nothing on disk: asks again
    assert len(calls) > n


def test_without_cache_dir_nothing_touches_the_disk(listing, monkeypatch, tmp_path):
    calls, _, path = listing
    monkeypatch.delenv('SOFASCORE_LISTING_CACHE_DIR')
    assert len(ss._scheduled_events_via_categories('football', DAY)['events']) == 2
    assert not path.parent.exists()
