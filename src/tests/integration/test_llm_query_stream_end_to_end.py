# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The chat's live turn end to end (BL-023).

Everything is real from the SSE view down to the OpenAI adapter: the stream
view and its thread, QueryService, llmClient's tool loop, the Dispatcher, the
SQL service, LLMProxy and OpenAIAdapter. The only fake below the view is the
OpenAI HTTP client, which answers `responses.create(stream=True)` with the
events the Responses API sends; the SQL source and the repositories are
in-memory.
"""

import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_providers.openai_adapter import OpenAIAdapter
from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.repositories.models import Company
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.views.llmquery_stream_api_view import LLMQueryStreamApiView

COMPANY = "acme"
USER = "ana@acme.com"
DATABASE_KEY = "main_db"
MODEL = "gpt-5"


# ---------------------------------------------------------------------------
# In-memory collaborators
# ---------------------------------------------------------------------------

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
        self.executed.append(query)
        return self.rows

    def rollback(self):
        return None


class FakeLLMQueryRepo:
    def __init__(self):
        self.saved_queries = []
        self.saved = threading.Event()

    def add_query(self, query):
        query.id = len(self.saved_queries) + 1
        self.saved_queries.append(query)
        self.saved.set()

    def commit(self):
        return None

    def rollback(self):
        return None


class FakeModelRegistry:
    def resolve_request_params(self, model, text, reasoning=None):
        return {"text": text or {}, "reasoning": reasoning or {}}


class FakeHistoryManager:
    def __init__(self):
        self.updates = []

    def populate_request_params(self, handle, user_turn_prompt, ignore_history):
        handle.request_params = {"context_history": [{"role": "user", "content": "company context"}]}
        return False

    def update_history(self, handle, user_turn_prompt, response):
        self.updates.append(response)


class FakeContextBuilder:
    def build_user_turn_prompt(self, company, user_identifier, client_data, files, prompt_name, question):
        return question, question, []


class FakeToolService:
    def __init__(self, sql_service):
        self.sql_service = sql_service

    def get_tools_for_llm(self, company, user_identifier=None):
        return [{
            "type": "function",
            "name": "iat_sql_query",
            "description": "Execute SQL against a company database",
            "parameters": {
                "type": "object",
                "properties": {"database_key": {"type": "string"}, "query": {"type": "string"}},
                "required": ["database_key", "query"],
            },
        }]

    def get_tool_definition(self, company_short_name, function_name):
        return SimpleNamespace(tool_type="SYSTEM") if function_name == "iat_sql_query" else None

    def get_system_handler(self, function_name):
        return self.sql_service.exec_sql if function_name == "iat_sql_query" else None


class FakeCompanyRegistry:
    def get_revision(self):
        return 1

    def get_all_company_instances(self):
        return {COMPANY: object()}


# ---------------------------------------------------------------------------
# The OpenAI Responses API, streamed
# ---------------------------------------------------------------------------

def _usage(input_tokens, output_tokens):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           total_tokens=input_tokens + output_tokens)


def _message(text):
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])


def _completed(response_id, output, usage):
    response = SimpleNamespace(id=response_id, model=MODEL, status="completed",
                               output_text="", output=output, usage=usage)
    return SimpleNamespace(type="response.completed", response=response)


def _text_deltas(*pieces):
    return [SimpleNamespace(type="response.output_text.delta", delta=piece) for piece in pieces]


def tool_round_events():
    """The model says what it will do, then asks for a SQL query."""
    call = SimpleNamespace(type="function_call", call_id="call_sql_1", name="iat_sql_query",
                           arguments=json.dumps({"database_key": DATABASE_KEY, "query": "SELECT 42 AS total"}))
    return (
        [SimpleNamespace(type="response.created")]
        + _text_deltas("Voy a ", "contar los registros.")
        + [_completed("resp_1", [_message("Voy a contar los registros."), call], _usage(100, 20))]
    )


def answer_round_events():
    return (
        _text_deltas("Hay ", "**42**", " registros.")
        + [_completed("resp_2", [_message("Hay **42** registros.")], _usage(130, 10))]
    )


class FakeOpenAIStream:
    """What `responses.create(stream=True)` returns: an iterable that can be closed."""

    def __init__(self, events, delay=0.0):
        self._events = events
        self._delay = delay
        self.closed = False

    def __iter__(self):
        for event in self._events:
            if self._delay:
                time.sleep(self._delay)
            yield event

    def close(self):
        self.closed = True


class FakeOpenAIClient:
    """Answers each streamed call with the next scripted round."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []
        self.streams = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **params):
        if isinstance(self._rounds[0], FakeOpenAIStream):
            assert params.get("stream") is True, "the chat turn must be streamed"
        else:
            assert "stream" not in params, "a provider that does not stream gets a plain call"
        self.calls.append(params)
        stream = self._rounds.pop(0)
        self.streams.append(stream)
        return stream


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

class StreamingStack:
    def __init__(self, openai_rounds):
        utility = Utility()
        i18n_service = FakeI18nService()
        company = Company(id=1, name="Acme", short_name=COMPANY)

        self.db_provider = FakeDatabaseProvider(rows=[{"total": 42}])
        sql_service = SqlService(util=utility, i18n_service=i18n_service)
        sql_service._db_connections[(COMPANY, DATABASE_KEY)] = self.db_provider
        sql_service._db_schemas[(COMPANY, DATABASE_KEY)] = "public"
        tool_service = FakeToolService(sql_service)

        self.llmquery_repo = FakeLLMQueryRepo()
        dispatcher = Dispatcher(llmquery_repo=self.llmquery_repo, inference_service=MagicMock(), util=utility)
        dispatcher._tool_service = tool_service
        dispatcher._company_registry = FakeCompanyRegistry()

        # The real proxy, routing to a real OpenAIAdapter over the fake HTTP client.
        self.openai_client = FakeOpenAIClient(openai_rounds)
        proxy_config = MagicMock(spec=ConfigurationService)
        proxy_config.get_llm_model_config.return_value = None
        proxy_config.get_llm_provider_config.return_value = {}
        proxy_config.get_llm_gateway_config.return_value = {}
        proxy_config.get_llm_request_defaults.return_value = {}
        model_registry = MagicMock(spec=ModelRegistry)
        model_registry.get_provider.return_value = "openai"
        self.llm_proxy = LLMProxy(
            util=utility,
            configuration_service=proxy_config,
            model_registry=model_registry,
            secret_provider=MagicMock(spec=SecretProvider),
            telemetry_service=MagicMock(**{"wrap_client_for_request.side_effect": lambda **kw: kw["client"]}),
        )
        self.adapter = OpenAIAdapter(self.openai_client)
        self._adapter_patch = patch.object(self.llm_proxy, "_get_or_create_adapter", return_value=self.adapter)
        self._adapter_patch.start()

        llm_client = llmClient(
            llmquery_repo=self.llmquery_repo,
            llm_proxy=self.llm_proxy,
            model_registry=FakeModelRegistry(),
            storage_service=MagicMock(),
            util=utility,
        )
        llm_client._dispatcher = dispatcher
        llm_client.count_tokens = lambda text, history=None: 12

        self.history_manager = FakeHistoryManager()
        query_service = QueryService(
            dispatcher=dispatcher,
            tool_service=tool_service,
            llm_client=llm_client,
            profile_repo=FakeProfileRepo(company),
            i18n_service=i18n_service,
            session_context=MagicMock(),
            configuration_service=MagicMock(**{"get_llm_configuration.return_value": (None, [])}),
            history_manager=self.history_manager,
            model_registry=FakeModelRegistry(),
            context_builder=FakeContextBuilder(),
        )

        auth_service = MagicMock()
        auth_service.verify_for_company.return_value = {"success": True, "user_identifier": USER}
        view_config = MagicMock(spec=ConfigurationService)
        view_config.is_chat_streaming_enabled.return_value = True

        self.app = Flask(__name__)
        self.app.add_url_rule(
            "/<company_short_name>/api/llm_query/stream",
            view_func=LLMQueryStreamApiView.as_view(
                "llm_query_stream_e2e",
                auth_service=auth_service,
                query_service=query_service,
                config_service=view_config,
                i18n_service=i18n_service,
            ),
            methods=["POST"],
        )
        self.client = self.app.test_client()

    def close(self):
        self._adapter_patch.stop()


@pytest.fixture
def env():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        yield


def _parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if lines:
            fields = dict(line.split(": ", 1) for line in lines)
            events.append((fields["event"], json.loads(fields["data"])))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_a_streamed_turn_with_a_tool_end_to_end(env):
    stack = StreamingStack([FakeOpenAIStream(tool_round_events()), FakeOpenAIStream(answer_round_events())])
    try:
        response = stack.client.post(
            f"/{COMPANY}/api/llm_query/stream",
            json={"question": "¿Cuántos registros hay?", "model": MODEL},
        )
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        events = _parse_sse(response.get_data(as_text=True))
    finally:
        stack.close()

    names = [event for event, _ in events]
    assert names == [
        "round_start", "text_delta", "text_delta", "round_end",
        "tool_start", "tool_end",
        "round_start", "text_delta", "text_delta", "text_delta", "round_end",
        "final",
    ]
    payloads = [payload for _, payload in events]

    # Round 1: the preamble streams, then the round turns out to ask for a tool.
    assert "".join(p["text"] for p in payloads[1:3]) == "Voy a contar los registros."
    assert payloads[3] == {"round": 1, "has_tool_calls": True}
    # The tool runs for real, reported by name only.
    assert payloads[4] == {"call_id": "call_sql_1", "name": "iat_sql_query"}
    assert payloads[5]["ok"] is True
    assert stack.db_provider.executed == ["SELECT 42 AS total"]
    # Round 2: the answer, as it was written.
    assert "".join(p["text"] for p in payloads[7:10]) == "Hay **42** registros."
    assert payloads[10] == {"round": 2, "has_tool_calls": False}

    # The final event is what /api/llm_query answers: rendered and sanitized HTML.
    final = payloads[-1]
    assert final["valid_response"] is True
    assert "<strong>42</strong>" in final["answer"]
    assert final["response_id"] == "resp_2"
    assert final["stats"]["input_tokens"] == 230
    assert final["stats"]["output_tokens"] == 30
    assert "schema_valid" not in final
    # What the person saw live is recorded with the query.
    stream_stats = final["stats"]["stream"]
    assert stream_stats["mode"] == "text"
    assert stream_stats["text_deltas"] == 5
    assert isinstance(stream_stats["first_text_ms"], int)
    assert stack.llmquery_repo.saved_queries[0].stats["stream"] == stream_stats

    # Both rounds were streamed and closed; the second carried the tool output.
    assert len(stack.openai_client.calls) == 2
    assert all(stream.closed for stream in stack.openai_client.streams)
    second_input = stack.openai_client.calls[1]["input"]
    assert any(item.get("type") == "function_call_output" and item.get("call_id") == "call_sql_1"
               for item in second_input)

    # One query row, one history update: the turn happened once.
    assert len(stack.llmquery_repo.saved_queries) == 1
    assert stack.llmquery_repo.saved_queries[0].valid_response is True
    assert len(stack.history_manager.updates) == 1


def test_a_browser_that_leaves_stops_the_turn_end_to_end(env):
    # The answer round is slow: the browser leaves while it is being written.
    slow_answer = FakeOpenAIStream(_text_deltas(*["palabra "] * 200) + answer_round_events(), delay=0.01)
    stack = StreamingStack([FakeOpenAIStream(tool_round_events()), slow_answer])
    try:
        response = stack.client.post(
            f"/{COMPANY}/api/llm_query/stream",
            json={"question": "¿Cuántos registros hay?", "model": MODEL},
            buffered=False,
        )
        seen = ""
        for chunk in response.response:
            seen += chunk.decode() if isinstance(chunk, bytes) else chunk
            if seen.count("event: text_delta") >= 5 and "event: tool_end" in seen:
                break
        response.close()  # the browser goes away

        assert stack.llmquery_repo.saved.wait(timeout=5), "the stopped turn was never recorded"
    finally:
        stack.close()

    # The provider stream was cut well before its end.
    assert slow_answer.closed
    query = stack.llmquery_repo.saved_queries[0]
    assert query.valid_response is False
    assert query.stats["cancelled"] is True
    assert query.stats["usage_estimated"] is True
    # The tool round completed and kept its real usage; the cut round was estimated on top.
    assert query.stats["input_tokens"] > 100
    assert len(query.function_calls) == 1
    assert query.stats["stream"]["mode"] == "text"
    # A stopped turn never reaches the history.
    assert stack.history_manager.updates == []


def test_a_provider_that_does_not_stream_still_shows_the_activity(env):
    """Any provider goes through the live endpoint: its rounds and tools are
    reported, and the answer arrives with the final event."""
    tool_round = tool_round_events()[-1].response
    answer_round = answer_round_events()[-1].response
    stack = StreamingStack([tool_round, answer_round])
    try:
        with patch.object(OpenAIAdapter, "supports_streaming", False):
            response = stack.client.post(
                f"/{COMPANY}/api/llm_query/stream",
                json={"question": "¿Cuántos registros hay?", "model": MODEL},
            )
            # Read inside the patch: the turn runs while the response is consumed.
            events = _parse_sse(response.get_data(as_text=True))
    finally:
        stack.close()

    assert [event for event, _ in events] == [
        "round_start", "round_end", "tool_start", "tool_end", "round_start", "round_end", "final",
    ]
    assert events[-1][1]["valid_response"] is True
    assert "<strong>42</strong>" in events[-1][1]["answer"]
    assert events[-1][1]["stats"]["stream"]["mode"] == "activity"
    assert len(stack.history_manager.updates) == 1
