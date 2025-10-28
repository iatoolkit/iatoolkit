# tests/views/test_base_login_view.py
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from iatoolkit.views.base_login_view import BaseLoginView
from iatoolkit.repositories.models import Company  # Import Company for spec

# Constants for test data
COMPANY_SHORT_NAME = "test-co"
USER_IDENTIFIER = "test-user@example.com"
DUMMY_TARGET_URL = "/fake/target/url"


class TestBaseLoginView:
    """Test suite for the BaseLoginView class."""

    def setup_method(self):
        """Set up a new view instance and fresh mocks before each test method runs."""
        self.mock_services = {
            "profile_service": MagicMock(),
            "branding_service": MagicMock(),
            "prompt_service": MagicMock(),
            "onboarding_service": MagicMock(),
            "query_service": MagicMock(),
            "jwt_service": MagicMock(),
            "auth_service": MagicMock(),
        }
        self.view_instance = BaseLoginView(**self.mock_services)

        # Mock Company object with a short_name attribute
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.short_name = COMPANY_SHORT_NAME

    def test_handle_login_path_slow_path(self):
        """Slow path: should render onboarding_shell.html with correct context."""
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": True}
        self.mock_services["branding_service"].get_company_branding.return_value = {"logo": "logo.png"}
        self.mock_services["onboarding_service"].get_onboarding_cards.return_value = [{"title": "Card 1"}]

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                # Act: Call with the new signature
                _ = self.view_instance._handle_login_path(
                    company=self.mock_company,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL
                )

        # Assert
        self.mock_services["query_service"].prepare_context.assert_called_once_with(
            company_short_name=self.mock_company.short_name, user_identifier=USER_IDENTIFIER
        )
        self.mock_services["branding_service"].get_company_branding.assert_called_once_with(self.mock_company)
        self.mock_services["onboarding_service"].get_onboarding_cards.assert_called_once_with(self.mock_company)

        mock_rt.assert_called_once()
        template_name, ctx = mock_rt.call_args[0], mock_rt.call_args[1]
        assert template_name[0] == "onboarding_shell.html"
        assert ctx["iframe_src_url"] == DUMMY_TARGET_URL
        assert ctx["branding"] == {"logo": "logo.png"}
        assert ctx["onboarding_cards"] == [{"title": "Card 1"}]

    def test_handle_login_path_fast_path_without_token(self):
        """Fast path: should render chat.html with redeem_token as None."""
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": False}
        self.mock_services["branding_service"].get_company_branding.return_value = {"theme": "dark"}
        self.mock_services["prompt_service"].get_user_prompts.return_value = [{"id": "p1"}]
        self.mock_services["onboarding_service"].get_onboarding_cards.return_value = []

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                # Act: Call without redeem_token
                _ = self.view_instance._handle_login_path(
                    company=self.mock_company,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL
                )

        # Assert
        self.mock_services["query_service"].prepare_context.assert_called_once_with(
            company_short_name=self.mock_company.short_name, user_identifier=USER_IDENTIFIER
        )
        self.mock_services["prompt_service"].get_user_prompts.assert_called_once_with(self.mock_company.short_name)

        mock_rt.assert_called_once()
        template_name, ctx = mock_rt.call_args[0], mock_rt.call_args[1]
        assert template_name[0] == "chat.html"
        assert ctx["branding"] == {"theme": "dark"}
        assert ctx["prompts"] == [{"id": "p1"}]
        assert ctx["redeem_token"] is None

    def test_handle_login_path_fast_path_with_token(self):
        """Fast path: should pass the redeem_token to the chat.html template."""
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": False}
        self.mock_services["branding_service"].get_company_branding.return_value = {}
        self.mock_services["prompt_service"].get_user_prompts.return_value = []
        self.mock_services["onboarding_service"].get_onboarding_cards.return_value = []
        test_token = "test-token-123"

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                # Act: Call with redeem_token
                _ = self.view_instance._handle_login_path(
                    company=self.mock_company,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL,
                    redeem_token=test_token
                )

        # Assert
        mock_rt.assert_called_once()
        ctx = mock_rt.call_args[1]
        assert ctx["redeem_token"] == test_token