import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.llmquery_api_view import LLMQueryApiView
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company

MOCK_COMPANY_SHORT_NAME = "test-api-comp"
MOCK_EXTERNAL_USER_ID = "api-user-789"


class TestLLMQueryApiView:
    """Tests for the stateless, API-only LLMQueryApiView."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.mock_auth = MagicMock(spec=AuthService)
        self.mock_query = MagicMock(spec=QueryService)
        self.mock_profile = MagicMock(spec=ProfileService)

        # Common successful auth mock
        self.mock_auth.verify.return_value = {"success": True, 'user_identifier': MOCK_EXTERNAL_USER_ID}
        self.mock_profile.get_company_by_short_name.return_value = Company(id=1, short_name=MOCK_COMPANY_SHORT_NAME)

        view = LLMQueryApiView.as_view(
            'llm_query_api',
            auth_service=self.mock_auth,
            query_service=self.mock_query,
            profile_service=self.mock_profile
        )
        self.app.add_url_rule('/<company_short_name>/api/query', view_func=view, methods=['POST'])
        self.url = f'/{MOCK_COMPANY_SHORT_NAME}/api/query'

    def test_api_query_for_first_time_user(self):
        """
        Tests a successful query for a new API user, triggering on-the-fly session state creation.
        """
        # Arrange
        self.mock_profile.get_profile_by_identifier.return_value = {}  # Simulate user does not exist yet
        self.mock_query.llm_query.return_value = {"answer": "Welcome, new user!"}

        # Act
        response = self.client.post(self.url,
                                    json={"external_user_id": MOCK_EXTERNAL_USER_ID, "question": "First time"})

        # Assert
        assert response.status_code == 200
        assert response.json["answer"] == "Welcome, new user!"
        # Verify that the session creation was triggered
        self.mock_profile.create_external_user_profile_context.assert_called_once()
        # Verify the query was still called
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_EXTERNAL_USER_ID,
            question="First time",
            prompt_name=None,
            client_data={},
            files=[]
        )

    def test_api_query_for_returning_user(self):
        """
        Tests a successful query for a returning API user, skipping session creation.
        """
        # Arrange
        self.mock_profile.get_profile_by_identifier.return_value = {"id": MOCK_EXTERNAL_USER_ID}  # Simulate user exists
        self.mock_query.llm_query.return_value = {"answer": "Welcome back!"}

        # Act
        response = self.client.post(self.url,
                                    json={"external_user_id": MOCK_EXTERNAL_USER_ID})

        # Assert
        assert response.status_code == 200
        # Verify that session creation was SKIPPED
        self.mock_profile.create_external_user_profile_context.assert_not_called()
        # Verify the query was called correctly
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_EXTERNAL_USER_ID,
            question='',
            prompt_name=None,
            client_data={},
            files=[]
        )

    def test_api_query_fails_on_auth_failure(self):
        """Tests that the view returns a 401 if API Key authentication fails."""
        # Arrange
        self.mock_auth.verify.return_value = {"success": False, "error_message": "Invalid API Key", "status_code": 401}

        # Act
        response = self.client.post(self.url, json={"user_identifier": "any"})

        # Assert
        assert response.status_code == 401
        assert "Invalid API Key" in response.json['error']
        self.mock_query.llm_query.assert_not_called()

    def test_api_query_fails_if_no_user_identifier(self):
        """Tests that the view returns a 400 if user_identifier is missing."""
        # Act
        self.mock_auth.verify.return_value = {"success": True}

        response = self.client.post(self.url, json={"question": "some question"})

        # Assert
        assert response.status_code == 400
        assert "Payload must include 'user_identifier'" in response.json['error']