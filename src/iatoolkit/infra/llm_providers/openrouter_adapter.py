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

    # llm_capabilities.yaml marks `application/pdf` as natively supported for
    # every OpenRouter model, but that flag isn't verified per-model the way
    # native images are (see AttachmentPolicyService._get_openrouter_native_image_error).
    # Models with no native PDF support (e.g. some Qwen models) reject the raw
    # file part and OpenRouter answers with no `choices`. Always routing PDFs
    # through OpenRouter's own `file-parser` plugin sidesteps that per-model gap
    # instead of trying to track which routed model does or doesn't accept PDFs.
    #
    # engine="native": let the routed model read the PDF with its own
    # multimodal capability, falling back to OpenRouter's own extraction only
    # when the model doesn't support that. engine="mistral-ocr" used to be the
    # default here, but it forces every PDF - regardless of model support -
    # through OpenRouter's shared OCR pipeline, which is what produced the
    # "document parsing engine is currently rate limited" failures.
    _PDF_FILE_PARSER_PLUGIN = [{"id": "file-parser", "pdf": {"engine": "native"}}]

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

        if "plugins" not in extra_body and self._has_pdf_attachment(kwargs.get("attachments")):
            extra_body["plugins"] = self._PDF_FILE_PARSER_PLUGIN

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
