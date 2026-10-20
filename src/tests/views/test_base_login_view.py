# tests/views/test_base_login_view.py
# IAToolkit is open source software.

import pytest
from unittest.mock import ANY, MagicMock, patch
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
            "config_service": MagicMock(),
            "query_service": MagicMock(),
            "jwt_service": MagicMock(),
            "auth_service": MagicMock(),
            "utility": MagicMock(),
            "i18n_service": MagicMock(),
        }
        self.view_instance = BaseLoginView(**self.mock_services)

    def test_a_context_to_rebuild_is_started_and_the_chat_renders_directly(self):
        """No loading shell with onboarding cards: starting the context calls no model (BL-009)."""
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": True}
        self.mock_services["config_service"].get_configuration.return_value = [{"title": "Card 1"}]
        self.mock_services["config_service"].get_llm_configuration.return_value = (
            "test-model",
            [{"id": "test-model", "label": "Test model", "description": "desc"}],
        )

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                _ = self.view_instance._handle_login_path(
                    company_short_name=COMPANY_SHORT_NAME,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL
                )

        self.mock_services["query_service"].set_context_for_llm.assert_called_once_with(
            company_short_name=COMPANY_SHORT_NAME, user_identifier=USER_IDENTIFIER
        )
        assert mock_rt.call_args[0][0] == "chat.html"
        assert mock_rt.call_args[1]["onboarding_cards"] == [{"title": "Card 1"}]

    def test_an_unchanged_context_is_not_started_again(self):
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": False}
        self.mock_services["config_service"].get_llm_configuration.return_value = ("test-model", [])

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template"):
                self.view_instance._handle_login_path(
                    company_short_name=COMPANY_SHORT_NAME,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL
                )

        self.mock_services["query_service"].set_context_for_llm.assert_not_called()

    def test_handle_login_path_fast_path_without_token(self):
        """Fast path: should render chat.html with redeem_token as None."""
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {"rebuild_needed": False}
        self.mock_services["branding_service"].get_company_branding.return_value = {"theme": "dark"}
        self.mock_services["prompt_service"].get_prompts.return_value = [{"id": "p1"}]
        self.mock_services["config_service"].get_configuration.return_value = []
        self.mock_services["config_service"].get_llm_configuration.return_value = (
            "test-model",
            [{"id": "test-model", "label": "Test model", "description": "desc"}],
        )

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                # Act: Call without redeem_token
                _ = self.view_instance._handle_login_path(
                    company_short_name=COMPANY_SHORT_NAME,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL
                )

        # Assert
        self.mock_services["query_service"].prepare_context.assert_called_once_with(
            company_short_name=COMPANY_SHORT_NAME, user_identifier=USER_IDENTIFIER
        )
        self.mock_services["prompt_service"].get_prompts.assert_called_once_with(
            COMPANY_SHORT_NAME, user_identifier=ANY)

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
        self.mock_services["prompt_service"].get_prompts.return_value = []
        self.mock_services["config_service"].get_onboarding_cards.return_value = []
        self.mock_services["config_service"].get_llm_configuration.return_value = (
            "test-model",
            [{"id": "test-model", "label": "Test model", "description": "desc"}],
        )
        test_token = "test-token-123"

        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                # Act: Call with redeem_token
                _ = self.view_instance._handle_login_path(
                    company_short_name=COMPANY_SHORT_NAME,
                    user_identifier=USER_IDENTIFIER,
                    target_url=DUMMY_TARGET_URL,
                    redeem_token=test_token
                )

        # Assert
        mock_rt.assert_called_once()
        ctx = mock_rt.call_args[1]
        assert ctx["redeem_token"] == test_token
