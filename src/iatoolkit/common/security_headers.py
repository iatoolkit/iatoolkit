# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Security headers on every response (BL-030, PR-7).

Always on: HSTS on HTTPS requests, `X-Content-Type-Options: nosniff` and a
`Referrer-Policy` that keeps paths (which can carry tokens) out of other sites.

The Content-Security-Policy, `frame-ancestors` included, starts in report-only
mode: browsers report what the policy would block to `/csp-report`, which logs it,
and nothing is blocked. That tells, in production, which portals embed IAToolkit
and which outside resources pages really use, before the policy is enforced.

Configuration (config dict or environment):
- IAT_CSP_MODE: "report" (default), "enforce" or "off".
- IAT_FRAME_ANCESTORS: who may embed the pages, space separated
  (default "'self'"), e.g. "'self' https://portal.example.com".

Own resources are named by the app's own origin besides 'self'. The templates
build absolute URLs to /static (`url_for(..., _external=True)`) and the JS calls the
API at `request.url_root`. When another site serves a page through a reverse proxy
(Maxxa's internal portal does), 'self' is that site, and without the app's origin
the browser would block the chat's own CSS and JS while the CDNs still load.

`form-action` covers the redirects that follow a form's POST. A page whose form
sends the browser to another origin on purpose (the MCP consent screen, whose POST
redirects to the gateway's callback) names that origin with `allow_form_action()`,
and only that page's policy widens.
"""

import json
import logging
import os
from urllib.parse import urlsplit

from flask import Flask, g, request

CSP_REPORT_PATH = "/csp-report"
CSP_MODES = ("report", "enforce", "off")
DEFAULT_FRAME_ANCESTORS = "'self'"
# Sources the templates load today: the CDNs for scripts, styles and fonts, Google
# Tag Manager on the public site and Google Fonts.
CDN_SOURCES = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://code.jquery.com"
# Google Analytics: gtag.js (script-src above) sends its hits here.
ANALYTICS_CONNECT_SOURCES = ("https://*.google-analytics.com https://*.analytics.google.com "
                             "https://www.googletagmanager.com")
HSTS_VALUE = "max-age=31536000"
MAX_REPORT_BYTES = 16 * 1024


_FORM_ACTION_ATTR = "_iat_csp_form_action_origins"


def allow_form_action(url: str | None) -> bool:
    """Let the form of the page being rendered post to, or be redirected to, the origin
    of `url` (http/https only). Returns whether an origin was added."""
    origin = _plain_origin(url)
    if not origin:
        return False
    origins = getattr(g, _FORM_ACTION_ATTR, None)
    if origins is None:
        origins = []
        setattr(g, _FORM_ACTION_ATTR, origins)
    if origin not in origins:
        origins.append(origin)
    return True


def _plain_origin(url: str | None) -> str | None:
    """scheme://host[:port] of an http(s) URL, or None; nothing else reaches the header."""
    try:
        parts = urlsplit(str(url or "").strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("https", "http") or not host:
        return None
    if not all(ch.isalnum() or ch in ".-" for ch in host):
        return None
    return f"{parts.scheme}://{host}{f':{port}' if port else ''}"


def build_csp(frame_ancestors: str,
              form_action_origins: tuple[str, ...] | list[str] = (),
              app_origin: str | None = None) -> str:
    form_action = " ".join(["'self'", *form_action_origins])
    # 'self' plus the app's own origin: they differ when a proxy serves the page.
    own = f"'self' {app_origin}" if app_origin else "'self'"
    directives = [
        f"default-src {own}",
        f"script-src {own} 'unsafe-inline' {CDN_SOURCES} https://www.googletagmanager.com",
        f"style-src {own} 'unsafe-inline' {CDN_SOURCES} https://fonts.googleapis.com",
        f"font-src {own} data: {CDN_SOURCES} https://fonts.gstatic.com",
        f"img-src {own} data: blob: https:",
        f"connect-src {own} {ANALYTICS_CONNECT_SOURCES}",
        "frame-src 'self'",
        f"frame-ancestors {frame_ancestors}",
        "object-src 'none'",
        "base-uri 'self'",
        f"form-action {form_action}",
        f"report-uri {CSP_REPORT_PATH}",
    ]
    return "; ".join(directives)


def _setting(app: Flask, config: dict, key: str, default: str) -> str:
    value = config.get(key) if config else None
    if value is None:
        value = app.config.get(key)
    if value is None:
        value = os.getenv(key, default)
    return str(value or default).strip()


def install_security_headers(app: Flask, config: dict | None = None) -> None:
    if app.config.get("_IATOOLKIT_SECURITY_HEADERS_INSTALLED"):
        return
    app.config["_IATOOLKIT_SECURITY_HEADERS_INSTALLED"] = True

    mode = _setting(app, config, "IAT_CSP_MODE", "report").lower()
    if mode not in CSP_MODES:
        logging.warning("IAT_CSP_MODE=%s is not one of %s; using 'report'.", mode, ", ".join(CSP_MODES))
        mode = "report"
    frame_ancestors = _setting(app, config, "IAT_FRAME_ANCESTORS", DEFAULT_FRAME_ANCESTORS)
    csp_header = {"report": "Content-Security-Policy-Report-Only",
                  "enforce": "Content-Security-Policy"}.get(mode)

    @app.after_request
    def _security_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.is_secure:
            headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        if csp_header and "Content-Security-Policy" not in headers \
                and "Content-Security-Policy-Report-Only" not in headers:
            extra = tuple(getattr(g, _FORM_ACTION_ATTR, None) or ())
            headers[csp_header] = build_csp(frame_ancestors, extra, _plain_origin(request.host_url))
        return response

    app.add_url_rule(CSP_REPORT_PATH, "csp_report", _csp_report, methods=["POST"])


def _where(uri) -> str:
    """Origin and first path segment only: full URLs can carry tokens
    (finalize/<token>, links with codes), which must not reach the logs."""
    value = str(uri or "").strip()
    if not value or "://" not in value:
        return value[:40]  # keywords such as 'inline' or 'eval'
    parts = urlsplit(value)
    first = parts.path.strip("/").split("/", 1)[0]
    return f"{parts.scheme}://{parts.netloc}/{first[:40]}"


def _csp_report():
    """Logs what the policy reported; always answers 204 and never fails."""
    try:
        if (request.content_length or 0) > MAX_REPORT_BYTES:
            return "", 204
        payload = json.loads(request.get_data(cache=False, as_text=True) or "{}")
        reports = payload if isinstance(payload, list) else [payload]
        for item in reports[:10]:
            body = item.get("csp-report") or item.get("body") or {}
            logging.warning(
                "event=csp_violation directive=%s blocked=%s document=%s disposition=%s",
                body.get("effective-directive") or body.get("effectiveDirective") or body.get("violated-directive"),
                _where(body.get("blocked-uri") or body.get("blockedURL")),
                _where(body.get("document-uri") or body.get("documentURL")),
                body.get("disposition"),
            )
    except Exception as exc:  # a malformed report is not worth an error
        logging.debug("Ignoring an unreadable CSP report: %s", exc)
    return "", 204
