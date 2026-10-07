# tests/views/test_global_login_view.py
# IAToolkit is open source software.

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.login_view import (
    GlobalLoginView,
    GlobalGoogleLoginStartView,
    GoogleLoginCallbackView,
)
from iatoolkit.views.base_login_view import BaseLoginView


class TestGlobalLoginView:

    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.client = self.app.test_client()

        self.auth_service = MagicMock()
        self.google_auth_client = MagicMock()
        self.google_auth_client.is_enabled.return_value = True
        self.google_auth_client.build_authorization_url.return_value = "https://accounts.google.com/mock"
        self.i18n_service = MagicMock()
        self.i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        original_global_init = GlobalLoginView.__init__
        monkeypatch.setattr(
            GlobalLoginView, "__init__",
            lambda instance, **kwargs: original_global_init(
                instance, auth_service=self.auth_service, i18n_service=self.i18n_service
            ),
        )
        original_start_init = GlobalGoogleLoginStartView.__init__
        monkeypatch.setattr(
            GlobalGoogleLoginStartView, "__init__",
            lambda instance, **kwargs: original_start_init(
                instance, google_auth_client=self.google_auth_client, i18n_service=self.i18n_service
            ),
        )
        original_base_init = BaseLoginView.__init__
        monkeypatch.setattr(
            BaseLoginView, "__init__",
            lambda instance, **kwargs: original_base_init(
                instance,
                profile_service=MagicMock(),
                auth_service=self.auth_service,
                jwt_service=MagicMock(),
                branding_service=MagicMock(),
                prompt_service=MagicMock(),
                config_service=MagicMock(),
                query_service=MagicMock(),
                utility=MagicMock(),
                i18n_service=self.i18n_service,
            ),
        )

        self.app.add_url_rule("/auth/login", view_func=GlobalLoginView.as_view("global_login"))
        self.app.add_url_rule(
            "/auth/login/google",
            view_func=GlobalGoogleLoginStartView.as_view("global_login_google_start"),
        )
        self.app.add_url_rule(
            "/auth/google/callback",
            view_func=GoogleLoginCallbackView.as_view("login_google_callback"),
        )

        @self.app.route("/home", endpoint="root_redirect")
        def root_redirect():
            return "Root redirect", 200

    @patch("iatoolkit.views.login_view.render_template", return_value="LOGIN")
    def test_get_renders_login_with_safe_next(self, mock_render):
        resp = self.client.get("/auth/login?lang=es&next=/mcp/authorize?x=1")

        assert resp.status_code == 200
        assert mock_render.call_args.args[0] == "login_global.html"
        assert mock_render.call_args.kwargs["login_next"] == "/mcp/authorize?x=1"
        assert mock_render.call_args.kwargs["lang"] == "es"

    @patch("iatoolkit.views.login_view.render_template", return_value="LOGIN")
    def test_get_drops_offsite_next(self, mock_render):
        self.client.get("/auth/login?next=https://evil.example/steal")

        assert mock_render.call_args.kwargs["login_next"] is None

    def test_post_success_returns_to_next(self):
        self.auth_service.login_global_local_user.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
        }

        resp = self.client.post(
            "/auth/login",
            data={"email": "user@example.com", "password": "secret", "next": "/mcp/authorize?x=1"},
        )

        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://localhost/mcp/authorize?x=1"
        self.auth_service.login_global_local_user.assert_called_once_with(
            email="user@example.com", password="secret"
        )

    @patch("iatoolkit.views.login_view.render_template", return_value="LOGIN")
    def test_post_failure_renders_400_and_does_not_follow_next(self, mock_render):
        self.auth_service.login_global_local_user.return_value = {"success": False, "message": "bad"}

        resp = self.client.post(
            "/auth/login",
            data={"email": "user@example.com", "password": "wrong", "next": "/mcp/authorize"},
        )

        assert resp.status_code == 400
        assert mock_render.call_args.kwargs["login_next"] == "/mcp/authorize"
        assert mock_render.call_args.kwargs["form_data"] == {"email": "user@example.com"}

    @patch("iatoolkit.views.login_view.SessionManager")
    def test_google_start_stores_global_state(self, mock_session_manager):
        mock_session_manager.get.return_value = {}

        resp = self.client.get("/auth/login/google?lang=es&next=/mcp/authorize")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "https://accounts.google.com/mock"
        saved_state = next(iter(mock_session_manager.set.call_args.args[1].values()))
        assert saved_state["global"] is True
        assert saved_state["next_target"] == "/mcp/authorize"
        assert "company_short_name" not in saved_state

    @patch("iatoolkit.views.login_view.SessionManager")
    def test_callback_with_global_state_identifies_and_returns_to_next(self, mock_session_manager):
        mock_session_manager.get.return_value = {
            "oauth-state": {"nonce": "n", "global": True, "lang": "es", "next_target": "/mcp/authorize?x=1"},
        }
        self.auth_service.login_global_google_user.return_value = {
            "success": True,
            "user_identifier": "user@example.com",
        }

        resp = self.client.get("/auth/google/callback?state=oauth-state&code=auth-code")

        assert resp.status_code == 302
        assert resp.headers["Location"] == "http://localhost/mcp/authorize?x=1"
        call = self.auth_service.login_global_google_user.call_args.kwargs
        assert call["code"] == "auth-code"
        assert call["nonce"] == "n"
        self.auth_service.login_google_user.assert_not_called()
        mock_session_manager.remove.assert_called_once_with("google_oauth_states")

    @patch("iatoolkit.views.login_view.SessionManager")
    def test_callback_with_global_state_failure_returns_to_global_login(self, mock_session_manager):
        mock_session_manager.get.return_value = {
            "oauth-state": {"nonce": "n", "global": True, "lang": "es", "next_target": "/mcp/authorize"},
        }
        self.auth_service.login_global_google_user.return_value = {"success": False, "message": "nope"}

        resp = self.client.get("/auth/google/callback?state=oauth-state&code=auth-code")

        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/auth/login?")
        assert resp.headers["Location"] == "/auth/login?lang=es&next=/mcp/authorize"
