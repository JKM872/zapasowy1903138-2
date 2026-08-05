"""
Auth Middleware for Flask API
-----------------------------
Validates Supabase JWTs for protected endpoints.

Usage:
    from auth_middleware import require_auth

    @app.route('/api/bets', methods=['POST'])
    @require_auth
    def create_bet():
        user_id = request.user_id   # set by middleware
        ...
"""

import os
import functools
import jwt
from flask import request, jsonify

import logging

logger = logging.getLogger(__name__)

# Supabase JWT secret — the same as your project's JWT secret
# Found in Supabase Dashboard → Settings → API → JWT Secret
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')


def _is_deployed() -> bool:
    """True when this looks like a hosted run rather than a laptop.

    Heroku sets ``PORT``; the explicit escape hatch is for anyone who wants the
    permissive local behaviour anyway.
    """
    if os.environ.get('ALLOW_INSECURE_AUTH', '').strip().lower() in ('1', 'true', 'yes'):
        return False
    return bool(os.environ.get('PORT'))


def auth_is_configured() -> bool:
    """True when tokens can actually be verified."""
    return bool(SUPABASE_JWT_SECRET)


def _decode_token(token: str) -> dict | None:
    """Decode and verify a Supabase JWT. Returns payload or None.

    Without a secret nothing can be verified, so this returns None. It used to
    hand back a synthetic ``{'sub': 'anonymous'}`` payload, which made *any*
    string a valid token: the paywall and every per-user endpoint could be
    reached by sending `Authorization: Bearer whatever`.
    """
    if not SUPABASE_JWT_SECRET:
        return None

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=['HS256'],
            audience='authenticated',
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(fn):
    """Decorator: reject requests without a valid Supabase JWT."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # A hosted deployment with no secret cannot authenticate anyone. Serving
        # the endpoint anyway would hand every protected route — subscriptions,
        # bets, comments — to whoever asked, so it refuses instead.
        if not SUPABASE_JWT_SECRET and _is_deployed():
            logger.error(
                'SUPABASE_JWT_SECRET is not set — refusing to serve %s. '
                'Set it, or set ALLOW_INSECURE_AUTH=true for local work.',
                fn.__name__,
            )
            return jsonify({
                'error': 'Authentication is not configured on this server',
            }), 503

        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            # Local development without a secret: allow, but say so out loud.
            if not SUPABASE_JWT_SECRET:
                logger.warning(
                    'No SUPABASE_JWT_SECRET — %s served as anonymous (local mode)',
                    fn.__name__,
                )
                request.user_id = 'anonymous'  # type: ignore[attr-defined]
                return fn(*args, **kwargs)
            return jsonify({'error': 'Missing Authorization header'}), 401

        if not SUPABASE_JWT_SECRET:
            # A token was sent but cannot be checked. Treating it as valid is how
            # a forged token used to get in.
            logger.warning(
                'No SUPABASE_JWT_SECRET — token on %s cannot be verified, '
                'treating the caller as anonymous', fn.__name__,
            )
            request.user_id = 'anonymous'  # type: ignore[attr-defined]
            return fn(*args, **kwargs)

        token = auth_header.split(' ', 1)[1]
        payload = _decode_token(token)

        if payload is None:
            return jsonify({'error': 'Invalid or expired token'}), 401

        # Attach user id to request context
        request.user_id = payload.get('sub', 'anonymous')  # type: ignore[attr-defined]
        return fn(*args, **kwargs)

    return wrapper


def optional_auth(fn):
    """Decorator: parse JWT if present but don't reject unauthenticated."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')

        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ', 1)[1]
            payload = _decode_token(token)
            request.user_id = payload.get('sub', 'anonymous') if payload else 'anonymous'  # type: ignore[attr-defined]
        else:
            request.user_id = 'anonymous'  # type: ignore[attr-defined]

        return fn(*args, **kwargs)

    return wrapper
