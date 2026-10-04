from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from flask import Flask, get_flashed_messages, url_for
from flask_injector import FlaskInjector

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.views.account_view import AccountView


@pytest.fixture
def account_app():
    root = Path(__file__).parents[2] / "iatoolkit"
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.secret_key = "test-secret"
    app.testing = True
    profile = MagicMock(spec=ProfileService)
    profile.get_company_by_short_name.return_value = SimpleNamespace(name="ACME")
    profile.get_current_session_info.return_value = {
        "company_short_name": "acme", "user_identifier": "user@acme.com",
        "profile": {"user_fullname": "Ana Perez", "user_is_local": True},
    }
    profile.get_account_profile.return_value = dict(
        first_name="Ana", last_name="Perez", full_name="Ana Perez",
        email="user@acme.com", role="user", auth_method="local",
        can_edit_name=True, language="es", language_is_browser_only=False,
    )
    branding = MagicMock(spec=BrandingService)
    branding.get_company_branding.return_value = {"name": "ACME", "css_variables": ""}
    config = MagicMock(spec=ConfigurationService)
    config.get_llm_configuration.return_value = ("gpt-test", [{"id": "gpt-test", "label": "Test model"}])
    config.get_llm_request_defaults.return_value = {}
    i18n = MagicMock(spec=I18nService)
    translations = yaml.safe_load((root / "locales/es.yaml").read_text())
    def translate(key, lang=None):
        value = translations
        for part in key.split("."):
            value = value[part]
        return value
    i18n.t.side_effect = translate
    app.jinja_env.globals.update(t=translate, optional_url_for=lambda *args, **kwargs: None)
    app.add_url_rule("/<company_short_name>/home", "home", lambda **kw: "HOME")
    app.add_url_rule("/<company_short_name>/chat", "chat", lambda **kw: "CHAT")
    app.add_url_rule("/<company_short_name>/account", view_func=AccountView.as_view(
        "account", profile_service=profile, branding_service=branding, i18n_service=i18n,
        config_service=config,
    ))

    @app.context_processor
    def inject_messages():
        return {"flashed_messages": get_flashed_messages(with_categories=True), "url_for": url_for}

    FlaskInjector(app=app)
    return app, profile


def test_profile_renders_without_tokens(account_app):
    app, _ = account_app
    response = app.test_client().get("/acme/account")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'value="Ana"' in html
    assert 'user@acme.com' in html
    assert 'create_token' not in html
    assert 'mcp_tokens' not in html
    assert 'id="company-section"' in html
    assert 'data-account-page="true"' in html
    assert 'id="llm-model-button"' in html
    assert 'data-chat-action="history-button"' in html
    assert 'data-chat-action="logout-button"' in html
    assert 'window.defaultLlmModel = "gpt-test"' in html


@pytest.mark.parametrize("info", [{}, {"company_short_name": "other", "user_identifier": "someone", "profile": {"name": "Other"}},
                                  {"company_short_name": "acme", "user_identifier": "user@acme.com", "profile": {}}])
def test_invalid_session_redirects(account_app, info):
    app, profile = account_app
    profile.get_current_session_info.return_value = info
    response = app.test_client().get("/acme/account")
    assert response.status_code == 302
    assert response.location.endswith("/acme/home")


def test_unknown_company_is_404(account_app):
    app, profile = account_app
    profile.get_company_by_short_name.return_value = None
    assert app.test_client().get("/missing/account").status_code == 404


@pytest.mark.parametrize("action", ["create_token", "revoke_token"])
def test_old_token_actions_are_rejected(account_app, action):
    app, profile = account_app
    response = app.test_client().post("/acme/account", data={"action": action})
    assert response.status_code == 400
    profile.update_account.assert_not_called()


def test_profile_save_requires_csrf_and_uses_session_identity(account_app):
    app, profile = account_app
    profile.update_account.return_value = {"success": True}
    client = app.test_client()
    assert client.post("/acme/account", data={"action": "update_profile"}).status_code == 400
    profile.update_account.assert_not_called()
    client.get("/acme/account")
    with client.session_transaction() as session:
        csrf = session["account_csrf_token"]
    response = client.post("/acme/account", data={
        "action": "update_profile", "csrf_token": csrf, "first_name": "Ana", "last_name": "Lopez",
        "user_identifier": "victim@acme.com", "user_role": "owner",
    })
    assert response.status_code == 303
    args = profile.update_account.call_args
    assert args.args[1]["user_identifier"] == "user@acme.com"
    assert args.kwargs == dict(action="update_profile", first_name="Ana", last_name="Lopez", language="")


def test_preferences_and_managed_profile_render(account_app):
    app, profile = account_app
    client = app.test_client()
    assert 'name="language"' in client.get("/acme/account?section=preferences").get_data(as_text=True)
    profile.get_account_profile.return_value.update(can_edit_name=False, auth_method="google")
    html = client.get("/acme/account").get_data(as_text=True)
    assert 'name="first_name"' not in html
    assert 'Google' in html


def test_preferences_save_redirects_to_preferences(account_app):
    app, profile = account_app
    profile.update_account.return_value = {"success": True}
    client = app.test_client()
    client.get("/acme/account?section=preferences")
    with client.session_transaction() as session:
        csrf = session["account_csrf_token"]
    response = client.post("/acme/account", data={
        "action": "update_preferences", "language": "en", "csrf_token": csrf,
    })
    assert response.status_code == 303
    assert response.location.endswith("/acme/account?section=preferences")
    assert profile.update_account.call_args.kwargs["language"] == "en"


def test_validation_error_preserves_name_input(account_app):
    app, profile = account_app
    profile.update_account.return_value = {"error": "ui.account.invalid_name"}
    client = app.test_client()
    client.get("/acme/account")
    with client.session_transaction() as session:
        csrf = session["account_csrf_token"]
    response = client.post("/acme/account", data={
        "action": "update_profile", "csrf_token": csrf, "first_name": "Changed", "last_name": "",
    })
    assert response.status_code == 400
    assert 'value="Changed"' in response.get_data(as_text=True)
    assert "Completa nombre y apellido" in response.get_data(as_text=True)


def test_saved_notice_is_rendered_once_with_flask_injector(account_app):
    app, profile = account_app
    profile.update_account.return_value = {"success": True}
    client = app.test_client()
    client.get("/acme/account")
    with client.session_transaction() as session:
        csrf = session["account_csrf_token"]
    response = client.post("/acme/account", data={
        "action": "update_profile", "csrf_token": csrf, "first_name": "Ana", "last_name": "Perez",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert response.get_data(as_text=True).count("Cambios guardados.") == 1
    assert "Cambios guardados." not in client.get("/acme/account").get_data(as_text=True)
