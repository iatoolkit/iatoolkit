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
            company=self.company, user_identifier='user1', previous_response_id='prev1',
            model='gpt-5', question='q', context='c', tools=[{"name": "t"}], text={},
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


class TestContextInitUsage(_LLMClientFixture):
    def test_context_init_is_recorded_as_its_own_query_row(self):
        self.proxy.create_response.return_value = LLMResponse(
            'resp_ctx', 'gpt-5', 'completed', '', [], Usage(30_000, 12, 30_012)
        )

        response_id = self.client.set_company_context(
            company=self.company, company_base_context="ctx", model="gpt-5", user_identifier="user1",
        )

        assert response_id == 'resp_ctx'
        row = self.llmquery_repo.add_query.call_args.args[0]
        assert row.user_identifier == "user1"
        assert row.company_id == 1
        assert row.query == llmClient.CONTEXT_INIT_QUERY_LABEL
        assert row.stats["request_source"] == "context_init"
        assert row.stats["input_tokens"] == 30_000
        assert row.stats["output_tokens"] == 12
        assert row.stats["total_tokens"] == 30_012
        assert row.stats["model"] == "gpt-5"

    def test_a_failure_to_record_does_not_fail_the_initialization(self):
        self.proxy.create_response.return_value = LLMResponse(
            'resp_ctx', 'gpt-5', 'completed', '', [], Usage(10, 1, 11)
        )
        self.llmquery_repo.add_query.side_effect = RuntimeError("db down")

        response_id = self.client.set_company_context(
            company=self.company, company_base_context="ctx", model="gpt-5", user_identifier="user1",
        )

        assert response_id == 'resp_ctx'
        self.llmquery_repo.rollback.assert_called_once()

    def test_failed_llm_call_records_nothing(self):
        self.proxy.create_response.side_effect = RuntimeError("down")

        with pytest.raises(IAToolkitException):
            self.client.set_company_context(
                company=self.company, company_base_context="ctx", model="gpt-5", user_identifier="user1",
            )

        self.llmquery_repo.add_query.assert_not_called()
