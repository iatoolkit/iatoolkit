# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Rate limits on the doors that guess credentials (BL-030, PR-10).

Fixed windows in Redis, per client IP and, where there is one, per account. A
limit is a (max_hits, window_seconds) pair; `over_limit` counts one hit and says
whether it went past the limit. Failures are counted with `record_failure`, and
`clear` forgets them after a success.

Fails open: if Redis cannot answer, nothing is blocked. Sessions live in the same
Redis, so with it down there is no login to protect anyway, and a limiter that
locked everybody out would turn a Redis hiccup into an outage.

IAT_RATE_LIMITS=off turns every limit off (automated end-to-end tests).
"""

import hashlib
import logging
import os

from iatoolkit.infra.redis_session_manager import RedisSessionManager

KEY_PREFIX = "iat:ratelimit"

# (max hits, window in seconds)
LOGIN_FAILURES_PER_ACCOUNT = (10, 15 * 60)
LOGIN_ATTEMPTS_PER_IP = (50, 15 * 60)
PASSWORD_RESET_REQUESTS_PER_ACCOUNT = (5, 60 * 60)
PASSWORD_RESET_REQUESTS_PER_IP = (20, 60 * 60)
PASSWORD_CHANGE_ATTEMPTS_PER_IP = (20, 15 * 60)
TOKEN_REDEEMS_PER_IP = (60, 60)
INVALID_API_KEYS_PER_IP = (30, 60)


def enabled() -> bool:
    return os.getenv("IAT_RATE_LIMITS", "on").strip().lower() not in ("off", "false", "0")


def _key(bucket: str, identity: str) -> str:
    # Hashed so emails and IPs are not readable from Redis keys.
    digest = hashlib.sha256(str(identity or "").strip().lower().encode("utf-8")).hexdigest()[:32]
    return f"{KEY_PREFIX}:{bucket}:{digest}"


def _incr(key: str, window_seconds: int) -> int:
    try:
        pipe = RedisSessionManager.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl is None or int(ttl) < 0:
            RedisSessionManager.pipeline().expire(key, window_seconds).execute()
        return int(count)
    except Exception as exc:
        logging.warning("rate limiter unavailable, letting the request through (%s)", exc)
        return 0


def _peek(key: str) -> int | None:
    """The current count, or None when Redis cannot answer (which never blocks)."""
    try:
        return int(RedisSessionManager.get(key, "0") or 0)
    except Exception as exc:
        logging.warning("rate limiter unavailable, letting the request through (%s)", exc)
        return None


def over_limit(bucket: str, identity: str | None, limit: tuple[int, int]) -> bool:
    """Counts one hit for `identity` and says whether it went past `limit`."""
    if not identity or not enabled():
        return False
    max_hits, window = limit
    over = _incr(_key(bucket, identity), window) > max_hits
    if over:
        logging.warning("event=rate_limited bucket=%s", bucket)
    return over


def is_blocked(bucket: str, identity: str | None, limit: tuple[int, int]) -> bool:
    """Whether `identity` already used up `limit`, without counting a hit."""
    if not identity or not enabled():
        return False
    count = _peek(_key(bucket, identity))
    blocked = count is not None and count >= limit[0]
    if blocked:
        logging.warning("event=rate_limited bucket=%s", bucket)
    return blocked


def record_failure(bucket: str, identity: str | None, limit: tuple[int, int]) -> None:
    if identity and enabled():
        _incr(_key(bucket, identity), limit[1])


def clear(bucket: str, identity: str | None) -> None:
    if not identity:
        return
    try:
        RedisSessionManager.remove(_key(bucket, identity))
    except Exception as exc:
        logging.warning("rate limiter unavailable (%s)", exc)


def client_ip(request) -> str | None:
    """The real client IP; same rules as the signup guard (Cloudflare, proxy hops)."""
    from iatoolkit.services.signup_guard_service import SignupGuardService
    return SignupGuardService.client_ip(request)
