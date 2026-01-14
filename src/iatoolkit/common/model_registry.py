# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from dataclasses import dataclass
from injector import inject, singleton
from typing import Literal


HistoryType = Literal["server_side", "client_side"]
ProviderType = Literal["openai", "gemini", "deepseek", "xai", "anthropic", "unknown"]


@dataclass(frozen=True)
class ModelMetadata:
    """Static metadata for a logical family of models."""
    provider: ProviderType
    history_type: HistoryType


@singleton
class ModelRegistry:
    """
    Central registry for model metadata.

    Responsibilities:
    - Map a model name to its provider (openai, gemini, deepseek, etc.).
    - Decide which history strategy to use for a model (server_side / client_side).
    - Provide convenience helpers (is_openai, is_gemini, is_deepseek, etc.).
    """

    @inject
    def __init__(self):
        # Hardcoded rules for now; can be extended or loaded from config later.
        # The order of patterns matters: first match wins.
        self._provider_patterns: dict[ProviderType, tuple[str, ...]] = {
            "openai": ("gpt", "gpt-5", "gpt-5-mini", "gpt-5.1"),
            "gemini": ("gemini", "gemini-3", "gemini-3-flash-preview"),
            "deepseek": ("deepseek",),
            "xai": ("grok", "grok-1", "grok-beta"),
            "anthropic": ("claude", "claude-3", "claude-2"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_provider(self, model: str) -> ProviderType:
        """
        Returns the logical provider for a given model name.

        Examples:
            "gpt-4o"        -> "openai"
            "gemini-pro"    -> "gemini"
            "deepseek-chat" -> "deepseek"
        """
        if not model:
            return "unknown"

        model_lower = model.lower()
        for provider, patterns in self._provider_patterns.items():
            if any(pat in model_lower for pat in patterns):
                return provider

        return "unknown"

    def get_request_defaults(self, model: str) -> dict:
        """
        Return per-model request defaults to keep model-specific policy centralized.

        Notes:
        - This should only include keys that are supported by the target provider.
        - Callers should merge these defaults with user-provided params (do not mutate inputs).
        """
        model_lower = (model or "").lower()
        provider = self.get_provider(model_lower)

        # Conservative defaults: do not send provider-specific knobs unless we know they are supported.
        defaults = {"text": {}, "reasoning": {}}

        # OpenAI/xAI (OpenAI-compatible) support 'text.verbosity' and 'reasoning.effort' in our current integration.
        if provider in ("openai", "xai"):
            defaults["text"] = {"verbosity": "low"}
            defaults["reasoning"] = {"effort": "low"}

        # Gemini/DeepSeek/unknown: keep defaults empty to avoid sending unsupported parameters.
        return defaults

    def resolve_request_params(self, model: str, text: dict | None = None, reasoning: dict | None = None) -> dict:
        """
        Resolve provider/model defaults and merge them with caller-provided overrides.

        Rules:
        - Defaults come from get_request_defaults(model).
        - Caller overrides win over defaults.
        - Input dictionaries are never mutated.
        """
        defaults = self.get_request_defaults(model)

        merged_text: dict = {}
        merged_text.update(defaults.get("text") or {})
        merged_text.update(text or {})

        merged_reasoning: dict = {}
        merged_reasoning.update(defaults.get("reasoning") or {})
        merged_reasoning.update(reasoning or {})

        return {
            "text": merged_text,
            "reasoning": merged_reasoning,
        }

    def get_history_type(self, model: str) -> HistoryType:
        """
        Returns the history strategy for a given model.

        Current rules:
        - openai/xai/anthropic: server_side (API manages conversation state via ids)
        - gemini/deepseek/unknown: client_side (we manage full message history)
        """
        provider = self.get_provider(model)

        if provider in ("openai", "xai", "anthropic"):
            return "server_side"

        # Default for gemini, deepseek and any unknown provider
        return "client_side"

    # ------------------------------------------------------------------
    # Convenience helpers (used during migration)
    # ------------------------------------------------------------------

    def is_openai_model(self, model: str) -> bool:
        return self.get_provider(model) == "openai"

    def is_gemini_model(self, model: str) -> bool:
        return self.get_provider(model) == "gemini"

    def is_deepseek_model(self, model: str) -> bool:
        return self.get_provider(model) == "deepseek"

    def is_xai_model(self, model: str) -> bool:
        return self.get_provider(model) == "xai"

    def is_anthropic_model(self, model: str) -> bool:
        return self.get_provider(model) == "anthropic"