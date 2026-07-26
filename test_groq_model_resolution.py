"""Tests for Groq model resolution.

Background: the config pinned ``mixtral-8x7b-32768``, which Groq retired in
March 2025, while the caller ignored that setting and hardcoded a different ID.
A retired model answers HTTP 400, and the caller only logged the error and
returned None — so AI-assisted name matching would break silently and stay
broken. Model IDs are resolved against the live model list instead, with a
single retry when the chosen one turns out to be gone.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import groq_config as gc  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    gc.reset_resolved_model()
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    yield
    gc.reset_resolved_model()


def _models_response(ids, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {'data': [{'id': i} for i in ids]}
    return resp


class TestRetiredModelIsGone:
    def test_retired_mixtral_is_not_a_preference(self):
        assert 'mixtral-8x7b-32768' not in gc.GROQ_MODEL_PREFERENCES

    def test_default_model_is_not_the_retired_one(self):
        assert gc.GROQ_MODEL != 'mixtral-8x7b-32768'

    def test_preferences_are_not_empty(self):
        assert len(gc.GROQ_MODEL_PREFERENCES) >= 2


class TestListAvailableModels:
    def test_parses_ids(self):
        with patch('requests.get', return_value=_models_response(['a', 'b'])):
            assert gc.list_available_models('key') == ['a', 'b']

    def test_empty_without_key(self):
        assert gc.list_available_models('') == []

    def test_empty_on_http_error(self):
        with patch('requests.get', return_value=_models_response([], status=401)):
            assert gc.list_available_models('key') == []

    def test_empty_on_network_error(self):
        with patch('requests.get', side_effect=OSError('boom')):
            assert gc.list_available_models('key') == []

    def test_malformed_payload_is_safe(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'unexpected': True}
        with patch('requests.get', return_value=resp):
            assert gc.list_available_models('key') == []


class TestResolveModel:
    def test_prefers_first_available_preference(self):
        available = ['llama-3.1-8b-instant', 'llama-3.3-70b-versatile', 'other']
        with patch('requests.get', return_value=_models_response(available)):
            assert gc.resolve_model('key') == 'llama-3.3-70b-versatile'

    def test_falls_through_to_next_preference(self):
        # Top preference retired; the next one must be chosen.
        available = ['llama-3.1-8b-instant', 'whatever']
        with patch('requests.get', return_value=_models_response(available)):
            assert gc.resolve_model('key') == 'llama-3.1-8b-instant'

    def test_uses_any_model_when_no_preference_survives(self):
        with patch('requests.get', return_value=_models_response(['brand-new-1'])):
            assert gc.resolve_model('key') == 'brand-new-1'

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv('GROQ_MODEL', 'my-pinned-model')
        with patch('requests.get', return_value=_models_response(['x'])):
            assert gc.resolve_model('key') == 'my-pinned-model'

    def test_falls_back_when_discovery_fails(self):
        with patch('requests.get', side_effect=OSError('offline')):
            assert gc.resolve_model('key') == gc.GROQ_MODEL_PREFERENCES[0]

    def test_result_is_cached(self):
        with patch('requests.get', return_value=_models_response(
                ['llama-3.3-70b-versatile'])) as mock_get:
            gc.resolve_model('key')
            gc.resolve_model('key')
            assert mock_get.call_count == 1

    def test_force_bypasses_cache(self):
        with patch('requests.get', return_value=_models_response(
                ['llama-3.3-70b-versatile'])) as mock_get:
            gc.resolve_model('key')
            gc.resolve_model('key', force=True)
            assert mock_get.call_count == 2

    def test_reset_clears_cache(self):
        with patch('requests.get', return_value=_models_response(
                ['llama-3.3-70b-versatile'])) as mock_get:
            gc.resolve_model('key')
            gc.reset_resolved_model()
            gc.resolve_model('key')
            assert mock_get.call_count == 2


def _load_call_groq_api():
    """Import the caller, skipping when its heavy Selenium deps are unusable.

    forebet_scraper imports undetected_chromedriver, which still relies on
    distutils and therefore cannot import on Python 3.12+. CI runs 3.11 where
    this works; locally these tests skip rather than report a false failure.
    """
    import importlib

    try:
        module = importlib.import_module('forebet_scraper')
        return module._call_groq_api
    except Exception as exc:  # pragma: no cover - environment dependent
        # forebet_scraper pulls in undetected_chromedriver at import time, which
        # needs distutils and therefore fails on Python 3.12+. CI runs 3.11, so
        # these four tests execute there; locally they skip instead of
        # reporting a false failure.
        pytest.skip(f'forebet_scraper import unavailable here: {exc}')


class TestCallRetriesOnDecommissionedModel:
    def _chat_ok(self, text='ANSWER'):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'choices': [{'message': {'content': text}}]}
        return resp

    def _chat_decommissioned(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = ('{"error":{"message":"The model `mixtral-8x7b-32768` has '
                     'been decommissioned"}}')
        return resp

    def test_retries_with_a_new_model_and_succeeds(self, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'k')
        _call_groq_api = _load_call_groq_api()

        calls = []

        def fake_post(url, **kwargs):
            calls.append(kwargs['json']['model'])
            return (self._chat_decommissioned() if len(calls) == 1
                    else self._chat_ok('MATCHED'))

        with patch('requests.post', side_effect=fake_post), \
             patch('requests.get', return_value=_models_response(
                 ['llama-3.1-8b-instant'])):
            out = _call_groq_api('prompt')

        assert out == 'MATCHED'
        assert len(calls) == 2, 'should retry once with a replacement model'
        assert calls[1] == 'llama-3.1-8b-instant'

    def test_no_retry_on_unrelated_error(self, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'k')
        _call_groq_api = _load_call_groq_api()

        resp = MagicMock()
        resp.status_code = 429
        resp.text = 'rate limit exceeded'

        with patch('requests.post', return_value=resp) as mock_post, \
             patch('requests.get', return_value=_models_response(['x'])):
            assert _call_groq_api('prompt') is None
        assert mock_post.call_count == 1

    def test_returns_none_without_api_key(self, monkeypatch):
        monkeypatch.delenv('GROQ_API_KEY', raising=False)
        monkeypatch.setattr(gc, 'GROQ_API_KEY', None)
        _call_groq_api = _load_call_groq_api()
        assert _call_groq_api('prompt') is None

    def test_successful_call_uses_resolved_model(self, monkeypatch):
        monkeypatch.setenv('GROQ_API_KEY', 'k')
        _call_groq_api = _load_call_groq_api()

        seen = {}

        def fake_post(url, **kwargs):
            seen['model'] = kwargs['json']['model']
            return self._chat_ok()

        with patch('requests.post', side_effect=fake_post), \
             patch('requests.get', return_value=_models_response(
                 ['llama-3.1-8b-instant', 'llama-3.3-70b-versatile'])):
            _call_groq_api('prompt')

        assert seen['model'] == 'llama-3.3-70b-versatile'
