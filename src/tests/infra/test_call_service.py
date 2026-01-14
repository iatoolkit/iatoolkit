# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import patch, MagicMock
from iatoolkit.infra.call_service import CallServiceClient
from requests import RequestException
from iatoolkit.common.exceptions import IAToolkitException


class TestCallServiceClient:

    def setup_method(self):
        self.client = CallServiceClient()
        self.endpoint = "http://fake-endpoint.com/api/test"
        self.mock_response = MagicMock()
        self.mock_response.json.return_value = {'result': 'ok'}
        self.mock_response.status_code = 200

        # Patch 'requests' methods
        self.get_patcher = patch('iatoolkit.infra.call_service.requests.get', return_value=self.mock_response)
        self.post_patcher = patch('iatoolkit.infra.call_service.requests.post', return_value=self.mock_response)
        self.put_patcher = patch('iatoolkit.infra.call_service.requests.put', return_value=self.mock_response)
        self.patch_patcher = patch('iatoolkit.infra.call_service.requests.patch', return_value=self.mock_response)
        self.delete_patcher = patch('iatoolkit.infra.call_service.requests.delete', return_value=self.mock_response)

        # Start patching
        self.mock_get = self.get_patcher.start()
        self.mock_post = self.post_patcher.start()
        self.mock_put = self.put_patcher.start()
        self.mock_patch = self.patch_patcher.start()
        self.mock_delete = self.delete_patcher.start()

    def teardown_method(self):
        patch.stopall()

    def test_get_success(self):
        response, status = self.client.get(self.endpoint)
        self.mock_get.assert_called_once_with(self.endpoint,
                                              headers= {'Content-Type': 'application/json'},
                                              params=None, timeout=(10, 10.0))
        assert status == 200
        assert response == {'result': 'ok'}

    def test_get_failure(self):
        self.mock_get.side_effect = RequestException("Failed GET")

        with pytest.raises(IAToolkitException) as exc_info:
            self.client.get(self.endpoint)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_post_success(self):
        json_dict = {'key': 'value'}
        response, status = self.client.post(self.endpoint, json_dict)
        self.mock_post.assert_called_once_with(self.endpoint,
                                               params=None,
                                               json=json_dict,
                                               headers=self.client.headers,
                                               data=None,
                                               timeout=(10, 10.0))
        assert status == 200
        assert response == {'result': 'ok'}

    def test_post_failure(self):
        self.mock_post.side_effect = RequestException("Failed POST")

        with pytest.raises(IAToolkitException) as exc_info:
            self.client.post(self.endpoint, {'data': 'test'})

        assert exc_info.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_put_success(self):
        json_dict = {'key': 'updated'}
        response, status = self.client.put(self.endpoint, json_dict)
        assert status == 200
        assert response == {'result': 'ok'}


    def test_delete_success(self):
        json_dict = {'key': 'deleted'}
        response, status = self.client.delete(self.endpoint, json_dict)

        assert status == 200
        assert response == {'result': 'ok'}

    def test_post_files_success(self):
        files = {'file': ('filename.txt', 'filecontent')}
        response, status = self.client.post_files(self.endpoint, files)
        assert status == 200
        assert response == {'result': 'ok'}

