import json
from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.llmquery_stream_api_view import LLMQueryStreamApiView

COMPANY = "acme"
USER = "user@acme.com"


def _parse_sse(body: str):
    """The (event, payload) pairs of an SSE body; comments (heartbeats) are skipped."""
    events = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


class TestLLMQueryStreamApiView:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.auth = MagicMock(spec=AuthService)
        self.query = MagicMock(spec=QueryService)
        self.config = MagicMock(spec=ConfigurationService)
        self.i18n = MagicMock(spec=I18nService)
        self.i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.auth.verify_for_company.return_value = {"success": True, "user_identifier": USER}
        self.config.is_chat_streaming_enabled.return_value = True

        view = LLMQueryStreamApiView.as_view(
            'llm_query_stream_api',
            auth_service=self.auth,
            query_service=self.query,
            config_service=self.config,
            i18n_service=self.i18n,
        )
        self.app.add_url_rule('/<company_short_name>/api/llm_query/stream', view_func=view, methods=['POST'])
        self.url = f'/{COMPANY}/api/llm_query/stream'

    def test_relays_the_turn_events_and_ends_with_the_same_result_as_llm_query(self):
        def fake_llm_query(**kwargs):
            sink = kwargs["event_sink"]
            sink.emit("round_start", {"round": 1})
            sink.emit("tool_start", {"call_id": "c1", "name": "iat_sql_query"})
            sink.emit("tool_end", {"call_id": "c1", "name": "iat_sql_query", "ok": True, "ms": 12})
            return {"answer": "<p>hola</p>", "query_id": 7, "schema_valid": True, "schema_errors": []}

        self.query.llm_query.side_effect = fake_llm_query

        response = self.client.post(self.url, json={"question": "hola", "model": "gpt-5"})

        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert response.headers["X-Accel-Buffering"] == "no"
        events = _parse_sse(response.get_data(as_text=True))
        assert [event for event, _ in events] == ["round_start", "tool_start", "tool_end", "final"]
        # The final event is what /api/llm_query answers, schema diagnostics removed.
        assert events[-1][1] == {"answer": "<p>hola</p>", "query_id": 7}

        kwargs = self.query.llm_query.call_args.kwargs
        assert kwargs["company_short_name"] == COMPANY
        assert kwargs["user_identifier"] == USER
        assert kwargs["question"] == "hola"
        assert kwargs["model"] == "gpt-5"
        assert kwargs["client_data"] == {"source": "chat_ui"}

    def test_pii_tokens_reach_the_person_as_values(self, monkeypatch):
        """BL-034 R11: a token cut between deltas is restored whole, and held text
        goes out before the next event so the order is kept."""
        from iatoolkit.common import pii_masking
        from iatoolkit.services.pii_masking_service import PersonView
        from iatoolkit.views import llmquery_stream_api_view as stream_view

        token = "[PII-0123456789ab]"
        values = {token: "Ana Pérez"}
        monkeypatch.setattr(stream_view, "person_view_for", lambda company, user: PersonView(
            lambda t: values.get(t, pii_masking.MISSING)))

        def fake_llm_query(**kwargs):
            sink = kwargs["event_sink"]
            sink.emit("text_delta", {"text": "Cliente [PII-0123"})
            sink.emit("text_delta", {"text": "456789ab] y [PII"})
            sink.emit("round_end", {"round": 1, "has_tool_calls": False})
            return {"answer": f"<p>Cliente {token}</p>", "query_id": 7}

        self.query.llm_query.side_effect = fake_llm_query

        events = _parse_sse(self.client.post(self.url, json={"question": "x"}).get_data(as_text=True))

        assert events == [
            ("text_delta", {"text": "Cliente "}),
            ("text_delta", {"text": "Ana Pérez y "}),
            ("text_delta", {"text": "[PII"}),
            ("round_end", {"round": 1, "has_tool_calls": False}),
            ("final", {"answer": "<p>Cliente Ana Pérez</p>", "query_id": 7}),
        ]

    def test_a_failed_turn_ends_with_an_error_event(self):
        self.query.llm_query.return_value = {"error": True, "error_message": "el modelo falló"}

        events = _parse_sse(self.client.post(self.url, json={"question": "x"}).get_data(as_text=True))

        assert events == [("error", {"error_message": "el modelo falló"})]

    def test_an_exception_ends_with_a_generic_error_event(self):
        self.query.llm_query.side_effect = RuntimeError("boom")

        events = _parse_sse(self.client.post(self.url, json={"question": "x"}).get_data(as_text=True))

        assert events == [("error", {"error_message": "translated:errors.general.unexpected_error"})]

    def test_a_cancelled_turn_sends_nothing_more(self):
        self.query.llm_query.return_value = {"error": True, "cancelled": True, "error_message": "cancelled"}

        events = _parse_sse(self.client.post(self.url, json={"question": "x"}).get_data(as_text=True))

        assert events == []

    def test_a_browser_that_leaves_cancels_the_turn(self):
        from iatoolkit.services.chat_stream import QueueEventSink
        view = LLMQueryStreamApiView(self.auth, self.query, self.config, self.i18n)
        sink = QueueEventSink()
        sink.emit("round_start", {"round": 1})
        relay = view._relay(sink)

        assert next(relay).startswith(": stream open")
        assert next(relay).startswith("event: round_start")
        relay.close()  # what the server does when the client disconnects

        assert sink.is_cancelled()

    def test_rejects_an_api_key(self):
        self.auth.verify_for_company.return_value = {
            "success": True, "user_identifier": USER, "auth_type": "api_key",
        }

        response = self.client.post(self.url, json={"question": "x"})

        assert response.status_code == 403
        self.query.llm_query.assert_not_called()

    def test_rejects_when_the_company_turned_it_off(self):
        self.config.is_chat_streaming_enabled.return_value = False

        response = self.client.post(self.url, json={"question": "x"})

        assert response.status_code == 404
        self.query.llm_query.assert_not_called()

    def test_failed_authentication_is_plain_json(self):
        self.auth.verify_for_company.return_value = {
            "success": False, "error_message": "auth required", "status_code": 401,
        }

        response = self.client.post(self.url, json={"question": "x"})

        assert response.status_code == 401
        assert response.get_json()["error_message"] == "auth required"

    def test_an_empty_body_is_rejected(self):
        response = self.client.post(self.url, data="", content_type="application/json")

        assert response.status_code == 400


class TestChatStreamingFlag:
    def _service(self, parameters):
        service = ConfigurationService.__new__(ConfigurationService)
        service.get_configuration = MagicMock(return_value=parameters)
        return service

    def test_on_by_default(self):
        assert self._service({}).is_chat_streaming_enabled(COMPANY) is True
        assert self._service(None).is_chat_streaming_enabled(COMPANY) is True
        assert self._service({"chat_streaming": True}).is_chat_streaming_enabled(COMPANY) is True

    def test_off_only_when_set_to_false(self):
        assert self._service({"chat_streaming": False}).is_chat_streaming_enabled(COMPANY) is False
        assert self._service({"chat_streaming": "no"}).is_chat_streaming_enabled(COMPANY) is True
