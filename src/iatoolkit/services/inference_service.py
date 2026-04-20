# iatoolkit/services/inference_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import logging
import base64
import time
import uuid
from typing import Optional, Dict, Any
from injector import inject
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.storage_service import StorageService


class InferenceService:
    """
    Service specific for interacting with the custom Hugging Face Inference Endpoint.
    It handles configuration loading per company and manages the HTTP communication.
    """

    DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
    DEFAULT_READ_TIMEOUT_SECONDS = 300.0
    DEFAULT_RETRY_INITIAL_DELAY_SECONDS = 5.0
    DEFAULT_RETRY_MAX_DELAY_SECONDS = 30.0
    RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}

    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 call_service: CallServiceClient,
                 storage_service: StorageService,
                 i18n_service: I18nService,
                 secret_provider: SecretProvider):
        self.config_service = config_service
        self.call_service = call_service
        self.storage_service = storage_service
        self.i18n_service = i18n_service
        self.secret_provider = secret_provider

    def predict(
            self,
            company_short_name: str,
            tool_name: str,
            input_data: Dict[str, Any],
            suppress_error_logging: bool = False
    ) -> Dict[str, Any]:
        """
        Executes an inference task by calling the configured HF endpoint.

        Args:
            company_short_name: The company identifier.
            tool_name: The specific tool key in company.yaml (or the mapping key).
            input_data: The payload required for the model.

        Returns:
            Dict containing the model's response or formatted result.
        """
        # 1. Load configuration for the specific tool
        config = self._get_tool_config(company_short_name, tool_name)

        endpoint_url = config.get('endpoint_url')
        endpoint_url_env = config.get('endpoint_url_env')
        api_key_ref = config.get('api_key_secret_ref') or config.get('api_key_name', 'HF_TOKEN')
        model_id = config.get('model_id')
        model_parameters = config.get('model_parameters', {})
        request_timeout = self._resolve_request_timeout(config)
        retry_budget_seconds = self._resolve_retry_budget_seconds(config)

        if not endpoint_url:
            if endpoint_url_env:
                raise ValueError(
                    f"Missing endpoint URL for tool '{tool_name}' in company '{company_short_name}'. "
                    f"Environment variable '{endpoint_url_env}' is not set."
                )
            raise ValueError(f"Missing 'endpoint_url' for tool '{tool_name}' in company '{company_short_name}'.")

        # 2. Get the API Key
        api_key = resolve_secret(self.secret_provider, company_short_name, api_key_ref)
        if not api_key:
            raise ValueError(f"Secret reference '{api_key_ref}' is not set.")

        # 3. Construct the payload
        payload = {
            "inputs": input_data
        }

        # Optional enrichment
        parameters = {}
        if model_id:
            parameters["model_id"] = model_id

        if model_parameters:
            parameters.update(model_parameters)

        if parameters:
            payload["parameters"] = parameters

        # 4. Execute Call
        logging.debug(f"Called inference tool {tool_name} with model {model_id}.")
        response_data = self._call_endpoint(
            endpoint_url,
            api_key,
            payload,
            suppress_error_logging=suppress_error_logging,
            timeout=request_timeout,
            retry_budget_seconds=retry_budget_seconds,
        )

        # 5. Post-Processing

        # CASO A: Audio Base64 (TTS)
        if isinstance(response_data, dict) and "audio_base64" in response_data:
            try:
                audio_bytes = base64.b64decode(response_data["audio_base64"])
                return self._handle_binary_response(company_short_name, audio_bytes, "audio/wav")
            except Exception as e:
                logging.error(f"Error decoding audio: {e}")
                return {"error": True, "message": "Failed to decode audio."}

        # CASO B: Video Base64 (Text-to-Video)
        if isinstance(response_data, dict) and "video_base64" in response_data:
            try:
                video_bytes = base64.b64decode(response_data["video_base64"])
                return self._handle_binary_response(company_short_name, video_bytes, "video/mp4")
            except Exception as e:
                logging.error(f"Error decoding video: {e}")
                return {"error": True, "message": "Failed to decode video."}

        # CASO C: Imagen Base64 (Text-to-Image)
        if isinstance(response_data, dict) and "image_base64" in response_data:
            try:
                image_bytes = base64.b64decode(response_data["image_base64"])
                return self._handle_binary_response(company_short_name, image_bytes, "image/png")
            except Exception as e:
                logging.error(f"Error decoding image: {e}")
                return {"error": True, "message": "Failed to decode image."}

        return response_data

    def _handle_binary_response(self, company_short_name: str, content: bytes, mime_type: str) -> dict:
        """Sube el contenido binario y retorna la estructura con el HTML tag adecuado."""
        # Determinar extensión y tipo de asset
        ext = ".bin"
        asset_type = "file"

        if "audio" in mime_type:
            ext = ".wav"
            asset_type = "audio"
        elif "video" in mime_type:
            ext = ".mp4"
            asset_type = "video"
        elif "image" in mime_type:  # NUEVO
            ext = ".png"
            asset_type = "image"

        filename = f"generated_{asset_type}_{uuid.uuid4().hex}{ext}"

        try:
            # Subir
            storage_key = self.storage_service.upload_document(
                company_short_name=company_short_name,
                file_content=content,
                filename=filename,
                mime_type=mime_type
            )
            # URL
            url = self.storage_service.generate_presigned_url(company_short_name, storage_key)

            # Generar HTML Snippet dinámico
            html_snippet = ""
            if asset_type == "audio":
                html_snippet = f'<audio controls src="{url}" style="width: 100%; margin-top: 10px;"></audio>'
            elif asset_type == "video":
                html_snippet = f'<video controls src="{url}" style="width: 100%; max-width: 500px; border-radius: 8px; margin-top: 10px;"></video>'
            elif asset_type == "image":
                html_snippet = f'<img src="{url}" alt="Generated Image" style="width: 100%; max-width: 512px; border-radius: 8px; margin-top: 10px;" />'

            return {
                "status": "success",
                "message": f"{asset_type.capitalize()} generated successfully.",
                f"{asset_type}_url": url,
                "html_snippet": html_snippet
            }
        except Exception as e:
            logging.exception(f"Error saving binary response: {e}")
            return {"error": True, "message": "Failed to save generated content."}

    def _get_tool_config(self, company_short_name: str, tool_name: str) -> dict:
        """
        Helper to safely extract and resolve tool configuration from company.yaml.
        It supports shared defaults via inference_tools._defaults and endpoint URL indirection via endpoint_url_env.
        """
        inference_config = self.config_service.get_configuration(company_short_name, 'inference_tools')

        if not inference_config:
            raise ValueError(f"Section 'inference_tools' not found for company '{company_short_name}'.")

        tool_config = inference_config.get(tool_name)
        if not tool_config:
            raise ValueError(f"Tool '{tool_name}' not configured in 'inference_tools' for '{company_short_name}'.")

        defaults = inference_config.get("_defaults") or {}
        if not isinstance(defaults, dict):
            defaults = {}

        if not isinstance(tool_config, dict):
            raise ValueError(
                f"Tool '{tool_name}' config must be a dictionary in 'inference_tools' for '{company_short_name}'."
            )

        resolved_config = {**defaults, **tool_config}

        endpoint_url = (resolved_config.get("endpoint_url") or "").strip()
        if not endpoint_url:
            endpoint_url_secret_ref = (resolved_config.get("endpoint_url_secret_ref") or "").strip()
            if endpoint_url_secret_ref:
                endpoint_url = (
                    resolve_secret(self.secret_provider, company_short_name, endpoint_url_secret_ref, default="") or ""
                ).strip()
        if not endpoint_url:
            endpoint_url_env = (resolved_config.get("endpoint_url_env") or "").strip()
            if endpoint_url_env:
                endpoint_url = (resolve_secret(self.secret_provider, company_short_name, endpoint_url_env, default="") or "").strip()

        if endpoint_url:
            resolved_config["endpoint_url"] = endpoint_url

        return resolved_config

    def _resolve_request_timeout(self, config: dict) -> tuple[float, float]:
        connect_timeout = self._resolve_float_config(
            config,
            "connect_timeout_seconds",
            self.DEFAULT_CONNECT_TIMEOUT_SECONDS,
            minimum=0.1,
        )
        read_timeout = self._resolve_float_config(
            config,
            "read_timeout_seconds",
            self.DEFAULT_READ_TIMEOUT_SECONDS,
            minimum=0.1,
        )
        return connect_timeout, read_timeout

    def _resolve_retry_budget_seconds(self, config: dict) -> float:
        return self._resolve_float_config(
            config,
            "retry_budget_seconds",
            0.0,
            minimum=0.0,
        )

    @staticmethod
    def _resolve_float_config(config: dict, key: str, default: float, *, minimum: float) -> float:
        raw_value = config.get(key, default)
        if raw_value in (None, ""):
            return default

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            logging.warning(
                "Invalid inference config for '%s': expected numeric value, got %r. Using default=%s.",
                key,
                raw_value,
                default,
            )
            return default

        if value < minimum:
            logging.warning(
                "Invalid inference config for '%s': expected >= %s, got %s. Using default=%s.",
                key,
                minimum,
                value,
                default,
            )
            return default

        return value

    def _next_retry_delay(self, *, delay_seconds: float, deadline: float | None) -> float | None:
        if deadline is None:
            return delay_seconds

        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return None

        return min(delay_seconds, remaining_seconds)

    @staticmethod
    def _is_retryable_request_exception(exc: Exception) -> bool:
        return (
            isinstance(exc, IAToolkitException)
            and getattr(exc, "error_type", None) == IAToolkitException.ErrorType.REQUEST_ERROR
        )

    def _log_retry_attempt(
            self,
            *,
            attempt: int,
            delay_seconds: float,
            reason: str,
            suppress_error_logging: bool = False
    ) -> None:
        log_fn = logging.debug if suppress_error_logging else logging.warning
        log_fn(
            "Inference request retry %s scheduled in %.1fs: %s",
            attempt,
            delay_seconds,
            reason,
        )

    def _call_endpoint(
            self,
            url: str,
            api_key: str,
            payload: dict,
            suppress_error_logging: bool = False,
            timeout: tuple[float, float] = (DEFAULT_CONNECT_TIMEOUT_SECONDS, DEFAULT_READ_TIMEOUT_SECONDS),
            retry_budget_seconds: float = 0.0,
    ) -> Any:
        """Performs the POST request to the HF Endpoint."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        deadline = time.monotonic() + retry_budget_seconds if retry_budget_seconds > 0 else None
        attempt = 1
        delay_seconds = self.DEFAULT_RETRY_INITIAL_DELAY_SECONDS

        while True:
            try:
                resp, status = self.call_service.post(
                    url,
                    json_dict=payload,
                    headers=headers,
                    timeout=timeout
                )
            except Exception as exc:
                next_delay = self._next_retry_delay(delay_seconds=delay_seconds, deadline=deadline)
                if self._is_retryable_request_exception(exc) and next_delay is not None:
                    self._log_retry_attempt(
                        attempt=attempt,
                        delay_seconds=next_delay,
                        reason=str(exc),
                        suppress_error_logging=suppress_error_logging,
                    )
                    time.sleep(next_delay)
                    attempt += 1
                    delay_seconds = min(delay_seconds * 2, self.DEFAULT_RETRY_MAX_DELAY_SECONDS)
                    continue

                if not suppress_error_logging:
                    logging.error(f"Failed to call inference endpoint: {exc}")
                raise

            if status == 200:
                return resp

            error_msg = f"Inference Endpoint Error {status}"
            if isinstance(resp, dict) and 'error' in resp:
                error_msg += f": {resp['error']}"

            next_delay = self._next_retry_delay(delay_seconds=delay_seconds, deadline=deadline)
            if status in self.RETRYABLE_STATUS_CODES and next_delay is not None:
                self._log_retry_attempt(
                    attempt=attempt,
                    delay_seconds=next_delay,
                    reason=error_msg,
                    suppress_error_logging=suppress_error_logging,
                )
                time.sleep(next_delay)
                attempt += 1
                delay_seconds = min(delay_seconds * 2, self.DEFAULT_RETRY_MAX_DELAY_SECONDS)
                continue

            if not suppress_error_logging:
                logging.error(f"{error_msg} | Payload keys: {list(payload.keys())}")
                logging.error(f"Failed to call inference endpoint: {error_msg}")
            raise ValueError(error_msg)
