# iatoolkit/services/embedding_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import base64
import numpy as np
from openai import OpenAI
from injector import inject
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.inference_service import InferenceService
import logging
import importlib
import inspect
from typing import Union, Optional


# Wrapper classes to create a common interface for embedding clients
class EmbeddingClientWrapper:
    """Abstract base class for embedding client wrappers."""
    def __init__(self, client, model: str, dimensions: Optional[int] = None):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def get_embedding(self, text: str) -> list[float]:
        """Generates and returns an embedding for the given text."""
        raise NotImplementedError

    def get_image_embedding(self,
                            presigned_url: Optional[str] = None,
                            image_bytes: Optional[bytes] = None
                            ) -> list[float]:
        """Generates and returns an embedding for the given image (bytes or URL)."""
        raise NotImplementedError(f"Model {self.model} does not support image embeddings")

class HuggingFaceClientWrapper(EmbeddingClientWrapper):
    def __init__(
            self,
            client,
            model: str,
            dimensions: Optional[int] = None,
            inference_service: InferenceService = None,
            company_short_name: str = None,
            tool_name: str = None
    ):
        super().__init__(client, model, dimensions)
        self.inference_service = inference_service
        self.company_short_name = company_short_name
        self.tool_name = tool_name

        if not self.inference_service or not self.company_short_name or not self.tool_name:
            raise ValueError("HuggingFaceClientWrapper requires inference_service, company_short_name, and tool_name.")

    def get_embedding(self, text: str) -> list[float]:
        # Adapt text input to InferenceService payload structure
        input_data = {"mode": "text", "text": text}

        result = self.inference_service.predict(
            self.company_short_name,
            self.tool_name,
            input_data
        )
        return result["embedding"]

    def get_image_embedding(self,
                            presigned_url: Optional[str] = None,
                            image_bytes: Optional[bytes] = None
                            ) -> list[float]:
        input_data = {"mode": "image"}

        if presigned_url:
            input_data["url"] = presigned_url
        elif image_bytes:
            # InferenceService/Handler expects raw base64 string
            b64_data = base64.b64encode(image_bytes).decode("utf-8")
            input_data["base64"] = b64_data
        else:
            raise ValueError("Missing image data (presigned_url or image_bytes).")

        result = self.inference_service.predict(
            self.company_short_name,
            self.tool_name,
            input_data
        )
        return result["embedding"]

class OpenAIClientWrapper(EmbeddingClientWrapper):
    def get_embedding(self, text: str) -> list[float]:
        # The OpenAI API expects the input text to be clean
        text = text.replace("\n", " ")

        # Prepare arguments, passing dimensions only if explicitly set
        kwargs = {
            "input": [text],
            "model": self.model
        }
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions

        response = self.client.embeddings.create(**kwargs)
        return response.data[0].embedding

class CustomClassClientWrapper(EmbeddingClientWrapper):
    """
    Adapter for custom embedding classes defined by the user.
    The custom class is expected to implement 'get_embedding(text)'
    and optionally 'get_image_embedding()'.
    """
    def __init__(self, instance, model: str, dimensions: Optional[int] = None):
        super().__init__(instance, model, dimensions)
        # We assume the instance has methods compatible with our needs
        # or we adapt them here. For simplicity, we assume Duck Typing.

    def get_embedding(self, text: str) -> list[float]:
        if hasattr(self.client, 'get_embedding'):
            embedding = self.client.get_embedding(text)
        else:
            raise NotImplementedError(f"Custom class {type(self.client).__name__} must implement 'embed_text' or 'get_embedding'")

        # Normalize output
        if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
            return embedding[0]
        return embedding

    def get_image_embedding(self,
                            presigned_url: Optional[str] = None,
                            image_bytes: Optional[bytes] = None
                            ) -> list[float]:
        return self.client.get_image_embedding(presigned_url, image_bytes)


# Factory and Service classes
class EmbeddingClientFactory:
    """
    Manages the lifecycle of embedding client wrappers for different companies.
    It ensures that only one client wrapper is created per company, and it is thread-safe.
    """
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 call_service: CallServiceClient,
                 inference_service: InferenceService,
                 secret_provider: SecretProvider):
        self.config_service = config_service
        self.call_service = call_service
        self.inference_service = inference_service
        self.secret_provider = secret_provider
        self._clients = {}  # Cache for storing initialized client wrappers

    def get_client(self, company_short_name: str, model_type: str = 'text') -> EmbeddingClientWrapper:
        """
        Retrieves a configured embedding client wrapper for a specific company.
        If the client is not in the cache, it creates and stores it.
        model_type: 'text' or 'image'
        """
        cache_key = (company_short_name, model_type)
        if cache_key in self._clients:
            return self._clients[cache_key]

        # Determine config section based on model type
        config_section = 'visual_embedding_provider' if model_type in ['image', 'image_query'] else 'embedding_provider'

        # Get the embedding provider and model from the company.yaml
        embedding_config = self.config_service.get_configuration(company_short_name, config_section)
        if not embedding_config:
            raise ValueError(f"{config_section} not configured for company '{company_short_name}'.")

        provider = embedding_config.get('provider')
        if not provider:
            raise ValueError(f"Provider not configured in {config_section} for '{company_short_name}'.")

        model = embedding_config.get('model')

        # Dimensions are optional. If not present, we let the provider/model decide defaults.
        dimensions = embedding_config.get('dimensions')
        if dimensions is not None:
            dimensions = int(dimensions)

        # Extract class path if provider is custom
        class_path = embedding_config.get('class_path')

        # Logic to handle multiple providers
        wrapper = None
        if provider == 'custom_class':
            if not class_path:
                raise ValueError(f"Missing 'class_path' for custom_class provider in {config_section}")

            try:
                # Dynamic Import Logic
                module_name, class_name = class_path.rsplit('.', 1)
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)

                # Get optional init parameters
                init_params = embedding_config.get('init_params', {})

                # auto-inject dependencies based on the constructor signature
                sig = inspect.signature(cls.__init__)
                params = sig.parameters

                if 'api_key' in params:
                    init_params['api_key'] = self._get_api_key_from_config(company_short_name, embedding_config)
                if 'call_service' in params:
                    init_params['call_service'] = self.call_service
                if 'model' in params and 'model' not in init_params:
                    init_params['model'] = model

                # Instantiate the custom class
                instance = cls(**init_params)

                wrapper = CustomClassClientWrapper(instance, model, dimensions)
                logging.info(f"Loaded custom embedding provider: {class_name}")

            except (ImportError, AttributeError) as e:
                raise ValueError(f"Could not import custom provider class '{class_path}': {e}")
            except Exception as e:
                raise ValueError(f"Error initializing custom provider '{class_path}': {e}")

        elif provider == 'huggingface':
            # NEW: Use InferenceService logic
            # We need to know which tool to call in inference_tools.
            # We look for 'tool_name' in the embedding config.
            # Default fallback could be implied from context but explicit is better.
            tool_name = embedding_config.get('tool_name')
            if not tool_name:
                # Fallback: if no tool_name, we can't use InferenceService effectively
                # unless we assume 'text_embeddings' or 'clip_embeddings' based on model_type
                if model_type in ['image', 'image_query']:
                    tool_name = 'clip_embeddings'
                else:
                    tool_name = 'text_embeddings'

                logging.warning(f"No 'tool_name' found in {config_section} for '{company_short_name}'. Defaulting to '{tool_name}'.")

            wrapper = HuggingFaceClientWrapper(
                client=None,
                model=model,
                dimensions=dimensions,
                inference_service=self.inference_service,
                company_short_name=company_short_name,
                tool_name=tool_name
            )

        elif provider == 'openai':
            api_key = self._get_api_key_from_config(company_short_name, embedding_config)

            client = OpenAI(api_key=api_key)
            if not model:
                model='text-embedding-ada-002'
            wrapper = OpenAIClientWrapper(client, model, dimensions)
        else:
            raise NotImplementedError(f"Embedding provider '{provider}' is not implemented.")

        logging.debug(f"Embedding client ({model_type}) for '{company_short_name}' created with model: {model}")
        self._clients[cache_key] = wrapper
        return wrapper

    def clear_runtime_cache(self, company_short_name: str | None = None):
        if not company_short_name:
            self._clients.clear()
            return

        keys_to_clear = [key for key in self._clients if key[0] == company_short_name]
        for key in keys_to_clear:
            self._clients.pop(key, None)

    def _get_api_key_from_config(self, company_short_name: str, embedding_config: dict):
        api_key_ref = embedding_config.get('api_key_secret_ref') or embedding_config.get('api_key_name')
        if not api_key_ref:
            raise ValueError("Missing configuration for embedding api_key_secret_ref (or legacy api_key_name).")

        api_key = resolve_secret(self.secret_provider, company_short_name, api_key_ref)
        if not api_key:
            raise ValueError(f"Secret reference '{api_key_ref}' is not set.")

        return api_key


class EmbeddingService:
    """
    A stateless service for generating text embeddings.
    It relies on the EmbeddingClientFactory to get the correct,
    company-specific embedding client on demand.
    """
    @inject
    def __init__(self,
                 client_factory: EmbeddingClientFactory,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService):
        self.client_factory = client_factory
        self.i18n_service = i18n_service
        self.profile_repo = profile_repo

    def embed_text(self, company_short_name: str, text: str, to_base64: bool = False, model_type: str = 'text') -> list[float] | str:
        """
        Generates the embedding for a given text using the appropriate company model.
        model_type: 'text' (default) or 'image_query' (for CLIP-like text encoders)
        """
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                raise ValueError(self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name))

            # 1. Get the correct client wrapper from the factory based on model_type
            client_wrapper = self.client_factory.get_client(company_short_name, model_type)

            # 2. Use the wrapper's common interface to get the embedding
            embedding = client_wrapper.get_embedding(text)
            # 3. Process the result
            if to_base64:
                return base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode('utf-8')

            return embedding
        except Exception as e:
            logging.error(f"Error generating embedding for text: {text[:80]}... - {e}")
            raise

    def embed_image(self, company_short_name: str,
                    presigned_url: Optional[str] = None,
                    image_bytes: Optional[bytes] = None) -> list[float]:
        try:
            client_wrapper = self.client_factory.get_client(company_short_name, model_type='image')
            return client_wrapper.get_image_embedding(presigned_url, image_bytes)
        except Exception as e:
            logging.error(f"Error generating embedding for image (url) - {e}")
            raise


    def get_model_name(self, company_short_name: str, model_type: str = 'text') -> str:
        """
        Helper method to get the model name for a specific company and type.
        """
        # Get the wrapper and return the model name from it
        client_wrapper = self.client_factory.get_client(company_short_name, model_type)
        return client_wrapper.model
