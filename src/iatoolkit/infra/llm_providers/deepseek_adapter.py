# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter


class DeepseekAdapter(OpenAICompatibleChatAdapter):
    """DeepSeek V4 adapter."""

    supports_reasoning = False
    supports_reasoning_effort = True
    supports_reasoning_content_messages = True
    supports_thinking = True
    model_capabilities = {
        "deepseek-v4-flash": {
            "supports_thinking": True,
            "supports_tool_choice_required": True,
        },
        "deepseek-v4-pro": {
            "supports_thinking": True,
            "supports_tool_choice_required": True,
        },
    }
    supported_models = frozenset(model_capabilities)

    def __init__(self, deepseek_client):
        super().__init__(openai_compatible_client=deepseek_client, provider_label="DeepSeek")

    def create_response(self, model: str, input: list[dict], **kwargs):
        self._validate_model(model)
        return super().create_response(model=model, input=input, **kwargs)

    @classmethod
    def _validate_model(cls, model: str) -> None:
        normalized_model = str(model or "").strip().lower()
        if normalized_model in cls.supported_models:
            return

        raise IAToolkitException(
            IAToolkitException.ErrorType.MODEL,
            (
                f"Unsupported DeepSeek model '{model}'. "
                f"Supported models: {sorted(cls.supported_models)}"
            ),
        )

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

        reasoning_effort = self._extract_reasoning_effort(reasoning, kwargs)

        if reasoning_effort == "minimal":
            return {"type": "disabled"}
        if reasoning_effort:
            return {"type": "enabled"}

        # Keep the default deterministic: unless a prompt explicitly asks for
        # reasoning, use non-thinking mode.
        return {"type": "disabled"}
