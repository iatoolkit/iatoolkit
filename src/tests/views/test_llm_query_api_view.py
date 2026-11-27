import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.llmquery_api_view import LLMQueryApiView
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company
from iatoolkit.services.i18n_service import I18nService

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
        self.mock_i18n_service = MagicMock(spec=I18nService)


        # Common successful auth mock
        self.mock_auth.verify_for_company.return_value = {"success": True, 'user_identifier': MOCK_EXTERNAL_USER_ID}
        self.mock_profile.get_company_by_short_name.return_value = Company(id=1, short_name=MOCK_COMPANY_SHORT_NAME)

        view = LLMQueryApiView.as_view(
            'llm_query_api',
            auth_service=self.mock_auth,
            query_service=self.mock_query,
            profile_service=self.mock_profile,
            i18n_service=self.mock_i18n_service
        )

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.app.add_url_rule('/<company_short_name>/api/query', view_func=view, methods=['POST'])
        self.url = f'/{MOCK_COMPANY_SHORT_NAME}/api/query'


    def test_api_query_for_user(self):
        """
        Tests a successful query for a  API user, skipping session creation.
        """
        # Arrange
        self.mock_query.llm_query.return_value = {"answer": "Welcome back!"}

        # Act
        response = self.client.post(self.url,
                                    json={"external_user_id": MOCK_EXTERNAL_USER_ID, "model": 'gpt-5'})

        # Assert
        assert response.status_code == 200
        # Verify the query was called correctly
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_EXTERNAL_USER_ID,
            model='gpt-5',
            llm_request_options={"reasoning_effort": ""},
            question='',
            prompt_name=None,
            client_data={"source": "chat_ui"},
            ignore_history=False,
            files=[]
        )

    def test_api_query_preserves_explicit_client_source(self):
        self.mock_query.llm_query.return_value = {"answer": "ok"}

        response = self.client.post(
            self.url,
            json={
                "external_user_id": MOCK_EXTERNAL_USER_ID,
                "client_data": {"source": "iatoolkit_mcp", "foo": "bar"},
            },
        )

        assert response.status_code == 200
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_EXTERNAL_USER_ID,
            model='',
            llm_request_options={"reasoning_effort": ""},
            question='',
            prompt_name=None,
            client_data={"source": "iatoolkit_mcp", "foo": "bar"},
            ignore_history=False,
            files=[]
        )

    def test_api_query_when_error(self):
        self.mock_query.llm_query.return_value = {"error": True, 'error_message': 'some error'}

        response = self.client.post(self.url,
                                    json={"external_user_id": MOCK_EXTERNAL_USER_ID})

        # Assert
        assert response.status_code == 409
        assert response.json['error_message'] == 'some error'


    def test_api_query_fails_on_auth_failure(self):
        """Tests that the view returns a 401 if API Key authentication fails."""
        self.mock_auth.verify_for_company.return_value = {"success": False, "error_message": "Invalid API Key", "status_code": 401}

        response = self.client.post(self.url, json={"user_identifier": "any"})

        assert response.status_code == 401
        assert "Invalid API Key" in response.json['error_message']
        self.mock_query.llm_query.assert_not_called()

    def test_api_query_returns_structured_output_and_hides_schema_diagnostics(self):
        self.mock_query.llm_query.return_value = {
            "answer": "ok",
            "structured_output": {"employees": [{"employeeid": 1}]},
            "schema_valid": True,
            "schema_errors": [],
            "schema_mode": "best_effort",
            "schema_applied": True,
        }

        response = self.client.post(self.url, json={"external_user_id": MOCK_EXTERNAL_USER_ID})

        assert response.status_code == 200
        body = response.json
        assert body["structured_output"] == {"employees": [{"employeeid": 1}]}
        assert "schema_valid" not in body
        assert "schema_errors" not in body
        assert "schema_mode" not in body
        assert "schema_applied" not in body

    def test_api_query_returns_null_structured_output_when_not_available(self):
        self.mock_query.llm_query.return_value = {
            "answer": "ok",
            "structured_output": None,
            "schema_valid": False,
            "schema_errors": ["$.employees: is required."],
            "schema_mode": "best_effort",
            "schema_applied": True,
        }

        response = self.client.post(self.url, json={"external_user_id": MOCK_EXTERNAL_USER_ID})

        assert response.status_code == 200
        body = response.json
        assert "structured_output" in body
        assert body["structured_output"] is None
        assert "schema_valid" not in body
        assert "schema_errors" not in body
        assert "schema_mode" not in body
        assert "schema_applied" not in body

    def test_api_query_for_when_no_data(self):
        self.mock_query.llm_query.return_value = {"answer": "Welcome back!"}

        response = self.client.post(self.url, json={})
        assert response.status_code == 400


class TestLLMQueryApiPiiRestore:
    """BL-034 R11: a person in the chat reads values; an API key caller keeps tokens."""

    TOKEN = "[PII-0123456789ab]"

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        from iatoolkit.common import pii_masking
        from iatoolkit.services.pii_masking_service import PersonView
        from iatoolkit.views import llmquery_api_view

        values = {self.TOKEN: "Ana"}
        monkeypatch.setattr(llmquery_api_view, "person_view_for", lambda company, user: PersonView(
            lambda t: values.get(t, pii_masking.MISSING)))
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.auth = MagicMock(spec=AuthService)
        self.query = MagicMock(spec=QueryService)
        self.query.llm_query.return_value = {"answer": f"<p>{self.TOKEN}</p>"}
        view = LLMQueryApiView.as_view('llm_query_api', auth_service=self.auth, query_service=self.query,
                                       profile_service=MagicMock(spec=ProfileService),
                                       i18n_service=MagicMock(spec=I18nService))
        self.app.add_url_rule('/<company_short_name>/api/query', view_func=view, methods=['POST'])

    def test_a_web_session_reads_the_values(self):
        self.auth.verify_for_company.return_value = {"success": True, "user_identifier": "ana", "auth_type": "session"}
        assert self.client.post('/acme/api/query', json={"question": "x"}).get_json()["answer"] == "<p>Ana</p>"

    def test_an_api_key_keeps_the_tokens(self):
        self.auth.verify_for_company.return_value = {"success": True, "user_identifier": "ana", "auth_type": "api_key"}
        assert self.client.post('/acme/api/query', json={"question": "x"}).get_json()["answer"] == f"<p>{self.TOKEN}</p>"
