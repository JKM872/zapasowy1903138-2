"""What happens to protected routes when SUPABASE_JWT_SECRET is missing.

Two holes lived here. `_decode_token` handed back a synthetic
`{'sub': 'anonymous'}` payload whenever the secret was absent, so *any* string
passed as a valid token — `Authorization: Bearer whatever` reached every
per-user route. And `require_auth` served requests with no header at all. On a
hosted deployment that meant the paywall and every user-scoped endpoint were
open to anyone who asked.

Local work still needs the permissive path, so the split is by environment: a
hosted run (PORT set) refuses, a laptop allows and logs a warning.
"""
import importlib
import os
import sys

import pytest
from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_app(monkeypatch, *, secret=None, port=None, allow_insecure=None):
    """A one-route app with auth_middleware reloaded under given environment."""
    for var, value in (('SUPABASE_JWT_SECRET', secret),
                       ('PORT', port),
                       ('ALLOW_INSECURE_AUTH', allow_insecure)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)

    import auth_middleware
    importlib.reload(auth_middleware)

    app = Flask(__name__)
    app.config['TESTING'] = True

    @app.route('/protected')
    @auth_middleware.require_auth
    def protected():
        from flask import request
        return jsonify({'user_id': getattr(request, 'user_id', None)})

    return app, auth_middleware


@pytest.fixture(autouse=True)
def _restore_module():
    """Leave the module as the rest of the suite expects to find it."""
    yield
    import auth_middleware
    importlib.reload(auth_middleware)


class TestHostedWithoutSecret:
    """PORT is set, so this is a real deployment."""

    def test_no_header_is_refused(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port='8000')
        resp = app.test_client().get('/protected')
        assert resp.status_code == 503

    def test_a_forged_token_is_refused(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port='8000')
        resp = app.test_client().get(
            '/protected', headers={'Authorization': 'Bearer whatever'})
        assert resp.status_code == 503, 'an unverifiable token must not be honoured'

    def test_the_reason_is_stated(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port='8000')
        body = app.test_client().get('/protected').get_json()
        assert 'not configured' in body['error'].lower()


class TestLocalWithoutSecret:
    """No PORT: a laptop. Permissive, because nothing is exposed."""

    def test_no_header_is_served_as_anonymous(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port=None)
        resp = app.test_client().get('/protected')
        assert resp.status_code == 200
        assert resp.get_json()['user_id'] == 'anonymous'

    def test_a_forged_token_does_not_become_an_identity(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port=None)
        resp = app.test_client().get(
            '/protected', headers={'Authorization': 'Bearer forged'})
        assert resp.status_code == 200
        assert resp.get_json()['user_id'] == 'anonymous', \
            'an unverifiable token must never yield a real user id'


class TestEscapeHatch:
    def test_allow_insecure_auth_restores_local_behaviour(self, monkeypatch):
        app, _ = build_app(monkeypatch, secret=None, port='8000',
                           allow_insecure='true')
        resp = app.test_client().get('/protected')
        assert resp.status_code == 200


class TestDecodeToken:
    def test_no_secret_means_no_payload(self, monkeypatch):
        _, auth_middleware = build_app(monkeypatch, secret=None, port=None)
        assert auth_middleware._decode_token('anything') is None

    def test_auth_is_configured_reports_the_truth(self, monkeypatch):
        _, without = build_app(monkeypatch, secret=None, port=None)
        assert without.auth_is_configured() is False
        _, with_secret = build_app(monkeypatch, secret='x' * 40, port=None)
        assert with_secret.auth_is_configured() is True
