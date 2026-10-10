import sofascore_scraper as ss


class _R:
    status_code = 403


def test_trips_after_streak_without_success(monkeypatch):
    monkeypatch.setattr(ss, '_sofascore_unreachable_for_run', False)
    monkeypatch.setattr(ss, '_app_client_403_streak', 0)
    monkeypatch.setattr(ss, '_app_stats', {})
    monkeypatch.setattr(ss, '_APP_FAIL_LIMIT', 3)
    monkeypatch.setattr(ss, '_get_sofascore_proxies', lambda: None)
    monkeypatch.setattr(ss.time, 'sleep', lambda s: None)
    calls = []
    monkeypatch.setattr(ss.curl_requests, 'get', lambda *a, **k: calls.append(1) or _R())
    for _ in range(3):
        assert ss._app_client_response('https://www.sofascore.com/api/v1/event/1') is None
    assert ss.is_sofascore_unreachable()
    n = len(calls)
    assert ss._app_client_response('https://www.sofascore.com/api/v1/event/1') is None
    assert len(calls) == n  # po wyłączeniu już nie pytamy


def test_no_trip_when_some_request_succeeded(monkeypatch):
    monkeypatch.setattr(ss, '_sofascore_unreachable_for_run', False)
    monkeypatch.setattr(ss, '_app_client_403_streak', 0)
    monkeypatch.setattr(ss, '_app_stats', {'200': 5})
    monkeypatch.setattr(ss, '_APP_FAIL_LIMIT', 2)
    monkeypatch.setattr(ss, '_get_sofascore_proxies', lambda: None)
    monkeypatch.setattr(ss.time, 'sleep', lambda s: None)
    monkeypatch.setattr(ss.curl_requests, 'get', lambda *a, **k: _R())
    for _ in range(5):
        ss._app_client_response('https://www.sofascore.com/api/v1/event/1')
    assert not ss._sofascore_unreachable_for_run
