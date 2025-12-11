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
            "openai": ("gpt", "gpt-5"),
            "gemini": ("gemini", "gemini-3"),
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