# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.infra.llm_providers.openai_adapter import OpenAIAdapter
from iatoolkit.infra.llm_providers.gemini_adapter import GeminiAdapter
from iatoolkit.infra.llm_providers.deepseek_adapter import DeepseekAdapter
# from iatoolkit.infra.llm_providers.anthropic_adapter import AnthropicAdapter
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_response import LLMResponse
from iatoolkit.common.model_registry import ModelRegistry

from openai import OpenAI         # For OpenAI and xAI (OpenAI-compatible)
# from anthropic import Anthropic  # For Claude (Anthropic)

from typing import Dict, List, Any, Tuple
import os
import threading
from injector import inject


class LLMProxy:
    """
    Proxy for routing calls to the correct LLM adapter and managing the creation of LLM clients.
    """

    # Class-level cache for low-level clients (per provider + API key)
    _clients_cache: Dict[Tuple[str, str], Any] = {}
    _clients_cache_lock = threading.Lock()

    # Provider identifiers
    PROVIDER_OPENAI = "openai"
    PROVIDER_GEMINI = "gemini"
    PROVIDER_DEEPSEEK = "deepseek"
    PROVIDER_XAI = "xai"
    PROVIDER_ANTHROPIC = "anthropic"

    @inject
    def __init__(
        self,
        util: Utility,
        configuration_service: ConfigurationService,
        model_registry: ModelRegistry,
    ):
        """
        Init a new instance of the proxy. It can be a base factory or a working instance with configured clients.
        Pre-built clients can be injected for tests or special environments.
        """
        self.util = util
        self.configuration_service = configuration_service
        self.model_registry = model_registry

        # adapter cache por provider
        self.adapters: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def create_response(self, company_short_name: str, model: str, input: List[Dict], **kwargs) -> LLMResponse:
        """
        Route the call to the correct adapter based on the model name.
        This method is the single entry point used by the rest of the application.
        """
        if not company_short_name:
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                "company_short_name is required in kwargs to resolve LLM credentials."
            )

        # Determine the provider based on the model name
        provider = self._resolve_provider_from_model(model)

        adapter = self._get_or_create_adapter(
            provider=provider,
            company_short_name=company_short_name,
        )

        # Delegate to the adapter (OpenAI, Gemini, DeepSeek, xAI, Anthropic, etc.)
        return adapter.create_response(model=model, input=input, **kwargs)

    # -------------------------------------------------------------------------
    # Provider resolution
    # -------------------------------------------------------------------------

    def _resolve_provider_from_model(self, model: str) -> str:
        """
        Determine which provider must be used for a given model name.
        This uses Utility helper methods, so you can keep all naming logic in one place.
        """
        provider_key = self.model_registry.get_provider(model)

        if provider_key == "openai":
            return self.PROVIDER_OPENAI
        if provider_key == "gemini":
            return self.PROVIDER_GEMINI
        if provider_key == "deepseek":
            return self.PROVIDER_DEEPSEEK
        if provider_key == "xai":
            return self.PROVIDER_XAI
        if provider_key == "anthropic":
            return self.PROVIDER_ANTHROPIC

        raise IAToolkitException(
            IAToolkitException.ErrorType.MODEL,
            f"Unknown or unsupported model: {model}"
        )

    # -------------------------------------------------------------------------
    # Adapter management
    # -------------------------------------------------------------------------

    def _get_or_create_adapter(self, provider: str, company_short_name: str) -> Any:
        """
        Return an adapter instance for the given provider.
        If none exists yet, create it using a cached or new low-level client.
        """
        # If already created, just return it
        if provider in self.adapters and self.adapters[provider] is not None:
            return self.adapters[provider]

        # Otherwise, create a low-level client from configuration
        api_key = self._get_api_key_from_config(company_short_name, provider)
        client = self._get_or_create_client(provider, api_key)

        # Wrap client with the correct adapter
        if provider == self.PROVIDER_OPENAI:
            adapter = OpenAIAdapter(client)
        elif provider == self.PROVIDER_GEMINI:
            adapter = GeminiAdapter(client)
        elif provider == self.PROVIDER_DEEPSEEK:
            adapter = DeepseekAdapter(client)
        else:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MODEL,
                f"Provider not supported in _get_or_create_adapter: {provider}"
            )

        '''
        elif provider == self.PROVIDER_XAI:
            adapter = XAIAdapter(client)
        elif provider == self.PROVIDER_ANTHROPIC:
            adapter = AnthropicAdapter(client)
        '''
        self.adapters[provider] = adapter
        return adapter

    # -------------------------------------------------------------------------
    # Client cache
    # -------------------------------------------------------------------------

    def _get_or_create_client(self, provider: str, api_key: str) -> Any:
        """
        Return a low-level client for the given provider and API key.
        Uses a class-level cache to avoid recreating clients.
        """
        cache_key = (provider, api_key or "")

        with self._clients_cache_lock:
            if cache_key in self._clients_cache:
                return self._clients_cache[cache_key]

            client = self._create_client_for_provider(provider, api_key)
            self._clients_cache[cache_key] = client
            return client

    def _create_client_for_provider(self, provider: str, api_key: str) -> Any:
        """
        Actually create the low-level client for a provider.
        This is the only place where provider-specific client construction lives.
        """
        if provider == self.PROVIDER_OPENAI:
            # Standard OpenAI client for GPT models
            return OpenAI(api_key=api_key)

        if provider == self.PROVIDER_XAI:
            # xAI Grok is OpenAI-compatible; we can use the OpenAI client with a different base_url.
            return OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
            )

        if provider == self.PROVIDER_DEEPSEEK:
            # Example: if you use the official deepseek client or OpenAI-compatible wrapper
            # return DeepSeekAPI(api_key=api_key)

            # We use OpenAI client with a DeepSeek base_url:
            return OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )

        if provider == self.PROVIDER_GEMINI:
            # Example placeholder: you may already have a Gemini client factory elsewhere.
            # Here you could create and configure the Gemini client (e.g. google.generativeai).
            #
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            return genai
        if provider == self.PROVIDER_ANTHROPIC:
            # Example using Anthropic official client:
            #
            # from anthropic import Anthropic
            # return Anthropic(api_key=api_key)
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                "Anthropic client creation must be implemented in _create_client_for_provider."
            )

        raise IAToolkitException(
            IAToolkitException.ErrorType.MODEL,
            f"Provider not supported in _create_client_for_provider: {provider}"
        )

    # -------------------------------------------------------------------------
    # Configuration helpers
    # -------------------------------------------------------------------------
    def _get_api_key_from_config(self, company_short_name: str, provider: str) -> str:
        """
        Read the LLM API key from company configuration and environment variables.

        Resolución de prioridad:
        1. llm.provider_api_keys[provider] -> env var específica por proveedor.
        2. llm.api-key                      -> env var global (compatibilidad hacia atrás).
        """
        llm_config = self.configuration_service.get_configuration(company_short_name, "llm")

        if not llm_config:
            # Mantener compatibilidad con los tests: el mensaje debe indicar
            # que no hay API key configurada.
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"Company '{company_short_name}' doesn't have an API key configured."
            )

        provider_keys = llm_config.get("provider_api_keys") or {}
        env_var_name = None

        # 1) Intentar api-key específica por proveedor (si existe el bloque provider_api_keys)
        if provider_keys and isinstance(provider_keys, dict):
            env_var_name = provider_keys.get(provider)

        # 2) Fallback: usar api-key global si no hay específica
        if not env_var_name and llm_config.get("api-key"):
            env_var_name = llm_config["api-key"]

        if not env_var_name:
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"Company '{company_short_name}' doesn't have an API key configured "
                f"for provider '{provider}'."
            )

        api_key_value = os.getenv(env_var_name, "")

        if not api_key_value:
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"Environment variable '{env_var_name}' for company '{company_short_name}' "
                f"and provider '{provider}' is not set or is empty."
            )

        return api_key_value