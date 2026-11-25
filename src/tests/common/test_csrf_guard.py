# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging

import pytest
from flask import Flask

from iatoolkit.common.csrf_guard import csrf_verdict, install_csrf_guard

OWN = "https://www.iatoolkit.com"


def _verdict(**overrides):
    args = dict(method="POST", has_authorization=False, has_session_cookie=True, endpoint="some_view",
                sec_fetch_site=None, origin=None, referer=None, own_origin=OWN, trusted_origins=frozenset())
    args.update(overrides)
    return csrf_verdict(**args)


@pytest.mark.parametrize("overrides, reason", [
    ({"method": "GET"}, "safe_method"),
    ({"has_authorization": True, "sec_fetch_site": "cross-site", "origin": "https://evil.example"},
     "authorization_header"),
    ({"has_session_cookie": False, "sec_fetch_site": "cross-site"}, "no_session_cookie"),
    ({"endpoint": "csp_report", "sec_fetch_site": "cross-site"}, "exempt_endpoint"),
    ({"sec_fetch_site": "same-origin"}, "same_origin_fetch"),
    ({"sec_fetch_site": "none"}, "same_origin_fetch"),
    ({"origin": OWN}, "trusted_origin"),
    ({"referer": f"{OWN}/acme/admin/dashboard?x=1"}, "trusted_origin"),
    ({"origin": "https://portal.example.com", "trusted_origins": frozenset({"https://portal.example.com"})},
     "trusted_origin"),
    ({}, "no_browser_signal"),
])
def test_allowed(overrides, reason):
    assert _verdict(**overrides) == (True, reason)


@pytest.mark.parametrize("overrides, reason", [
    ({"sec_fetch_site": "cross-site", "origin": "https://evil.example"}, "foreign_origin"),
    ({"origin": "https://evil.example"}, "foreign_origin"),
    ({"referer": "https://evil.example/page"}, "foreign_origin"),
    ({"sec_fetch_site": "cross-site"}, "sec_fetch_site_cross-site"),
    # a sibling subdomain is not this origin unless it is trusted
    ({"sec_fetch_site": "same-site", "origin": "https://mcp.iatoolkit.com"}, "foreign_origin"),
    ({"method": "DELETE", "origin": "null"}, "no_browser_signal"),
])
def test_refused_or_passed_through(overrides, reason):
    allowed, got = _verdict(**overrides)
    assert got == reason
    assert allowed is (reason == "no_browser_signal")


def _client(config=None):
    app = Flask(__name__)
    app.config["SESSION_COOKIE_NAME"] = "session"
    install_csrf_guard(app, config or {})

    @app.route("/change", methods=["POST"])
    def change():
        return "changed"

    client = app.test_client()
    client.set_cookie("session", "abc")
    return client


def test_a_cross_site_post_with_the_session_is_refused(caplog):
    with caplog.at_level(logging.WARNING):
        response = _client().post("/change", headers={"Sec-Fetch-Site": "cross-site",
                                                     "Origin": "https://evil.example"})

    assert response.status_code == 403
    assert "event=csrf_blocked" in caplog.text


def test_a_same_origin_post_passes():
    response = _client().post("/change", headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://localhost"})
    assert response.status_code == 200


def test_report_mode_logs_but_lets_it_through(caplog):
    with caplog.at_level(logging.WARNING):
        response = _client({"IAT_CSRF_MODE": "report"}).post(
            "/change", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})

    assert response.status_code == 200
    assert "event=csrf_would_block" in caplog.text


def test_off_mode_installs_nothing():
    response = _client({"IAT_CSRF_MODE": "off"}).post(
        "/change", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})
    assert response.status_code == 200


def test_a_trusted_origin_from_config_passes():
    response = _client({"IAT_CSRF_TRUSTED_ORIGINS": "https://portal.example.com/ https://other.example"}).post(
        "/change", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://portal.example.com"})
    assert response.status_code == 200


def test_an_origin_declared_in_cors_may_post_with_the_session():
    """BL-030: Maxxa's portal serves the chat and calls back cross-site with the cookie;
    its origin is in the company's cors_origin, which the guard trusts."""
    app = Flask(__name__)
    app.config["SESSION_COOKIE_NAME"] = "session"
    install_csrf_guard(app, {})
    app.config["IAT_CORS_ORIGINS"] = ["https://portal-interno.maxxa.cl"]  # set later by _setup_cors

    @app.route("/change", methods=["POST"])
    def change():
        return "changed"

    client = app.test_client()
    client.set_cookie("session", "abc")
    portal = client.post("/change", headers={"Sec-Fetch-Site": "cross-site",
                                             "Origin": "https://portal-interno.maxxa.cl"})
    other = client.post("/change", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})

    assert portal.status_code == 200
    assert other.status_code == 403
