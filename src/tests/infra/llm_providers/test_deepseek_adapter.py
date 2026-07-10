# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock

from iatoolkit.infra.llm_providers.deepseek_adapter import DeepseekAdapter
from iatoolkit.infra.llm_response import LLMResponse, ToolCall
from iatoolkit.common.exceptions import IAToolkitException


class TestDeepseekAdapter:
    def setup_method(self):
        """Common setup for all DeepseekAdapter tests."""
        self.mock_deepseek_client = MagicMock()
        self.adapter = DeepseekAdapter(deepseek_client=self.mock_deepseek_client)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_mock_response(self, content="Hello", tool_calls=None, reasoning_content=""):
        """Helper to create a mock DeepSeek-like response object."""
        mock_response = MagicMock()
        mock_response.id = "chatcmpl-deepseek-123"
        mock_response.model = "deepseek-v4-flash"

        mock_message = MagicMock()
        mock_message.content = content
        mock_message.tool_calls = tool_calls
        mock_message.reasoning_content = reasoning_content

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response.choices = [mock_choice]

        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        return mock_response

    # ------------------------------------------------------------------
    # Request building tests
    # ------------------------------------------------------------------

    def test_create_response_merges_history_and_input_and_maps_model_role(self):
        """
        Ensure:
        1. History and current input are merged in order.
        2. 'model' role is mapped to 'assistant'.
        3. chat.completions.create is called with correct messages.
        """
        # Arrange
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response()

        context_history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello there"},  # should become assistant
        ]
        input_data = [{"role": "user", "content": "How are you?"}]

        # Act
        result = self.adapter.create_response(
            model="deepseek-v4-flash",
            input=input_data,
            context_history=context_history,
        )

        # Assert API call
        self.mock_deepseek_client.chat.completions.create.assert_called_once()
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs

        assert call_kwargs["model"] == "deepseek-v4-flash"
        messages = call_kwargs["messages"]
        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "Hi"}
        assert messages[1] == {"role": "assistant", "content": "Hello there"}
        assert messages[2] == {"role": "user", "content": "How are you?"}

        # Assert mapped response
        assert isinstance(result, LLMResponse)
        assert result.output_text == "Hello"
        assert result.id == "chatcmpl-deepseek-123"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        assert result.usage.total_tokens == 15

        # Check content_parts consistency
        assert len(result.content_parts) == 1
        assert result.content_parts[0] == {"type": "text", "text": "Hello"}

    def test_create_response_with_tools_and_tool_calls(self):
        """
        When tools are provided and the model returns tool_calls:
        - tools are passed to the API.
        - tool calls are mapped to ToolCall objects in LLMResponse.
        """
        # Arrange: build a mock tool_call in the DeepSeek response
        mock_tool_call = MagicMock()
        mock_tool_call.type = "function"
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "search_web"
        mock_tool_call.function.arguments = '{"query": "python"}'

        mock_response = self._create_mock_response(content=None, tool_calls=[mock_tool_call])
        self.mock_deepseek_client.chat.completions.create.return_value = mock_response

        input_data = [{"role": "user", "content": "Search python"}]
        tools = [{"type": "function", "function": {"name": "search_web"}}]

        # Act
        result = self.adapter.create_response(
            model="deepseek-v4-pro",
            input=input_data,
            tools=tools,
            tool_choice="auto",
        )

        # Assert API call
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-v4-pro"
        assert call_kwargs["messages"][-1] == {"role": "user", "content": "Search python"}
        # tools should be passed as-is
        assert call_kwargs["tools"] is not None
        assert "tool_choice" not in call_kwargs

        # Assert mapped LLMResponse
        assert len(result.output) == 1
        assert isinstance(result.output[0], ToolCall)
        assert result.output[0].name == "search_web"
        assert result.output[0].arguments == '{"query": "python"}'
        assert result.status == "tool_calls"
        assert result.output_text == ""

    def test_create_response_with_specific_tool_choice_required(self):
        """
        When tool_choice is "required", it must be passed to the API call.
        """
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response()
        tools = [{"type": "function", "function": {"name": "search_web"}}]

        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[],
            tools=tools,
            tool_choice="required",
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tools"] is not None
        assert call_kwargs["tool_choice"] == "required"

    def test_create_response_without_tools_does_not_pass_tool_choice(self):
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response()

        self.adapter.create_response(
            model="deepseek-v4-flash",
            input=[{"role": "user", "content": "Hello"}],
            tool_choice="auto",
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert "tools" not in call_kwargs
        assert "tool_choice" not in call_kwargs

    def test_create_response_passes_response_format_when_json_output_is_requested(self):
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response(content="{}")

        self.adapter.create_response(
            model="deepseek-v4-flash",
            input=[{"role": "user", "content": "Return json"}],
            text={"response_format": {"type": "json_object"}},
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_create_response_maps_reasoning_to_deepseek_thinking_mode(self):
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response(content="ok")

        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[{"role": "user", "content": "Think this through"}],
            reasoning={"effort": "xhigh"},
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "max"
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled"}

    def test_create_response_maps_minimal_reasoning_to_non_thinking_mode(self):
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response(content="ok")

        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[{"role": "user", "content": "Answer fast"}],
            reasoning={"effort": "minimal"},
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert "reasoning_effort" not in call_kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "disabled"}

    def test_create_response_maps_reasoning_effort_kwarg_to_deepseek_thinking_mode(self):
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response(content="ok")

        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[{"role": "user", "content": "Think this through"}],
            reasoning_effort="high",
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning_effort"] == "high"
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled"}

    def test_create_response_rejects_native_images_with_clear_error(self):
        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(
                model="deepseek-v4-pro",
                input=[{"role": "user", "content": "Describe this"}],
                images=[{"name": "photo.png", "base64": "AAAA"}],
            )

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "no expone visión" in str(excinfo.value)
        assert "imagenes" in str(excinfo.value)
        self.mock_deepseek_client.chat.completions.create.assert_not_called()

    def test_create_response_rejects_native_file_attachments_with_clear_error(self):
        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(
                model="deepseek-v4-pro",
                input=[{"role": "user", "content": "Review this"}],
                attachments=[{"name": "report.pdf", "mime_type": "application/pdf", "base64": "AAAA"}],
            )

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "no expone visión" in str(excinfo.value)
        assert "archivos nativos" in str(excinfo.value)
        self.mock_deepseek_client.chat.completions.create.assert_not_called()

    @pytest.mark.parametrize("legacy_model", ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"])
    def test_create_response_rejects_unsupported_legacy_or_unknown_model(self, legacy_model):
        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(
                model=legacy_model,
                input=[{"role": "user", "content": "Hello"}],
            )

        assert excinfo.value.error_type == IAToolkitException.ErrorType.MODEL
        assert "Unsupported DeepSeek model" in str(excinfo.value)
        assert "deepseek-v4-flash" in str(excinfo.value)
        assert "deepseek-v4-pro" in str(excinfo.value)

    def test_build_messages_from_input_maps_function_call_output_to_tool_message(self):
        """
        function_call_output items must be converted into proper tool messages so
        chat.completions providers can associate the result with the original call_id.
        """
        # Arrange
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response()

        input_data = [
            {"role": "user", "content": "question"},
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "status": "completed",
                "output": '{"rows": [{"id": 1, "name": "Alice"}]}',
            },
        ]

        # Act
        self.adapter.create_response(
            model="deepseek-v4-flash",
            input=input_data,
        )

        # Assert that messages contain the tool result as a tool message
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]

        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "question"}
        assert messages[1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": '{"rows": [{"id": 1, "name": "Alice"}]}',
        }

    def test_create_response_reconstructs_assistant_tool_call_turn_before_tool_output(self):
        """
        DeepSeek requires a prior assistant message with tool_calls before any tool
        message. The adapter reconstructs that assistant message from the previous
        model response when the caller only reinjects function_call_output items.
        """
        mock_tool_call = MagicMock()
        mock_tool_call.type = "function"
        mock_tool_call.id = "call_1"
        mock_tool_call.function.name = "iat_sql_query"
        mock_tool_call.function.arguments = '{"query":"select 1"}'

        self.mock_deepseek_client.chat.completions.create.side_effect = [
            self._create_mock_response(
                content="Let me query that",
                tool_calls=[mock_tool_call],
                reasoning_content="Need database lookup first.",
            ),
            self._create_mock_response(content="done"),
        ]

        tools = [{"type": "function", "function": {"name": "iat_sql_query"}}]
        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[{"role": "user", "content": "question"}],
            tools=tools,
            tool_choice="auto",
            reasoning={"effort": "high"},
        )

        self.adapter.create_response(
            model="deepseek-v4-pro",
            input=[
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "status": "completed",
                    "output": "some result",
                },
            ],
            tools=tools,
            tool_choice="auto",
            reasoning={"effort": "high"},
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args_list[1].kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {
            "role": "assistant",
            "content": "Let me query that",
            "reasoning_content": "Need database lookup first.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "iat_sql_query",
                        "arguments": '{"query":"select 1"}',
                    },
                }
            ],
        }
        assert messages[1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "some result",
        }
        assert call_kwargs["tools"] is not None
        assert "tool_choice" not in call_kwargs
        assert call_kwargs["reasoning_effort"] == "high"
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled"}

    # ------------------------------------------------------------------
    # Response mapping and error handling
    # ------------------------------------------------------------------

    def test_map_deepseek_chat_response_plain_message(self):
        """
        _map_deepseek_chat_response should map a plain assistant message
        when there are no tool_calls.
        """
        mock_response = self._create_mock_response(content="Plain answer", tool_calls=None)

        result = self.adapter._map_deepseek_chat_response(mock_response)

        assert isinstance(result, LLMResponse)
        assert result.output_text == "Plain answer"
        assert result.status == "completed"
        assert result.output == []

        # Check content_parts consistency
        assert len(result.content_parts) == 1
        assert result.content_parts[0] == {"type": "text", "text": "Plain answer"}


    def test_map_deepseek_chat_response_no_choices_raises(self):
        """
        If DeepSeek returns no choices, an IAToolkitException with LLM_ERROR should be raised.
        """
        mock_response = MagicMock()
        mock_response.choices = []

        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter._map_deepseek_chat_response(mock_response)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "no choices" in str(excinfo.value)

    def test_create_response_wraps_generic_api_errors(self):
        """
        Generic exceptions from the DeepSeek client must be wrapped into an
        IAToolkitException with LLM_ERROR and a descriptive message.
        """
        self.mock_deepseek_client.chat.completions.create.side_effect = Exception("Deepseek Server Error")

        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(model="deepseek-v4-flash", input=[])

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "DeepSeek error:" in str(excinfo.value)
        assert "Deepseek Server Error" in str(excinfo.value)
