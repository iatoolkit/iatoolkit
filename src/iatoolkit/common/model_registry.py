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
ProviderType = Literal["openai", "gemini", "deepseek", "xai", "anthropic", "openrouter", "openai_compatible", "unknown"]


@dataclass(frozen=True)
class ModelMetadata:
    """Static metadata for a logical family of models."""
    provider: ProviderType
    history_type: HistoryType


#: Providers a model can actually be served by: the ones `LLMProxy._build_adapter`
#: knows how to build. Deliberately narrower than `ProviderType`, which also
#: contains `xai` — `normalize_provider` accepts it and a client is built for it,
#: but there is no xAI adapter, so a model declared `xai` raises "Provider not
#: supported" on its first request. A test pins this tuple to the adapters that
#: exist so the two cannot drift.
#:
#: Anything that lets a person choose a provider must offer exactly these: the
#: value reaches `_build_adapter` verbatim, so a typo becomes a runtime failure in
#: front of an end user, hours after it was saved.
SERVABLE_PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "openrouter",
    "openai_compatible",
)


@dataclass(frozen=True)
class RouteParam:
    """One thing a provider needs to know before it can be reached.

    `is_env_name` marks a value that is the *name* of a deployment environment
    variable, not the secret itself: what gets stored is `OSS_LLM_API_KEY`, and the
    value behind it is read at request time and never persisted here.
    """

    name: str
    required: bool = True
    is_env_name: bool = False
    #: A regular expression the value must match, or None for "any non-empty".
    pattern: str | None = None
    #: How to finish "'base_url' does not look like ___" when the pattern refuses a
    #: value. Declared here so a new parameter cannot inherit another one's wording:
    #: the message for `model_name` read "does not look like a URL".
    looks_like: str = "a valid value"


#: What each provider needs in order to be reached, keyed by provider.
#:
#: The single declaration behind three things: what a catalogue entry may store,
#: what refuses to publish without it, and which fields a form draws. Kept beside
#: SERVABLE_PROVIDERS because the two answer halves of the same question — which
#: providers exist, and what each one needs.
#:
#: Most providers need nothing: their SDK knows its own endpoint, and the
#: credential comes from the company's provider_api_keys mapping. The two that
#: appear here are the ones whose endpoint is a decision.
#:
#: `openai_compatible` requires both, and that is the point of the whole feature:
#: an entry that carries its own endpoint and credential is reachable on its own,
#: instead of depending on a block in every company's own configuration file. Two
#: self-hosted models on two different endpoints stop being impossible.
#:
#: `openrouter` allows both and requires neither: there is one OpenRouter for
#: everyone and its base URL has a working default, so an entry only overrides
#: when it has a reason to.
#: `model_name` is optional and exists because a catalogue key is lowercased: it
#: identifies the model across entitlements, rate cards and usage rows, so it cannot
#: also be the name on the wire. A vLLM endpoint serving
#: `meta-llama/Llama-3.1-8B-Instruct` answers 404 to the lowercased key. When set,
#: it is the exact name that endpoint answers to, and only the wire value changes.
PROVIDER_ROUTE_PARAMS: dict[str, tuple[RouteParam, ...]] = {
    "openai_compatible": (
        RouteParam("base_url", required=True, pattern=r"^https?://\S+$", looks_like="a URL"),
        RouteParam("api_key_env", required=True, is_env_name=True, pattern=r"^[A-Z][A-Z0-9_]*$",
                   looks_like="an environment variable name"),
        RouteParam("model_name", required=False, pattern=r"^[A-Za-z0-9._:\-/]+$",
                   looks_like="a model name"),
    ),
    "openrouter": (
        RouteParam("base_url", required=False, pattern=r"^https?://\S+$", looks_like="a URL"),
        RouteParam("api_key_env", required=False, is_env_name=True, pattern=r"^[A-Z][A-Z0-9_]*$",
                   looks_like="an environment variable name"),
    ),
}


def route_params_for(provider: str | None) -> tuple[RouteParam, ...]:
    """What this provider needs. Empty for the ones that need nothing."""
    return PROVIDER_ROUTE_PARAMS.get(str(provider or "").strip().lower(), ())


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
            "openrouter": ("openrouter/",),
        }
        self._reasoning_effort_options = ("minimal", "low", "medium", "high", "xhigh")
        self._text_verbosity_options = ("low", "medium", "high")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_provider(self, model: str) -> ProviderType:
        """
        Returns the logical provider for a given model name.

        Examples:
            "gpt-4o"        -> "openai"
            "gemini-pro"    -> "gemini"
            "deepseek-v4-pro" -> "deepseek"
        """
        if not model:
            return "unknown"

        model_lower = model.lower()
        for provider, patterns in self._provider_patterns.items():
            if any(pat in model_lower for pat in patterns):
                return provider

        return "unknown"

    def normalize_provider(self, provider: str | None = None, model: str | None = None) -> ProviderType:
        candidate = str(provider or "").strip().lower()
        if candidate in {
            "openai",
            "gemini",
            "deepseek",
            "xai",
            "anthropic",
            "openrouter",
            "openai_compatible",
        }:
            return candidate  # type: ignore[return-value]
        return self.get_provider(model or "")

    def get_capabilities(self, model: str, provider: str | None = None) -> dict:
        normalized_provider = self.normalize_provider(provider=provider, model=model)
        # `openai_compatible` is absent on purpose. Its adapter targets any server
        # that speaks chat.completions — llama.cpp, vLLM, a private gateway — and
        # forwards no reasoning field, because one the server does not know earns a
        # 400. Claiming the capability here made the tenant's Models page offer a
        # reasoning control whose value went nowhere.
        supports_reasoning_effort = normalized_provider in {
            "openai",
            "xai",
            "openrouter",
            "deepseek",
        }
        supports_text_verbosity = normalized_provider in {"openai", "xai", "openrouter"}
        supports_store = normalized_provider in {"openai", "xai"}

        return {
            "provider": normalized_provider,
            "history_type": self.get_history_type(model),
            "supports_reasoning_effort": supports_reasoning_effort,
            "allowed_reasoning_efforts": list(self._reasoning_effort_options) if supports_reasoning_effort else [],
            "supports_text_verbosity": supports_text_verbosity,
            "allowed_text_verbosity": list(self._text_verbosity_options) if supports_text_verbosity else [],
            "supports_store": supports_store,
        }

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
        - openai/xai: server_side (API manages conversation state via ids)
        - gemini/deepseek/anthropic/unknown: client_side (we manage full message history)
        """
        provider = self.get_provider(model)

        if provider in ("openai", "xai"):
            return "server_side"

        # Default for gemini, deepseek, anthropic and any unknown provider
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
