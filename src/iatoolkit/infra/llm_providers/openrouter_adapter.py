# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from typing import Any, Dict

from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter


class OpenRouterAdapter(OpenAICompatibleChatAdapter):
    """OpenRouter-specific adapter built on top of the shared chat.completions core."""

    supports_multimodal = True
    supports_reasoning = False
    supports_metadata = True
    supports_parallel_tool_calls = True

    def __init__(self, openrouter_client):
        super().__init__(openai_compatible_client=openrouter_client, provider_label="OpenRouter")

    def _extend_call_kwargs(self, call_kwargs: Dict[str, Any], kwargs: Dict[str, Any]) -> None:
        text = kwargs.get("text") or {}
        verbosity = text.get("verbosity") if isinstance(text, dict) else None
        if verbosity:
            call_kwargs["verbosity"] = verbosity

        passthrough_keys = (
            "service_tier",
            "temperature",
            "top_p",
            "max_tokens",
            "max_completion_tokens",
            "seed",
            "stop",
            "stream",
            "stream_options",
            "modalities",
            "user",
        )
        for key in passthrough_keys:
            if kwargs.get(key) is not None:
                call_kwargs[key] = kwargs.get(key)

        extra_body = dict(call_kwargs.get("extra_body") or {})

        reasoning = kwargs.get("reasoning")
        if isinstance(reasoning, dict) and reasoning:
            extra_body["reasoning"] = dict(reasoning)

        vendor_specific_keys = (
            "models",
            "provider",
            "plugins",
            "session_id",
        )
        for key in vendor_specific_keys:
            if kwargs.get(key) is not None:
                extra_body[key] = kwargs.get(key)

        if extra_body:
            call_kwargs["extra_body"] = extra_body
