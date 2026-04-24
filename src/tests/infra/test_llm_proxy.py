import os
import pytest
from unittest.mock import patch, MagicMock, ANY

from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.common.interfaces.secret_provider import SecretProvider

class TestLLMProxy:
    def setup_method(self):
        """Configuración común para las pruebas de LLMProxy."""
        # Utility y configuration_service mockeados
        self.util_mock = MagicMock()
        self.config_service_mock = MagicMock(spec=ConfigurationService)
        self.model_registry_mock = MagicMock(spec=ModelRegistry)
        self.secret_provider_mock = MagicMock(spec=SecretProvider)
        self.secret_provider_mock.get_secret.side_effect = (
            lambda _company, key_name, default=None: os.getenv(key_name, default)
        )
        self.config_service_mock.get_llm_model_config.return_value = None
        self.config_service_mock.get_llm_provider_config.return_value = {}

        # Empresa base
        self.company_short_name = "test_company"

        # Parches para los clientes de los proveedores
        self.openai_patcher = patch("iatoolkit.infra.llm_proxy.OpenAI")

        self.mock_openai_class = self.openai_patcher.start()

        # Parches para los adaptadores
        self.openai_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenAIAdapter")
        self.gemini_adapter_patcher = patch("iatoolkit.infra.llm_proxy.GeminiAdapter")
        self.openai_compatible_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenAICompatibleChatAdapter")
        self.anthropic_adapter_patcher = patch("iatoolkit.infra.llm_proxy.AnthropicAdapter")

        self.mock_openai_adapter_class = self.openai_adapter_patcher.start()
        self.mock_gemini_adapter_class = self.gemini_adapter_patcher.start()
        self.mock_openai_compatible_adapter_class = self.openai_compatible_adapter_patcher.start()
        self.mock_anthropic_adapter_class = self.anthropic_adapter_patcher.start()

        # Instancias mock de adaptadores
        self.mock_openai_adapter_instance = MagicMock()
        self.mock_gemini_adapter_instance = MagicMock()
        self.mock_openai_compatible_adapter_instance = MagicMock()
        self.mock_anthropic_adapter_instance = MagicMock()

        self.mock_openai_adapter_class.return_value = self.mock_openai_adapter_instance
        self.mock_gemini_adapter_class.return_value = self.mock_gemini_adapter_instance
        self.mock_openai_compatible_adapter_class.return_value = self.mock_openai_compatible_adapter_instance
        self.mock_anthropic_adapter_class.return_value = self.mock_anthropic_adapter_instance

        # Instancia de LLMProxy bajo prueba
        self.proxy = LLMProxy(
            util=self.util_mock,
            configuration_service=self.config_service_mock,
            model_registry=self.model_registry_mock,
            secret_provider=self.secret_provider_mock,
        )

        # Aseguramos que el cache global esté limpio para cada test
        LLMProxy._clients_cache.clear()

    def teardown_method(self):
        patch.stopall()
        LLMProxy._clients_cache.clear()

    def test_create_response_raises_if_no_api_key_configured(self):
        """
        Si ninguna API key está configurada (get_configuration devuelve None o no tiene 'api-key'),
        create_response debe lanzar una IAToolkitException indicando que no hay API configurada.
        """
        # Simular que no hay configuración de LLM para la compañía
        self.config_service_mock.get_configuration.return_value = None

        # Forzar que el modelo se resuelva como OpenAI para que llegue a leer la config
        self.model_registry_mock.get_provider.return_value = "openai"

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IAToolkitException, match="doesn't have an API key configured"):
                self.proxy.create_response(
                    company_short_name=self.company_short_name,
                    model="gpt-5",
                    input=[],
                )

    def test_client_caching_works_for_same_provider_and_api_key(self):
        """_get_or_create_client debe cachear el cliente para (provider, api_key) y reutilizarlo."""
        self.config_service_mock.get_configuration.return_value = {"api-key": "KEY"}

        with patch.dict(os.environ, {"KEY": "val"}, clear=True):
            api_key = self.proxy._get_api_key_from_config(
                self.company_short_name,
                LLMProxy.PROVIDER_OPENAI
            )
            client1 = self.proxy._get_or_create_client(LLMProxy.PROVIDER_OPENAI, api_key)
            client2 = self.proxy._get_or_create_client(LLMProxy.PROVIDER_OPENAI, api_key)

        self.mock_openai_class.assert_called_once_with(api_key="val", timeout=ANY, max_retries=0)
        timeout = self.mock_openai_class.call_args.kwargs["timeout"]
        assert timeout.connect == 10.0
        assert timeout.read == 300.0
        assert client1 is client2

    def test_routing_to_correct_adapter(self):
        """create_response debe rutear al adaptador correcto según el modelo."""

        # Configure model -> provider mapping for this test
        def provider_side_effect(model: str):
            if "gpt" in model:
                return "openai"
            if "gemini" in model:
                return "gemini"
            if "deepseek" in model:
                return "deepseek"
            if "claude" in model:
                return "anthropic"
            return "unknown"

        self.model_registry_mock.get_provider.side_effect = provider_side_effect

        # Config común para que _get_api_key_from_config funcione
        self.config_service_mock.get_configuration.return_value = {"api-key": "LLM_KEY"}

        with patch.dict(os.environ, {"LLM_KEY": "dummy"}, clear=True):
            # 1) Modelo OpenAI
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="gpt-4",
                input=[],
            )
            self.mock_openai_adapter_instance.create_response.assert_called_once()
            self.mock_gemini_adapter_instance.create_response.assert_not_called()
            self.mock_openai_compatible_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas de los adapters (no del cache de adapters)
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_anthropic_adapter_instance.reset_mock()

            # 2) Modelo Gemini
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="gemini-pro",
                input=[],
            )
            self.mock_gemini_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_openai_compatible_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_anthropic_adapter_instance.reset_mock()

            # 3) Modelo DeepSeek
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="deepseek-chat",
                input=[],
            )
            self.mock_openai_compatible_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_gemini_adapter_instance.create_response.assert_not_called()
            self.mock_anthropic_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_anthropic_adapter_instance.reset_mock()

            # 4) Modelo Anthropic (mockeamos _get_or_create_client para no depender del SDK real)
            with patch.object(self.proxy, "_get_or_create_client", return_value=MagicMock()):
                self.proxy.create_response(
                    company_short_name=self.company_short_name,
                    model="claude-3-5-sonnet-latest",
                    input=[],
                )
            self.mock_anthropic_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_gemini_adapter_instance.create_response.assert_not_called()
            self.mock_openai_compatible_adapter_instance.create_response.assert_not_called()

    def test_routing_to_openai_compatible_provider_uses_model_config_provider(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai_compatible": "OSS_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "llama-3.3-70b-instruct",
            "provider": "openai_compatible",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://oss.example.com/v1",
        }

        with patch.dict(os.environ, {"OSS_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="llama-3.3-70b-instruct",
                input=[],
            )

        self.mock_openai_compatible_adapter_instance.create_response.assert_called_once()
        self.mock_openai_class.assert_called_once_with(
            api_key="dummy",
            base_url="https://oss.example.com/v1",
            timeout=ANY,
            max_retries=0,
        )
        timeout = self.mock_openai_class.call_args.kwargs["timeout"]
        assert timeout.connect == 10.0
        assert timeout.read == 300.0

    def test_client_uses_provider_timeout_and_retry_config(self):
        self.config_service_mock.get_configuration.return_value = {"api-key": "KEY"}
        self.config_service_mock.get_llm_provider_config.return_value = {
            "connect_timeout_seconds": 7,
            "read_timeout_seconds": 123,
            "max_retries": 1,
        }

        with patch.dict(os.environ, {"KEY": "val"}, clear=True):
            self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI, self.company_short_name)

        self.mock_openai_class.assert_called_once_with(api_key="val", timeout=ANY, max_retries=1)
        timeout = self.mock_openai_class.call_args.kwargs["timeout"]
        assert timeout.connect == 7.0
        assert timeout.read == 123.0
        assert timeout.write == 123.0
        assert timeout.pool == 123.0

    def test_adapter_cache_uses_provider_and_api_key(self):
        """
        _get_or_create_adapter debe cachear por (provider, api_key), no solo por provider.
        """
        self.config_service_mock.get_configuration.side_effect = (
            lambda company, _section: {
                "provider_api_keys": {
                    "openai": "OPENAI_KEY_A" if company == "company_a" else "OPENAI_KEY_B"
                }
            }
        )

        adapter_a = MagicMock(name="adapter_a")
        adapter_b = MagicMock(name="adapter_b")
        self.mock_openai_adapter_class.side_effect = [adapter_a, adapter_b]

        with patch.dict(os.environ, {"OPENAI_KEY_A": "sk-a", "OPENAI_KEY_B": "sk-b"}, clear=True):
            first = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI, "company_a")
            second = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI, "company_b")
            third = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI, "company_a")

        assert first is adapter_a
        assert second is adapter_b
        assert third is adapter_a
        assert self.mock_openai_adapter_class.call_count == 2
        assert self.mock_openai_adapter_class.call_count == 2

    def test_openai_compatible_cache_uses_base_url(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai_compatible": "OSS_KEY"}
        }
        self.config_service_mock.get_llm_provider_config.side_effect = (
            lambda company, _provider: {
                "base_url": "https://endpoint-a.example.com/v1"
                if company == "company_a"
                else "https://endpoint-b.example.com/v1"
            }
        )

        adapter_a = MagicMock(name="adapter_a")
        adapter_b = MagicMock(name="adapter_b")
        self.mock_openai_compatible_adapter_class.side_effect = [adapter_a, adapter_b]

        with patch.dict(os.environ, {"OSS_KEY": "sk-oss"}, clear=True):
            first = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI_COMPATIBLE, "company_a")
            second = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI_COMPATIBLE, "company_b")
            third = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI_COMPATIBLE, "company_a")

        assert first is adapter_a
        assert second is adapter_b
        assert third is adapter_a

    def test_openai_compatible_can_disable_tools_via_provider_config(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai_compatible": "OSS_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "meta-llama/Llama-3.1-8B-Instruct",
            "provider": "openai_compatible",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://oss.example.com/v1",
            "disable_tools": True,
        }

        with patch.dict(os.environ, {"OSS_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="meta-llama/Llama-3.1-8B-Instruct",
                input=[],
                tools=[{"type": "function", "function": {"name": "search_docs"}}],
                tool_choice="auto",
            )

        self.mock_openai_compatible_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openai_compatible_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["tools"] == []
        assert adapter_kwargs["tool_choice"] is None

    def test_clear_runtime_cache_clears_adapter_and_client_caches(self):
        self.proxy.adapters = {(LLMProxy.PROVIDER_OPENAI, "key", ""): MagicMock()}
        LLMProxy._clients_cache[(LLMProxy.PROVIDER_OPENAI, "key", "")] = MagicMock()

        self.proxy.clear_runtime_cache()
        LLMProxy.clear_low_level_clients_cache()

        assert self.proxy.adapters == {}
        assert LLMProxy._clients_cache == {}
