# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

import pytest
import json
from unittest.mock import Mock

from sympy.physics.vector.printing import params

from services.api_service import ApiService
from infra.call_service import CallServiceClient
from common.exceptions import IAToolkitException


class TestApiService:

    def setup_method(self, method):
        self.mock_call_service_client = Mock(spec=CallServiceClient)
        self.api_service = ApiService(call_service=self.mock_call_service_client)

        self.test_endpoint = "/v1/test"
        self.success_payload = {"data": "success", "value": 123}
        self.error_payload = {"error": "client error"}
        self.post_kwargs = {"param1": "value1", "param2": 42}

    def test_call_api_get_success(self):
        self.mock_call_service_client.get.return_value = (self.success_payload, 200)

        response_json = self.api_service.call_api(self.test_endpoint, 'get')

        response_data = json.loads(response_json)
        self.mock_call_service_client.get.assert_called_once_with(
            self.test_endpoint,
            params=None,
            headers=None,
            timeout=10)
        assert response_data == self.success_payload

    def test_call_api_post_success(self):
        self.mock_call_service_client.post.return_value = (self.success_payload, 200)
        response_json = self.api_service.call_api(self.test_endpoint, 'post', body=self.post_kwargs)

        response_data = json.loads(response_json)
        self.mock_call_service_client.post.assert_called_once_with(
            headers=None,
            endpoint=self.test_endpoint,
            json_dict=self.post_kwargs,
            params=None,
            timeout=10,
        )
        assert response_data == self.success_payload

    def test_call_api_get_error_status_code(self):
        error_status_code = 400
        self.mock_call_service_client.get.return_value = (self.error_payload, error_status_code)

        with pytest.raises(IAToolkitException) as excinfo:
            self.api_service.call_api(self.test_endpoint, 'get')

        assert excinfo.value.error_type == IAToolkitException.ErrorType.CALL_ERROR
        assert f"API {self.test_endpoint} error: {error_status_code}" in str(excinfo.value)

    def test_call_api_post_error_status_code(self):
        error_status_code = 503
        self.mock_call_service_client.post.return_value = (self.error_payload, error_status_code)

        with pytest.raises(IAToolkitException) as excinfo:
            self.api_service.call_api(self.test_endpoint, 'post', body=self.post_kwargs)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.CALL_ERROR
        assert f"API {self.test_endpoint} error: {error_status_code}" in str(excinfo.value)


    def test_call_api_post_no_kwargs(self):
        self.mock_call_service_client.post.return_value = (self.success_payload, 200)

        response_json = self.api_service.call_api(self.test_endpoint, 'post') # Sin kwargs
        response_data = json.loads(response_json)

        assert response_data == self.success_payload
