# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock

from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter


class TestOpenAICompatibleChatAdapter:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.adapter = OpenAICompatibleChatAdapter(self.mock_client)

    @staticmethod
    def _create_mock_response(content="ok"):
        mock_response = MagicMock()
        mock_response.id = "chatcmpl-oss-123"
        mock_response.model = "oss-model"

        mock_message = MagicMock()
        mock_message.content = content
        mock_message.tool_calls = None
        mock_message.reasoning_content = ""

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 3
        mock_response.usage.total_tokens = 8
        return mock_response

    def test_create_response_passes_reasoning_payload(self):
        self.mock_client.chat.completions.create.return_value = self._create_mock_response()

        self.adapter.create_response(
            model="oss-model",
            input=[{"role": "user", "content": "Hello"}],
            reasoning={"effort": "high"},
        )

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning"] == {"effort": "high"}

    def test_create_response_builds_reasoning_payload_from_reasoning_effort_kwarg(self):
        self.mock_client.chat.completions.create.return_value = self._create_mock_response()

        self.adapter.create_response(
            model="oss-model",
            input=[{"role": "user", "content": "Hello"}],
            reasoning_effort="medium",
        )

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["reasoning"] == {"effort": "medium"}
