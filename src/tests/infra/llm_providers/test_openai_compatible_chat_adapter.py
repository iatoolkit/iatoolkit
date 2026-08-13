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

    def _client_with_the_real_signature(self):
        """
        A client whose `create` accepts exactly what chat.completions accepts.

        The two tests below used to assert that `reasoning` WAS forwarded, and they
        passed: a bare MagicMock swallows any keyword. Production does not — the
        OpenAI SDK raised `TypeError: Completions.create() got an unexpected keyword
        argument 'reasoning'` before any request left the process. Binding the real
        parameter list is what stops a mock from hiding that again.
        """
        response = self._create_mock_response()

        def create(*, model, messages, reasoning_effort=None, **rest):
            create.seen = {"model": model, "messages": messages, "reasoning_effort": reasoning_effort, **rest}
            return response

        client = MagicMock()
        client.chat.completions.create = create
        return client, create

    def test_create_response_never_sends_the_responses_api_reasoning_argument(self):
        client, create = self._client_with_the_real_signature()
        adapter = OpenAICompatibleChatAdapter(client)

        # A company-level `llm.reasoning_effort` reaches the proxy as this payload.
        adapter.create_response(
            model="meta-llama/llama-3.1-8b-instruct",
            input=[{"role": "user", "content": "Hello"}],
            reasoning={"effort": "medium"},
        )

        assert "reasoning" not in create.seen

    def test_create_response_sends_no_reasoning_field_at_all_for_a_generic_endpoint(self):
        client, create = self._client_with_the_real_signature()
        adapter = OpenAICompatibleChatAdapter(client)

        adapter.create_response(
            model="oss-model",
            input=[{"role": "user", "content": "Hello"}],
            reasoning_effort="medium",
        )

        # An arbitrary OpenAI-compatible server answers 400 to a field it does not
        # know, so this adapter forwards neither form. A provider whose API does
        # accept it opts in, as DeepseekAdapter does.
        assert create.seen["reasoning_effort"] is None
        assert "reasoning" not in create.seen

    def test_the_reasoning_flags_stay_off_so_subclasses_do_not_have_to_correct_them(self):
        assert OpenAICompatibleChatAdapter.supports_reasoning is False
        assert OpenAICompatibleChatAdapter.supports_reasoning_effort is False

    def test_create_response_retries_without_tool_choice_when_provider_rejects_it(self):
        self.mock_client.chat.completions.create.side_effect = [
            Exception("Error code: 400 - deepseek-reasoner does not support this tool_choice"),
            self._create_mock_response(),
        ]

        self.adapter.create_response(
            model="oss-model",
            input=[{"role": "user", "content": "Hello"}],
            tools=[{"type": "function", "function": {"name": "search_web"}}],
            tool_choice="required",
        )

        assert self.mock_client.chat.completions.create.call_count == 2
        first_call_kwargs = self.mock_client.chat.completions.create.call_args_list[0].kwargs
        second_call_kwargs = self.mock_client.chat.completions.create.call_args_list[1].kwargs

        assert first_call_kwargs["tool_choice"] == "required"
        assert first_call_kwargs["tools"] == second_call_kwargs["tools"]
        assert "tool_choice" not in second_call_kwargs
