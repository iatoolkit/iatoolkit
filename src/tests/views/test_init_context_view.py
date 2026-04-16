import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.init_context_api_view import InitContextApiView
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.user_session_context_service import UserSessionContextService

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_USER_IDENTIFIER = "api-user-123"


class TestInitContextApiView:
    """
    Tests for the InitContextApiView, which forces a context rebuild.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up a clean test environment before each test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks for injected services
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        # Create a mock for session_context and attach it to query_service
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_query_service.session_context = self.mock_session_context

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"


        # Register the view with its dependencies
        view_func = InitContextApiView.as_view(
            'init_context_api',
            auth_service=self.mock_auth_service,
            query_service=self.mock_query_service,
            profile_service=self.mock_profile_service,
            i18n_service=self.mock_i18n_service
        )
        self.app.add_url_rule('/api/<company_short_name>/init-context', view_func=view_func, methods=['POST'])

        self.mock_auth_service.verify_for_company.return_value = \
            {"success": True,
             "company_short_name": MOCK_COMPANY_SHORT_NAME,
             "user_identifier": MOCK_USER_IDENTIFIER}

    def test_rebuild_when_ok(self):
        """
        Tests the flow for a pure API call using an API Key.
        """
        self.mock_query_service.init_context.return_value = {'response_id': 'messagge_1234'}
        response = self.client.post(
            f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context',
            json={'external_user_id': MOCK_USER_IDENTIFIER, 'model':'gpt-5-mini'}
        )

        assert response.status_code == 200
        assert response.json['status'] == 'OK'
        assert response.json['response_id'] == 'messagge_1234'

        # Verify the sequence was called with the user ID from the JSON payload.
        self.mock_query_service.init_context.assert_called_once_with(company_short_name=MOCK_COMPANY_SHORT_NAME,
                                                                        user_identifier=MOCK_USER_IDENTIFIER,
                                                                     model='gpt-5-mini')


    def test_rebuild_fails_if_auth_fails(self):
        """
        Tests that the view returns a 401 if authentication fails.
        """
        self.mock_auth_service.verify_for_company.return_value = {"success": False, "error_message": "Invalid API Key",
                                                      "status_code": 401}

        response = self.client.post(f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context', json={'external_user_id': 'any'})

        assert response.status_code == 401
        assert "Invalid API Key" in response.json['error_message']
        self.mock_query_service.prepare_context.assert_not_called()

    def test_rebuild_when_exception(self):
        self.mock_query_service.prepare_context.side_effect = Exception('Database connection failed')

        response = self.client.post(
            f'/api/{MOCK_COMPANY_SHORT_NAME}/init-context',
            json={'external_user_id': MOCK_USER_IDENTIFIER}
        )

        # Assert
        assert response.status_code == 406
        assert response.json['error_message'] == 'translated:errors.general.unexpected_error'
