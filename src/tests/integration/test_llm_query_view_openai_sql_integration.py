import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask

from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.repositories.models import Company
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.views.llmquery_api_view import LLMQueryApiView


COMPANY_SHORT_NAME = "test-api-comp"
USER_IDENTIFIER = "api-user-789"
DATABASE_KEY = "main_db"
MODEL = "gpt-5"


class FakeI18nService:
    def t(self, key, **kwargs):
        return f"translated:{key}"


class FakeProfileRepo:
    def __init__(self, company):
        self.company = company

    def get_company_by_short_name(self, short_name=None, **kwargs):
        return self.company if short_name == self.company.short_name else None


class FakeDatabaseProvider:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute_query(self, query, commit=None):
        self.executed.append((query, commit))
        return self.rows

    def rollback(self):
        return None


class FakeLLMQueryRepo:
    def __init__(self):
        self.saved_queries = []

    def add_query(self, query):
        query.id = len(self.saved_queries) + 1
        self.saved_queries.append(query)

    def rollback(self):
        return None


class FakeModelRegistry:
    def get_history_type(self, model):
        return "server_side"

    def resolve_request_params(self, model, text):
        return {
            "text": text or {},
            "reasoning": {},
        }


class FakeHistoryManager:
    def __init__(self, previous_response_id):
        self.previous_response_id = previous_response_id
        self.updates = []

    def populate_request_params(self, handle, user_turn_prompt, ignore_history):
        handle.request_params = {
            "previous_response_id": self.previous_response_id,
            "context_history": None,
        }
        return False

    def update_history(self, handle, user_turn_prompt, response):
        self.updates.append(
            {
                "handle": handle,
                "user_turn_prompt": user_turn_prompt,
                "response": response,
            }
        )


class FakeContextBuilder:
    def build_user_turn_prompt(self, company, user_identifier, client_data, files, prompt_name, question):
        return question, question, []


class FakeToolService:
    def __init__(self, sql_service):
        self.sql_service = sql_service

    def get_tools_for_llm(self, company):
        return [
            {
                "type": "function",
                "name": "iat_sql_query",
                "description": "Execute SQL against a company database",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "database_key": {"type": "string"},
                        "query": {"type": "string"},
                        "format": {"type": "string"},
                    },
                    "required": ["database_key", "query"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        ]

    def get_tool_definition(self, company_short_name, function_name):
        if function_name != "iat_sql_query":
            return None
        return SimpleNamespace(tool_type="SYSTEM")

    def get_system_handler(self, function_name):
        if function_name == "iat_sql_query":
            return self.sql_service.exec_sql
        return None


class FakeCompanyRegistry:
    def __init__(self, company_short_name):
        self._revision = 1
        self._instances = {company_short_name: object()}

    def get_revision(self):
        return self._revision

    def get_all_company_instances(self):
        return self._instances


class FakeLLMProxy:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


def test_llm_query_view_openai_sql_function_call_success():
    app = Flask(__name__)
    client = app.test_client()

    company = Company(id=1, name="Test Company", short_name=COMPANY_SHORT_NAME)
    i18n_service = FakeI18nService()
    utility = Utility()

    # Real SQL service with an in-memory fake provider
    sql_service = SqlService(util=utility, i18n_service=i18n_service)
    db_provider = FakeDatabaseProvider(rows=[{"total": 42}])
    sql_service._db_connections[(COMPANY_SHORT_NAME, DATABASE_KEY)] = db_provider
    sql_service._db_schemas[(COMPANY_SHORT_NAME, DATABASE_KEY)] = "public"

    tool_service = FakeToolService(sql_service)
    llmquery_repo = FakeLLMQueryRepo()

    dispatcher = Dispatcher(
        llmquery_repo=llmquery_repo,
        inference_service=MagicMock(),
        util=utility,
    )
    dispatcher._tool_service = tool_service
    dispatcher._company_registry = FakeCompanyRegistry(COMPANY_SHORT_NAME)

    first_response = LLMResponse(
        id="resp_openai_1",
        model=MODEL,
        status="completed",
        output_text="",
        output=[
            ToolCall(
                call_id="call_sql_1",
                type="function_call",
                name="iat_sql_query",
                arguments=json.dumps(
                    {
                        "database_key": DATABASE_KEY,
                        "query": "SELECT 42 AS total",
                        "format": "dict",
                    }
                ),
            )
        ],
        usage=Usage(input_tokens=100, output_tokens=25, total_tokens=125),
    )

    second_response = LLMResponse(
        id="resp_openai_2",
        model=MODEL,
        status="completed",
        output_text=json.dumps({"answer": "Hay 42 registros.", "aditional_data": {}}),
        output=[],
        usage=Usage(input_tokens=30, output_tokens=15, total_tokens=45),
    )

    llm_proxy = FakeLLMProxy([first_response, second_response])

    llm_client = llmClient(
        llmquery_repo=llmquery_repo,
        llm_proxy=llm_proxy,
        model_registry=FakeModelRegistry(),
        storage_service=MagicMock(),
        util=utility,
    )
    llm_client._dispatcher = dispatcher
    llm_client.count_tokens = lambda text, history=None: 12

    query_service = QueryService(
        dispatcher=dispatcher,
        tool_service=tool_service,
        llm_client=llm_client,
        profile_repo=FakeProfileRepo(company),
        i18n_service=i18n_service,
        session_context=MagicMock(),
        configuration_service=MagicMock(),
        history_manager=FakeHistoryManager(previous_response_id="ctx_openai_prev_1"),
        model_registry=FakeModelRegistry(),
        context_builder=FakeContextBuilder(),
    )

    auth_service = MagicMock()
    auth_service.verify.return_value = {"success": True, "user_identifier": USER_IDENTIFIER}

    view = LLMQueryApiView.as_view(
        "llm_query_api_integration",
        auth_service=auth_service,
        query_service=query_service,
        profile_service=MagicMock(),
        i18n_service=i18n_service,
    )
    app.add_url_rule("/<company_short_name>/api/query", view_func=view, methods=["POST"])

    response = client.post(
        f"/{COMPANY_SHORT_NAME}/api/query",
        json={
            "question": "Cuantos registros hay?",
            "model": MODEL,
        },
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["valid_response"] is True
    assert payload["model"] == MODEL
    assert payload["response_id"] == "resp_openai_2"
    assert "Hay 42 registros" in payload["answer"]

    assert db_provider.executed == [("SELECT 42 AS total", None)]
    assert len(llm_proxy.calls) == 2
    assert llm_proxy.calls[0]["model"] == MODEL
    assert llm_proxy.calls[1]["previous_response_id"] == "resp_openai_1"

    function_output_event = llm_proxy.calls[1]["input"][1]
    assert function_output_event["type"] == "function_call_output"
    assert function_output_event["call_id"] == "call_sql_1"
    assert json.loads(function_output_event["output"]) == [{"total": 42}]

    assert len(llmquery_repo.saved_queries) == 1
