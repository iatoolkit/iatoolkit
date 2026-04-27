# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock

from iatoolkit.infra.llm_providers.openrouter_adapter import OpenRouterAdapter
from iatoolkit.infra.llm_response import LLMResponse, ToolCall


class TestOpenRouterAdapter:
    def setup_method(self):
        self.mock_openrouter_client = MagicMock()
        self.adapter = OpenRouterAdapter(openrouter_client=self.mock_openrouter_client)

    @staticmethod
    def _create_mock_response(content="Hello", tool_calls=None):
        mock_response = MagicMock()
        mock_response.id = "chatcmpl-openrouter-123"
        mock_response.model = "openai/gpt-5.2"

        mock_message = MagicMock()
        mock_message.content = content
        mock_message.tool_calls = tool_calls
        mock_message.reasoning_content = "reasoning trace"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 11
        mock_response.usage.completion_tokens = 6
        mock_response.usage.total_tokens = 17
        return mock_response

    def test_create_response_builds_multimodal_message_parts_for_images_and_files(self):
        self.mock_openrouter_client.chat.completions.create.return_value = self._create_mock_response()

        self.adapter.create_response(
            model="openai/gpt-5.2",
            input=[{"role": "user", "content": "Summarize this"}],
            images=[{
                "name": "chart.png",
                "mime_type": "image/png",
                "base64": "aGVsbG8=",
            }],
            attachments=[{
                "name": "report.pdf",
                "mime_type": "application/pdf",
                "base64": "aGVsbG8=",
            }],
        )

        call_kwargs = self.mock_openrouter_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-5.2"

        message = call_kwargs["messages"][0]
        assert message["role"] == "user"
        assert message["content"] == [
            {"type": "text", "text": "Summarize this"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,aGVsbG8="},
            },
            {
                "type": "file",
                "file": {
                    "filename": "report.pdf",
                    "file_data": "data:application/pdf;base64,aGVsbG8=",
                },
            },
        ]

    def test_create_response_passes_json_schema_reasoning_metadata_and_parallel_tools(self):
        self.mock_openrouter_client.chat.completions.create.return_value = self._create_mock_response(content="{}")

        result = self.adapter.create_response(
            model="openai/gpt-5.2",
            input=[{"role": "user", "content": "Return structured json"}],
            text={
                "verbosity": "high",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "prompt_output",
                        "strict": True,
                        "schema": {"type": "object"},
                    },
                },
            },
            reasoning={"effort": "high"},
            metadata={"prompt_name": "sales_prompt"},
            parallel_tool_calls=True,
        )

        call_kwargs = self.mock_openrouter_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["response_format"]["type"] == "json_schema"
        assert call_kwargs["metadata"] == {"prompt_name": "sales_prompt"}
        assert call_kwargs["verbosity"] == "high"
        assert call_kwargs["parallel_tool_calls"] is True
        assert call_kwargs["extra_body"]["reasoning"] == {"effort": "high"}

        assert isinstance(result, LLMResponse)
        assert result.output_text == "{}"
        assert result.reasoning_content == "reasoning trace"

    def test_create_response_passthroughs_openrouter_request_options(self):
        self.mock_openrouter_client.chat.completions.create.return_value = self._create_mock_response()

        self.adapter.create_response(
            model="openai/gpt-5.2",
            input=[{"role": "user", "content": "Hello"}],
            models=["openai/gpt-5.2", "anthropic/claude-sonnet-4.5"],
            provider={"require_parameters": True, "sort": "price"},
            plugins=[{"id": "response-healing"}],
            service_tier="auto",
            session_id="sess_123",
            temperature=0.2,
            top_p=0.9,
            max_tokens=250,
            max_completion_tokens=300,
            seed=7,
            stop=["END"],
            stream=False,
            stream_options={"include_usage": True},
            modalities=["text"],
            user="user-123",
        )

        call_kwargs = self.mock_openrouter_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["service_tier"] == "auto"
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["max_tokens"] == 250
        assert call_kwargs["max_completion_tokens"] == 300
        assert call_kwargs["seed"] == 7
        assert call_kwargs["stop"] == ["END"]
        assert call_kwargs["stream"] is False
        assert call_kwargs["stream_options"] == {"include_usage": True}
        assert call_kwargs["modalities"] == ["text"]
        assert call_kwargs["user"] == "user-123"
        assert call_kwargs["extra_body"]["models"] == ["openai/gpt-5.2", "anthropic/claude-sonnet-4.5"]
        assert call_kwargs["extra_body"]["provider"] == {"require_parameters": True, "sort": "price"}
        assert call_kwargs["extra_body"]["plugins"] == [{"id": "response-healing"}]
        assert call_kwargs["extra_body"]["session_id"] == "sess_123"

    def test_create_response_maps_named_tool_choice_and_tool_calls(self):
        mock_tool_call = MagicMock()
        mock_tool_call.type = "function"
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "search_web"
        mock_tool_call.function.arguments = '{"query":"python"}'
        self.mock_openrouter_client.chat.completions.create.return_value = self._create_mock_response(
            content=None,
            tool_calls=[mock_tool_call],
        )

        result = self.adapter.create_response(
            model="openai/gpt-5.2",
            input=[{"role": "user", "content": "Search python"}],
            tools=[{"type": "function", "function": {"name": "search_web"}}],
            tool_choice="search_web",
        )

        call_kwargs = self.mock_openrouter_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == {
            "type": "function",
            "function": {"name": "search_web"},
        }
        assert len(result.output) == 1
        assert isinstance(result.output[0], ToolCall)
        assert result.output[0].call_id == "call_123"
        assert result.output[0].name == "search_web"
        assert result.status == "tool_calls"
