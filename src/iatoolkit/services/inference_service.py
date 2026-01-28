# iatoolkit/services/inference_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import os
import logging
import base64
import uuid
from typing import Optional, Dict, Any
from injector import inject
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.storage_service import StorageService


class InferenceService:
    """
    Service specific for interacting with the custom Hugging Face Inference Endpoint.
    It handles configuration loading per company and manages the HTTP communication.
    """

    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 call_service: CallServiceClient,
                 storage_service: StorageService,
                 i18n_service: I18nService):
        self.config_service = config_service
        self.call_service = call_service
        self.storage_service = storage_service
        self.i18n_service = i18n_service

    def predict(self, company_short_name: str, tool_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
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
        api_key_name = config.get('api_key_name', 'HF_TOKEN')
        model_id = config.get('model_id')
        model_parameters = config.get('model_parameters', {})

        if not endpoint_url:
            raise ValueError(f"Missing 'endpoint_url' for tool '{tool_name}' in company '{company_short_name}'.")

        # 2. Get the API Key
        api_key = os.getenv(api_key_name)
        if not api_key:
            raise ValueError(f"Environment variable '{api_key_name}' is not set.")

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
        logging.info(f"Called inference tool {tool_name} with model {model_id}.")
        response_data = self._call_endpoint(endpoint_url, api_key, payload)

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
        """Helper to safely extract tool configuration from company.yaml."""
        inference_config = self.config_service.get_configuration(company_short_name, 'inference_tools')

        if not inference_config:
            raise ValueError(f"Section 'inference_tools' not found for company '{company_short_name}'.")

        tool_config = inference_config.get(tool_name)
        if not tool_config:
            raise ValueError(f"Tool '{tool_name}' not configured in 'inference_tools' for '{company_short_name}'.")

        return tool_config

    def _call_endpoint(self, url: str, api_key: str, payload: dict) -> Any:
        """Performs the POST request to the HF Endpoint."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp, status = self.call_service.post(
                url,
                json_dict=payload,
                headers=headers,
                timeout=(5, 300.0)
            )

            if status != 200:
                error_msg = f"Inference Endpoint Error {status}"
                if isinstance(resp, dict) and 'error' in resp:
                    error_msg += f": {resp['error']}"
                logging.error(f"{error_msg} | Payload keys: {list(payload.keys())}")
                raise ValueError(error_msg)

            return resp

        except Exception as e:
            logging.error(f"Failed to call inference endpoint: {e}")
            raise