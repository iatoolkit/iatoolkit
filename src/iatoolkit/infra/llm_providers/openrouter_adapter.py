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

    # Fixed at "native" by policy: a PDF attachment must reach the routed model
    # as-is, for it to read with its own vision/multimodal capability - never
    # silently rewritten into extracted text by OpenRouter's OCR/parsing
    # pipeline. This only applies when nothing else already requested a plugin
    # (see _extend_call_kwargs below); an explicit `plugins` kwarg always wins.
    _PDF_FILE_PARSER_PLUGIN = [{"id": "file-parser", "pdf": {"engine": "native"}}]

    # Providers observed returning HTTP 400 on `type: "file"` content parts
    # even when routed to a model whose aggregate catalog entry lists "file"
    # as a supported input modality (OpenRouter's per-endpoint support lags
    # the model-level declaration). Excluded via `provider.ignore` whenever
    # we send a native file attachment, so routing skips them instead of
    # failing the request.
    _FILE_UNSUPPORTED_PROVIDERS = ("parasail", "akashml", "alibaba", "chutes", "reka")

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

        if self._has_pdf_attachment(kwargs.get("attachments")):
            if "plugins" not in extra_body:
                extra_body["plugins"] = self._PDF_FILE_PARSER_PLUGIN

            provider_opts = dict(extra_body.get("provider") or {})
            ignore = list(provider_opts.get("ignore") or [])
            for provider_slug in self._FILE_UNSUPPORTED_PROVIDERS:
                if provider_slug not in ignore:
                    ignore.append(provider_slug)
            provider_opts["ignore"] = ignore
            extra_body["provider"] = provider_opts

        if extra_body:
            call_kwargs["extra_body"] = extra_body

    @staticmethod
    def _has_pdf_attachment(attachments: Any) -> bool:
        for attachment in attachments or []:
            if not isinstance(attachment, dict):
                continue
            mime_type = str(attachment.get("mime_type") or attachment.get("type") or "").strip().lower()
            filename = str(attachment.get("name") or attachment.get("filename") or "").strip().lower()
            if mime_type == "application/pdf" or filename.endswith(".pdf"):
                return True
        return False
