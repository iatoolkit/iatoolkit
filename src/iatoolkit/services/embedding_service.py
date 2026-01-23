# iatoolkit/services/embedding_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import os
import base64
import numpy as np
from huggingface_hub import InferenceClient
from openai import OpenAI
from injector import inject
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.call_service import CallServiceClient
import logging
import importlib
import inspect
from typing import Union


# Wrapper classes to create a common interface for embedding clients
class EmbeddingClientWrapper:
    """Abstract base class for embedding client wrappers."""
    def __init__(self, client, model: str, dimensions: int = 1536):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def get_embedding(self, text: str) -> list[float]:
        """Generates and returns an embedding for the given text."""
        raise NotImplementedError

    def get_image_embedding(self, image_input: Union[bytes, str]) -> list[float]:
        """Generates and returns an embedding for the given image (bytes or URL)."""
        raise NotImplementedError(f"Model {self.model} does not support image embeddings")


class HuggingFaceClientWrapper(EmbeddingClientWrapper):
    def __init__(
            self,
            client,
            model: str,
            dimensions: int = 1536,
            endpoint: str | None = None,
            api_key: str | None = None,
            call_service: None = None
    ):
        super().__init__(client, model, dimensions)
        self.endpoint = endpoint
        self.api_key = api_key
        self.call_service = call_service

    def _post_endpoint(self, payload: dict) -> dict:
        if not self.endpoint:
            raise ValueError("Missing HuggingFace endpoint URL (endpoint_url).")
        if not self.call_service:
            raise ValueError("Missing call_service dependency for HuggingFaceClientWrapper.")
        if not self.api_key:
            raise ValueError("Missing HuggingFace token (api_key).")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        resp, status = self.call_service.post(
            self.endpoint,
            json_dict=payload,
            headers=headers,
            timeout=(10, 120.0)
        )

        if status != 200:
            raise ValueError(f"HuggingFace endpoint error {status}: {resp}")

        if not isinstance(resp, dict):
            raise ValueError(f"Unexpected response format: {type(resp)} - {resp}")

        if "error" in resp:
            raise ValueError(f"HuggingFace endpoint error: {resp['error']}")

        if "embedding" not in resp or not isinstance(resp["embedding"], list):
            raise ValueError(f"Unexpected response format: {type(resp)} - {resp}")

        return resp

    def get_embedding(self, text: str) -> list[float]:
        result = self._post_endpoint({"inputs": {"mode": "text", "text": text}})
        embedding = result["embedding"]

        if self.dimensions and len(embedding) != self.dimensions:
            logging.warning(
                f"HuggingFace embedding dimensions mismatch: expected={self.dimensions} got={len(embedding)} model={self.model}"
            )
        return embedding

    def get_image_embedding(self, image_input: Union[bytes, str]) -> list[float]:
        import base64

        if isinstance(image_input, bytes):
            b64_data = base64.b64encode(image_input).decode("utf-8")
            result = self._post_endpoint({"inputs": {"mode": "image", "base64": b64_data}})
            return result["embedding"]

        if isinstance(image_input, str):
            result = self._post_endpoint({"inputs": {"mode": "image", "url": image_input}})
            return result["embedding"]

        raise TypeError(f"Unsupported image_input type: {type(image_input)}")

class OpenAIClientWrapper(EmbeddingClientWrapper):
    def get_embedding(self, text: str) -> list[float]:
        # The OpenAI API expects the input text to be clean
        text = text.replace("\n", " ")
        response = self.client.embeddings.create(input=[text],
                                                 model=self.model,
                                                 dimensions=self.dimensions)
        return response.data[0].embedding

class CustomClassClientWrapper(EmbeddingClientWrapper):
    """
    Adapter for custom embedding classes defined by the user.
    The custom class is expected to implement 'get_embedding(text)'
    and optionally 'get_image_embedding(image_bytes)'.
    """
    def __init__(self, instance, model: str, dimensions: int):
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

    def get_image_embedding(self, image_input: Union[bytes, str]) -> list[float]:
        if hasattr(self.client, 'get_image_embedding'):
            return self.client.get_image_embedding(image_input)
        raise NotImplementedError(f"Custom class {type(self.client).__name__} does not support image embeddings")


# Factory and Service classes
class EmbeddingClientFactory:
    """
    Manages the lifecycle of embedding client wrappers for different companies.
    It ensures that only one client wrapper is created per company, and it is thread-safe.
    """
    @inject
    def __init__(self, config_service: ConfigurationService, call_service: CallServiceClient):
        self.config_service = config_service
        self.call_service = call_service
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
        config_section = 'visual_embedding_provider' if model_type == 'image' else 'embedding_provider'

        # Get the embedding provider and model from the company.yaml
        embedding_config = self.config_service.get_configuration(company_short_name, config_section)
        if not embedding_config:
            raise ValueError(f"{config_section} not configured for company '{company_short_name}'.")

        provider = embedding_config.get('provider')
        if not provider:
            raise ValueError(f"Provider not configured in {config_section} for '{company_short_name}'.")

        model = embedding_config.get('model')
        dimensions = int(embedding_config.get('dimensions', "512" if model_type == 'image' else "1536"))

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
                    init_params['api_key'] = self._get_api_key_from_config(embedding_config)
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
            # api_key validation
            api_key = self._get_api_key_from_config(embedding_config)

            # read the endpoint_url from the config
            endpoint_url = embedding_config.get('endpoint_url')
            wrapper = HuggingFaceClientWrapper(
                client=None,
                model=model,
                dimensions=dimensions,
                endpoint=endpoint_url,
                api_key=api_key,
                call_service=self.call_service
            )
        elif provider == 'openai':
            api_key = self._get_api_key_from_config(embedding_config)

            client = OpenAI(api_key=api_key)
            if not model:
                model='text-embedding-ada-002'
            wrapper = OpenAIClientWrapper(client, model, dimensions)
        else:
            raise NotImplementedError(f"Embedding provider '{provider}' is not implemented.")

        logging.debug(f"Embedding client ({model_type}) for '{company_short_name}' created with model: {model}")
        self._clients[cache_key] = wrapper
        return wrapper

    def _get_api_key_from_config(self, embedding_config: dict):
        api_key_name = embedding_config.get('api_key_name')
        if not api_key_name:
            raise ValueError(f"Missing configuration for {config_section}:api_key_name in config.yaml.")

        api_key = os.getenv(api_key_name)
        if not api_key:
            raise ValueError(f"Environment variable '{api_key_name}' is not set.")

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

    def embed_image_from_url(self, company_short_name: str, presigned_url: str) -> list[float]:
        """
        Embedding para imagen a partir de una URL firmada (ingestions / assets).
        """
        try:
            client_wrapper = self.client_factory.get_client(company_short_name, model_type='image')
            return client_wrapper.get_image_embedding(presigned_url)
        except Exception as e:
            logging.error(f"Error generating embedding for image (url) - {e}")
            raise

    def embed_image_from_bytes(self, company_short_name: str, image_bytes: bytes) -> list[float]:
        """
        Embedding para imagen a partir de bytes (visual search / uploads).
        """
        try:
            client_wrapper = self.client_factory.get_client(company_short_name, model_type='image')
            return client_wrapper.get_image_embedding(image_bytes)
        except Exception as e:
            logging.error(f"Error generating embedding for image (bytes) - {e}")
            raise

    def embed_image(self, company_short_name: str, presigned_url: str) -> list[float]:
        """
        Backwards-compatible alias: conserva la firma anterior (URL).
        """
        return self.embed_image_from_url(company_short_name, presigned_url)


    def get_model_name(self, company_short_name: str, model_type: str = 'text') -> str:
        """
        Helper method to get the model name for a specific company and type.
        """
        # Get the wrapper and return the model name from it
        client_wrapper = self.client_factory.get_client(company_short_name, model_type)
        return client_wrapper.model