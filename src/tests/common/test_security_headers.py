# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import json
import logging

from flask import Flask

from iatoolkit.common.security_headers import CSP_REPORT_PATH, install_security_headers


def _client(config=None):
    app = Flask(__name__)
    install_security_headers(app, config or {})

    @app.route("/page")
    def page():
        return "ok"

    @app.route("/own-csp")
    def own_csp():
        return "ok", 200, {"Content-Security-Policy": "default-src 'none'"}

    return app.test_client()


def test_always_on_headers():
    response = _client().get("/page")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_hsts_only_over_https():
    client = _client()

    assert "Strict-Transport-Security" not in client.get("/page").headers
    assert client.get("/page", base_url="https://localhost").headers["Strict-Transport-Security"] == "max-age=31536000"


def test_csp_starts_in_report_only_with_self_as_frame_ancestor():
    headers = _client().get("/page").headers

    assert "Content-Security-Policy" not in headers
    policy = headers["Content-Security-Policy-Report-Only"]
    assert "frame-ancestors 'self'" in policy
    assert f"report-uri {CSP_REPORT_PATH}" in policy
    assert "object-src 'none'" in policy


def test_enforce_mode_and_configured_frame_ancestors():
    headers = _client({"IAT_CSP_MODE": "enforce",
                       "IAT_FRAME_ANCESTORS": "'self' https://portal.example.com"}).get("/page").headers

    assert "Content-Security-Policy-Report-Only" not in headers
    assert "frame-ancestors 'self' https://portal.example.com" in headers["Content-Security-Policy"]


def test_off_mode_sends_no_csp_but_keeps_the_other_headers():
    headers = _client({"IAT_CSP_MODE": "off"}).get("/page").headers

    assert "Content-Security-Policy" not in headers
    assert "Content-Security-Policy-Report-Only" not in headers
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_a_view_that_sets_its_own_csp_keeps_it():
    headers = _client().get("/own-csp").headers

    assert headers["Content-Security-Policy"] == "default-src 'none'"
    assert "Content-Security-Policy-Report-Only" not in headers


def test_a_csp_report_is_logged_without_full_urls(caplog):
    report = {"csp-report": {
        "document-uri": "https://www.iatoolkit.com/acme/finalize/eyJhbGciOiJIUzI1NiJ9.secret-token?x=1",
        "blocked-uri": "https://evil.example.com/steal.js?token=abc",
        "effective-directive": "script-src-elem",
        "disposition": "report",
    }}

    with caplog.at_level(logging.WARNING):
        response = _client().post(CSP_REPORT_PATH, data=json.dumps(report),
                                  content_type="application/csp-report")

    assert response.status_code == 204
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "event=csp_violation" in logged
    assert "directive=script-src-elem" in logged
    assert "https://evil.example.com/steal.js" in logged
    assert "secret-token" not in logged
    assert "token=abc" not in logged


def test_a_malformed_or_huge_report_is_ignored():
    client = _client()

    assert client.post(CSP_REPORT_PATH, data="not json", content_type="application/csp-report").status_code == 204
    assert client.post(CSP_REPORT_PATH, data="x" * 20000, content_type="application/csp-report").status_code == 204


def test_google_analytics_can_send_its_hits():
    """Found in production (report-only): gtag.js posts to region1.google-analytics.com."""
    policy = _client().get("/page").headers["Content-Security-Policy-Report-Only"]
    connect = next(d for d in policy.split("; ") if d.startswith("connect-src"))
    assert "https://*.google-analytics.com" in connect


# --- BL-034 R1: a page whose form redirects to another origin names it ---

def _app(config=None):
    app = Flask(__name__)
    install_security_headers(app, config or {})

    @app.route("/")
    def index():
        return "ok"

    return app


def _csp_of(response):
    return response.headers.get("Content-Security-Policy-Report-Only") or response.headers.get("Content-Security-Policy")


def _form_action(response):
    return next(d for d in _csp_of(response).split("; ") if d.startswith("form-action"))


def test_form_action_is_self_by_default():
    app = _app()
    assert _form_action(app.test_client().get("/")) == "form-action 'self'"


def test_a_page_can_allow_its_form_to_reach_one_more_origin():
    from iatoolkit.common.security_headers import allow_form_action
    app = _app({"IAT_CSP_MODE": "enforce"})

    @app.get("/consent")
    def consent():
        allow_form_action("https://mcp.example.com/acme/oauth/callback?x=1")
        allow_form_action("https://mcp.example.com/other")
        return "consent"

    assert _form_action(app.test_client().get("/consent")) == "form-action 'self' https://mcp.example.com"
    # only that page widens
    assert _form_action(app.test_client().get("/")) == "form-action 'self'"


def test_only_a_plain_http_origin_reaches_the_policy():
    from iatoolkit.common.security_headers import allow_form_action
    app = _app()
    results = {}

    @app.get("/try")
    def try_():
        for value in ("javascript:alert(1)", "https://a.example.com; script-src *", "data:text/html,x",
                      "https://user:pw@b.example.com:8443/cb", "", None):
            results[value] = allow_form_action(value)
        return "ok"

    response = app.test_client().get("/try")

    assert _form_action(response) == "form-action 'self' https://b.example.com:8443"
    assert results["https://user:pw@b.example.com:8443/cb"] is True
    assert not any(v for k, v in results.items() if k != "https://user:pw@b.example.com:8443/cb")


def test_own_resources_allowed_by_the_app_origin_when_a_proxy_serves_the_page():
    # A portal that proxies the chat makes 'self' its own origin; the absolute
    # /static URLs and API calls point at the app's origin, which must stay allowed.
    policy = _client({"IAT_CSP_MODE": "enforce"}).get(
        "/page", base_url="https://iatoolkit.example.com").headers["Content-Security-Policy"]

    for directive in ("default-src", "script-src", "style-src", "font-src", "img-src", "connect-src"):
        assert f"{directive} 'self' https://iatoolkit.example.com" in policy
    assert "frame-ancestors 'self';" in policy
    assert "form-action 'self';" in policy
