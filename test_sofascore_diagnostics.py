"""Regression tests for SofaScore HTTP diagnostics and FlareSolverr fallback (v4.1).

Pokrywa konkretne scenariusze, które najczęściej tłumaczą "brak SofaScore Fan
Vote w mailu w GitHub Actions":

- Statystyki HTTP są agregowane per klient i widoczne w `print_http_stats()`,
  żeby z jednego rzutu oka po runie wiedzieć, czy dominują 403, 404, timeout
  czy ok.
- `_api_get_json()` po 403 z curl/requests faktycznie próbuje FlareSolverr,
  a po sukcesie FlareSolverr zwraca sparsowany JSON.
- Brak FlareSolverr (`FLARESOLVERR_URL` puste) wyłącza tę ścieżkę i pipeline
  zachowuje się jak dotąd.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

import sofascore_scraper as ss


@pytest.fixture(autouse=True)
def _reset_http_stats():
    """Czyść globalne statystyki HTTP między testami."""
    for client in list(ss._http_stats.keys()):
        ss._http_stats[client] = {}
    yield
    for client in list(ss._http_stats.keys()):
        ss._http_stats[client] = {}


class TestHttpStats:
    def test_record_and_snapshot(self):
        ss._record_http_outcome('curl_cffi', '403')
        ss._record_http_outcome('curl_cffi', '403')
        ss._record_http_outcome('curl_cffi', 'ok')
        ss._record_http_outcome('flaresolverr', 'ok')
        snap = ss.get_http_stats_snapshot()
        assert snap['curl_cffi'] == {'403': 2, 'ok': 1}
        assert snap['flaresolverr'] == {'ok': 1}

    def test_format_skips_empty_clients(self):
        ss._record_http_outcome('curl_cffi', '403')
        out = ss._format_http_stats()
        # Tylko ten klient ma dane → tylko on jest na liście.
        assert 'curl_cffi' in out
        assert 'requests' not in out
        assert '403=1' in out
        assert 'total=1' in out

    def test_print_http_stats_is_noop_when_empty(self, capsys):
        ss.print_http_stats()
        captured = capsys.readouterr()
        # Brak requestów → brak nagłówka "SofaScore HTTP statistics".
        assert captured.out == ''

    def test_print_http_stats_emits_header_when_data(self, capsys):
        ss._record_http_outcome('curl_cffi', '403')
        ss.print_http_stats()
        captured = capsys.readouterr()
        assert 'SofaScore HTTP statistics' in captured.out
        assert 'curl_cffi' in captured.out


class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[Any] = None):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError('no payload')
        return self._payload


class TestApiGetJsonFallback:
    """Po 403 z curl/requests powinniśmy wpaść na FlareSolverr (jeśli dostępny)."""

    def test_returns_json_on_200(self, monkeypatch):
        payload = {'events': [{'id': 1}]}
        monkeypatch.setattr(ss, '_retry_request_with_session',
                            lambda *a, **kw: _FakeResponse(200, payload))
        # FlareSolverr nie powinien być w ogóle wołany.
        called = {'fs': 0}
        monkeypatch.setattr(ss, '_try_flaresolverr_json',
                            lambda *a, **kw: called.__setitem__('fs', called['fs'] + 1) or None)
        out = ss._api_get_json('https://api.sofascore.com/test', timeout=5)
        assert out == payload
        assert called['fs'] == 0

    def test_403_triggers_flaresolverr_when_available(self, monkeypatch):
        monkeypatch.setattr(ss, '_retry_request_with_session',
                            lambda *a, **kw: _FakeResponse(403))
        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', True)
        fs_payload = {'events': [{'id': 42}]}
        monkeypatch.setattr(ss, '_try_flaresolverr_json',
                            lambda *a, **kw: fs_payload)
        out = ss._api_get_json('https://api.sofascore.com/test', timeout=5)
        assert out == fs_payload

    def test_403_without_flaresolverr_returns_none(self, monkeypatch):
        monkeypatch.setattr(ss, '_retry_request_with_session',
                            lambda *a, **kw: _FakeResponse(403))
        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', False)
        # Nawet jeśli funkcja istnieje, nie powinna być wywołana.
        called = {'fs': 0}
        monkeypatch.setattr(ss, '_try_flaresolverr_json',
                            lambda *a, **kw: called.__setitem__('fs', called['fs'] + 1) or {'x': 1})
        out = ss._api_get_json('https://api.sofascore.com/test', timeout=5)
        assert out is None
        assert called['fs'] == 0

    def test_no_response_falls_back_to_flaresolverr_when_available(self, monkeypatch):
        # `_retry_request_with_session` zwraca None (timeout/error chain) →
        # spróbuj FlareSolverr jako last resort.
        monkeypatch.setattr(ss, '_retry_request_with_session', lambda *a, **kw: None)
        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', True)
        monkeypatch.setattr(ss, '_try_flaresolverr_json',
                            lambda *a, **kw: {'events': []})
        out = ss._api_get_json('https://api.sofascore.com/test', timeout=5)
        assert out == {'events': []}

    def test_404_does_not_trigger_flaresolverr(self, monkeypatch):
        # 404 to "nie ma takiego eventu" — to nie blokada, FS nic tu nie zmieni.
        monkeypatch.setattr(ss, '_retry_request_with_session',
                            lambda *a, **kw: _FakeResponse(404))
        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', True)
        called = {'fs': 0}
        monkeypatch.setattr(ss, '_try_flaresolverr_json',
                            lambda *a, **kw: called.__setitem__('fs', called['fs'] + 1) or {'x': 1})
        out = ss._api_get_json('https://api.sofascore.com/test', timeout=5)
        assert out is None
        assert called['fs'] == 0


class TestFlareSolverrJsonParser:
    """`_try_flaresolverr_json` musi obsłużyć wrapper `<pre>...</pre>` i czysty JSON."""

    def _setup_flaresolverr(self, monkeypatch, body: str, status_code: int = 200,
                            fs_status: str = 'ok') -> Dict[str, int]:
        called = {'post': 0}
        # Lokalne aliasy, żeby uniknąć kolizji z atrybutem klasy `status_code`.
        _status = status_code
        _fs_status = fs_status

        class _FakePost:
            status_code = _status
            def json(self):
                return {'status': _fs_status, 'solution': {'response': body}}

        def _fake_post(*args, **kwargs):
            called['post'] += 1
            return _FakePost()

        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', True)
        monkeypatch.setattr(ss, '_FLARESOLVERR_URL_ENV', 'http://localhost:8191/v1')
        monkeypatch.setattr(ss, '_flaresolverr_disabled_for_run', False)
        # v8.2 — zablokuj proaktywne tworzenie session by jeden test = jeden post
        monkeypatch.setattr(ss, '_flaresolverr_session_id', None)
        monkeypatch.setattr(ss, '_flaresolverr_session_warmed', False)
        monkeypatch.setattr(ss, '_flaresolverr_session_failed', True)
        monkeypatch.setattr(ss.requests, 'post', _fake_post)
        return called

    def test_pure_json_body(self, monkeypatch):
        payload = {'events': [{'id': 7}]}
        called = self._setup_flaresolverr(monkeypatch, body=json.dumps(payload))
        out = ss._try_flaresolverr_json('https://api.sofascore.com/x')
        assert out == payload
        assert called['post'] == 1
        assert ss.get_http_stats_snapshot()['flaresolverr'].get('ok') == 1

    def test_html_pre_wrapped_json(self, monkeypatch):
        payload = {'events': [{'id': 8}]}
        body = f'<html><body><pre style="word-wrap: break-word;">{json.dumps(payload)}</pre></body></html>'
        self._setup_flaresolverr(monkeypatch, body=body)
        out = ss._try_flaresolverr_json('https://api.sofascore.com/x')
        assert out == payload

    def test_non_json_body_records_error(self, monkeypatch):
        self._setup_flaresolverr(monkeypatch, body='<html>Cloudflare challenge</html>')
        out = ss._try_flaresolverr_json('https://api.sofascore.com/x')
        assert out is None
        assert ss.get_http_stats_snapshot()['flaresolverr'].get('json_error') == 1

    def test_disabled_when_url_missing(self, monkeypatch):
        monkeypatch.setattr(ss, '_FLARESOLVERR_AVAILABLE', False)
        out = ss._try_flaresolverr_json('https://api.sofascore.com/x')
        assert out is None


class TestRetryRequestRecordsStats:
    """Smoke test: po sukcesie 200 stat `curl_cffi=ok` musi narastać."""

    def test_curl_success_records_ok(self, monkeypatch):
        monkeypatch.setattr(ss, 'CURL_CFFI_AVAILABLE', True)
        monkeypatch.setattr(ss, '_get_api_session', lambda: 'curl_cffi')

        class _CurlResp:
            status_code = 200
            content = b'{"ok":true}'

        class _FakeCurl:
            @staticmethod
            def get(url, **kwargs):
                return _CurlResp()

        monkeypatch.setattr(ss, 'curl_requests', _FakeCurl)
        resp = ss._retry_request_with_session('https://api.sofascore.com/x', timeout=2)
        assert resp is not None
        assert ss.get_http_stats_snapshot()['curl_cffi'].get('ok') == 1
