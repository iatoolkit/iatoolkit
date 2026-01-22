# tests/services/test_embedding_service.py

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import numpy as np
import base64
from iatoolkit.repositories.models import Company

# Import the classes to be tested, including the new wrappers
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


class TestEmbeddingService:
    """
    Test suite for the EmbeddingService and its dependent EmbeddingClientFactory.
    """

    # --- Test Data ---
    MOCK_CONFIG_HF = {
        'provider': 'huggingface',
        'model': 'hf-model',
        'api_key_name': 'HF_KEY'
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
        Set up a mock ConfigurationService and instantiate the factory and service for each test.
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
                    # Default text config for this company
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

        # Instantiate the classes under test
        self.client_factory = EmbeddingClientFactory(
            config_service=self.mock_config_service,
            call_service=self.mock_call_service)
        self.embedding_service = EmbeddingService(client_factory=self.client_factory,
                                                  profile_repo=self.mock_profile_repo,
                                                  i18n_service=self.mock_i18n_service)

    # --- Factory Tests ---

    def test_factory_creates_huggingface_wrapper(self, mocker):
        """Tests that the factory correctly creates a HuggingFaceClientWrapper."""
        mocker.patch('os.getenv', return_value='fake-hf-key')
        mock_hf_client_class = mocker.patch('iatoolkit.services.embedding_service.InferenceClient')

        # Act
        wrapper = self.client_factory.get_client('company_hf')

        # Assert
        assert isinstance(wrapper, HuggingFaceClientWrapper)
        mock_hf_client_class.assert_called_once_with(model='hf-model', token='fake-hf-key')
        assert wrapper.model == 'hf-model'

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

    def test_factory_get_client_visual_model(self, mocker):
        """Tests that requesting model_type='image' loads the visual configuration."""
        mocker.patch('os.getenv', return_value='fake-openai-key')
        mock_openai_client_class = mocker.patch('iatoolkit.services.embedding_service.OpenAI')

        # Act
        wrapper = self.client_factory.get_client('company_visual', model_type='image')

        # Assert
        # Check that it used the visual config (dimensions=512, model=clip-vit-base)
        assert wrapper.model == 'clip-vit-base'
        assert wrapper.dimensions == 512
        # Should be OpenAI wrapper because provider is 'openai' in MOCK_CONFIG_VISUAL
        assert isinstance(wrapper, OpenAIClientWrapper)

    def test_factory_caching_separates_text_and_image(self, mocker):
        """Tests that the factory caches text and image clients separately."""
        mocker.patch('os.getenv', return_value='fake-key')
        mocker.patch('iatoolkit.services.embedding_service.OpenAI')

        # Act
        wrapper_text = self.client_factory.get_client('company_visual', model_type='text')
        wrapper_image = self.client_factory.get_client('company_visual', model_type='image')

        # Assert
        assert wrapper_text is not wrapper_image
        assert wrapper_text.model == 'openai-model' # From MOCK_CONFIG_OPENAI
        assert wrapper_image.model == 'clip-vit-base' # From MOCK_CONFIG_VISUAL

    def test_factory_raises_error_if_api_key_is_not_set(self, mocker):
        """Tests that a ValueError is raised if the API key environment variable is missing."""
        mocker.patch('os.getenv', return_value=None)
        with pytest.raises(ValueError, match="Environment variable 'HF_KEY' is not set"):
            self.client_factory.get_client('company_hf')

    # --- Service Tests (Provider Agnostic) ---

    def test_service_embed_text_returns_vector(self, mocker):
        """
        Tests that embed_text correctly calls the wrapper's interface and returns a vector.
        """
        # Arrange
        mock_wrapper = MagicMock(spec=EmbeddingClientWrapper)
        mock_wrapper.get_embedding.return_value = self.SAMPLE_VECTOR
        # Mock get_client to return our mock wrapper regardless of args
        mocker.patch.object(self.client_factory, 'get_client', return_value=mock_wrapper)

        # Act
        result = self.embedding_service.embed_text("any_company", "some text")

        # Assert
        self.client_factory.get_client.assert_called_once_with("any_company", "text")
        mock_wrapper.get_embedding.assert_called_once_with("some text")
        assert result == self.SAMPLE_VECTOR

    def test_service_embed_image_returns_vector(self, mocker):
        """
        Tests that embed_image (alias) calls embed_image_from_url and uses get_image_embedding(url).
        """
        # Arrange
        mock_wrapper = MagicMock(spec=EmbeddingClientWrapper)
        mock_wrapper.get_image_embedding.return_value = self.SAMPLE_VECTOR
        mocker.patch.object(self.client_factory, 'get_client', return_value=mock_wrapper)

        presigned_url = "https://example.com/presigned"

        # Act
        result = self.embedding_service.embed_image("any_company", presigned_url)

        # Assert
        self.client_factory.get_client.assert_called_once_with("any_company", model_type="image")
        mock_wrapper.get_image_embedding.assert_called_once_with(presigned_url)
        assert result == self.SAMPLE_VECTOR

    def test_service_embed_image_from_url_returns_vector(self, mocker):
        """
        Tests that embed_image_from_url calls the factory with model_type='image' and uses get_image_embedding(url).
        """
        # Arrange
        mock_wrapper = MagicMock(spec=EmbeddingClientWrapper)
        mock_wrapper.get_image_embedding.return_value = self.SAMPLE_VECTOR
        mocker.patch.object(self.client_factory, 'get_client', return_value=mock_wrapper)

        presigned_url = "https://example.com/presigned"

        # Act
        result = self.embedding_service.embed_image_from_url("any_company", presigned_url)

        # Assert
        self.client_factory.get_client.assert_called_once_with("any_company", model_type="image")
        mock_wrapper.get_image_embedding.assert_called_once_with(presigned_url)
        assert result == self.SAMPLE_VECTOR

    def test_service_embed_image_from_bytes_returns_vector(self, mocker):
        """
        Tests that embed_image_from_bytes calls the factory with model_type='image' and uses get_image_embedding(bytes).
        """
        # Arrange
        mock_wrapper = MagicMock(spec=EmbeddingClientWrapper)
        mock_wrapper.get_image_embedding.return_value = self.SAMPLE_VECTOR
        mocker.patch.object(self.client_factory, 'get_client', return_value=mock_wrapper)

        fake_image_bytes = b'\x89PNG\r\n\x1a\n'

        # Act
        result = self.embedding_service.embed_image_from_bytes("any_company", fake_image_bytes)

        # Assert
        self.client_factory.get_client.assert_called_once_with("any_company", model_type="image")
        mock_wrapper.get_image_embedding.assert_called_once_with(fake_image_bytes)
        assert result == self.SAMPLE_VECTOR

        def test_huggingface_wrapper_get_embedding_flattens_nested_list(self):
            """
            feature_extraction puede devolver [[...]] para batch=1; el wrapper debe aplanar a [...]
            """
        mock_client = MagicMock()
        mock_client.feature_extraction.return_value = [[0.1, 0.2, 0.3]]

        wrapper = HuggingFaceClientWrapper(
            client=mock_client,
            model="any-model",
            dimensions=3,
            endpoint="https://example.com/endpoint",
            api_key="fake-token"
        )

        result = wrapper.get_embedding("hola")

        mock_client.feature_extraction.assert_called_once_with("hola")
        assert result == [0.1, 0.2, 0.3]

    def test_huggingface_wrapper_get_image_embedding_raises_without_endpoint(self):
        mock_client = MagicMock()
        wrapper = HuggingFaceClientWrapper(
            client=mock_client,
            model="any-model",
            dimensions=512,
            endpoint=None,
            api_key="fake-token"
        )

        with pytest.raises(ValueError, match="Missing HuggingFace endpoint URL"):
            wrapper.get_image_embedding("https://example.com/presigned")

    def test_huggingface_wrapper_get_image_embedding_raises_without_token(self, mocker):
        mock_client = MagicMock()
        # asegurar que no exista token fallback en el cliente
        if hasattr(mock_client, "token"):
            delattr(mock_client, "token")

        wrapper = HuggingFaceClientWrapper(
            client=mock_client,
            model="any-model",
            dimensions=512,
            endpoint="https://example.com/endpoint",
            api_key=None
        )

        with pytest.raises(ValueError, match="Missing HuggingFace token"):
            wrapper.get_image_embedding("https://example.com/presigned")

    def test_huggingface_wrapper_get_image_embedding_sends_url_inside_inputs_dict(self, mocker):
        requests_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"embedding": [0.0, 1.0, 2.0], "dimensions": 3}
        requests_post.return_value = mock_resp

        mock_client = MagicMock()
        wrapper = HuggingFaceClientWrapper(
            client=mock_client,
            model="clip",
            dimensions=3,
            endpoint="https://example.com/endpoint",
            api_key="fake-token"
        )

        presigned_url = "https://example.com/presigned"
        result = wrapper.get_image_embedding(presigned_url)

        assert result == [0.0, 1.0, 2.0]

        requests_post.assert_called_once()
        call_kwargs = requests_post.call_args.kwargs
        assert call_kwargs["json"] == {"inputs": {"presigned_url": presigned_url}}
        assert call_kwargs["timeout"] == 60

        headers = call_kwargs["headers"]
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer fake-token"

    def test_huggingface_wrapper_get_image_embedding_sends_bytes_as_base64_in_inputs(self, mocker):
        requests_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"embedding": [0.1, 0.2], "dimensions": 2}
        requests_post.return_value = mock_resp

        mock_client = MagicMock()
        wrapper = HuggingFaceClientWrapper(
            client=mock_client,
            model="clip",
            dimensions=2,
            endpoint="https://example.com/endpoint",
            api_key="fake-token"
        )

        image_bytes = b"\x89PNG\r\n\x1a\n"
        result = wrapper.get_image_embedding(image_bytes)

        assert result == [0.1, 0.2]

        requests_post.assert_called_once()
        call_kwargs = requests_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert "inputs" in payload
        assert isinstance(payload["inputs"], str)
        assert payload["inputs"] != ""  # base64 string

    def test_huggingface_wrapper_get_image_embedding_raises_on_hf_error_payload(self, mocker):
        requests_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "Bad things happened"}
        requests_post.return_value = mock_resp

        wrapper = HuggingFaceClientWrapper(
            client=MagicMock(),
            model="clip",
            dimensions=512,
            endpoint="https://example.com/endpoint",
            api_key="fake-token"
        )

        with pytest.raises(ValueError, match="HuggingFace endpoint error: Bad things happened"):
            wrapper.get_image_embedding("https://example.com/presigned")
