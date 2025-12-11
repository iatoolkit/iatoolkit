import os
import pytest
from unittest.mock import patch, MagicMock

from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.model_registry import ModelRegistry

class TestLLMProxy:
    def setup_method(self):
        """Configuración común para las pruebas de LLMProxy."""
        # Utility y configuration_service mockeados
        self.util_mock = MagicMock()
        self.config_service_mock = MagicMock(spec=ConfigurationService)
        self.model_registry_mock = MagicMock(spec=ModelRegistry)

        # Empresa base
        self.company_short_name = "test_company"

        # Parches para los clientes de los proveedores
        self.openai_patcher = patch("iatoolkit.infra.llm_proxy.OpenAI")

        self.mock_openai_class = self.openai_patcher.start()

        # Parches para los adaptadores
        self.openai_adapter_patcher = patch("iatoolkit.infra.llm_proxy.OpenAIAdapter")
        self.gemini_adapter_patcher = patch("iatoolkit.infra.llm_proxy.GeminiAdapter")
        self.deepseek_adapter_patcher = patch("iatoolkit.infra.llm_proxy.DeepseekAdapter")

        self.mock_openai_adapter_class = self.openai_adapter_patcher.start()
        self.mock_gemini_adapter_class = self.gemini_adapter_patcher.start()
        self.mock_deepseek_adapter_class = self.deepseek_adapter_patcher.start()

        # Instancias mock de adaptadores
        self.mock_openai_adapter_instance = MagicMock()
        self.mock_gemini_adapter_instance = MagicMock()
        self.mock_deepseek_adapter_instance = MagicMock()

        self.mock_openai_adapter_class.return_value = self.mock_openai_adapter_instance
        self.mock_gemini_adapter_class.return_value = self.mock_gemini_adapter_instance
        self.mock_deepseek_adapter_class.return_value = self.mock_deepseek_adapter_instance

        # Instancia de LLMProxy bajo prueba
        self.proxy = LLMProxy(
            util=self.util_mock,
            configuration_service=self.config_service_mock,
            model_registry=self.model_registry_mock
        )

        # Aseguramos que el cache global esté limpio para cada test
        LLMProxy._clients_cache.clear()

    def teardown_method(self):
        patch.stopall()
        LLMProxy._clients_cache.clear()

    def test_create_openai_client_from_config(self):
        """El cliente OpenAI se crea usando la API key leída desde configuration_service + os.environ."""
        # Configuración de company.yaml simulada
        self.config_service_mock.get_configuration.return_value = {"api-key": "COMPANY_OPENAI_KEY"}

        with patch.dict(os.environ, {"COMPANY_OPENAI_KEY": "key_from_env"}, clear=True):
            api_key = self.proxy._get_api_key_from_config(self.company_short_name)
            client = self.proxy._get_or_create_client(LLMProxy.PROVIDER_OPENAI, api_key)

        # Debe haberse construido el cliente OpenAI con la API key tomada del env
        self.mock_openai_class.assert_called_once_with(api_key="key_from_env")
        # Y el cliente retornado debe ser el mismo objeto devuelto por la clase OpenAI mockeada
        assert client is self.mock_openai_class.return_value

    def test_create_deepseek_client_from_config(self):
        """El cliente DeepSeek se crea usando la API key leída desde configuration_service + os.environ."""
        self.config_service_mock.get_configuration.return_value = {"api-key": "COMPANY_DEEPSEEK_KEY"}

        with patch.dict(os.environ, {"COMPANY_DEEPSEEK_KEY": "deepseek_key"}, clear=True):
            api_key = self.proxy._get_api_key_from_config(self.company_short_name)
            client = self.proxy._get_or_create_client(LLMProxy.PROVIDER_DEEPSEEK, api_key)

        # DeepSeek usa el cliente OpenAI con un base_url distinto
        self.mock_openai_class.assert_called_once_with(
            api_key="deepseek_key",
            base_url="https://api.deepseek.com",
        )
        assert client is self.mock_openai_class.return_value

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
            api_key = self.proxy._get_api_key_from_config(self.company_short_name)
            client1 = self.proxy._get_or_create_client(LLMProxy.PROVIDER_OPENAI, api_key)
            client2 = self.proxy._get_or_create_client(LLMProxy.PROVIDER_OPENAI, api_key)

        # La clase OpenAI solo debe haberse instanciado una vez
        self.mock_openai_class.assert_called_once_with(api_key="val")
        # Y ambas llamadas deben devolver el mismo cliente
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
            self.mock_deepseek_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas de los adapters (no del cache de adapters)
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_deepseek_adapter_instance.reset_mock()

            # 2) Modelo Gemini
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="gemini-pro",
                input=[],
            )
            self.mock_gemini_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_deepseek_adapter_instance.create_response.assert_not_called()

            # Reset de llamadas
            self.mock_openai_adapter_instance.reset_mock()
            self.mock_gemini_adapter_instance.reset_mock()
            self.mock_deepseek_adapter_instance.reset_mock()

            # 3) Modelo DeepSeek
            self.proxy.create_response(
                company_short_name=self.company_short_name,
                model="deepseek-chat",
                input=[],
            )
            self.mock_deepseek_adapter_instance.create_response.assert_called_once()
            self.mock_openai_adapter_instance.create_response.assert_not_called()
            self.mock_gemini_adapter_instance.create_response.assert_not_called()