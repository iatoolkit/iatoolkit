# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter


class DeepseekAdapter(OpenAICompatibleChatAdapter):
    """Backward-compatible DeepSeek adapter wrapper."""

    supports_reasoning_effort = True
    supports_reasoning_content_messages = True
    supports_thinking = True

    def __init__(self, deepseek_client):
        super().__init__(openai_compatible_client=deepseek_client, provider_label="DeepSeek")

    def _map_reasoning_effort(self, model: str, effort: str, kwargs: dict) -> str | None:
        _ = model
        _ = kwargs

        candidate = str(effort or "").strip().lower()
        if candidate in {"low", "medium", "high"}:
            return "high"
        if candidate in {"xhigh", "max"}:
            return "max"
        return None

    def _build_thinking_payload(self, model: str, reasoning: dict | None, kwargs: dict) -> dict | None:
        explicit_thinking = self._normalize_thinking_payload(kwargs.get("thinking"))
        if explicit_thinking is not None:
            return explicit_thinking

        model_name = str(model or "").strip().lower()
        reasoning_effort = self._extract_reasoning_effort(reasoning, kwargs)

        if "reasoner" in model_name:
            return {"type": "enabled"}
        if reasoning_effort == "minimal":
            return {"type": "disabled"}
        if reasoning_effort:
            return {"type": "enabled"}

        # Keep the legacy "chat" behavior deterministic: unless a prompt explicitly
        # asks for reasoning, use non-thinking mode.
        return {"type": "disabled"}
