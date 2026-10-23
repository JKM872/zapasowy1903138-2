"""Verifying tokens by asking Supabase when no JWT secret is configured.

Production has SUPABASE_URL and SUPABASE_KEY but no SUPABASE_JWT_SECRET. The
token issuer's own /auth/v1/user endpoint is authoritative, so a hosted run
can authenticate without the secret — and a forged token is still rejected.
"""
import importlib
import os
import sys

import pytest
from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.delenv('SUPABASE_JWT_SECRET', raising=False)
    monkeypatch.delenv('ALLOW_INSECURE_AUTH', raising=False)
    monkeypatch.setenv('PORT', '8000')
    monkeypatch.setenv('SUPABASE_URL', 'https://proj.supabase.test')
    monkeypatch.setenv('SUPABASE_KEY', 'anon-key')
    import auth_middleware
    importlib.reload(auth_middleware)
    auth_middleware._cache.clear()
    yield auth_middleware
    importlib.reload(auth_middleware)


def app_for(mod):
    app = Flask(__name__)

    @app.route('/p')
    @mod.require_auth
    def p():
        from flask import request
        return jsonify({'user_id': request.user_id})
    return app.test_client()


def test_a_genuine_token_is_accepted(mod, monkeypatch):
    monkeypatch.setattr(mod, '_verify_with_supabase',
                        lambda t: {'sub': 'user-1'} if t == 'good' else None)
    resp = app_for(mod).get('/p', headers={'Authorization': 'Bearer good'})
    assert resp.status_code == 200
    assert resp.get_json()['user_id'] == 'user-1'


def test_a_forged_token_is_rejected(mod, monkeypatch):
    monkeypatch.setattr(mod, '_verify_with_supabase', lambda t: None)
    resp = app_for(mod).get('/p', headers={'Authorization': 'Bearer forged'})
    assert resp.status_code == 401


def test_no_header_is_rejected_when_verification_is_possible(mod):
    assert app_for(mod).get('/p').status_code == 401


def test_hosted_run_no_longer_refuses_everyone(mod):
    assert mod.auth_is_configured() is True


def test_verified_tokens_are_cached(mod, monkeypatch):
    calls = []

    def verify(t):
        calls.append(t)
        return {'sub': 'user-1'}
    monkeypatch.setattr(mod, '_verify_with_supabase', verify)
    client = app_for(mod)
    for _ in range(3):
        client.get('/p', headers={'Authorization': 'Bearer good'})
    assert len(calls) == 1


def test_rejections_are_not_cached(mod, monkeypatch):
    calls = []

    def verify(t):
        calls.append(t)
        return None
    monkeypatch.setattr(mod, '_verify_with_supabase', verify)
    client = app_for(mod)
    client.get('/p', headers={'Authorization': 'Bearer x'})
    client.get('/p', headers={'Authorization': 'Bearer x'})
    assert len(calls) == 2


def test_supabase_unreachable_means_rejected_not_admitted(mod, monkeypatch):
    import urllib.request

    def down(*a, **k):
        raise OSError('network down')
    monkeypatch.setattr(urllib.request, 'urlopen', down)
    resp = app_for(mod).get('/p', headers={'Authorization': 'Bearer anything'})
    assert resp.status_code == 401
