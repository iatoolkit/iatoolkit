# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Cross-site request forgery guard (BL-030, PR-8).

A request that changes something (POST, PUT, PATCH, DELETE), carries the session
cookie and no Authorization header is accepted only when the browser says it
comes from this same site:

1. `Sec-Fetch-Site: same-origin` (or `none`, typed by the person) is enough; every
   current browser sends it.
2. Otherwise its `Origin`, or the origin of its `Referer`, must be this host or one
   listed in IAT_CSRF_TRUSTED_ORIGINS.
3. A request with neither signal is not from a browser, and a forgery needs a
   browser, so it passes.

No client changes are needed: the chat, the admin console, tenant apps and forms
already send these headers, and a page embedded in another site's iframe still
calls its own origin. Calls with an Authorization header (API keys, bearer tokens)
and requests without the session cookie are out of scope: nothing ambient to abuse.

Configuration (config dict or environment):
- IAT_CSRF_MODE: "enforce" (default), "report" (log what would be blocked) or "off".
- IAT_CSRF_TRUSTED_ORIGINS: other origins allowed to post with the session,
  space separated, e.g. "https://portal.example.com".
"""

import logging
import os
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SAME_SITE_SIGNALS = frozenset({"same-origin", "none"})
CSRF_MODES = ("enforce", "report", "off")
# Endpoints a browser reaches across sites on purpose and that change nothing a
# session owns.
EXEMPT_ENDPOINTS = frozenset({"csp_report"})


def _setting(app: Flask, config: dict | None, key: str, default: str) -> str:
    value = config.get(key) if config else None
    if value is None:
        value = app.config.get(key)
    if value is None:
        value = os.getenv(key, default)
    return str(value or default).strip()


def _origin_of(url: str | None) -> str | None:
    value = str(url or "").strip()
    if not value or value == "null":
        return None
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def csrf_verdict(*, method: str, has_authorization: bool, has_session_cookie: bool, endpoint: str | None,
                 sec_fetch_site: str | None, origin: str | None, referer: str | None,
                 own_origin: str, trusted_origins: frozenset[str]) -> tuple[bool, str]:
    """(allowed, reason). Pure, so every rule can be tested on its own."""
    if method.upper() not in UNSAFE_METHODS:
        return True, "safe_method"
    if has_authorization:
        return True, "authorization_header"
    if not has_session_cookie:
        return True, "no_session_cookie"
    if endpoint in EXEMPT_ENDPOINTS:
        return True, "exempt_endpoint"

    fetch_site = str(sec_fetch_site or "").strip().lower()
    if fetch_site in SAME_SITE_SIGNALS:
        return True, "same_origin_fetch"

    source = _origin_of(origin) or _origin_of(referer)
    if source:
        if source == own_origin.lower() or source in trusted_origins:
            return True, "trusted_origin"
        return False, "foreign_origin"
    if fetch_site:  # cross-site or same-site with no origin to trust
        return False, f"sec_fetch_site_{fetch_site}"
    return True, "no_browser_signal"


def install_csrf_guard(app: Flask, config: dict | None = None) -> None:
    if app.config.get("_IATOOLKIT_CSRF_GUARD_INSTALLED"):
        return
    app.config["_IATOOLKIT_CSRF_GUARD_INSTALLED"] = True

    mode = _setting(app, config, "IAT_CSRF_MODE", "enforce").lower()
    if mode not in CSRF_MODES:
        logging.warning("IAT_CSRF_MODE=%s is not one of %s; using 'enforce'.", mode, ", ".join(CSRF_MODES))
        mode = "enforce"
    if mode == "off":
        logging.warning("CSRF guard is off (IAT_CSRF_MODE=off).")
        return
    trusted = frozenset(
        origin for origin in (_origin_of(item) for item in
                              _setting(app, config, "IAT_CSRF_TRUSTED_ORIGINS", "").split())
        if origin)

    @app.before_request
    def _csrf_guard():
        cookie_name = app.config.get("SESSION_COOKIE_NAME") or "session"
        allowed, reason = csrf_verdict(
            method=request.method,
            has_authorization=bool(request.headers.get("Authorization")),
            has_session_cookie=cookie_name in request.cookies,
            endpoint=request.endpoint,
            sec_fetch_site=request.headers.get("Sec-Fetch-Site"),
            origin=request.headers.get("Origin"),
            referer=request.headers.get("Referer"),
            own_origin=f"{request.scheme}://{request.host}",
            trusted_origins=trusted,
        )
        if allowed:
            return None

        first_segment = request.path.strip("/").split("/", 1)[0][:40]
        logging.warning(
            "event=csrf_%s method=%s path=/%s reason=%s origin=%s sec_fetch_site=%s",
            "blocked" if mode == "enforce" else "would_block", request.method, first_segment, reason,
            _origin_of(request.headers.get("Origin")) or _origin_of(request.headers.get("Referer")),
            request.headers.get("Sec-Fetch-Site"),
        )
        if mode == "report":
            return None
        return jsonify({"error": "forbidden", "error_message": "Cross-site request refused."}), 403
