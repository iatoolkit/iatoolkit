# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import json
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_providers.anthropic_adapter import AnthropicAdapter
from iatoolkit.infra.llm_response import LLMResponse, ToolCall


class TestAnthropicAdapter:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.adapter = AnthropicAdapter(anthropic_client=self.mock_client)

    def _mock_response(self, blocks, input_tokens=10, output_tokens=5):
        response = MagicMock()
        response.id = "msg_123"
        response.model = "claude-3-5-sonnet-latest"
        response.content = blocks
        response.usage = MagicMock()
        response.usage.input_tokens = input_tokens
        response.usage.output_tokens = output_tokens
        return response

    def test_create_response_text_only(self):
        block = MagicMock()
        block.type = "text"
        block.text = "Hola desde Claude"
        response = self._mock_response([block])
        self.mock_client.messages.create.return_value = response

        result = self.adapter.create_response(
            model="claude-3-5-sonnet-latest",
            input=[{"role": "user", "content": "Hola"}]
        )

        assert isinstance(result, LLMResponse)
        assert result.status == "completed"
        assert result.output_text == "Hola desde Claude"
        assert result.usage.total_tokens == 15
        assert result.content_parts[0] == {"type": "text", "text": "Hola desde Claude"}

    def test_create_response_with_tool_call(self):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_1"
        tool_block.name = "iat_sql_query"
        tool_block.input = {"query": "select 1"}
        response = self._mock_response([tool_block])
        self.mock_client.messages.create.return_value = response

        result = self.adapter.create_response(
            model="claude-3-5-sonnet-latest",
            input=[{"role": "user", "content": "Consulta SQL"}],
            tools=[{"type": "function", "name": "iat_sql_query", "parameters": {"type": "object"}}],
            tool_choice="required",
        )

        assert result.status == "tool_calls"
        assert len(result.output) == 1
        assert isinstance(result.output[0], ToolCall)
        assert result.output[0].name == "iat_sql_query"
        assert result.output[0].arguments == json.dumps({"query": "select 1"}, ensure_ascii=False)

        call_kwargs = self.mock_client.messages.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == {"type": "any"}
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["name"] == "iat_sql_query"

    def test_create_response_includes_function_call_output_as_tool_result_when_call_id_is_known(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Resultado recibido"
        response = self._mock_response([text_block])
        self.mock_client.messages.create.return_value = response

        self.adapter._tool_calls_by_id["call_abc"] = {
            "name": "iat_sql_query",
            "input": {"query": "select 1"},
        }

        self.adapter.create_response(
            model="claude-3-5-sonnet-latest",
            input=[
                {"role": "user", "content": "Pregunta"},
                {
                    "type": "function_call_output",
                    "call_id": "call_abc",
                    "output": "{\"ok\": true}"
                }
            ],
        )

        call_kwargs = self.mock_client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"][0]["type"] == "tool_use"
        assert messages[1]["content"][0]["id"] == "call_abc"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"][0]["type"] == "tool_result"
        assert messages[2]["content"][0]["tool_use_id"] == "call_abc"

    def test_create_response_falls_back_to_plain_text_when_tool_use_is_missing(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Resultado recibido"
        response = self._mock_response([text_block])
        self.mock_client.messages.create.return_value = response

        self.adapter.create_response(
            model="claude-3-5-sonnet-latest",
            input=[
                {"role": "user", "content": "Pregunta"},
                {
                    "type": "function_call_output",
                    "call_id": "unknown_call",
                    "output": "{\"ok\": true}"
                }
            ],
        )

        call_kwargs = self.mock_client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[1]["role"] == "user"
        assert isinstance(messages[1]["content"], str)
        assert "Tool result:" in messages[1]["content"]

    def test_create_response_attaches_images_to_user_message(self):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Veo la imagen"
        response = self._mock_response([text_block])
        self.mock_client.messages.create.return_value = response

        self.adapter.create_response(
            model="claude-3-5-sonnet-latest",
            input=[{"role": "user", "content": "Describe la imagen"}],
            images=[{"name": "photo.png", "base64": "AAAA"}],
        )

        call_kwargs = self.mock_client.messages.create.call_args.kwargs
        message_content = call_kwargs["messages"][0]["content"]
        assert isinstance(message_content, list)
        assert message_content[0]["type"] == "text"
        assert message_content[1]["type"] == "image"
        assert message_content[1]["source"]["media_type"] == "image/png"
        assert message_content[1]["source"]["data"] == "AAAA"

    def test_create_response_wraps_provider_errors(self):
        self.mock_client.messages.create.side_effect = Exception("Anthropic down")

        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(
                model="claude-3-5-sonnet-latest",
                input=[{"role": "user", "content": "Hola"}]
            )

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "Error calling Anthropic API" in str(excinfo.value)
