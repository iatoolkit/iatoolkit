from unittest.mock import MagicMock

from iatoolkit.services.telemetry_service import BraintrustTelemetryBridge, TelemetryExecution, TelemetryService


class TestTelemetryService:
    def test_resolve_execution_request_normalizes_company_label_for_braintrust(self):
        configuration_service = MagicMock()
        configuration_service.get_llm_telemetry_config.return_value = {
            "enabled": True,
            "provider": "braintrust",
            "braintrust": {
                "project": "bt-project",
                "api_key": "BRAINTRUST_API_KEY",
            },
        }
        secret_provider = MagicMock()
        secret_provider.get_secret.return_value = "secret-value"

        service = TelemetryService(
            configuration_service=configuration_service,
            secret_provider=secret_provider,
        )

        request = service.resolve_execution_request(
            company_short_name="ent_company_prod",
            prompt_output_contract={
                "prompt_name": "sales_prompt",
                "llm_request_options": {"telemetry_enabled": True},
            },
            model="gpt-5",
            provider="openai",
            task_id=7,
            user_identifier="user-1",
        )

        assert request["metadata"]["company"] == "ent_company_prod"
        assert request["metadata"]["agent_name"] == "sales_prompt"
        assert "company_short_name" not in request["metadata"]
        assert "prompt_name" not in request["metadata"]

    def test_resolve_execution_request_enables_chat_requests_when_company_telemetry_is_global(self):
        configuration_service = MagicMock()
        configuration_service.get_llm_telemetry_config.return_value = {
            "enabled": True,
            "provider": "braintrust",
            "braintrust": {
                "project": "bt-project",
                "api_key": "BRAINTRUST_API_KEY",
            },
        }
        secret_provider = MagicMock()
        secret_provider.get_secret.return_value = "secret-value"

        service = TelemetryService(
            configuration_service=configuration_service,
            secret_provider=secret_provider,
        )

        request = service.resolve_execution_request(
            company_short_name="ent_company_prod",
            prompt_output_contract={},
            model="gpt-5",
            provider="openai",
            task_id=None,
            user_identifier="user-1",
            execution_metadata={"request_source": "chat_ui"},
        )

        assert request["enabled"] is True
        assert request["execution_name"] == "iatoolkit.chat"
        assert request["metadata"]["agent_name"] == "chat"
        assert request["metadata"]["execution_mode"] == "chat"
        assert request["metadata"]["request_source"] == "chat_ui"
        assert request["metadata"]["telemetry_scope"] == "chat"

    def test_resolve_execution_request_uses_prompt_opt_in_when_company_telemetry_disabled(self):
        configuration_service = MagicMock()
        configuration_service.get_llm_telemetry_config.return_value = {
            "enabled": False,
            "provider": "braintrust",
            "braintrust": {
                "project": "bt-project",
                "api_key": "BRAINTRUST_API_KEY",
            },
        }
        secret_provider = MagicMock()
        secret_provider.get_secret.return_value = "secret-value"

        service = TelemetryService(
            configuration_service=configuration_service,
            secret_provider=secret_provider,
        )

        request = service.resolve_execution_request(
            company_short_name="ent_company_prod",
            prompt_output_contract={
                "prompt_name": "sales_prompt",
                "llm_request_options": {"telemetry_enabled": True},
            },
            model="gpt-5",
            provider="openai",
            task_id=7,
            user_identifier="user-1",
        )

        assert request["requested"] is True
        assert request["disabled_reason"] == "company_disabled"
        assert request["metadata"]["agent_name"] == "sales_prompt"
        assert request["metadata"]["telemetry_scope"] == "prompt"

    def test_resolve_execution_request_ignores_chat_source_when_company_telemetry_disabled(self):
        configuration_service = MagicMock()
        configuration_service.get_llm_telemetry_config.return_value = {
            "enabled": False,
            "provider": "braintrust",
            "braintrust": {
                "project": "bt-project",
                "api_key": "BRAINTRUST_API_KEY",
            },
        }
        secret_provider = MagicMock()
        secret_provider.get_secret.return_value = "secret-value"

        service = TelemetryService(
            configuration_service=configuration_service,
            secret_provider=secret_provider,
        )

        request = service.resolve_execution_request(
            company_short_name="ent_company_prod",
            prompt_output_contract={},
            model="gpt-5",
            provider="openai",
            task_id=None,
            user_identifier="user-1",
            execution_metadata={"request_source": "chat_ui"},
        )

        assert request == {}

    def test_finalize_logs_exact_root_input_payload(self):
        bridge = MagicMock()
        span = MagicMock()
        execution = TelemetryExecution(
            enabled=True,
            bridge=bridge,
            span=span,
        )

        execution.record_input({
            "model": "gpt-5",
            "input": [{"role": "user", "content": "hola"}],
        })
        execution.finalize(success=True, answer_preview="ok")

        event = bridge.log_span.call_args.args[1]
        assert event["input"] == {
            "model": "gpt-5",
            "input": [{"role": "user", "content": "hola"}],
        }

    def test_finalize_wraps_multiple_provider_requests_in_root_input(self):
        bridge = MagicMock()
        span = MagicMock()
        execution = TelemetryExecution(
            enabled=True,
            bridge=bridge,
            span=span,
        )

        execution.record_input({"model": "gpt-5", "input": [{"role": "user", "content": "primer turno"}]})
        execution.record_input({"model": "gpt-5", "input": [{"type": "function_call_output", "output": "ok"}]})
        execution.finalize(success=True, answer_preview="ok")

        event = bridge.log_span.call_args.args[1]
        assert event["input"] == {
            "requests": [
                {"model": "gpt-5", "input": [{"role": "user", "content": "primer turno"}]},
                {"model": "gpt-5", "input": [{"type": "function_call_output", "output": "ok"}]},
            ]
        }

    def test_child_span_helpers_delegate_to_bridge(self):
        bridge = MagicMock()
        span = MagicMock()
        child_span = MagicMock()
        bridge.start_span.return_value = child_span
        execution = TelemetryExecution(
            enabled=True,
            bridge=bridge,
            span=span,
        )

        returned_span = execution.start_child_span(
            name="tool.test_func",
            span_type="tool",
            event={"metadata": {"tool_name": "test_func"}},
        )
        execution.log_child_span(returned_span, {"metadata": {"status": "completed"}})
        execution.end_child_span(returned_span)

        assert returned_span is child_span
        bridge.start_span.assert_called_once_with(
            span,
            name="tool.test_func",
            span_type="tool",
            event={"metadata": {"tool_name": "test_func"}},
        )
        bridge.log_span.assert_called_once_with(
            child_span,
            {"metadata": {"status": "completed"}},
        )
        bridge.end_span.assert_called_once_with(child_span)

    def test_child_span_helpers_are_noop_when_disabled(self):
        bridge = MagicMock()
        span = MagicMock()
        execution = TelemetryExecution(
            enabled=False,
            bridge=bridge,
            span=span,
        )

        child_span = execution.start_child_span(
            name="tool.test_func",
            event={"metadata": {"tool_name": "test_func"}},
        )
        execution.log_child_span(MagicMock(), {"metadata": {"status": "completed"}})
        execution.end_child_span(MagicMock())

        assert child_span is None
        bridge.start_span.assert_not_called()
        bridge.log_span.assert_not_called()
        bridge.end_span.assert_not_called()

    def test_braintrust_bridge_start_span_expands_input_and_metadata_fields(self):
        captured = {}

        class FakeParent:
            def start_span(self, **kwargs):
                captured.update(kwargs)
                return "child-span"

        bridge = BraintrustTelemetryBridge()

        child_span = bridge.start_span(
            FakeParent(),
            name="tool.test_func",
            span_type="tool",
            event={
                "metadata": {"tool_name": "test_func"},
                "input": {"arguments": {"a": 1}},
            },
        )

        assert child_span == "child-span"
        assert captured["name"] == "tool.test_func"
        assert captured["type"] == "tool"
        assert captured["metadata"] == {"tool_name": "test_func"}
        assert captured["input"] == {"arguments": {"a": 1}}
        assert "event" not in captured
