# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.exceptions import IAToolkitException
from injector import inject
# call_service.py
import requests
from typing import Optional, Dict, Any, Tuple, Union
from requests import RequestException

class CallServiceClient:
    @inject
    def __init__(self):
        self.headers = {'Content-Type': 'application/json'}

    def _merge_headers(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not extra:
            return dict(self.headers)
        merged = dict(self.headers)
        merged.update(extra)
        return merged

    def _normalize_timeout(self, timeout: Union[int, float, Tuple[int, int], Tuple[float, float]]) -> Tuple[float, float]:
        # Si pasan un solo número → (connect, read) = (10, timeout)
        if isinstance(timeout, (int, float)):
            return (10, float(timeout))
        return (float(timeout[0]), float(timeout[1]))

    def _deserialize_response(self, response) -> Tuple[Any, int]:
        try:
            return response.json(), response.status_code
        except ValueError:
            # No es JSON → devolver texto
            return response.text, response.status_code

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float, Tuple[int, int]] = 10,
        allow_redirects: Optional[bool] = None,
    ):
        try:
            request_kwargs = {
                "params": params,
                "headers": self._merge_headers(headers),
                "timeout": self._normalize_timeout(timeout),
            }
            if allow_redirects is not None:
                request_kwargs["allow_redirects"] = allow_redirects
            response = requests.get(endpoint, **request_kwargs)
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))
        return self._deserialize_response(response)

    def post(
            self,
            endpoint: str,
            json_dict: Optional[Dict[str, Any]] = None,
            data: Any = None,  # Nuevo argumento para datos crudos/binarios
            params: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout: Union[int, float, Tuple[int, int]] = 10,
            allow_redirects: Optional[bool] = None,
    ):
        try:
            request_kwargs = {
                "params": params,
                "json": json_dict,
                "data": data,  # Pasamos data a requests
                "headers": self._merge_headers(headers),
                "timeout": self._normalize_timeout(timeout),
            }
            if allow_redirects is not None:
                request_kwargs["allow_redirects"] = allow_redirects
            response = requests.post(endpoint, **request_kwargs)
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))

        return self._deserialize_response(response)

    def put(
        self,
        endpoint: str,
        json_dict: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float, Tuple[int, int]] = 10,
        allow_redirects: Optional[bool] = None,
    ):
        try:
            request_kwargs = {
                "params": params,
                "json": json_dict,
                "headers": self._merge_headers(headers),
                "timeout": self._normalize_timeout(timeout),
            }
            if allow_redirects is not None:
                request_kwargs["allow_redirects"] = allow_redirects
            response = requests.put(endpoint, **request_kwargs)
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))
        return self._deserialize_response(response)

    def delete(
        self,
        endpoint: str,
        json_dict: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float, Tuple[int, int]] = 10,
        allow_redirects: Optional[bool] = None,
    ):
        try:
            request_kwargs = {
                "params": params,
                "json": json_dict,
                "headers": self._merge_headers(headers),
                "timeout": self._normalize_timeout(timeout),
            }
            if allow_redirects is not None:
                request_kwargs["allow_redirects"] = allow_redirects
            response = requests.delete(endpoint, **request_kwargs)
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))
        return self._deserialize_response(response)

    def patch(
        self,
        endpoint: str,
        json_dict: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float, Tuple[int, int]] = 10,
        allow_redirects: Optional[bool] = None,
    ):
        try:
            request_kwargs = {
                "params": params,
                "json": json_dict,
                "headers": self._merge_headers(headers),
                "timeout": self._normalize_timeout(timeout),
            }
            if allow_redirects is not None:
                request_kwargs["allow_redirects"] = allow_redirects
            response = requests.patch(endpoint, **request_kwargs)
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))
        return self._deserialize_response(response)

    def post_files(
        self,
        endpoint: str,
        data: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Union[int, float, Tuple[int, int]] = 10
    ):
        # Para multipart/form-data no imponemos Content-Type por defecto
        merged_headers = dict(self.headers)
        merged_headers.pop('Content-Type', None)
        if headers:
            merged_headers.update(headers)

        try:
            response = requests.post(
                endpoint,
                params=params,
                files=data,
                headers=merged_headers,
                timeout=self._normalize_timeout(timeout)
            )
        except RequestException as e:
            raise IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, str(e))
        return self._deserialize_response(response)
