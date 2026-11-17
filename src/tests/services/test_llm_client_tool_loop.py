# Tool loop guarantees of llmClient.invoke: the round budget, tool errors fed
# back to the model, and the stop on repeated failures.

import json
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.repositories.models import Company
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.chat_stream import RoundStream, TurnCancelled
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.telemetry_service import TelemetryExecution


def _tool_response(response_id, *calls):
    tool_calls = [
        ToolCall(call_id, 'function_call', name, arguments)
        for call_id, name, arguments in calls
    ]
    return LLMResponse(response_id, 'gpt-4o', 'completed', '', tool_calls, Usage(10, 5, 15))


def _final_response(answer="final answer"):
    return LLMResponse(
        'final', 'gpt-4o', 'completed',
        json.dumps({"answer": answer, "additional_data": {}}),
        [], Usage(100, 50, 150),
    )


class JobTimeoutException(Exception):
    """Same class name and module check as RQ's timeout signal."""


JobTimeoutException.__module__ = "rq.timeouts"


class _LLMClientFixture:
    def setup_method(self):
        self.proxy = MagicMock()
        self.proxy.describe_provider.return_value = "unknown"
        self.proxy.describe_transport.return_value = "direct"
        model_registry = MagicMock(spec=ModelRegistry)
        model_registry.resolve_request_params.return_value = {"text": {}, "reasoning": {}}
        telemetry_service = MagicMock()
        telemetry_service.start_execution.return_value = TelemetryExecution()
        self.llmquery_repo = MagicMock()

        patch('iatoolkit.services.llm_client_service.tiktoken').start()

        self.client = llmClient(
            llmquery_repo=self.llmquery_repo,
            util=MagicMock(),
            llm_proxy=self.proxy,
            model_registry=model_registry,
            storage_service=MagicMock(spec=StorageService),
            telemetry_service=telemetry_service,
        )
        self.dispatcher = MagicMock()
        self.client._dispatcher = self.dispatcher
        self.company = Company(id=1, name='Test Company', short_name='test_company')

    def teardown_method(self):
        patch.stopall()

    def _invoke(self, **kwargs):
        return self.client.invoke(
            company=self.company, user_identifier='user1', model='gpt-5', question='q', context='c', tools=[{"name": "t"}], text={},
            images=[], **kwargs,
        )

    def _outputs_sent_on_call(self, call_index):
        sent = self.proxy.create_response.call_args_list[call_index].kwargs["input"]
        return [m for m in sent if isinstance(m, dict) and m.get("type") == "function_call_output"]


class TestToolLoop(_LLMClientFixture):
    def test_tool_error_is_returned_to_the_model_instead_of_aborting(self):
        self.dispatcher.dispatch.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.PERMISSION, "Runtime policy blocked this tool call."
        )
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'get_sales', '{"year": 2026}')),
            _final_response("no tengo permiso"),
        ]

        result = self._invoke()

        assert result['answer']
        output = json.loads(self._outputs_sent_on_call(1)[0]["output"])
        assert output["status"] == "error"
        assert output["tool"] == "get_sales"
        assert output["error_type"] == "PERMISSION"
        assert "Runtime policy blocked" in output["message"]
        assert result['stats']['tool_error_count'] == 1
        assert result['stats']['tool_round_count'] == 1
        assert 'tool_loop_stop_reason' not in result['stats']
        assert self.proxy.create_response.call_args_list[1].kwargs["tool_choice"] == "auto"

    def test_invalid_tool_arguments_are_returned_without_dispatching(self):
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'get_sales', '{not json')),
            _final_response(),
        ]

        result = self._invoke()

        self.dispatcher.dispatch.assert_not_called()
        output = json.loads(self._outputs_sent_on_call(1)[0]["output"])
        assert output["error_type"] == "INVALID_ARGUMENTS"
        assert result['stats']['tool_error_count'] == 1

    def test_long_error_messages_are_truncated(self):
        self.dispatcher.dispatch.side_effect = RuntimeError("x" * 10_000)
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'get_sales', '{}')),
            _final_response(),
        ]

        self._invoke()

        output = json.loads(self._outputs_sent_on_call(1)[0]["output"])
        assert len(output["message"]) <= llmClient.TOOL_ERROR_MESSAGE_MAX_LENGTH + 1
        assert output["error_type"] == "RuntimeError"

    def test_worker_timeout_signal_is_never_swallowed(self):
        self.dispatcher.dispatch.side_effect = JobTimeoutException("job timed out")
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'get_sales', '{}')),
            _final_response(),
        ]

        # The timeout stops the execution; it is not fed back to the model as a
        # tool error (the outer handler of invoke wraps every failure).
        with pytest.raises(IAToolkitException, match="job timed out"):
            self._invoke()

        assert self.proxy.create_response.call_count == 1

    def test_budget_exhausted_skips_pending_calls_and_forces_final_answer(self):
        self.dispatcher.dispatch.return_value = {"ok": True}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _tool_response('r2', ('c2', 'search', '{}')),
            _tool_response('r3', ('c3', 'search', '{}'), ('c4', 'other', '{}')),
            _final_response("con lo que tengo"),
        ]

        result = self._invoke(max_tool_rounds=2)

        assert self.dispatcher.dispatch.call_count == 2
        final_call = self.proxy.create_response.call_args_list[3].kwargs
        assert final_call["tool_choice"] == "none"
        skipped = {m["call_id"]: json.loads(m["output"]) for m in self._outputs_sent_on_call(3)}
        assert skipped["c3"]["error_type"] == "TOOL_BUDGET_EXHAUSTED"
        assert skipped["c4"]["status"] == "not_executed"
        assert result['stats']['tool_round_count'] == 2
        assert result['stats']['tool_loop_stop_reason'] == "tool_budget_exhausted"

    def test_model_ignoring_tool_choice_none_does_not_loop(self):
        self.dispatcher.dispatch.return_value = {"ok": True}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _tool_response('r2', ('c2', 'search', '{}')),
            _tool_response('r3', ('c3', 'search', '{}')),
        ]

        result = self._invoke(max_tool_rounds=1)

        assert self.proxy.create_response.call_count == 3
        assert self.dispatcher.dispatch.call_count == 1
        assert result['stats']['tool_loop_stop_reason'] == "tool_budget_exhausted"

    def test_repeated_failed_rounds_force_a_final_answer(self):
        self.dispatcher.dispatch.side_effect = RuntimeError("upstream down")
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _tool_response('r2', ('c2', 'search', '{}')),
            _tool_response('r3', ('c3', 'search', '{}')),
            _final_response(),
        ]

        result = self._invoke()

        assert self.dispatcher.dispatch.call_count == llmClient.MAX_CONSECUTIVE_FAILED_TOOL_ROUNDS
        assert self.proxy.create_response.call_args_list[3].kwargs["tool_choice"] == "none"
        last_output = self._outputs_sent_on_call(3)[-1]["output"]
        assert llmClient.TOOL_LOOP_FAILURES_NOTICE in last_output
        assert result['stats']['tool_loop_stop_reason'] == "repeated_tool_failures"

    def test_a_successful_call_resets_the_failure_streak(self):
        self.dispatcher.dispatch.side_effect = [
            RuntimeError("a"), RuntimeError("b"), {"ok": True}, RuntimeError("c"), RuntimeError("d"),
        ]
        self.proxy.create_response.side_effect = [
            _tool_response(f'r{i}', (f'c{i}', 'search', '{}')) for i in range(5)
        ] + [_final_response()]

        result = self._invoke()

        assert 'tool_loop_stop_reason' not in result['stats']
        assert result['stats']['tool_error_count'] == 4

    def _recorded_calls(self):
        return self.llmquery_repo.add_query.call_args.args[0].function_calls

    def test_each_call_records_its_outcome_next_to_its_arguments(self):
        self.dispatcher.dispatch.return_value = {"status": "success", "content": {"databases": ["KB_TASK"]}}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'list_dbs', '{}')),
            _final_response(),
        ]

        # One token per character, so the count is checkable.
        self.client.encoding = MagicMock(encode=lambda text: list(text))

        self._invoke()

        [call] = self._recorded_calls()
        # The tool name stays the first key: every reader takes it from there.
        assert next(iter(call)) == "list_dbs"
        assert call["list_dbs"] == {}
        output = '{"status": "success", "content": {"databases": ["KB_TASK"]}}'
        assert call["result"] == {
            "status": "ok",
            "excerpt": output,
            # Tokens of the whole output the model received, not of the excerpt.
            "tokens": len(output),
        }

    def test_tokens_count_the_whole_output_even_when_the_excerpt_is_cut(self):
        long_rows = [{"id": index, "text": "x" * 50} for index in range(200)]
        self.dispatcher.dispatch.return_value = long_rows
        self.client.encoding = MagicMock(encode=lambda text: list(text))
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'iat_sql_query', '{"query": "SELECT 1"}')),
            _final_response(),
        ]

        self._invoke()

        [call] = self._recorded_calls()
        assert call["result"]["excerpt"].endswith("…")
        assert call["result"]["tokens"] == len(llmClient._serialize_tool_output(long_rows))

    def test_an_error_returned_as_a_payload_is_recorded_as_an_error(self):
        # An MCP server with no connection does not raise: it answers with its error.
        self.dispatcher.dispatch.return_value = {
            "status": "error", "error_code": "MCP_NO_USER_FOR_PER_USER_SERVER",
            "error": "'Maxxa' acts with each user's own account",
        }
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'list_dbs', '{}')),
            _final_response(),
        ]

        self._invoke()

        [call] = self._recorded_calls()
        assert call["result"]["status"] == "error"
        assert "MCP_NO_USER_FOR_PER_USER_SERVER" in call["result"]["excerpt"]

    def test_a_tool_that_raises_is_recorded_as_an_error(self):
        self.dispatcher.dispatch.side_effect = RuntimeError("connection refused")
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'get_sales', '{"year": 2026}')),
            _final_response(),
        ]

        self._invoke()

        [call] = self._recorded_calls()
        assert call["get_sales"] == {"year": 2026}
        assert call["result"]["status"] == "error"
        assert "connection refused" in call["result"]["excerpt"]

    def test_the_excerpt_is_short(self):
        self.dispatcher.dispatch.return_value = "fila " * 1000
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'query', '{}')),
            _final_response(),
        ]

        self._invoke()

        excerpt = self._recorded_calls()[0]["result"]["excerpt"]
        assert len(excerpt) == llmClient.TOOL_CALL_EXCERPT_MAX_LENGTH
        assert excerpt.endswith("…")

    def test_token_stats_accumulate_across_every_round(self):
        self.dispatcher.dispatch.return_value = {"ok": True}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _tool_response('r2', ('c2', 'search', '{}')),
            _final_response(),
        ]

        result = self._invoke()

        # 15 (first call) + 15 (second round) + 150 (final answer)
        assert result['stats']['total_tokens'] == 180

    @pytest.mark.parametrize("value, expected", [
        (None, llmClient.DEFAULT_MAX_TOOL_ROUNDS),
        (0, llmClient.DEFAULT_MAX_TOOL_ROUNDS),
        (-3, llmClient.DEFAULT_MAX_TOOL_ROUNDS),
        ("abc", llmClient.DEFAULT_MAX_TOOL_ROUNDS),
        (True, llmClient.DEFAULT_MAX_TOOL_ROUNDS),
        (5, 5),
        ("8", 8),
        (10_000, llmClient.MAX_TOOL_ROUNDS_CEILING),
    ])
    def test_resolve_max_tool_rounds(self, value, expected):
        assert self.client._resolve_max_tool_rounds(value) == expected


class TestTokenUsageRecording(_LLMClientFixture):
    def _stored_query(self):
        return self.llmquery_repo.add_query.call_args.args[0]

    def test_failure_halfway_records_the_tokens_already_spent(self):
        self.dispatcher.dispatch.return_value = {"ok": True}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _tool_response('r2', ('c2', 'search', '{}')),
            RuntimeError("context_length_exceeded"),
        ]

        with pytest.raises(IAToolkitException):
            self._invoke(execution_metadata={"request_source": "chat_ui"})

        stats = self._stored_query().stats
        assert stats["input_tokens"] == 20
        assert stats["output_tokens"] == 10
        assert stats["total_tokens"] == 30
        assert stats["model"] == "gpt-5"
        assert stats["failed"] is True
        assert stats["tool_round_count"] == 2
        assert stats["request_source"] == "chat_ui"
        assert self._stored_query().valid_response is False

    def test_failure_on_the_first_call_records_no_usage(self):
        self.proxy.create_response.side_effect = RuntimeError("invalid api key")

        with pytest.raises(IAToolkitException):
            self._invoke()

        assert not self._stored_query().stats

    def test_failure_after_the_success_row_does_not_count_tokens_twice(self):
        self.proxy.create_response.return_value = _final_response()
        with patch.object(self.client, "format_answer", side_effect=RuntimeError("render failed")):
            with pytest.raises(IAToolkitException):
                self._invoke()

        success_row, error_row = [c.args[0] for c in self.llmquery_repo.add_query.call_args_list]
        assert success_row.stats["total_tokens"] == 150
        assert not error_row.stats


class TestToolLoopSendsTheWholeHistory(_LLMClientFixture):
    def test_every_round_carries_the_history_and_no_previous_response(self):
        self.dispatcher.dispatch.return_value = {"ok": True}
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 'search', '{}')),
            _final_response(),
        ]
        history = [{"role": "user", "content": "company context"}]

        self._invoke(context_history=history)

        for call in self.proxy.create_response.call_args_list:
            assert 'previous_response_id' not in call.kwargs
            assert call.kwargs['context_history'] == history
        follow_up = self.proxy.create_response.call_args_list[1].kwargs['input']
        assert [m.get('role') or m.get('type') for m in follow_up] == [
            'user', 'assistant', 'function_call_output',
        ]


class _RecordingSink:
    """An event sink that keeps what the turn reported (BL-023)."""

    def __init__(self):
        self.events = []

    def emit(self, event, payload=None):
        self.events.append((event, payload or {}))

    def is_cancelled(self):
        return False


class TestChatEventSink(_LLMClientFixture):
    def test_without_sink_the_proxy_never_sees_one(self):
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 't', '{}')),
            _final_response(),
        ]
        self.dispatcher.dispatch.return_value = {"ok": True}

        self._invoke()

        for call in self.proxy.create_response.call_args_list:
            assert "event_sink" not in call.kwargs
            assert "stream_callbacks" not in call.kwargs

    def test_reports_rounds_and_tools_in_order(self):
        sink = _RecordingSink()
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 't', '{"a": 1}'), ('c2', 'other', 'not json')),
            _final_response(),
        ]
        self.dispatcher.dispatch.return_value = {"ok": True}

        result = self._invoke(event_sink=sink)

        assert [event for event, _ in sink.events] == [
            "round_start", "round_end",
            "tool_start", "tool_end",
            "tool_start", "tool_end",
            "round_start", "round_end",
        ]
        payloads = [payload for _, payload in sink.events]
        assert payloads[0] == {"round": 1}
        assert payloads[1] == {"round": 1, "has_tool_calls": True}
        assert payloads[2] == {"call_id": "c1", "name": "t"}
        assert payloads[3]["ok"] is True and payloads[3]["name"] == "t"
        assert isinstance(payloads[3]["ms"], int)
        # The second call had arguments that are not JSON: the tool failed.
        assert payloads[5]["ok"] is False and payloads[5]["call_id"] == "c2"
        assert payloads[7] == {"round": 2, "has_tool_calls": False}
        assert result["answer"]
        # The proxy got the round's stream, so a streaming adapter can report deltas.
        for call in self.proxy.create_response.call_args_list:
            assert isinstance(call.kwargs["stream_callbacks"], RoundStream)
            assert "event_sink" not in call.kwargs

    def test_tool_start_never_carries_arguments(self):
        sink = _RecordingSink()
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 't', '{"query": "select secret from t"}')),
            _final_response(),
        ]
        self.dispatcher.dispatch.return_value = {"ok": True}

        self._invoke(event_sink=sink)

        for event, payload in sink.events:
            assert "select secret" not in json.dumps(payload)

    def test_a_failing_sink_does_not_break_the_turn(self):
        sink = MagicMock()
        sink.emit.side_effect = RuntimeError("socket closed")
        sink.is_cancelled.return_value = False
        self.proxy.create_response.side_effect = [_final_response()]

        result = self._invoke(event_sink=sink)

        assert result["valid_response"] is True

    def test_a_turn_with_an_output_schema_streams_no_text(self):
        sink = _RecordingSink()
        self.proxy.create_response.side_effect = [_final_response()]

        self._invoke(event_sink=sink, response_contract={"schema": {"type": "object"}})

        stream = self.proxy.create_response.call_args.kwargs["stream_callbacks"]
        stream.on_text_delta("Hola")
        assert not [event for event, _ in sink.events if event == "text_delta"]

    def test_a_chat_turn_streams_text(self):
        sink = _RecordingSink()
        self.proxy.create_response.side_effect = [_final_response()]

        self._invoke(event_sink=sink)

        stream = self.proxy.create_response.call_args.kwargs["stream_callbacks"]
        stream.on_text_delta("Hola")
        assert ("text_delta", {"text": "Hola"}) in sink.events


class _CancellingSink(_RecordingSink):
    """Cancels once a given event has been reported."""

    def __init__(self, cancel_on):
        super().__init__()
        self._cancel_on = cancel_on
        self.cancelled = False

    def emit(self, event, payload=None):
        super().emit(event, payload)
        if event == self._cancel_on:
            self.cancelled = True

    def is_cancelled(self):
        return self.cancelled


class TestTurnCancellation(_LLMClientFixture):
    def _saved_query(self):
        return self.llmquery_repo.add_query.call_args.args[0]

    def test_cancelled_between_rounds_stops_before_the_next_model_call(self):
        sink = _CancellingSink(cancel_on="tool_end")
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('c1', 't', '{}')),
            _final_response(),
        ]
        self.dispatcher.dispatch.return_value = {"ok": True}

        with pytest.raises(TurnCancelled):
            self._invoke(event_sink=sink)

        assert self.proxy.create_response.call_count == 1
        query = self._saved_query()
        assert query.valid_response is False
        assert query.output == llmClient.TURN_CANCELLED_OUTPUT
        assert query.stats["cancelled"] is True
        # The first call completed: its usage is real, nothing is estimated.
        assert query.stats["input_tokens"] == 10 and query.stats["output_tokens"] == 5
        assert "usage_estimated" not in query.stats
        assert len(query.function_calls) == 1

    def test_cancelled_before_a_tool_runs_skips_it(self):
        sink = _CancellingSink(cancel_on="round_end")
        self.proxy.create_response.side_effect = [_tool_response('r1', ('c1', 't', '{}'))]

        with pytest.raises(TurnCancelled):
            self._invoke(event_sink=sink)

        self.dispatcher.dispatch.assert_not_called()
        assert self._saved_query().stats["cancelled"] is True

    def test_a_call_cut_short_records_an_estimated_usage(self):
        sink = _CancellingSink(cancel_on="never")

        def cut_short(**kwargs):
            stream = kwargs["stream_callbacks"]
            stream.on_text_delta("Las ventas de marzo fueron")
            raise TurnCancelled()

        self.proxy.create_response.side_effect = cut_short
        self.client._count_text_tokens = MagicMock(side_effect=lambda text: len(text.split()))

        with pytest.raises(TurnCancelled):
            self._invoke(event_sink=sink)

        stats = self._saved_query().stats
        assert stats["cancelled"] is True
        assert stats["usage_estimated"] is True
        assert stats["output_tokens"] == 5
        assert stats["input_tokens"] > 0
        assert stats["total_tokens"] == stats["input_tokens"] + stats["output_tokens"]

    def test_a_turn_nobody_cancels_records_no_cancellation(self):
        self.proxy.create_response.side_effect = [_final_response()]

        self._invoke(event_sink=_CancellingSink(cancel_on="never"))

        assert "cancelled" not in self._saved_query().stats


class TestCharts(_LLMClientFixture):
    """Output charts (BL-025): a chart travels with the turn, not with the model."""

    CHART = {"id": "abc123def456", "kind": "chart", "type": "bar", "columns": ["m", "v"],
             "rows": [["Ene", 1]], "echarts": {"series": []}}

    def _chart_turn(self, answer):
        self.dispatcher.dispatch.return_value = {
            "status": "ok", "chart_id": self.CHART["id"], "marker": f"[[chart:{self.CHART['id']}]]",
            "__iat_chart__": dict(self.CHART),
        }
        self.proxy.create_response.side_effect = [
            _tool_response('r1', ('call1', 'iat_chart', '{"x": "m", "series": ["v"]}')),
            _final_response(answer),
        ]
        return self._invoke()

    def test_the_chart_goes_with_the_answer_in_its_slot(self):
        result = self._chart_turn("Así fue el año:\n\n[[chart:abc123def456]]\n\nOctubre fue el mayor.")

        assert result["parts"] == [self.CHART]
        assert '<div class="iat-part" data-part-id="abc123def456"></div>' in result["answer"]
        assert "[[chart:" not in result["answer"]
        assert result["answer"].index("Así fue") < result["answer"].index("iat-part") < result["answer"].index("Octubre")

    def test_the_model_never_reads_the_chart_itself(self):
        result = self._chart_turn("[[chart:abc123def456]]")

        sent = json.loads(self._outputs_sent_on_call(1)[0]["output"])
        assert "__iat_chart__" not in sent
        assert sent["marker"] == "[[chart:abc123def456]]"
        history_outputs = [m for m in result["history_messages"] if m.get("type") == "function_call_output"]
        assert all("__iat_chart__" not in m["output"] for m in history_outputs)

    def test_the_chart_is_saved_with_the_turn(self):
        self._chart_turn("[[chart:abc123def456]]")

        saved = self.llmquery_repo.add_query.call_args.args[0]
        assert saved.response["parts"] == [self.CHART]

    def test_a_chart_the_model_did_not_place_still_shows(self):
        result = self._chart_turn("Listo, aquí está el gráfico.")

        assert result["answer"].rstrip().endswith('<div class="iat-part" data-part-id="abc123def456"></div>')

    def test_a_turn_without_charts_has_no_parts(self):
        self.proxy.create_response.side_effect = [_final_response("hola")]

        result = self._invoke()

        assert result["parts"] == []
        assert "iat-part" not in result["answer"]
        assert "parts" not in self.llmquery_repo.add_query.call_args.args[0].response


class TestPlaceParts:
    def test_markers_for_unknown_or_repeated_charts_are_dropped(self):
        html = "<p>[[chart:aaaaaa]]</p>\n<p>otra vez [[chart:aaaaaa]] y [[chart:bbbbbb]]</p>"

        placed = llmClient.place_parts(html, [{"id": "aaaaaa"}])

        assert placed.count("iat-part") == 1
        assert "[[chart:" not in placed

    def test_whatsapp_gets_no_markers(self):
        client = llmClient.__new__(llmClient)

        text = client.format_answer("Mira:\n\n[[chart:aaaaaa]]\n\nfin", {"delivery_channel": "whatsapp"},
                                    parts=[{"id": "aaaaaa"}])

        assert "[[chart" not in text and "iat-part" not in text
