# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The login widget shows only the sign-in methods the company allows (BL-031)."""

import os

import pytest
from flask import Flask, render_template

import iatoolkit

TEMPLATES = os.path.join(os.path.dirname(iatoolkit.__file__), "templates")
SSO = {"display_name": "Microsoft", "provider_type": "entra"}


@pytest.fixture
def app():
    app = Flask(__name__, template_folder=TEMPLATES)
    for rule, endpoint in [("/<company_short_name>/login/sso", "login_sso_start"),
                           ("/<company_short_name>/login/google", "login_google_start"),
                           ("/<company_short_name>/login", "login"),
                           ("/<company_short_name>/signup", "signup"),
                           ("/<company_short_name>/forgot", "forgot_password")]:
        app.add_url_rule(rule, endpoint, lambda **kw: "")
    return app


def _render(app, login_methods, google=True):
    with app.test_request_context("/acme/home?lang=es"):
        return render_template("_login_widget.html", company_short_name="acme",
                               login_methods=login_methods, google_login_enabled=google,
                               t=lambda key, **kw: f"[{key}{':' + kw['name'] if 'name' in kw else ''}]")


def test_everything_allowed_without_provider(app):
    html = _render(app, {"sso": None, "google": True, "password": True})

    assert "sso-login-button" not in html
    assert "/acme/login/google" in html
    assert 'id="login-form"' in html and "owner-password-access" not in html
    assert "/acme/signup" in html


def test_provider_button_and_password_form(app):
    html = _render(app, {"sso": SSO, "google": True, "password": True})

    assert "sso-login-button" in html
    assert "[ui.login_widget.sso_button:Microsoft]" in html
    assert "bi-microsoft" in html
    assert "/acme/login/sso?lang=es" in html


def test_password_off_hides_the_form_behind_the_owner_link(app):
    html = _render(app, {"sso": SSO, "google": False, "password": False}, google=False)

    assert "sso-login-button" in html
    assert "/acme/login/google" not in html
    assert 'id="owner-password-access"' in html
    assert "[ui.login_widget.owner_password_access]" in html
    assert "/acme/signup" not in html          # no account with a password to create
    assert "/acme/forgot" not in html


def test_without_login_methods_the_widget_behaves_as_before(app):
    with app.test_request_context("/acme/home"):
        html = render_template("_login_widget.html", company_short_name="acme",
                               google_login_enabled=False, t=lambda key, **kw: key)

    assert 'id="login-form"' in html and "sso-login-button" not in html
