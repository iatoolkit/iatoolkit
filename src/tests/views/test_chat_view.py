import pytest
from unittest.mock import MagicMock, patch
from flask import Flask, url_for
from iatoolkit.views.chat_view import ChatView
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService

class TestChatView:
    """Test suite for the ChatView class."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a new view instance and fresh mocks before each test method runs."""
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.app.secret_key = "test-secret"

        # Mock services
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_branding_service = MagicMock(spec=BrandingService)
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_prompt_service = MagicMock(spec=PromptService)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        # Mock translations
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.mock_i18n_service.get_translation_block.return_value = {"msg": "hello"}

        chat_view_func = ChatView.as_view("chat",
                                profile_service=self.mock_profile_service,
                                branding_service=self.mock_branding_service,
                                config_service=self.mock_config_service,
                                prompt_service=self.mock_prompt_service,
                                i18n_service=self.mock_i18n_service)

        # Register routes
        # We register a dummy home route to test redirects
        @self.app.route('/<company_short_name>/home', endpoint='home')
        def dummy_home(company_short_name):
            return "HOME"

        # Register the view function directly
        self.app.add_url_rule(
            '/<company_short_name>/chat',
            view_func=chat_view_func
        )


        self.company_short_name = "acme"
        self.user_identifier = "user@acme.com"

    def test_get_company_not_found_returns_404(self):
        """Should return 404 error page if company does not exist."""
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = None

        with patch("iatoolkit.views.chat_view.render_template") as mock_rt:
            mock_rt.return_value = "ERROR_HTML"
            # Act
            resp = self.client.get(f"/{self.company_short_name}/chat")

        # Assert
        assert resp.status_code == 404
        assert resp.data == b"ERROR_HTML"
        mock_rt.assert_called_once()
        assert mock_rt.call_args[0][0] == "error.html"

    def test_get_redirects_home_if_no_session(self):
        """Should redirect to home if there is no active session."""
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = MagicMock()
        self.mock_profile_service.get_current_session_info.return_value = {}  # Empty session

        # Act
        resp = self.client.get(f"/{self.company_short_name}/chat")

        # Assert
        assert resp.status_code == 302
        assert f"/{self.company_short_name}/home" in resp.headers["Location"]

    def test_get_redirects_home_if_session_mismatch(self):
        """Should redirect to home if session belongs to another company."""
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = MagicMock()
        self.mock_profile_service.get_current_session_info.return_value = {
            'user_identifier': self.user_identifier,
            'company_short_name': 'other_company'  # Mismatch
        }

        # Act
        resp = self.client.get(f"/{self.company_short_name}/chat")

        # Assert
        assert resp.status_code == 302
        assert f"/{self.company_short_name}/home" in resp.headers["Location"]

    def test_get_renders_chat_if_session_valid(self):
        """Should render chat.html with correct context if session is valid."""
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = MagicMock()
        self.mock_profile_service.get_current_session_info.return_value = {
            'user_identifier': self.user_identifier,
            'company_short_name': self.company_short_name
        }

        # Mock context data
        self.mock_branding_service.get_company_branding.return_value = {"logo": "logo.png"}
        self.mock_config_service.get_configuration.return_value = [{"title": "Card 1"}]
        self.mock_config_service.get_llm_configuration.return_value = ("gpt-4", [])
        self.mock_prompt_service.get_user_prompts.return_value = [{"name": "prompt1"}]

        with patch("iatoolkit.views.chat_view.render_template") as mock_rt:
            mock_rt.return_value = "CHAT_HTML"

            # Act
            resp = self.client.get(f"/{self.company_short_name}/chat")

        # Assert
        assert resp.status_code == 200
        assert resp.data == b"CHAT_HTML"

        # Verify context injection
        mock_rt.assert_called_once()
        args, kwargs = mock_rt.call_args
        assert args[0] == "chat.html"
        assert kwargs["company_short_name"] == self.company_short_name
        assert kwargs["user_identifier"] == self.user_identifier
        assert kwargs["branding"] == {"logo": "logo.png"}
        assert kwargs["prompts"] == [{"name": "prompt1"}]
        assert kwargs["llm_default_model"] == "gpt-4"
        assert kwargs["redeem_token"] is None

    def test_get_handles_exception_during_rendering(self):
        """Should return 500 error page if an exception occurs during processing."""
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = MagicMock()
        self.mock_profile_service.get_current_session_info.return_value = {
            'user_identifier': self.user_identifier,
            'company_short_name': self.company_short_name
        }
        # Simulate error in a service
        self.mock_prompt_service.get_user_prompts.side_effect = Exception("DB Error")

        with patch("iatoolkit.views.chat_view.render_template") as mock_rt:
            mock_rt.return_value = "ERROR_HTML", 500

            # Act
            resp = self.client.get(f"/{self.company_short_name}/chat")

        # Assert
        assert resp.status_code == 500
        mock_rt.assert_called_once()
        assert mock_rt.call_args[0][0] == "error.html"