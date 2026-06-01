from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.mcp_token_service import McpTokenService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.views.account_view import AccountView


class TestAccountView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.client = self.app.test_client()

        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_mcp_service = MagicMock(spec=McpTokenService)

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.mock_profile_service.get_company_by_short_name.return_value = MagicMock()
        self.mock_profile_service.get_current_session_info.return_value = {
            "company_short_name": "acme",
            "user_identifier": "user@acme.com",
        }
        self.mock_branding_service.get_company_branding.return_value = {"name": "ACME"}
        self.mock_mcp_service.list_user_tokens.return_value = {"data": []}
        self.mock_mcp_service.build_mcp_server_url.side_effect = McpTokenService.build_mcp_server_url
        self.mock_mcp_service.build_mcp_connection_snippet.side_effect = McpTokenService.build_mcp_connection_snippet

        @self.app.route("/<company_short_name>/home", endpoint="home")
        def home(company_short_name):
            return f"HOME:{company_short_name}"

        @self.app.route("/<company_short_name>/chat", endpoint="chat")
        def chat(company_short_name):
            return f"CHAT:{company_short_name}"

        view_func = AccountView.as_view(
            "account",
            profile_service=self.mock_profile_service,
            branding_service=self.mock_branding_service,
            i18n_service=self.mock_i18n_service,
            mcp_token_service=self.mock_mcp_service,
        )
        self.app.add_url_rule("/<company_short_name>/account", view_func=view_func, methods=["GET", "POST"])

    def test_get_redirects_home_without_valid_session(self):
        self.mock_profile_service.get_current_session_info.return_value = {}

        response = self.client.get("/acme/account")

        assert response.status_code == 302
        assert "/acme/home" in response.headers["Location"]

    def test_get_renders_account_page(self):
        with patch("iatoolkit.views.account_view.render_template") as mock_render:
            mock_render.return_value = "ACCOUNT_HTML"

            response = self.client.get("/acme/account")

        assert response.status_code == 200
        assert response.data == b"ACCOUNT_HTML"
        assert mock_render.call_args[0][0] == "account.html"
        assert mock_render.call_args[1]["active_section"] == "general"
        assert mock_render.call_args[1]["mcp_server_url"] == "https://mcp.iatoolkit.com/acme/mcp/"
        assert mock_render.call_args[1]["created_token_connection_snippet"] is None

    @patch.dict("os.environ", {"IAT_MCP_PUBLIC_BASE_URL": "https://mcp.example.com/"}, clear=False)
    def test_post_create_token_renders_created_token(self):
        self.mock_mcp_service.create_user_token.return_value = {
            "data": {
                "token": "iatmcp_created",
            }
        }

        with patch("iatoolkit.views.account_view.render_template") as mock_render:
            mock_render.return_value = "ACCOUNT_HTML"

            response = self.client.post(
                "/acme/account",
                data={"action": "create_token", "name": "Claude", "expires_in_days": "30"},
            )

        assert response.status_code == 200
        assert mock_render.call_args[1]["created_token"] == "iatmcp_created"
        assert mock_render.call_args[1]["active_section"] == "mcp_tokens"
        assert mock_render.call_args[1]["mcp_server_url"] == "https://mcp.example.com/acme/mcp/"
        assert '"Authorization": "Bearer iatmcp_created"' in mock_render.call_args[1]["created_token_connection_snippet"]
        self.mock_mcp_service.create_user_token.assert_called_once_with(
            "acme",
            "user@acme.com",
            name="Claude",
            expires_in_days="30",
            created_by_identifier="user@acme.com",
        )
