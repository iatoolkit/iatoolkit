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
