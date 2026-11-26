# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Pending OAuth / OpenID Connect sign-ins, kept outside the Flask session.

A sign-in leaves IAToolkit for the provider and comes back to a callback with a
``state``. What the callback needs (company, nonce, PKCE verifier, where to go next)
is stored here under that ``state`` while the person is at the provider.

It used to live in the server-side Flask session, and that loses it. Every request
writes back the whole session it read when it started (``SESSION_REFRESH_EACH_REQUEST``
keeps the idle timeout sliding), so a slow request from another tab that started
before the sign-in and finished while the person was at the provider wrote back a
session without the pending entry, and the callback failed with a missing state. In
production a 50-second admin dashboard request erased a Google sign-in four seconds
before Google came back.

Here each pending sign-in is its own Redis key with a TTL, so no other request can
overwrite it. The browser that started the sign-in is still the only one that can
finish it: it gets a random binding cookie, the entry keeps a hash of it, and the
callback must present the same cookie. A ``state`` alone (a forged link) is not enough.

Without Redis (a local install with no REDIS_URL), entries fall back to the session.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time

from flask import current_app, g, request

from iatoolkit.common.session_manager import SessionManager
from iatoolkit.infra.redis_session_manager import RedisSessionManager

BINDING_COOKIE = "iat_oauth_binding"
TTL_SECONDS = 10 * 60
_KEY_PREFIX = "oauth_state"
_SESSION_FALLBACK_KEY = "oauth_pending_states"
_NEW_BINDING_ATTR = "_iat_oauth_binding"


def save(namespace: str, state: str, entry: dict) -> None:
    """Keep a pending sign-in until its callback (or TTL_SECONDS). Call
    `with_binding_cookie` on the response that sends the browser to the provider."""
    binding = _request_binding() or secrets.token_urlsafe(32)
    setattr(g, _NEW_BINDING_ATTR, binding)
    record = {"entry": entry, "binding": _digest(binding), "issued_at": time.time()}
    key = _key(namespace, state)
    try:
        RedisSessionManager.set(key, json.dumps(record), ex=TTL_SECONDS)
        return
    except Exception as exc:
        logging.warning("oauth state store: Redis unavailable, using the session (%s)", type(exc).__name__)
    pending = _session_records()
    pending[key] = record
    SessionManager.set(_SESSION_FALLBACK_KEY, pending)


def peek(namespace: str, state: str) -> dict | None:
    """The pending sign-in for `state`, if this browser started it and it has not expired."""
    if not state:
        return None
    record = _load(_key(namespace, state))
    if not isinstance(record, dict) or not isinstance(record.get("entry"), dict):
        return None
    if time.time() - float(record.get("issued_at") or 0) >= TTL_SECONDS:
        return None
    binding = _request_binding()
    if not binding or not hmac.compare_digest(str(record.get("binding") or ""), _digest(binding)):
        logging.warning("oauth state store: state presented by a browser that did not start the sign-in. namespace=%s",
                        namespace)
        return None
    return record["entry"]


def discard(namespace: str, state: str) -> None:
    """Forget a pending sign-in: each state is used once."""
    if not state:
        return
    key = _key(namespace, state)
    try:
        RedisSessionManager.remove(key)
    except Exception as exc:
        logging.warning("oauth state store: Redis unavailable, using the session (%s)", type(exc).__name__)
    pending = SessionManager.get(_SESSION_FALLBACK_KEY)
    if isinstance(pending, dict) and key in pending:
        pending.pop(key)
        if pending:
            SessionManager.set(_SESSION_FALLBACK_KEY, pending)
        else:
            SessionManager.remove(_SESSION_FALLBACK_KEY)


def take(namespace: str, state: str) -> dict | None:
    """`peek` and `discard` in one step."""
    entry = peek(namespace, state)
    discard(namespace, state)
    return entry


def with_binding_cookie(response):
    """Set (or refresh) the binding cookie on the response that leaves for the provider."""
    binding = getattr(g, _NEW_BINDING_ATTR, None)
    if binding:
        response.set_cookie(
            BINDING_COOKIE,
            binding,
            max_age=TTL_SECONDS,
            path="/",
            secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")),
            httponly=True,
            # Lax: the provider sends the browser back with a top-level GET from its own site.
            samesite="Lax",
        )
    return response


def _key(namespace: str, state: str) -> str:
    return f"{_KEY_PREFIX}:{namespace}:{state}"


def _digest(binding: str) -> str:
    return hashlib.sha256(binding.encode("utf-8")).hexdigest()


def _request_binding() -> str | None:
    value = (request.cookies.get(BINDING_COOKIE) or "").strip()
    return value or None


def _session_records() -> dict:
    pending = SessionManager.get(_SESSION_FALLBACK_KEY, {})
    if not isinstance(pending, dict):
        return {}
    now = time.time()
    return {key: record for key, record in pending.items()
            if isinstance(record, dict) and now - float(record.get("issued_at") or 0) < TTL_SECONDS}


def _load(key: str) -> dict | None:
    try:
        raw = RedisSessionManager.get(key, "")
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logging.warning("oauth state store: Redis unavailable, using the session (%s)", type(exc).__name__)
    return _session_records().get(key)
