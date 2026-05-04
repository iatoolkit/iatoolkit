import pytest
from flask import Flask
from unittest.mock import MagicMock

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.invocations_api_view import InvocationsApiView

MOCK_COMPANY_SHORT_NAME = "test-api-comp"
MOCK_USER_IDENTIFIER = "api-user-789"


class TestInvocationsApiView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.mock_auth = MagicMock(spec=AuthService)
        self.mock_query = MagicMock(spec=QueryService)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.mock_auth.verify_for_company.return_value = {
            "success": True,
            "user_identifier": MOCK_USER_IDENTIFIER,
        }
        self.mock_i18n_service.t.side_effect = (
            lambda key, **kwargs: f"translated:{key}"
        )

        view = InvocationsApiView.as_view(
            "invocations_api",
            auth_service=self.mock_auth,
            query_service=self.mock_query,
            i18n_service=self.mock_i18n_service,
        )

        self.app.add_url_rule(
            "/<company_short_name>/api/invocations",
            view_func=view,
            methods=["POST"],
        )
        self.url = f"/{MOCK_COMPANY_SHORT_NAME}/api/invocations"

    def test_invocation_is_stateless_and_forwards_reasoning_effort(self):
        self.mock_query.llm_query.return_value = {"answer": "ok"}

        response = self.client.post(
            self.url,
            json={
                "user_identifier": MOCK_USER_IDENTIFIER,
                "model": "gpt-5",
                "agent_name": "sales_prompt",
                "question": "resume esto",
                "reasoning_effort": "high",
                "client_data": {"region": "EU"},
                "files": [{"filename": "brief.pdf"}],
                "ignore_history": False,
                "text_verbosity": "high",
                "store": False,
            },
        )

        assert response.status_code == 200
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_USER_IDENTIFIER,
            model="gpt-5",
            llm_request_options={"reasoning_effort": "high"},
            question="resume esto",
            prompt_name="sales_prompt",
            client_data={"region": "EU"},
            ignore_history=True,
            files=[{"filename": "brief.pdf"}],
        )

    def test_invocation_accepts_legacy_prompt_name_alias(self):
        self.mock_query.llm_query.return_value = {"answer": "ok"}

        response = self.client.post(
            self.url,
            json={
                "user_identifier": MOCK_USER_IDENTIFIER,
                "prompt_name": "legacy_prompt",
            },
        )

        assert response.status_code == 200
        self.mock_query.llm_query.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            user_identifier=MOCK_USER_IDENTIFIER,
            model="",
            llm_request_options={"reasoning_effort": ""},
            question="",
            prompt_name="legacy_prompt",
            client_data={},
            ignore_history=True,
            files=[],
        )

    def test_invocation_when_error(self):
        self.mock_query.llm_query.return_value = {
            "error": True,
            "error_message": "some error",
        }

        response = self.client.post(
            self.url,
            json={"user_identifier": MOCK_USER_IDENTIFIER},
        )

        assert response.status_code == 409
        assert response.json["error_message"] == "some error"

    def test_invocation_fails_on_auth_failure(self):
        self.mock_auth.verify_for_company.return_value = {
            "success": False,
            "error_message": "Invalid API Key",
            "status_code": 401,
        }

        response = self.client.post(self.url, json={"user_identifier": "any"})

        assert response.status_code == 401
        assert "Invalid API Key" in response.json["error_message"]
        self.mock_query.llm_query.assert_not_called()

    def test_invocation_hides_schema_diagnostics(self):
        self.mock_query.llm_query.return_value = {
            "answer": "ok",
            "structured_output": {"employees": [{"employeeid": 1}]},
            "schema_valid": True,
            "schema_errors": [],
            "schema_mode": "best_effort",
            "schema_applied": True,
        }

        response = self.client.post(
            self.url,
            json={"user_identifier": MOCK_USER_IDENTIFIER},
        )

        assert response.status_code == 200
        body = response.json
        assert body["structured_output"] == {"employees": [{"employeeid": 1}]}
        assert "schema_valid" not in body
        assert "schema_errors" not in body
        assert "schema_mode" not in body
        assert "schema_applied" not in body

    def test_invocation_requires_json_body(self):
        self.mock_query.llm_query.return_value = {"answer": "ok"}

        response = self.client.post(self.url, json={})

        assert response.status_code == 400
