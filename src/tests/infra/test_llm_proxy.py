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
        self.telemetry_service_mock = MagicMock()
        self.secret_provider_mock.get_secret.side_effect = (
            lambda _company, key_name, default=None: os.getenv(key_name, default)
        )
        self.telemetry_service_mock.wrap_client_for_request.side_effect = (
            lambda **kwargs: kwargs["client"]
        )
        self.config_service_mock.get_llm_model_config.return_value = None
        self.config_service_mock.get_llm_provider_config.return_value = {}
        self.config_service_mock.get_llm_gateway_config.return_value = {}
        self.config_service_mock.get_llm_request_defaults.return_value = {}

        # Empresa base
        self.company_short_name = "test_company"

        # Parches para los clientes de los proveedores
        self.openai_patcher = patch("iatoolkit.infra.llm_proxy.OpenAI")

        self.mock_openai_class = self.openai_patcher.start()

        # Parches para los adaptadores
        self.openai_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenAIAdapter")
        self.gemini_adapter_patcher = patch("iatoolkit.infra.llm_proxy.GeminiAdapter")
        self.deepseek_adapter_patcher = patch("iatoolkit.infra.llm_proxy.DeepseekAdapter")
        self.openai_compatible_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenAICompatibleChatAdapter")
        self.openrouter_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenRouterAdapter")
        self.anthropic_adapter_patcher = patch("iatoolkit.infra.llm_proxy.AnthropicAdapter")

        self.mock_openai_adapter_class = self.openai_adapter_patcher.start()
        self.mock_gemini_adapter_class = self.gemini_adapter_patcher.start()
        self.mock_deepseek_adapter_class = self.deepseek_adapter_patcher.start()
        self.mock_openai_compatible_adapter_class = self.openai_compatible_adapter_patcher.start()
        self.mock_openrouter_adapter_class = self.openrouter_adapter_patcher.start()
        self.mock_anthropic_adapter_class = self.anthropic_adapter_patcher.start()

        # Instancias mock de adaptadores
        self.mock_openai_adapter_instance = MagicMock()
        self.mock_gemini_adapter_instance = MagicMock()
        self.mock_deepseek_adapter_instance = MagicMock()
        self.mock_openai_compatible_adapter_instance = MagicMock()
        self.mock_openrouter_adapter_instance = MagicMock()
        self.mock_anthropic_adapter_instance = MagicMock()

        self.mock_openai_adapter_class.return_value = self.mock_openai_adapter_instance
        self.mock_gemini_adapter_class.return_value = self.mock_gemini_adapter_instance
        self.mock_deepseek_adapter_class.return_value = self.mock_deepseek_adapter_instance
        self.mock_openai_compatible_adapter_class.return_value = self.mock_openai_compatible_adapter_instance
        self.mock_openrouter_adapter_class.return_value = self.mock_openrouter_adapter_instance
        self.mock_anthropic_adapter_class.return_value = self.mock_anthropic_adapter_instance

        # Instancia de LLMProxy bajo prueba
        self.proxy = LLMProxy(
            util=self.util_mock,
            configuration_service=self.config_service_mock,
            model_registry=self.model_registry_mock,
            secret_provider=self.secret_provider_mock,
            telemetry_service=self.telemetry_service_mock,
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

        self.mock_openai_class.assert_called_once_with(
            api_key="val",
            base_url=None,
            timeout=ANY,
            max_retries=0,
            default_headers=None,
        )
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
            self.mock_deepseek_adapter_instance.create_response.assert_not_called()
            self.mock_openrouter_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas de los adapters (no del cache de adapters)
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_deepseek_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_openrouter_adapter_instance.reset_mock()
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
            self.mock_deepseek_adapter_instance.create_response.assert_not_called()
            self.mock_openrouter_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_deepseek_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_openrouter_adapter_instance.reset_mock()
            self.mock_anthropic_adapter_instance.reset_mock()

            # 3) Modelo DeepSeek
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="deepseek-v4-flash",
                input=[],
            )
            self.mock_deepseek_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_gemini_adapter_instance.create_response.assert_not_called()
            self.mock_openai_compatible_adapter_instance.create_response.assert_not_called()
            self.mock_anthropic_adapter_instance.create_response.assert_not_called()
            self.mock_openrouter_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_deepseek_adapter_instance.reset_mock()
            self.mock_openai_compatible_adapter_instance.reset_mock()
            self.mock_openrouter_adapter_instance.reset_mock()
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
            self.mock_deepseek_adapter_instance.create_response.assert_not_called()
            self.mock_openrouter_adapter_instance.create_response.assert_not_called()

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
            default_headers=None,
        )
        timeout = self.mock_openai_class.call_args.kwargs["timeout"]
        assert timeout.connect == 10.0
        assert timeout.read == 300.0

    def test_deepseek_applies_company_reasoning_effort_default(self):
        self.model_registry_mock.get_provider.return_value = "deepseek"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"deepseek": "DEEPSEEK_KEY"}
        }
        self.config_service_mock.get_llm_request_defaults.return_value = {
            "text": {},
            "reasoning": {"effort": "high"},
        }

        with patch.dict(os.environ, {"DEEPSEEK_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="deepseek-v4-pro",
                input=[],
            )

        self.mock_deepseek_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_deepseek_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["reasoning"] == {"effort": "high"}
        self.config_service_mock.get_llm_request_defaults.assert_called_with(
            self.company_short_name, "deepseek-v4-pro"
        )

    def test_create_response_wraps_client_when_telemetry_request_is_enabled(self):
        self.model_registry_mock.get_provider.return_value = "openai"
        self.config_service_mock.get_configuration.return_value = {"api-key": "LLM_KEY"}
        wrapped_client = MagicMock(name="wrapped_openai_client")
        self.telemetry_service_mock.wrap_client_for_request.side_effect = (
            lambda **kwargs: wrapped_client
        )

        with patch.dict(os.environ, {"LLM_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="gpt-5",
                input=[],
                telemetry_request={
                    "requested": True,
                    "enabled": True,
                    "provider": "braintrust",
                    "project": "acme-prod",
                },
            )

        self.telemetry_service_mock.wrap_client_for_request.assert_called_once()
        wrap_kwargs = self.telemetry_service_mock.wrap_client_for_request.call_args.kwargs
        assert wrap_kwargs["llm_provider"] == LLMProxy.PROVIDER_OPENAI
        assert wrap_kwargs["request"]["provider"] == "braintrust"
        self.mock_openai_adapter_class.assert_called_once_with(wrapped_client)

    def test_create_response_forwards_telemetry_execution_to_adapter(self):
        self.model_registry_mock.get_provider.return_value = "openai"
        self.config_service_mock.get_configuration.return_value = {"api-key": "LLM_KEY"}
        telemetry_execution = MagicMock(name="telemetry_execution")

        with patch.dict(os.environ, {"LLM_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="gpt-5",
                input=[],
                telemetry_execution=telemetry_execution,
            )

        adapter_kwargs = self.mock_openai_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["telemetry_execution"] is telemetry_execution

    def test_client_uses_provider_timeout_and_retry_config(self):
        self.config_service_mock.get_configuration.return_value = {"api-key": "KEY"}
        self.config_service_mock.get_llm_provider_config.return_value = {
            "connect_timeout_seconds": 7,
            "read_timeout_seconds": 123,
            "max_retries": 1,
        }

        with patch.dict(os.environ, {"KEY": "val"}, clear=True):
            self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENAI, self.company_short_name)

        self.mock_openai_class.assert_called_once_with(
            api_key="val",
            base_url=None,
            timeout=ANY,
            max_retries=1,
            default_headers=None,
        )
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

    def test_the_adapter_is_called_with_the_name_the_endpoint_serves(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai_compatible": "OSS_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "meta-llama/llama-3.1-8b-instruct",
            "provider": "openai_compatible",
            "route_config": {
                "base_url": "https://yr78.endpoints.huggingface.cloud/v1",
                "model_name": "meta-llama/Llama-3.1-8B-Instruct",
            },
        }
        self.config_service_mock.get_llm_provider_config.return_value = {}
        self.config_service_mock.get_llm_request_defaults.return_value = {}

        with patch.dict(os.environ, {"OSS_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                # Callers keep naming the model by its catalogue key.
                model="meta-llama/llama-3.1-8b-instruct",
                input=[],
            )

        adapter_kwargs = self.mock_openai_compatible_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["model"] == "meta-llama/Llama-3.1-8B-Instruct"
        # The lookups that price and meter the call still use the catalogue key, so
        # one model cannot split into two usage lines.
        assert self.config_service_mock.get_llm_model_config.call_args.args[1] == "meta-llama/llama-3.1-8b-instruct"

    def test_openai_compatible_does_not_receive_the_company_reasoning_effort_default(self):
        """
        The company default must stop at the proxy for this provider. When it did not,
        a model added from /hcc with provider `openai_compatible` failed on its first
        request with "Completions.create() got an unexpected keyword argument
        'reasoning'" — the adapter here is a mock, which is why this went unnoticed.
        """
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
        }
        self.config_service_mock.get_llm_request_defaults.return_value = {
            "text": {},
            "reasoning": {"effort": "high"},
        }

        with patch.dict(os.environ, {"OSS_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="meta-llama/Llama-3.1-8B-Instruct",
                input=[],
            )

        self.mock_openai_compatible_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openai_compatible_adapter_instance.create_response.call_args.kwargs
        assert "reasoning" not in adapter_kwargs

    def test_routing_to_openrouter_provider_uses_model_config_provider(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
            "config": {
                "routing": {
                    "order": ["openai"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                }
            },
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
            "http_referer": "https://example.com/app",
            "x_title": "IAToolkit",
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        self.mock_openai_class.assert_called_once_with(
            api_key="dummy",
            base_url="https://openrouter.ai/api/v1",
            timeout=ANY,
            max_retries=0,
            default_headers={
                "HTTP-Referer": "https://example.com/app",
                "X-Title": "IAToolkit",
                "X-OpenRouter-Title": "IAToolkit",
            },
        )
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["provider"] == {
            "order": ["openai"],
            "allow_fallbacks": False,
            "require_parameters": True,
        }

    def test_openrouter_applies_company_reasoning_effort_default(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
        }
        self.config_service_mock.get_llm_request_defaults.return_value = {
            "text": {},
            "reasoning": {"effort": "medium"},
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["reasoning"] == {"effort": "medium"}

    def test_openrouter_cache_uses_default_headers(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_provider_config.side_effect = (
            lambda company, _provider: {
                "base_url": "https://openrouter.ai/api/v1",
                "http_referer": "https://example.com/app",
                "x_title": "IAToolkit A" if company == "company_a" else "IAToolkit B",
            }
        )

        adapter_a = MagicMock(name="openrouter_adapter_a")
        adapter_b = MagicMock(name="openrouter_adapter_b")
        self.mock_openrouter_adapter_class.side_effect = [adapter_a, adapter_b]

        with patch.dict(os.environ, {"OPENROUTER_KEY": "sk-openrouter"}, clear=True):
            first = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENROUTER, "company_a")
            second = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENROUTER, "company_b")
            third = self.proxy._get_or_create_adapter(LLMProxy.PROVIDER_OPENROUTER, "company_a")

        assert first is adapter_a
        assert second is adapter_b
        assert third is adapter_a

    def test_openrouter_can_disable_tools_via_provider_config(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
            "disable_tools": True,
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
                tools=[{"type": "function", "function": {"name": "search_docs"}}],
                tool_choice="auto",
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["tools"] == []
        assert adapter_kwargs["tool_choice"] is None

    def test_openrouter_explicit_reasoning_overrides_company_default(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
        }
        self.config_service_mock.get_llm_request_defaults.return_value = {
            "text": {},
            "reasoning": {"effort": "low"},
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
                reasoning={"effort": "xhigh"},
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["reasoning"] == {"effort": "xhigh"}

    def test_openrouter_runtime_provider_overrides_model_routing_config(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
            "config": {
                "routing": {
                    "order": ["openai"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                }
            },
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
                provider={"allow_fallbacks": True, "sort": "latency"},
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["provider"] == {
            "order": ["openai"],
            "allow_fallbacks": True,
            "require_parameters": True,
            "sort": "latency",
        }

    def test_openrouter_applies_provider_level_default_routing_config(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
            "routing": {
                "order": ["venice"],
                "allow_fallbacks": False,
            },
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["provider"] == {
            "order": ["venice"],
            "allow_fallbacks": False,
        }

    def test_openrouter_model_routing_overrides_provider_level_default_routing(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
            "config": {
                "routing": {
                    "order": ["openai"],
                }
            },
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
            "routing": {
                "order": ["venice"],
                "allow_fallbacks": False,
                "sort": "price",
            },
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["provider"] == {
            "order": ["openai"],
            "allow_fallbacks": False,
            "sort": "price",
        }

    def test_openrouter_runtime_provider_overrides_provider_level_default_routing(self):
        self.model_registry_mock.get_provider.return_value = "unknown"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_model_config.return_value = {
            "id": "openai/gpt-5.2",
            "provider": "openrouter",
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
            "routing": {
                "order": ["venice"],
                "allow_fallbacks": False,
            },
        }

        with patch.dict(os.environ, {"OPENROUTER_KEY": "dummy"}, clear=True):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5.2",
                input=[],
                provider={"allow_fallbacks": True, "sort": "latency"},
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        adapter_kwargs = self.mock_openrouter_adapter_instance.create_response.call_args.kwargs
        assert adapter_kwargs["provider"] == {
            "order": ["venice"],
            "allow_fallbacks": True,
            "sort": "latency",
        }

    def test_get_client_config_applies_cloudflare_gateway_for_openai(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai": "OPENAI_KEY"}
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "provider_key_in_request",
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_KEY": "sk-openai",
                "CF_ACCOUNT_ID": "cf-account",
                "CF_API_TOKEN": "cf-token",
            },
            clear=True,
        ):
            client_config = self.proxy._get_client_config(self.company_short_name, LLMProxy.PROVIDER_OPENAI)

        assert client_config["api_key"] == "sk-openai"
        assert client_config["base_url"] == (
            "https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/openai"
        )
        assert client_config["default_headers"] == {
            "cf-aig-authorization": "Bearer cf-token",
        }

    def test_get_client_config_allows_cloudflare_managed_credentials_for_openai(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai": "OPENAI_KEY"}
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "cloudflare_managed",
        }

        with patch.dict(
            os.environ,
            {
                "CF_ACCOUNT_ID": "cf-account",
                "CF_API_TOKEN": "cf-token",
            },
            clear=True,
        ):
            client_config = self.proxy._get_client_config(self.company_short_name, LLMProxy.PROVIDER_OPENAI)

        assert client_config["api_key"] == ""
        assert client_config["base_url"] == (
            "https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/openai"
        )
        assert client_config["default_headers"]["cf-aig-authorization"] == "Bearer cf-token"

    def test_get_client_config_allows_cloudflare_managed_credentials_for_openrouter(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1"
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "cloudflare_managed",
        }

        with patch.dict(
            os.environ,
            {
                "CF_ACCOUNT_ID": "cf-account",
                "CF_API_TOKEN": "cf-token",
            },
            clear=True,
        ):
            client_config = self.proxy._get_client_config(self.company_short_name, LLMProxy.PROVIDER_OPENROUTER)

        assert client_config["api_key"] == ""
        assert client_config["base_url"] == (
            "https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/openrouter"
        )
        assert client_config["default_headers"]["cf-aig-authorization"] == "Bearer cf-token"

    def test_get_client_config_rejects_cloudflare_managed_without_authenticated_gateway(self):
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openai": "OPENAI_KEY"}
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": False,
            "credential_mode": "cloudflare_managed",
        }

        with patch.dict(os.environ, {"CF_ACCOUNT_ID": "cf-account"}, clear=True):
            with pytest.raises(IAToolkitException, match="authenticated_gateway: true"):
                self.proxy._get_client_config(self.company_short_name, LLMProxy.PROVIDER_OPENAI)

    def test_create_response_routes_deepseek_through_cloudflare_gateway(self):
        self.model_registry_mock.get_provider.return_value = "deepseek"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"deepseek": "DEEPSEEK_KEY"}
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "provider_key_in_request",
        }

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_KEY": "sk-deepseek",
                "CF_ACCOUNT_ID": "cf-account",
                "CF_API_TOKEN": "cf-token",
            },
            clear=True,
        ):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="deepseek-v4-pro",
                input=[],
            )

        self.mock_deepseek_adapter_instance.create_response.assert_called_once()
        self.mock_openai_class.assert_called_once_with(
            api_key="sk-deepseek",
            base_url="https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/deepseek",
            timeout=ANY,
            max_retries=0,
            default_headers={"cf-aig-authorization": "Bearer cf-token"},
        )

    def test_create_response_routes_openrouter_through_cloudflare_gateway(self):
        self.model_registry_mock.get_provider.return_value = "openrouter"
        self.config_service_mock.get_configuration.return_value = {
            "provider_api_keys": {"openrouter": "OPENROUTER_KEY"}
        }
        self.config_service_mock.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1"
        }
        self.config_service_mock.get_llm_gateway_config.return_value = {
            "enabled": True,
            "vendor": "cloudflare",
            "mode": "provider_native",
            "gateway_id": "primary-gateway",
            "account_id_secret_ref": "CF_ACCOUNT_ID",
            "authenticated_gateway": True,
            "cloudflare_api_token_secret_ref": "CF_API_TOKEN",
            "credential_mode": "cloudflare_managed",
        }

        with patch.dict(
            os.environ,
            {
                "CF_ACCOUNT_ID": "cf-account",
                "CF_API_TOKEN": "cf-token",
            },
            clear=True,
        ):
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="openai/gpt-5-mini",
                input=[],
            )

        self.mock_openrouter_adapter_instance.create_response.assert_called_once()
        self.mock_openai_class.assert_called_once_with(
            api_key="",
            base_url="https://gateway.ai.cloudflare.com/v1/cf-account/primary-gateway/openrouter",
            timeout=ANY,
            max_retries=0,
            default_headers={"cf-aig-authorization": "Bearer cf-token"},
        )

    def test_clear_runtime_cache_clears_adapter_and_client_caches(self):
        self.proxy.adapters = {(LLMProxy.PROVIDER_OPENAI, "key", ""): MagicMock()}
        LLMProxy._clients_cache[(LLMProxy.PROVIDER_OPENAI, "key", "")] = MagicMock()

        self.proxy.clear_runtime_cache()
        LLMProxy.clear_low_level_clients_cache()

        assert self.proxy.adapters == {}
        assert LLMProxy._clients_cache == {}


class TestWhoseKeyRunsAModel:
    """The credential follows the catalogue's per-model decision, not a name.

    Before this, the key was resolved only from `llm.provider_api_keys[provider]`
    — a *name*, looked up in the company's secret store first and the platform's
    environment second. So a model the catalogue said the platform pays for ran
    on the customer's key whenever the customer had stored a secret under the
    same name as the platform's variable, and was invoiced as platform-served
    anyway. Observed on a real entitlement: `gpt-5.6-sol`, owner `platform`,
    resolving to the customer's own `OPENAI_API_KEY`.
    """

    def _proxy(self):
        from unittest.mock import MagicMock
        from iatoolkit.infra.llm_proxy import LLMProxy

        config = MagicMock()
        config.get_configuration.return_value = {
            "provider_api_keys": {"openai": "PLATFORM_OPENAI_KEY"},
        }
        secrets = MagicMock()
        secrets.get_secret.side_effect = lambda _company, key_name, default=None: {
            "PLATFORM_OPENAI_KEY": "platform-value",
            "CUSTOMER_OPENAI_KEY": "customer-value",
        }.get(key_name, default)
        proxy = LLMProxy.__new__(LLMProxy)
        proxy.configuration_service = config
        proxy.secret_provider = secrets
        return proxy

    def test_a_company_owned_model_runs_on_the_secret_it_was_given(self):
        proxy = self._proxy()

        key = proxy._get_api_key_from_config(
            "acme", "openai",
            secret_ref=proxy._model_credential_ref(
                {"credential_owner": "company", "secret_key_name": "CUSTOMER_OPENAI_KEY"}
            ),
        )

        assert key == "customer-value"

    def test_a_platform_owned_model_runs_on_the_deployment_key(self):
        # Even when the company has stored a secret of its own: `platform` is what
        # "we pay for this" means, and it must not be overridable by a name.
        proxy = self._proxy()

        key = proxy._get_api_key_from_config(
            "acme", "openai",
            secret_ref=proxy._model_credential_ref(
                {"credential_owner": "platform", "secret_key_name": "CUSTOMER_OPENAI_KEY"}
            ),
        )

        assert key == "platform-value"

    def test_no_entitlement_falls_back_to_the_provider_mapping(self):
        # A company still on company.yaml behaves exactly as before.
        proxy = self._proxy()

        assert proxy._get_api_key_from_config("acme", "openai", secret_ref=None) == "platform-value"

    def test_company_ownership_without_a_secret_does_not_override(self):
        # enable_for_company refuses this combination, so it should not exist —
        # and if it does, falling back beats calling the provider with nothing.
        proxy = self._proxy()

        ref = proxy._model_credential_ref({"credential_owner": "company", "secret_key_name": ""})

        assert ref is None

    def test_a_model_config_that_is_not_a_dict_is_ignored(self):
        proxy = self._proxy()

        assert proxy._model_credential_ref(None) is None
        assert proxy._model_credential_ref("gpt-5") is None


class TestAModelCarriesItsOwnRoute:
    """The endpoint used to live in each company's configuration file.

    So every `openai_compatible` model a company enabled resolved to the same
    endpoint — two self-hosted models on two different endpoints were impossible,
    while the dialog that adds them promised "one entry per route".
    """

    def _proxy(self, env=None):
        import os
        from unittest.mock import MagicMock, patch
        from iatoolkit.infra.llm_proxy import LLMProxy

        config = MagicMock()
        config.get_configuration.return_value = {
            "provider_api_keys": {"openai_compatible": "COMPANY_FILE_KEY"},
        }
        config.get_llm_provider_config.return_value = {"base_url_env": "COMPANY_FILE_URL"}
        secrets = MagicMock()
        # The company's own store, which is what `resolve_secret` reads first.
        secrets.get_secret.side_effect = lambda _c, name, default=None: {
            "COMPANY_FILE_KEY": "from-the-company-file",
            "COMPANY_FILE_URL": "https://from-the-company-file/v1",
            "ROUTE_KEY": "customer-shadowed-this",
        }.get(name, default)
        proxy = LLMProxy.__new__(LLMProxy)
        proxy.configuration_service = config
        proxy.secret_provider = secrets
        return proxy, patch.dict(os.environ, env or {}, clear=True)

    def test_the_entrys_endpoint_wins_over_the_company_file(self):
        proxy, _ = self._proxy()

        url = proxy._get_base_url_from_config(
            "acme", "openai_compatible",
            model_config={"route_config": {"base_url": "https://the-entry/v1"}},
        )

        assert url == "https://the-entry/v1"

    def test_without_a_route_the_company_file_still_answers(self):
        # Every entry in the catalogue today has no route, and must keep working.
        proxy, _ = self._proxy()

        url = proxy._get_base_url_from_config("acme", "openai_compatible", model_config={})

        assert url == "https://from-the-company-file/v1"

    def test_two_models_of_one_provider_can_sit_on_two_endpoints(self):
        # The thing that was impossible. Asserted here because the caches are keyed
        # by base_url, so different endpoints already mean different clients.
        proxy, _ = self._proxy()

        first = proxy._get_base_url_from_config(
            "acme", "openai_compatible", model_config={"route_config": {"base_url": "https://a/v1"}})
        second = proxy._get_base_url_from_config(
            "acme", "openai_compatible", model_config={"route_config": {"base_url": "https://b/v1"}})

        assert first != second

    def test_the_route_can_carry_the_exact_name_the_endpoint_serves(self):
        # A vLLM endpoint serving `meta-llama/Llama-3.1-8B-Instruct` answered
        # "404 - The model `meta-llama/llama-3.1-8b-instruct` does not exist" to the
        # catalogue key, which upsert_entry lowercases.
        proxy, _ = self._proxy()

        wire = proxy._wire_model(
            "meta-llama/llama-3.1-8b-instruct",
            {"route_config": {"model_name": "meta-llama/Llama-3.1-8B-Instruct"}},
        )

        assert wire == "meta-llama/Llama-3.1-8B-Instruct"

    def test_without_a_served_name_the_catalogue_key_goes_on_the_wire(self):
        proxy, _ = self._proxy()

        assert proxy._wire_model("deepseek-v4-pro", {}) == "deepseek-v4-pro"
        assert proxy._wire_model("deepseek-v4-pro", {"route_config": {"base_url": "https://x/v1"}}) == "deepseek-v4-pro"
        # Blank is the same as absent: the form submits empty strings.
        assert proxy._wire_model("deepseek-v4-pro", {"route_config": {"model_name": "  "}}) == "deepseek-v4-pro"

    def test_the_routes_credential_comes_from_the_deployment_environment(self):
        proxy, env = self._proxy({"ROUTE_KEY": "from-the-deployment"})

        with env:
            key = proxy._get_api_key_from_config("acme", "openai_compatible", route_api_key_env="ROUTE_KEY")

        assert key == "from-the-deployment"

    def test_a_customer_cannot_take_over_the_routes_credential(self):
        """The decision this pins.

        `resolve_secret` reads the company's own store before the environment, so a
        customer that stored a secret named ROUTE_KEY would otherwise supply the
        credential for an endpoint the operator runs and pays for — silently. A
        customer that wants to pay with its own key has an explicit path:
        `credential_owner = company` on its entitlement.
        """
        proxy, env = self._proxy({"ROUTE_KEY": "from-the-deployment"})

        with env:
            key = proxy._get_api_key_from_config("acme", "openai_compatible", route_api_key_env="ROUTE_KEY")

        assert key == "from-the-deployment"
        assert key != "customer-shadowed-this"

    def test_a_variable_the_deployment_does_not_define_says_so(self):
        # Naming a variable is not setting it, and the message has to name which.
        from iatoolkit.common.exceptions import IAToolkitException

        proxy, env = self._proxy({})

        with env:
            with pytest.raises(IAToolkitException, match="MISSING_VAR"):
                proxy._get_api_key_from_config(
                    "acme", "openai_compatible", route_api_key_env="MISSING_VAR", required=True
                )

    def test_the_customers_own_key_still_outranks_the_route(self):
        # Whose key pays is the customer's decision; where it goes is the
        # operator's. They are different questions and both are honoured.
        proxy, env = self._proxy({"ROUTE_KEY": "from-the-deployment"})

        with env:
            key = proxy._get_api_key_from_config(
                "acme", "openai_compatible",
                secret_ref="COMPANY_FILE_KEY", route_api_key_env="ROUTE_KEY",
            )

        assert key == "from-the-company-file"
