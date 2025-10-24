# tests/views/test_base_login_view.py
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from iatoolkit.views.base_login_view import BaseLoginView

# Constants for test data
COMPANY_SHORT_NAME = "test-co"
USER_IDENTIFIER = "test-user@example.com"


class TestBaseLoginView:
    """Test suite for the BaseLoginView class."""

    def setup_method(self):
        """
        Set up a new view instance and fresh mocks before each test method runs.
        This ensures test isolation.
        """
        self.mock_services = {
            "profile_service": MagicMock(),
            "branding_service": MagicMock(),
            "prompt_service": MagicMock(),
            "onboarding_service": MagicMock(),
            "query_service": MagicMock(),
        }
        self.view_instance = BaseLoginView(**self.mock_services)

        # Common company double
        self.mock_company = MagicMock()

    def test_handle_login_path_slow_path(self):
        """
        Slow path: when rebuild is needed, it should render onboarding_shell.html
        with iframe_src_url, branding, and onboarding_cards.
        """
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {
            "rebuild_needed": True
        }
        self.mock_services["branding_service"].get_company_branding.return_value = {
            "logo": "logo.png"
        }
        self.mock_services["onboarding_service"].get_onboarding_cards.return_value = [
            {"title": "Card 1"}
        ]

        # Flask app context required for url_for and render_template
        app = Flask(__name__)
        # Register route to satisfy url_for('chat', ...)
        app.add_url_rule("/<company_short_name>/finalize_context_load", endpoint="finalize_context_load")

        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                _ = self.view_instance._handle_login_path(
                    COMPANY_SHORT_NAME, USER_IDENTIFIER, self.mock_company
                )

        # Assert: prepare_context called with expected params
        self.mock_services["query_service"].prepare_context.assert_called_once_with(
            company_short_name=COMPANY_SHORT_NAME, user_identifier=USER_IDENTIFIER
        )
        # Branding and onboarding used in slow path
        self.mock_services["branding_service"].get_company_branding.assert_called_once_with(
            self.mock_company
        )
        self.mock_services["onboarding_service"].get_onboarding_cards.assert_called_once_with(
            self.mock_company
        )
        # Template and context
        mock_rt.assert_called_once()
        template_name = mock_rt.call_args[0][0]
        ctx = mock_rt.call_args[1]
        assert template_name == "onboarding_shell.html"
        assert "iframe_src_url" in ctx
        assert ctx["branding"] == {"logo": "logo.png"}
        assert ctx["onboarding_cards"] == [{"title": "Card 1"}]

    def test_handle_login_path_fast_path(self):
        """
        Fast path: when rebuild is NOT needed, it should render chat.html
        with branding and prompts.
        """
        # Arrange
        self.mock_services["query_service"].prepare_context.return_value = {
            "rebuild_needed": False
        }
        self.mock_services["branding_service"].get_company_branding.return_value = {
            "theme": "dark"
        }
        self.mock_services["prompt_service"].get_user_prompts.return_value = [
            {"id": "p1"}
        ]

        # Flask app context required for render_template (no url_for used here)
        app = Flask(__name__)
        with app.test_request_context():
            with patch("iatoolkit.views.base_login_view.render_template") as mock_rt:
                mock_rt.return_value = "<html>chat</html>"
                result = self.view_instance._handle_login_path(
                    COMPANY_SHORT_NAME, USER_IDENTIFIER, self.mock_company
                )

        # Assert: prepare_context called with expected params
        self.mock_services["query_service"].prepare_context.assert_called_once_with(
            company_short_name=COMPANY_SHORT_NAME, user_identifier=USER_IDENTIFIER
        )
        # Branding and prompts used in fast path
        self.mock_services["branding_service"].get_company_branding.assert_called_once_with(
            self.mock_company
        )
        self.mock_services["prompt_service"].get_user_prompts.assert_called_once_with(
            COMPANY_SHORT_NAME
        )

        # Template and context
        assert result == "<html>chat</html>"
        mock_rt.assert_called_once()
        template_name = mock_rt.call_args[0][0]
        ctx = mock_rt.call_args[1]
        assert template_name == "chat.html"
        assert ctx["branding"] == {"theme": "dark"}
        assert ctx["prompts"] == [{"id": "p1"}]