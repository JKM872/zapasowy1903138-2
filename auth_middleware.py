"""
Auth Middleware for Flask API
-----------------------------
Validates Supabase access tokens for protected endpoints.

Two ways to verify, tried in order:

1. **Local signature check** with ``SUPABASE_JWT_SECRET`` (HS256). Fast, no
   network — used when the secret is configured.
2. **Ask Supabase.** ``GET {SUPABASE_URL}/auth/v1/user`` with the caller's
   token returns the user when the token is genuine and unexpired, and 401
   otherwise. Needs only ``SUPABASE_URL`` + ``SUPABASE_KEY``, which the app
   already has for database access. This exists because production had no
   JWT secret: without it every protected route either let anyone in (the old
   behaviour) or refused everyone (after that hole was closed). Supabase is the
   party that issued the token, so its answer is authoritative — a forged token
   is rejected there just as it would be by a signature check.

Verified tokens are cached briefly so a page load does not mean a round trip
per request. When neither method is available on a hosted run, protected
routes refuse rather than serve unauthenticated callers.

Usage:
    from auth_middleware import require_auth

    @app.route('/api/bets', methods=['POST'])
    @require_auth
    def create_bet():
        user_id = request.user_id   # set by middleware
"""

import functools
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

import jwt
from flask import jsonify, request

logger = logging.getLogger(__name__)

# Supabase Dashboard → Settings → API → JWT Secret. Optional now; see above.
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')

_VERIFY_TIMEOUT_S = 5
_CACHE_TTL_S = 60
_CACHE_MAX = 5000
_cache: dict = {}
_cache_lock = threading.Lock()


def _supabase_url() -> str:
    return (os.environ.get('SUPABASE_URL') or '').rstrip('/')


def _supabase_key() -> str:
    return (os.environ.get('SUPABASE_KEY')
            or os.environ.get('SUPABASE_ANON_KEY')
            or os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
            or '')


def _remote_available() -> bool:
    return bool(_supabase_url() and _supabase_key())


def _is_deployed() -> bool:
    """True when this looks like a hosted run rather than a laptop.

    Heroku sets ``PORT``; the explicit escape hatch is for anyone who wants the
    permissive local behaviour anyway.
    """
    if os.environ.get('ALLOW_INSECURE_AUTH', '').strip().lower() in ('1', 'true', 'yes'):
        return False
    return bool(os.environ.get('PORT'))


def auth_is_configured() -> bool:
    """True when tokens can actually be verified, by either method."""
    return bool(SUPABASE_JWT_SECRET) or _remote_available()


def _cache_get(token: str):
    key = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
        if hit:
            _cache.pop(key, None)
    return None


def _cache_put(token: str, payload: dict) -> None:
    key = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = (payload, time.time() + _CACHE_TTL_S)


def _verify_with_supabase(token: str) -> dict | None:
    """Ask the issuing Supabase project whether the token is valid."""
    req = urllib.request.Request(
        f'{_supabase_url()}/auth/v1/user',
        headers={'Authorization': f'Bearer {token}', 'apikey': _supabase_key()},
    )
    try:
        with urllib.request.urlopen(req, timeout=_VERIFY_TIMEOUT_S) as resp:
            user = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError:
        # 401/403: Supabase rejected the token. That is a real "no".
        return None
    except Exception as exc:  # network, timeout, bad JSON
        logger.warning('Supabase token verification unavailable: %s', exc)
        return None
    user_id = user.get('id') if isinstance(user, dict) else None
    if not user_id:
        return None
    return {'sub': user_id, 'email': user.get('email'), 'role': user.get('role')}


def _decode_token(token: str) -> dict | None:
    """Verify a Supabase access token. Returns its payload or None.

    Never returns a synthetic identity: an unverifiable token is None. The old
    fallback handed back ``{'sub': 'anonymous'}``, which made any string a
    valid token.
    """
    if not token:
        return None

    if SUPABASE_JWT_SECRET:
        try:
            return jwt.decode(token, SUPABASE_JWT_SECRET,
                              algorithms=['HS256'], audience='authenticated')
        except jwt.InvalidTokenError:
            return None

    if not _remote_available():
        return None

    cached = _cache_get(token)
    if cached is not None:
        return cached
    payload = _verify_with_supabase(token)
    if payload is not None:
        _cache_put(token, payload)
    return payload


def require_auth(fn):
    """Decorator: reject requests without a valid Supabase token."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        configured = auth_is_configured()

        # A hosted deployment that cannot verify anyone must not serve protected
        # routes to whoever asks.
        if not configured and _is_deployed():
            logger.error(
                'No way to verify tokens (set SUPABASE_URL+SUPABASE_KEY or '
                'SUPABASE_JWT_SECRET) — refusing to serve %s.', fn.__name__)
            return jsonify({'error': 'Authentication is not configured on this server'}), 503

        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            if not configured:
                # Local development with nothing to verify against.
                logger.warning('Auth not configured — %s served as anonymous (local mode)',
                               fn.__name__)
                request.user_id = 'anonymous'  # type: ignore[attr-defined]
                return fn(*args, **kwargs)
            return jsonify({'error': 'Missing Authorization header'}), 401

        if not configured:
            # A token arrived but cannot be checked. Never treat it as valid.
            logger.warning('Auth not configured — token on %s cannot be verified, '
                           'treating the caller as anonymous', fn.__name__)
            request.user_id = 'anonymous'  # type: ignore[attr-defined]
            return fn(*args, **kwargs)

        payload = _decode_token(auth_header.split(' ', 1)[1])
        if payload is None:
            return jsonify({'error': 'Invalid or expired token'}), 401

        request.user_id = payload.get('sub', 'anonymous')  # type: ignore[attr-defined]
        return fn(*args, **kwargs)

    return wrapper


def optional_auth(fn):
    """Decorator: identify the caller when possible, never reject."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            payload = _decode_token(auth_header.split(' ', 1)[1])
            request.user_id = payload.get('sub', 'anonymous') if payload else 'anonymous'  # type: ignore[attr-defined]
        else:
            request.user_id = 'anonymous'  # type: ignore[attr-defined]
        return fn(*args, **kwargs)

    return wrapper
