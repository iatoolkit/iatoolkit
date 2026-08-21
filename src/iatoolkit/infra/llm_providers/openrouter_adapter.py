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
    supports_reasoning_content_messages = True
    supports_reasoning_details_messages = True
    reasoning_content_message_field = "reasoning"
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

        reasoning_payload = self._build_reasoning_payload(kwargs.get("reasoning"), kwargs)
        if reasoning_payload:
            extra_body["reasoning"] = reasoning_payload

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

    def _extract_provider_metadata(self, response: Any) -> Dict[str, Any]:
        raw_metadata = self._get_message_value(response, "openrouter_metadata")
        metadata = self._normalize_metadata_object(raw_metadata)

        provider_name = self._extract_provider_name(metadata)
        if not provider_name:
            provider_name = self._coerce_optional_text(
                self._get_message_value(response, "provider_name")
            )

        provider_metadata: Dict[str, Any] = {"provider": "openrouter"}
        if provider_name:
            provider_metadata["provider_name"] = provider_name
        if metadata:
            provider_metadata["openrouter"] = metadata

        return provider_metadata

    @classmethod
    def _extract_provider_name(cls, metadata: Dict[str, Any]) -> str:
        for key in ("provider_name", "provider", "upstream_provider", "selected_provider"):
            value = metadata.get(key)
            if isinstance(value, dict):
                nested = cls._extract_provider_name(value)
                if nested:
                    return nested
            normalized = cls._coerce_optional_text(value)
            if normalized:
                return normalized

        for value in metadata.values():
            if isinstance(value, dict):
                nested = cls._extract_provider_name(value)
                if nested:
                    return nested

        return ""

    @classmethod
    def _normalize_metadata_object(cls, value: Any) -> Dict[str, Any]:
        if value is None or type(value).__module__.startswith("unittest.mock"):
            return {}

        if isinstance(value, dict):
            return cls._sanitize_metadata_dict(value)

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
                if isinstance(dumped, dict):
                    return cls._sanitize_metadata_dict(dumped)
            except Exception:
                return {}

        raw_dict = getattr(value, "__dict__", None)
        if isinstance(raw_dict, dict):
            return cls._sanitize_metadata_dict({
                key: item
                for key, item in raw_dict.items()
                if not key.startswith("_") and not callable(item)
            })

        return {}

    @classmethod
    def _sanitize_metadata_dict(cls, metadata: Dict[str, Any]) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {}
        for key, value in dict(metadata or {}).items():
            normalized_key = cls._coerce_optional_text(key)
            if not normalized_key:
                continue

            if isinstance(value, dict):
                sanitized_value = cls._sanitize_metadata_dict(value)
            elif isinstance(value, list):
                sanitized_value = [
                    cls._sanitize_metadata_dict(item) if isinstance(item, dict) else item
                    for item in value
                    if not type(item).__module__.startswith("unittest.mock")
                ]
            elif type(value).__module__.startswith("unittest.mock"):
                continue
            else:
                sanitized_value = value

            sanitized[normalized_key] = sanitized_value

        return sanitized
