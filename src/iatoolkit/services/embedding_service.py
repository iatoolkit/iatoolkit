# iatoolkit/services/embedding_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import base64
import io
import numpy as np
from openai import OpenAI
from injector import inject
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.infra.llm_gateway_resolver import LLMGatewayResolver
from iatoolkit.services.inference_service import InferenceService
import logging
import importlib
import inspect
from typing import Union, Optional
from PIL import Image


# Wrapper classes to create a common interface for embedding clients
class EmbeddingClientWrapper:
    """Abstract base class for embedding client wrappers."""
    def __init__(self, client, model: str, dimensions: Optional[int] = None):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def get_embedding(self, text: str, suppress_error_logging: bool = False) -> list[float]:
        """Generates and returns an embedding for the given text."""
        raise NotImplementedError

    def get_embeddings(self, texts: list[str], suppress_error_logging: bool = False) -> list[list[float]]:
        """Embeds several texts, returning one vector per input in the same order.

        The default walks the single-text path so every provider works without
        changes; wrappers whose backend accepts a list override this with one
        request per batch. Callers must not assume a single round trip.
        """
        return [
            self.get_embedding(text, suppress_error_logging=suppress_error_logging)
            for text in texts
        ]

    def supports_batching(self) -> bool:
        """Whether get_embeddings issues one request per batch instead of per text."""
        return False

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

    def get_embedding(self, text: str, suppress_error_logging: bool = False) -> list[float]:
        # Adapt text input to InferenceService payload structure
        input_data = {"mode": "text", "text": text}

        result = self.inference_service.predict(
            self.company_short_name,
            self.tool_name,
            input_data,
            suppress_error_logging=suppress_error_logging,
        )
        return result["embedding"]

    def supports_batching(self) -> bool:
        # Opt-in per tool: an endpoint still running a handler that predates
        # inputs.texts would reject the batch payload, so this stays off until the
        # deployment is confirmed via `supports_batch_embedding: true`.
        return bool(self._tool_config().get("supports_batch_embedding"))

    def _tool_config(self) -> dict:
        try:
            return self.inference_service._get_tool_config(self.company_short_name, self.tool_name) or {}
        except Exception:
            logging.debug("Could not read inference tool config for batching.", exc_info=True)
            return {}

    def get_embeddings(self, texts: list[str], suppress_error_logging: bool = False) -> list[list[float]]:
        if not self.supports_batching():
            return super().get_embeddings(texts, suppress_error_logging=suppress_error_logging)

        result = self.inference_service.predict(
            self.company_short_name,
            self.tool_name,
            {"mode": "text", "texts": list(texts)},
            suppress_error_logging=suppress_error_logging,
        )
        embeddings = result.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            # A silent length mismatch would pair each text with the wrong vector,
            # which no downstream check would catch. Fail instead.
            raise ValueError(
                f"Batch embedding returned {len(embeddings) if isinstance(embeddings, list) else 'no'} "
                f"vectors for {len(texts)} inputs."
            )
        return embeddings

    def get_image_embedding(self,
                            presigned_url: Optional[str] = None,
                            image_bytes: Optional[bytes] = None
                            ) -> list[float]:
        input_data = {"mode": "image"}

        if image_bytes:
            # InferenceService/Handler expects raw base64 string
            normalized_image_bytes = self._normalize_image_bytes(image_bytes)
            b64_data = base64.b64encode(normalized_image_bytes).decode("utf-8")
            input_data["base64"] = b64_data
        elif presigned_url:
            input_data["url"] = presigned_url
        else:
            raise ValueError("Missing image data (presigned_url or image_bytes).")

        result = self.inference_service.predict(
            self.company_short_name,
            self.tool_name,
            input_data
        )
        return result["embedding"]

    def _normalize_image_bytes(self, image_bytes: bytes) -> bytes:
        """
        Convert non-RGB images to RGB before sending them to remote CLIP-like endpoints.
        Falls back to the original bytes if decoding is not possible.
        """
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.mode == "RGB":
                    return image_bytes

                converted = image.convert("RGB")
                buffer = io.BytesIO()
                save_format = image.format or "PNG"
                converted.save(buffer, format=save_format)
                return buffer.getvalue()
        except Exception:
            logging.debug("Could not normalize image bytes before embedding request.", exc_info=True)
            return image_bytes

class OpenAIClientWrapper(EmbeddingClientWrapper):
    def get_embedding(self, text: str, suppress_error_logging: bool = False) -> list[float]:
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

    def supports_batching(self) -> bool:
        return True

    def get_embeddings(self, texts: list[str], suppress_error_logging: bool = False) -> list[list[float]]:
        kwargs = {
            "input": [text.replace("\n", " ") for text in texts],
            "model": self.model,
        }
        if self.dimensions is not None:
            kwargs["dimensions"] = self.dimensions
        response = self.client.embeddings.create(**kwargs)
        # The API documents input order, but pairing the wrong vector to a text is
        # invisible downstream, so sort by index rather than trusting arrival order.
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise ValueError(f"Batch embedding returned {len(ordered)} vectors for {len(texts)} inputs.")
        return [item.embedding for item in ordered]

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

    def get_embedding(self, text: str, suppress_error_logging: bool = False) -> list[float]:
        if hasattr(self.client, 'get_embedding'):
            embedding = self.client.get_embedding(text)
        else:
            raise NotImplementedError(f"Custom class {type(self.client).__name__} must implement 'embed_text' or 'get_embedding'")

        # Normalize output
        if isinstance(embedding, list) and len(embedding) > 0 and isinstance(embedding[0], list):
            return embedding[0]
        return embedding

    def supports_batching(self) -> bool:
        return hasattr(self.client, "get_embeddings")

    def get_embeddings(self, texts: list[str], suppress_error_logging: bool = False) -> list[list[float]]:
        if not self.supports_batching():
            return super().get_embeddings(texts, suppress_error_logging=suppress_error_logging)
        embeddings = self.client.get_embeddings(list(texts))
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError(
                f"Batch embedding returned {len(embeddings) if isinstance(embeddings, list) else 'no'} "
                f"vectors for {len(texts)} inputs."
            )
        return embeddings

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
                 secret_provider: SecretProvider,
                 gateway_resolver: LLMGatewayResolver | None = None):
        self.config_service = config_service
        self.call_service = call_service
        self.inference_service = inference_service
        self.secret_provider = secret_provider
        self.gateway_resolver = gateway_resolver or LLMGatewayResolver(
            configuration_service=config_service,
            secret_provider=secret_provider,
        )
        self._clients = {}  # Cache for storing initialized client wrappers

    @staticmethod
    def _freeze_value(value):
        if isinstance(value, dict):
            return tuple(
                (str(key), EmbeddingClientFactory._freeze_value(item))
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            )
        if isinstance(value, list):
            return tuple(EmbeddingClientFactory._freeze_value(item) for item in value)
        return value

    def _build_cache_key(
        self,
        company_short_name: str,
        model_type: str,
        config_section: str,
        provider: str,
        model: str | None,
        dimensions: Optional[int],
        embedding_config: dict,
        openai_client_config: dict | None = None,
    ) -> tuple:
        cache_payload = {"embedding_config": dict(embedding_config or {})}
        if provider == "openai" and isinstance(openai_client_config, dict):
            cache_payload["openai_client_config"] = {
                "api_key": openai_client_config.get("api_key") or "",
                "base_url": openai_client_config.get("base_url") or "",
                "default_headers": dict(openai_client_config.get("default_headers") or {}),
            }

        return (
            company_short_name,
            model_type,
            config_section,
            provider,
            model or "",
            dimensions,
            self._freeze_value(cache_payload),
        )

    def _drop_stale_cache_entries(self, company_short_name: str, model_type: str, active_cache_key: tuple) -> None:
        stale_keys = [
            key
            for key in self._clients
            if key[:2] == (company_short_name, model_type) and key != active_cache_key
        ]
        for stale_key in stale_keys:
            self._clients.pop(stale_key, None)

    @staticmethod
    def _describe_transport(provider: str, openai_client_config: dict | None = None) -> str:
        if provider != "openai":
            return provider

        base_url = str((openai_client_config or {}).get("base_url") or "").strip().lower()
        if "gateway.ai.cloudflare.com" in base_url:
            return "cloudflare/provider_native"
        if base_url:
            return "custom"
        return "direct"

    def get_client(self, company_short_name: str, model_type: str = 'text') -> EmbeddingClientWrapper:
        """
        Retrieves a configured embedding client wrapper for a specific company.
        If the client is not in the cache, it creates and stores it.
        model_type: 'text' or 'image'
        """
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

        openai_client_config = None
        if provider == 'openai':
            openai_client_config = self._get_openai_client_config(company_short_name, embedding_config)

        cache_key = self._build_cache_key(
            company_short_name=company_short_name,
            model_type=model_type,
            config_section=config_section,
            provider=provider,
            model=model,
            dimensions=dimensions,
            embedding_config=embedding_config,
            openai_client_config=openai_client_config,
        )
        if cache_key in self._clients:
            logging.debug(
                "Reusing embedding client (%s) for '%s' from %s with model: %s provider=%s transport=%s",
                model_type,
                company_short_name,
                config_section,
                model,
                provider,
                self._describe_transport(provider, openai_client_config),
            )
            return self._clients[cache_key]

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
            client = OpenAI(
                api_key=openai_client_config["api_key"],
                base_url=openai_client_config["base_url"] or None,
                default_headers=openai_client_config["default_headers"] or None,
            )
            if not model:
                model='text-embedding-ada-002'
            wrapper = OpenAIClientWrapper(client, model, dimensions)
        else:
            raise NotImplementedError(f"Embedding provider '{provider}' is not implemented.")

        self._drop_stale_cache_entries(company_short_name, model_type, cache_key)
        logging.debug(
            "Embedding client (%s) for '%s' created from %s with model: %s provider=%s transport=%s",
            model_type,
            company_short_name,
            config_section,
            model,
            provider,
            self._describe_transport(provider, openai_client_config),
        )
        self._clients[cache_key] = wrapper
        return wrapper

    def clear_runtime_cache(self, company_short_name: str | None = None):
        if not company_short_name:
            self._clients.clear()
            return

        keys_to_clear = [key for key in self._clients if key[0] == company_short_name]
        for key in keys_to_clear:
            self._clients.pop(key, None)

    def _get_openai_client_config(self, company_short_name: str, embedding_config: dict) -> dict:
        provider_api_key = self._get_api_key_from_config(
            company_short_name,
            embedding_config,
            required=False,
        )
        gateway_transport = self.gateway_resolver.resolve(
            company_short_name=company_short_name,
            provider="openai",
            provider_api_key=provider_api_key,
        )
        if gateway_transport.get("enabled"):
            logging.debug(
                "Embedding gateway enabled for company='%s' provider='openai' vendor='%s' mode='%s' credential_mode='%s' base_url='%s' headers=%s",
                company_short_name,
                gateway_transport.get("vendor"),
                gateway_transport.get("mode"),
                gateway_transport.get("credential_mode"),
                gateway_transport.get("base_url"),
                self._summarize_headers(gateway_transport.get("default_headers")),
            )
            return {
                "api_key": gateway_transport.get("api_key", provider_api_key) or "",
                "base_url": gateway_transport.get("base_url") or "",
                "default_headers": dict(gateway_transport.get("default_headers") or {}),
            }

        resolved_api_key = provider_api_key or self._get_api_key_from_config(
            company_short_name,
            embedding_config,
            required=True,
        )
        return {
            "api_key": resolved_api_key,
            "base_url": "",
            "default_headers": {},
        }

    def _get_api_key_from_config(self, company_short_name: str, embedding_config: dict, *, required: bool = True):
        api_key_ref = embedding_config.get('api_key_secret_ref') or embedding_config.get('api_key_name')
        if not api_key_ref:
            if required:
                raise ValueError("Missing configuration for embedding api_key_secret_ref (or legacy api_key_name).")
            return ""

        api_key = resolve_secret(self.secret_provider, company_short_name, api_key_ref)
        if not api_key:
            if required:
                raise ValueError(f"Secret reference '{api_key_ref}' is not set.")
            return ""

        return api_key

    @staticmethod
    def _summarize_headers(headers: dict | None) -> dict:
        summarized = {}
        for key, value in dict(headers or {}).items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key in {"authorization", "cf-aig-authorization", "x-api-key"}:
                summarized[str(key)] = "<redacted>"
            else:
                summarized[str(key)] = str(value)
        return summarized


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

    def embed_text(
            self,
            company_short_name: str,
            text: str,
            to_base64: bool = False,
            model_type: str = 'text',
            suppress_error_logging: bool = False
    ) -> list[float] | str:
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
            embedding = client_wrapper.get_embedding(text, suppress_error_logging=suppress_error_logging)
            # 3. Process the result
            if to_base64:
                return base64.b64encode(np.array(embedding, dtype=np.float32).tobytes()).decode('utf-8')

            return embedding
        except Exception as e:
            if not suppress_error_logging:
                logging.error(f"Error generating embedding for text: {text[:80]}... - {e}")
            raise

    # Batch defaults: 32 texts is a good round trip for short records, and the
    # character budget guards against a few long findings blowing the payload.
    DEFAULT_EMBED_BATCH_SIZE = 32
    DEFAULT_EMBED_BATCH_MAX_CHARS = 40000

    def embed_texts(
            self,
            company_short_name: str,
            texts: list[str],
            model_type: str = 'text',
            batch_size: Optional[int] = None,
            max_chars_per_batch: Optional[int] = None,
            suppress_error_logging: bool = False,
    ) -> list[list[float]]:
        """Embed many texts, returning one vector per input in the same order.

        Resolves the company and the client once instead of once per text, and
        sends batches when the provider supports them. If a batch fails, its
        texts are retried one by one so a single bad input cannot lose the rest.
        """
        if not texts:
            return []

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise ValueError(self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name))
        client_wrapper = self.client_factory.get_client(company_short_name, model_type)

        size = int(batch_size or self.DEFAULT_EMBED_BATCH_SIZE)
        char_budget = int(max_chars_per_batch or self.DEFAULT_EMBED_BATCH_MAX_CHARS)
        embeddings: list[list[float]] = []
        for batch in self._chunk_texts(texts, size=size, char_budget=char_budget):
            embeddings.extend(
                self._embed_batch(
                    client_wrapper,
                    batch,
                    suppress_error_logging=suppress_error_logging,
                )
            )
        if len(embeddings) != len(texts):
            raise ValueError(f"Embedded {len(embeddings)} vectors for {len(texts)} texts.")
        return embeddings

    def _embed_batch(self, client_wrapper, batch: list[str], *, suppress_error_logging: bool) -> list[list[float]]:
        try:
            return client_wrapper.get_embeddings(batch, suppress_error_logging=suppress_error_logging)
        except Exception as error:
            if len(batch) == 1 or not client_wrapper.supports_batching():
                raise
            logging.warning(
                "Batch embedding of %s texts failed (%s); retrying them individually.",
                len(batch),
                error,
            )
            return [
                client_wrapper.get_embedding(text, suppress_error_logging=suppress_error_logging)
                for text in batch
            ]

    @staticmethod
    def _chunk_texts(texts: list[str], *, size: int, char_budget: int):
        """Split by count and by characters, so a few long texts do not oversize a batch."""
        batch: list[str] = []
        batch_chars = 0
        for text in texts:
            length = len(text or "")
            if batch and (len(batch) >= size or batch_chars + length > char_budget):
                yield batch
                batch, batch_chars = [], 0
            batch.append(text)
            batch_chars += length
        if batch:
            yield batch

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
