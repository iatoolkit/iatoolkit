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

    def _create_mock_response(self, content="Hello", tool_calls=None):
        """Helper to create a mock DeepSeek-like response object."""
        mock_response = MagicMock()
        mock_response.id = "chatcmpl-deepseek-123"
        mock_response.model = "deepseek-chat"

        mock_message = MagicMock()
        mock_message.content = content
        mock_message.tool_calls = tool_calls

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
            model="deepseek-chat",
            input=input_data,
            context_history=context_history,
        )

        # Assert API call
        self.mock_deepseek_client.chat.completions.create.assert_called_once()
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs

        assert call_kwargs["model"] == "deepseek-chat"
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
            model="deepseek-coder",
            input=input_data,
            tools=tools,
            tool_choice="auto",
        )

        # Assert API call
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-coder"
        assert call_kwargs["messages"][-1] == {"role": "user", "content": "Search python"}
        # tools should be passed as-is
        assert call_kwargs["tools"] is not None
        # With current implementation, tool_choice "auto" is passed through
        assert call_kwargs["tool_choice"] == "auto"

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

        self.adapter.create_response(
            model="deepseek-chat",
            input=[],
            tool_choice="required",
        )

        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == "required"

    def test_build_messages_from_input_maps_function_call_output_to_assistant(self):
        """
        function_call_output items must be converted into assistant messages containing
        the tool result so the model can use them to answer.
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
            model="deepseek-chat",
            input=input_data,
        )

        # Assert that messages contain the tool result as an assistant message
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]

        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "question"}
        assert messages[1]["role"] == "user"
        assert "Tool result:" in messages[1]["content"]
        assert '{"rows": [{"id": 1, "name": "Alice"}]}' in messages[1]["content"]

    def test_create_response_disables_tools_after_function_output_with_auto_choice(self):
        """
        When input already contains function_call_output and tool_choice is 'auto',
        tools and tool_choice must be removed from the API call to avoid infinite loops.
        """
        self.mock_deepseek_client.chat.completions.create.return_value = self._create_mock_response()

        input_data = [
            {"role": "user", "content": "question"},
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "status": "completed",
                "output": "some result",
            },
        ]
        tools = [{"type": "function", "function": {"name": "iat_sql_query"}}]

        # Act
        self.adapter.create_response(
            model="deepseek-chat",
            input=input_data,
            tools=tools,
            tool_choice="auto",
        )

        # Assert: tools and tool_choice should NOT be sent
        call_kwargs = self.mock_deepseek_client.chat.completions.create.call_args.kwargs
        assert "tools" not in call_kwargs
        assert "tool_choice" not in call_kwargs

        # Messages should still include the tool result as assistant message
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[1]["role"] == "user"
        assert "Tool result:" in messages[1]["content"]

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
            self.adapter.create_response(model="deepseek-chat", input=[])

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "DeepSeek error:" in str(excinfo.value)
        assert "Deepseek Server Error" in str(excinfo.value)