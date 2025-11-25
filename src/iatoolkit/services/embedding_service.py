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
import logging


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

class HuggingFaceClientWrapper(EmbeddingClientWrapper):
    def get_embedding(self, text: str) -> list[float]:
        embedding = self.client.feature_extraction(text)
        # Ensure the output is a flat list of floats
        if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
            return embedding[0]
        return embedding

class OpenAIClientWrapper(EmbeddingClientWrapper):
    def get_embedding(self, text: str) -> list[float]:
        # The OpenAI API expects the input text to be clean
        text = text.replace("\n", " ")
        response = self.client.embeddings.create(input=[text],
                                                 model=self.model,
                                                 dimensions=self.dimensions)
        return response.data[0].embedding

# Factory and Service classes
class EmbeddingClientFactory:
    """
    Manages the lifecycle of embedding client wrappers for different companies.
    It ensures that only one client wrapper is created per company, and it is thread-safe.
    """
    @inject
    def __init__(self, config_service: ConfigurationService):
        self.config_service = config_service
        self._clients = {}  # Cache for storing initialized client wrappers

    def get_client(self, company_short_name: str) -> EmbeddingClientWrapper:
        """
        Retrieves a configured embedding client wrapper for a specific company.
        If the client is not in the cache, it creates and stores it.
        """
        if company_short_name in self._clients:
            return self._clients[company_short_name]

        # Get the embedding provider and model from the company.yaml
        embedding_config = self.config_service.get_configuration(company_short_name, 'embedding_provider')
        if not embedding_config:
            raise ValueError(f"Embedding provider not configured for company '{company_short_name}'.")

        provider = embedding_config.get('provider')
        if not provider:
            raise ValueError(f"Embedding provider not configured for company '{company_short_name}'.")
        model = embedding_config.get('model')
        dimensions = int(embedding_config.get('dimensions', "1536"))

        api_key_name = embedding_config.get('api_key_name')
        if not api_key_name:
            raise ValueError(f"Missiong configuration for embedding_provider:api_key_name en config.yaml.")

        api_key = os.getenv(api_key_name)
        if not api_key:
            raise ValueError(f"Environment variable '{api_key_name}' is not set.")

        # Logic to handle multiple providers
        wrapper = None
        if provider == 'huggingface':
            if not model:
                model='sentence-transformers/all-MiniLM-L6-v2'
            client = InferenceClient(model=model, token=api_key)
            wrapper = HuggingFaceClientWrapper(client, model, dimensions)
        elif provider == 'openai':
            client = OpenAI(api_key=api_key)
            if not model:
                model='text-embedding-ada-002'
            wrapper = OpenAIClientWrapper(client, model, dimensions)
        else:
            raise NotImplementedError(f"Embedding provider '{provider}' is not implemented.")

        logging.debug(f"Embedding client for '{company_short_name}' created with model: {model} via {provider}")
        self._clients[company_short_name] = wrapper
        return wrapper

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


    def embed_text(self, company_short_name: str, text: str, to_base64: bool = False) -> list[float] | str:
        """
        Generates the embedding for a given text using the appropriate company model.
        """
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                raise ValueError(self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name))

            # 1. Get the correct client wrapper from the factory
            client_wrapper = self.client_factory.get_client(company_short_name)

            # 2. Use the wrapper's common interface to get the embedding
            embedding = client_wrapper.get_embedding(text)
            # 3. Process the result
            if to_base64:
                return base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode('utf-8')

            return embedding
        except Exception as e:
            logging.error(f"Error generating embedding for text: {text[:80]}... - {e}")
            raise

    def get_model_name(self, company_short_name: str) -> str:
        """
        Helper method to get the model name for a specific company.
        """
        # Get the wrapper and return the model name from it
        client_wrapper = self.client_factory.get_client(company_short_name)
        return client_wrapper.model