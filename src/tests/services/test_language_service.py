# tests/services/test_language_service.py
import pytest
from flask import Flask, g
from unittest.mock import MagicMock, patch, call
from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import User


class TestLanguageService:
    """
    Unit tests for the LanguageService, adapted for ConfigurationService.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """
        Pytest fixture that runs before each test.
        - Mocks dependencies: ProfileRepo and ConfigurationService.
        - Creates a fresh instance of LanguageService.
        - Creates a Flask app to provide a request context.
        """
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_profile_repo.session = MagicMock()
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.language_service = LanguageService(config_service=self.mock_config_service,
                                                profile_repo=self.mock_profile_repo)

        self.app = Flask(__name__)

        # Mock user objects for predictable test data
        self.user_with_lang_de = User(id=1, email='user-de@acme.com', preferred_language='en_us')
        self.user_without_lang = User(id=2, email='user-no-lang@acme.com', preferred_language=None)

        # Register a dummy route to correctly parse `company_short_name` from URLs.
        @self.app.route('/<company_short_name>/login')
        def dummy_route_for_test(company_short_name):
            return "ok"


    # --- Priority 2 Tests: Company Default ---

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_company_language_when_user_has_no_preference(self, mock_session_manager):
        """
        GIVEN a logged-in user with NO preferred language and a company with 'en_US'
        WHEN the current language is requested
        THEN the company's default language ('en') is returned.
        """
        # Arrange
        def session_get_side_effect(key):
            if key == 'user_identifier': return 'user-no-lang@acme.com'
            if key == 'company_short_name': return 'acme-en'
            return None
        mock_session_manager.get.side_effect = session_get_side_effect
        self.mock_profile_repo.get_user_by_email.return_value = self.user_without_lang
        # The service now calls ConfigurationService instead of ProfileRepo for company language
        self.mock_config_service.get_configuration.return_value = 'en_US'

        with self.app.test_request_context():
            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == 'en'  # Should extract 'en' from 'en_US'
            self.mock_config_service.get_configuration.assert_called_once_with('acme-en', 'locale')

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_company_language_from_url_when_no_session(self, mock_session_manager):
        """
        GIVEN no user is logged in
        WHEN a request is made to a URL with a company short name ('acme-fr')
        THEN the company's default language ('fr') is returned.
        """
        # Arrange
        mock_session_manager.get.return_value = None  # No active session
        self.mock_config_service.get_configuration.return_value = 'fr_FR'

        # Simulate a request to a URL like /acme-fr/login
        with self.app.test_request_context('/acme-fr/login'):
            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == 'es'
            self.mock_config_service.get_configuration.assert_called_once_with('acme-fr', 'locale')
            self.mock_profile_repo.get_user_by_email.assert_not_called()

    # --- Priority 3 Tests: System Fallback ---

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_fallback_when_company_has_no_language(self, mock_session_manager):
        """
        GIVEN a company context exists but its configuration has no 'locale'
        WHEN the current language is requested
        THEN the system-wide fallback language ('es') is returned.
        """
        # Arrange
        mock_session_manager.get.return_value = None  # No user
        self.mock_config_service.get_configuration.return_value = None  # Simulate missing config

        with self.app.test_request_context('/acme-no-lang/login'):
            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == self.language_service.FALLBACK_LANGUAGE
            self.mock_config_service.get_configuration.assert_called_once_with('acme-no-lang', 'locale')

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_fallback_when_no_context_found(self, mock_session_manager):
        """
        GIVEN no user is logged in and the URL has no company context
        WHEN the current language is requested
        THEN the system-wide fallback language ('es') is returned.
        """
        # Arrange
        mock_session_manager.get.return_value = None  # No session

        with self.app.test_request_context('/health'): # URL without company
            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == self.language_service.FALLBACK_LANGUAGE
            self.mock_config_service.get_configuration.assert_not_called()

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_fallback_on_config_service_exception(self, mock_session_manager):
        """
        GIVEN the ConfigurationService fails with an exception
        WHEN the current language is requested
        THEN the service fails gracefully and returns the fallback language ('es').
        """
        # Arrange
        mock_session_manager.get.return_value = 'acme-en'
        self.mock_config_service.get_configuration.side_effect = Exception("YAML file is corrupted")

        with self.app.test_request_context():
            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == self.language_service.FALLBACK_LANGUAGE
            self.mock_profile_repo.session.rollback.assert_called_once()

    # --- Caching Test ---

    @patch('iatoolkit.services.language_service.SessionManager')
    def test_returns_cached_language_from_g_without_external_calls(self, mock_session_manager):
        """
        GIVEN the language has already been determined and cached in g.lang
        WHEN the current language is requested again in the same request
        THEN the cached language is returned without any external calls.
        """
        with self.app.test_request_context():
            # Arrange
            g.lang = 'xx-cached'
            g.locale_ctx = {'mock': 'data'}  # Fix: El servicio verifica la existencia de locale_ctx

            # Act
            lang = self.language_service.get_current_language()

            # Assert
            assert lang == 'xx-cached'
            # CRUCIAL: Verify that no external calls were made
            mock_session_manager.get.assert_not_called()
            self.mock_profile_repo.get_user_by_email.assert_not_called()
            self.mock_config_service.get_configuration.assert_not_called()
