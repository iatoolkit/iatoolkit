# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_providers.openai_compatible_chat_adapter import OpenAICompatibleChatAdapter


class DeepseekAdapter(OpenAICompatibleChatAdapter):
    """Backward-compatible DeepSeek adapter wrapper."""

    def __init__(self, deepseek_client):
        super().__init__(openai_compatible_client=deepseek_client, provider_label="DeepSeek")
