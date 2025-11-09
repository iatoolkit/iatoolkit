# tests/views/test_login_view.py
# IAToolkit is open source software.

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.login_view import LoginView, FinalizeContextView
from iatoolkit.views.base_login_view import BaseLoginView


class TestLoginView:
    """Test suite for LoginView and FinalizeContextView."""

    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        """Centralized setup: app, client, and service mocks."""
        # Flask app and client
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.client = self.app.test_client()

        # Service mocks
        self.profile_service = MagicMock()
        self.query_service = MagicMock()
        self.branding_service = MagicMock()
        self.config_service = MagicMock()
        self.prompt_service = MagicMock()
        self.jwt_service = MagicMock()
        self.auth_service = MagicMock()
        self.utility = MagicMock()
        self.i18n_service = MagicMock()

        # Patch BaseLoginView.__init__ to inject mocks before as_view is called
        original_base_init = BaseLoginView.__init__

        def patched_base_init(instance, **kwargs):
            """Call original __init__ with mocked services."""
            return original_base_init(
                instance,
                profile_service=self.profile_service,
                auth_service=self.auth_service,
                jwt_service=self.jwt_service,
                branding_service=self.branding_service,
                prompt_service=self.prompt_service,
                config_service=self.config_service,
                query_service=self.query_service,
                utility=self.utility,
                i18n_service=self.i18n_service,
            )

        monkeypatch.setattr(BaseLoginView, "__init__", patched_base_init)

        # Patch FinalizeContextView.__init__ to inject mocks before as_view is called
        original_finalize_init = FinalizeContextView.__init__

        def patched_finalize_init(instance, **kwargs):
            """Call original __init__ with mocked services."""
            return original_finalize_init(
                instance,
                profile_service=self.profile_service,
                query_service=self.query_service,
                prompt_service=self.prompt_service,
                branding_service=self.branding_service,
                config_service=self.config_service,
                jwt_service=self.jwt_service,
                i18n_service=self.i18n_service,
            )

        monkeypatch.setattr(FinalizeContextView, "__init__", patched_finalize_init)

        # Register endpoints after patching constructors
        self.app.add_url_rule(
            "/<company_short_name>/login",
            view_func=LoginView.as_view("login_post"),
            methods=["POST"],
        )
        self.app.add_url_rule(
            "/<company_short_name>/login",
            view_func=FinalizeContextView.as_view("login"),
            methods=["GET"],
        )

        self.app.add_url_rule(
            '/<company_short_name>/finalize',
            view_func=FinalizeContextView.as_view('finalize_no_token')
        )

        self.app.add_url_rule(
            '/<company_short_name>/finalize/<token>',
            view_func=FinalizeContextView.as_view('finalize_with_token')
        )

        # Minimal endpoint used by FinalizeContextView redirect
        @self.app.route("/<company_short_name>/home",
                        endpoint="home")
        def index(company_short_name):
            return "Index Page", 200

        # Common test values
        self.company_short_name = "acme"
        self.email = "user@example.com"
        self.password = "secret"
        self.user_identifier = "user-123"

        # Company lookup returns a dummy object (truthy) by default
        self.profile_service.get_company_by_short_name.return_value = MagicMock()

    def test_login_failure_renders_index_with_400(self):
        """When login fails, it should render index.html with 400."""
        self.auth_service.login_local_user.return_value = {
            "success": False,
            "message": "Invalid credentials",
        }
        self.utility.get_company_template.return_value = "<html>index</html>"

        resp = self.client.post(
                f"/{self.company_short_name}/login",
                data={"email": self.email, "password": self.password}
        )

        assert resp.status_code == 400


    def test_login_success_delegates_to_base_handler(self, monkeypatch):
        """When login succeeds, it should delegate to BaseLoginView._handle_login_path."""
        self.profile_service.login.return_value = {
            "success": True,
            "user_identifier": self.user_identifier,
        }

        # Patch the base handler to a predictable response
        def fake_handle(instance, csn, uid, company):
            return "OK", 200

        monkeypatch.setattr(BaseLoginView, "_handle_login_path", fake_handle, raising=True)

        resp = self.client.post(
            f"/{self.company_short_name}/login",
            data={"email": self.email, "password": self.password},
        )

        assert resp.status_code == 200
        assert resp.data == b"OK"

    def test_finalize_success_renders_chat(self):
        """FinalizeContextView should finalize context and render chat on success."""
        self.profile_service.get_current_session_info.return_value = {
            "user_identifier": self.user_identifier
        }
        self.prompt_service.get_user_prompts.return_value = [{"id": "p1"}]
        self.branding_service.get_company_branding.return_value = {"logo": "x.png"}
        self.config_service.get_company_content.return_value = [{"title": "card1"}]

        with patch("iatoolkit.views.login_view.render_template") as mock_rt:
            mock_rt.return_value = "CHAT", 200
            resp = self.client.get(f"/{self.company_short_name}/login")

        assert resp.status_code == 200
        assert resp.data == b"CHAT"
        self.query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=self.company_short_name,
            user_identifier=self.user_identifier,
        )
        self.prompt_service.get_user_prompts.assert_called_once_with(self.company_short_name)
        self.branding_service.get_company_branding.assert_called_once()
        self.config_service.get_company_content.assert_called_once()

        # Ensure chat.html is rendered with expected context
        mock_rt.assert_called_once()
        assert mock_rt.call_args[0][0] == "chat.html"
        ctx = mock_rt.call_args[1]
        assert ctx["branding"] == {"logo": "x.png"}
        assert ctx["prompts"] == [{"id": "p1"}]

    def test_finalize_redirects_when_no_user_in_session(self):
        """If there is no user in session, it should redirect to login_page."""
        self.profile_service.get_current_session_info.return_value = {}

        resp = self.client.get(f"/{self.company_short_name}/login")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/{self.company_short_name}/home")

    def test_finalize_exception_renders_error_with_500(self):
        """If finalize fails, it should render error.html with 500."""
        self.profile_service.get_current_session_info.return_value = {
            "user_identifier": self.user_identifier
        }
        self.query_service.finalize_context_rebuild.side_effect = Exception("boom")

        with patch("iatoolkit.views.login_view.render_template") as mock_rt:
            mock_rt.return_value = "<html>error</html>"
            resp = self.client.get(f"/{self.company_short_name}/login")

        assert resp.status_code == 500
        mock_rt.assert_called_once()
        assert mock_rt.call_args[0][0] == "error.html"

    def test_finalize_with_token_success_renders_chat(self):
        """Si no hay sesión pero llega token válido, debe validar JWT, finalizar contexto y renderizar chat."""
        # No hay sesión
        self.profile_service.get_current_session_info.return_value = {}
        # JWT válido
        self.jwt_service.validate_chat_jwt.return_value = {"user_identifier": self.user_identifier}
        # Datos auxiliares
        self.prompt_service.get_user_prompts.return_value = [{"id": "p1"}]
        self.branding_service.get_company_branding.return_value = {"logo": "x.png"}
        self.config_service.get_company_content.return_value = [{"title": "card1"}]

        with patch("iatoolkit.views.login_view.render_template") as mock_rt:
            mock_rt.return_value = "CHAT", 200
            resp = self.client.get(f"/{self.company_short_name}/finalize/abc123")

        assert resp.status_code == 200
        assert resp.data == b"CHAT"

        # Debe haberse validado el token y usado el user_identifier del payload
        self.jwt_service.validate_chat_jwt.assert_called_once_with("abc123")
        self.query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=self.company_short_name,
            user_identifier=self.user_identifier,
        )
        self.prompt_service.get_user_prompts.assert_called_once_with(self.company_short_name)
        self.branding_service.get_company_branding.assert_called_once()
        self.config_service.get_company_content.assert_called_once()

        mock_rt.assert_called_once()
        assert mock_rt.call_args[0][0] == "chat.html"
        ctx = mock_rt.call_args[1]
        assert ctx["user_identifier"] == self.user_identifier
        assert ctx["redeem_token"] == "abc123"

    def test_finalize_with_token_invalid_redirects_index(self):
        """Si no hay sesión y el token es inválido, debe redirigir a index."""
        # No hay sesión
        self.profile_service.get_current_session_info.return_value = {}
        # Token inválido
        self.jwt_service.validate_chat_jwt.return_value = None

        resp = self.client.get(f"/{self.company_short_name}/finalize/bad")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/{self.company_short_name}/home")
        self.jwt_service.validate_chat_jwt.assert_called_once_with("bad")
        self.query_service.finalize_context_rebuild.assert_not_called()
