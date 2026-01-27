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

    def predict(self, company_short_name: str, tool_name: str, input_data: Dict[str, Any], execution_config: dict = None) -> Dict[str, Any]:
        """
        Executes an inference task by calling the configured HF endpoint.

        Args:
            company_short_name: The company identifier.
            tool_name: The specific tool key in company.yaml (or the mapping key).
            input_data: The payload required for the model.
            execution_config: Metadata from the tool definition (e.g. {'method_name': 'vibe_voice'}).

        Returns:
            Dict containing the model's response or formatted result.
        """
        # 0. Resolver el nombre real de la configuración
        # Si execution_config tiene un 'method_name', úsalo como clave para buscar en el YAML.
        # Esto es útil si el nombre de la tool en el LLM difiere de la clave en inference_tools,
        # aunque por defecto suelen ser iguales.
        config_key = tool_name
        if execution_config and 'method_name' in execution_config:
            config_key = execution_config['method_name']

        # 1. Load configuration for the specific tool
        config = self._get_tool_config(company_short_name, config_key)

        endpoint_url = config.get('endpoint_url')
        api_key_name = config.get('api_key_name', 'HF_TOKEN')
        model_id = config.get('model_id')
        model_parameters = config.get('model_parameters', {})

        if not endpoint_url:
            raise ValueError(f"Missing 'endpoint_url' for tool '{config_key}' in company '{company_short_name}'.")

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
        response_data = self._call_endpoint(endpoint_url, api_key, payload)

        # 5. Post-Processing for Audio

        # CASO A: Bytes puros (si HF decidiera devolver raw bytes, poco común en custom handlers json)
        if isinstance(response_data, bytes):
            return self._handle_binary_response(company_short_name, response_data, "audio/flac")

        # CASO B: JSON con base64 (Estándar para Custom Handlers)
        if isinstance(response_data, dict) and "audio_base64" in response_data:
            try:
                audio_bytes = base64.b64decode(response_data["audio_base64"])
                # El handler usa wavfile.write, así que es WAV
                return self._handle_binary_response(company_short_name, audio_bytes, "audio/wav")
            except Exception as e:
                logging.error(f"Error decoding base64 audio: {e}")
                return {"error": True, "message": "Failed to decode audio from inference response."}

        return response_data

    def _handle_binary_response(self, company_short_name: str, content: bytes, mime_type: str) -> dict:
        """Sube el contenido binario al storage y retorna una estructura para el LLM."""
        filename = f"generated_audio_{uuid.uuid4().hex}.flac"

        try:
            # Subir usando StorageService
            storage_key = self.storage_service.upload_document(
                company_short_name=company_short_name,
                file_content=content,
                filename=filename,
                mime_type=mime_type
            )

            # Generar URL firmada
            url = self.storage_service.generate_presigned_url(company_short_name, storage_key)

            # Retornar respuesta estructurada para el LLM
            # Incluimos un snippet HTML para que el frontend pueda renderizarlo si el LLM decide mostrarlo.
            return {
                "status": "success",
                "message": "Audio generated successfully.",
                "audio_url": url,
                "html_snippet": f'<audio controls src="{url}" style="width: 100%; margin-top: 10px;"></audio>'
            }
        except Exception as e:
            logging.exception(f"Error handling binary response for {company_short_name}: {e}")
            return {"error": True, "message": "Failed to save generated audio."}

    def _get_tool_config(self, company_short_name: str, tool_name: str) -> dict:
        """Helper to safely extract tool configuration from company.yaml."""
        inference_config = self.config_service.get_configuration(company_short_name, 'inference_tools')

        if not inference_config:
            raise ValueError(f"Section 'inference_tools' not found for company '{company_short_name}'.")

        tool_config = inference_config.get(tool_name)
        if not tool_config:
            # Fallback: intentar buscar en _defaults o retornar error
            raise ValueError(f"Tool '{tool_name}' not configured in 'inference_tools' for '{company_short_name}'.")

        return tool_config

    def _call_endpoint(self, url: str, api_key: str, payload: dict) -> Any:
        """Performs the POST request to the HF Endpoint."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            # NOTA: Usamos call_service.post. Dependiendo de la implementación de call_service,
            # este podría intentar decodificar JSON automáticamente.
            # Si call_service falla con respuestas binarias, deberíamos usar requests.post directamente aquí
            # o asegurar que call_service maneje content-types no-json.
            resp, status = self.call_service.post(
                url,
                json_dict=payload,
                headers=headers,
                timeout=(5, 60.0) # 5s connect, 60s read (models can be slow)
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