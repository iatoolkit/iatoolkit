# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from infra.call_service import CallServiceClient
from injector import inject
from common.exceptions import IAToolkitException
import json
from typing import Optional, Dict, Any, Union

class ApiService:
    @inject
    def __init__(self, call_service: CallServiceClient):
        self.call_service = call_service

    def call_api(
        self,
        endpoint: str,
        method: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Union[str, int, float, bool]]] = None,
        body: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Union[int, float, tuple] = 10
    ) -> str:
        """
        Ejecuta una llamada HTTP genérica.

        - endpoint: URL completa
        - method: GET | POST | PUT | DELETE (case-insensitive)
        - headers: dict opcional de cabeceras
        - params: dict opcional de query string
        - body: dict opcional para JSON (POST/PUT/DELETE)
        - files: dict opcional para multipart/form-data (prioriza POST files)
        - timeout: segundos (int/float) o tuple (connect, read)
        """
        m = (method or "").strip().lower()

        if m == "get":
            response, status_code = self.call_service.get(
                endpoint, params=params, headers=headers, timeout=timeout
            )
        elif m == "post":
            # Si vienen files → multipart; si no → JSON
            if files:
                response, status_code = self.call_service.post_files(
                    endpoint, data=files, params=params, headers=headers, timeout=timeout
                )
            else:
                response, status_code = self.call_service.post(
                    endpoint=endpoint, json_dict=body, params=params, headers=headers, timeout=timeout
                )
        elif m == "put":
            response, status_code = self.call_service.put(
                endpoint, json_dict=body, params=params, headers=headers, timeout=timeout
            )
        elif m == "delete":
            response, status_code = self.call_service.delete(
                endpoint, json_dict=body, params=params, headers=headers, timeout=timeout
            )
        else:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"API error: método '{method}' no soportado"
            )

        if status_code < 200 or status_code >= 300:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CALL_ERROR,
                f"API {endpoint} error: {status_code}"
            )

        # Normalizamos a string JSON (para que el LLM lo consuma consistente)
        return json.dumps(response)
