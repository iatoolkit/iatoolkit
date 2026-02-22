# tests/services/test_embedding_service.py

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import numpy as np
import base64
from iatoolkit.repositories.models import Company

# Import the classes to be tested
from iatoolkit.services.embedding_service import (
    EmbeddingClientFactory,
    EmbeddingService,
    HuggingFaceClientWrapper,
    OpenAIClientWrapper,
    CustomClassClientWrapper,
    EmbeddingClientWrapper
)
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.inference_service import InferenceService
from iatoolkit.common.interfaces.secret_provider import SecretProvider


class TestEmbeddingService:
    """
    Test suite for the EmbeddingService and its dependent EmbeddingClientFactory.
    """

    # --- Test Data ---
    MOCK_CONFIG_HF = {
        'provider': 'huggingface',
        'model': 'hf-model',
        'tool_name': 'text_embeddings' # Nuevo campo requerido
    }
    MOCK_CONFIG_OPENAI = {
        'provider': 'openai',
        'model': 'openai-model',
        'api_key_name': 'OPENAI_KEY'
    }
    MOCK_CONFIG_CUSTOM = {
        'provider': 'custom_class',
        'model': 'my-custom-model',
        'class_path': 'companies.acme.my_model.MyEmbedder',
        'api_key_name': 'CUSTOM_KEY',
        'init_params': {'arg1': 'val1'}
    }
    # Mock config for visual provider
    MOCK_CONFIG_VISUAL = {
        'provider': 'openai',
        'model': 'clip-vit-base',
        'api_key_name': 'OPENAI_KEY',
        'dimensions': 512
    }

    SAMPLE_VECTOR = [0.1, 0.2, 0.3, 0.4]

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Set up mocks and instantiate the factory and service for each test.
        """
        self.mock_config_service = Mock(spec=ConfigurationService)

        # Configure the mock to return different configs for different companies
        def get_config_side_effect(company_short_name, key):
            if key == 'embedding_provider':
                if company_short_name == 'company_hf':
                    return self.MOCK_CONFIG_HF
                if company_short_name == 'company_openai':
                    return self.MOCK_CONFIG_OPENAI
                if company_short_name == 'company_custom':
                    return self.MOCK_CONFIG_CUSTOM
                if company_short_name == 'company_visual':
                    return self.MOCK_CONFIG_OPENAI

            if key == 'visual_embedding_provider':
                if company_short_name == 'company_visual':
                    return self.MOCK_CONFIG_VISUAL

            return None

        self.mock_config_service.get_configuration.side_effect = get_config_side_effect

        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_company = Company(id=1, short_name='acme')
        self.mock_profile_repo.get_company_by_short_name.return_value = self.mock_company

        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.mock_call_service = MagicMock(spec=CallServiceClient)

        # New dependency: InferenceService
        self.mock_inference_service = MagicMock(spec=InferenceService)
        self.mock_secret_provider = MagicMock(spec=SecretProvider)
        self.mock_secret_provider.get_secret.side_effect = (
            lambda _company, key_name, default=None: {
                "OPENAI_KEY": "fake-openai-key",
                "CUSTOM_KEY": "fake-custom-key",
            }.get(key_name, default)
        )

        # Instantiate the classes under test
        self.client_factory = EmbeddingClientFactory(
            config_service=self.mock_config_service,
            call_service=self.mock_call_service,
            inference_service=self.mock_inference_service,
            secret_provider=self.mock_secret_provider,
        )

        self.embedding_service = EmbeddingService(
            client_factory=self.client_factory,
            profile_repo=self.mock_profile_repo,
            i18n_service=self.mock_i18n_service
        )

    # --- Factory Tests ---

    def test_factory_creates_huggingface_wrapper(self, mocker):
        """Tests that the factory correctly creates a HuggingFaceClientWrapper with InferenceService."""
        # Arrange
        # No need to patch env vars for HF anymore as config comes from yaml logic handled by factory/service

        # Act
        wrapper = self.client_factory.get_client('company_hf')

        # Assert
        assert isinstance(wrapper, HuggingFaceClientWrapper)
        assert wrapper.client is None
        assert wrapper.model == 'hf-model'
        # Verifica que se inyectaron las dependencias correctas
        assert wrapper.inference_service == self.mock_inference_service
        assert wrapper.company_short_name == 'company_hf'
        assert wrapper.tool_name == 'text_embeddings' # From MOCK_CONFIG_HF

    def test_factory_creates_openai_wrapper(self, mocker):
        """Tests that the factory correctly creates an OpenAIClientWrapper."""
        mocker.patch('os.getenv', return_value='fake-openai-key')
        mock_openai_client_class = mocker.patch('iatoolkit.services.embedding_service.OpenAI')

        # Act
        wrapper = self.client_factory.get_client('company_openai')

        # Assert
        assert isinstance(wrapper, OpenAIClientWrapper)
        mock_openai_client_class.assert_called_once_with(api_key='fake-openai-key')
        assert wrapper.model == 'openai-model'

    def test_factory_creates_custom_class_wrapper(self, mocker):
        """Tests that the factory correctly loads and instantiates a custom class."""
        mocker.patch('os.getenv', return_value='fake-custom-key')

        # Mock importlib and the dynamic class
        mock_importlib = mocker.patch('importlib.import_module')
        mock_module = MagicMock()
        mock_class = MagicMock()
        mock_instance = MagicMock()

        # Setup import chain: import_module -> module -> class -> instance
        mock_importlib.return_value = mock_module
        setattr(mock_module, 'MyEmbedder', mock_class)
        mock_class.return_value = mock_instance

        # Act
        wrapper = self.client_factory.get_client('company_custom')

        # Assert
        assert isinstance(wrapper, CustomClassClientWrapper)
        mock_importlib.assert_called_once_with('companies.acme.my_model')
        mock_class.assert_called_once_with(arg1='val1')
        assert wrapper.client == mock_instance

    # --- HuggingFaceClientWrapper Tests (New Architecture) ---

    def test_huggingface_wrapper_get_embedding_calls_inference_service(self):
        """
        Verify get_embedding translates request to inference_service.predict call.
        """
        # Arrange
        mock_inference = MagicMock()
        mock_inference.predict.return_value = {"embedding": [0.1, 0.2, 0.3], "dimensions": 3}

        wrapper = HuggingFaceClientWrapper(
            client=None,
            model="hf-model",
            inference_service=mock_inference,
            company_short_name="test_co",
            tool_name="text_tool"
        )

        # Act
        result = wrapper.get_embedding("hello world")

        # Assert
        assert result == [0.1, 0.2, 0.3]

        mock_inference.predict.assert_called_once()
        call_args = mock_inference.predict.call_args

        # Check arguments passed to predict
        assert call_args[0][0] == "test_co"
        assert call_args[0][1] == "text_tool"
        assert call_args[0][2] == {"mode": "text", "text": "hello world"}

    def test_huggingface_wrapper_get_image_embedding_sends_url(self):
        """
        Verify get_image_embedding with URL calls inference_service correctly.
        """
        # Arrange
        mock_inference = MagicMock()
        mock_inference.predict.return_value = {"embedding": [0.9, 0.8], "dimensions": 2}

        wrapper = HuggingFaceClientWrapper(
            client=None,
            model="clip-model",
            inference_service=mock_inference,
            company_short_name="test_co",
            tool_name="visual_tool"
        )

        url = "https://example.com/image.jpg"

        # Act
        result = wrapper.get_image_embedding(presigned_url=url)

        # Assert
        assert result == [0.9, 0.8]
        mock_inference.predict.assert_called_once_with(
            "test_co",
            "visual_tool",
            {"mode": "image", "url": url}
        )

    def test_huggingface_wrapper_get_image_embedding_sends_base64(self):
        """
        Verify get_image_embedding with bytes converts to base64 and calls inference_service.
        """
        # Arrange
        mock_inference = MagicMock()
        mock_inference.predict.return_value = {"embedding": [0.5], "dimensions": 1}

        wrapper = HuggingFaceClientWrapper(
            client=None,
            model="clip-model",
            inference_service=mock_inference,
            company_short_name="test_co",
            tool_name="visual_tool"
        )

        image_bytes = b"fake_image_content"
        expected_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Act
        result = wrapper.get_image_embedding(image_bytes=image_bytes)

        # Assert
        assert result == [0.5]
        mock_inference.predict.assert_called_once_with(
            "test_co",
            "visual_tool",
            {"mode": "image", "base64": expected_b64}
        )

    def test_huggingface_wrapper_raises_if_dependencies_missing(self):
        """Verify wrapper validates required constructor args."""
        with pytest.raises(ValueError, match="requires inference_service"):
            HuggingFaceClientWrapper(
                client=None,
                model="model",
                inference_service=None, # Missing
                company_short_name="co",
                tool_name="tool"
            )

    # --- Service Tests (Provider Agnostic) ---

    def test_service_embed_text_returns_vector(self, mocker):
        """
        Tests that embed_text correctly calls the wrapper's interface and returns a vector.
        """
        # Arrange
        mock_wrapper = MagicMock(spec=EmbeddingClientWrapper)
        mock_wrapper.get_embedding.return_value = self.SAMPLE_VECTOR
        # Mock get_client to return our mock wrapper
        mocker.patch.object(self.client_factory, 'get_client', return_value=mock_wrapper)

        # Act
        result = self.embedding_service.embed_text("any_company", "some text")

        # Assert
        self.client_factory.get_client.assert_called_once_with("any_company", "text")
        mock_wrapper.get_embedding.assert_called_once_with("some text")
        assert result == self.SAMPLE_VECTOR
