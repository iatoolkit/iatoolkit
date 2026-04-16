from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.inference_service import InferenceService
from iatoolkit.services.storage_service import StorageService


class TestInferenceServiceLogging:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.service = InferenceService(
            config_service=MagicMock(spec=ConfigurationService),
            call_service=MagicMock(spec=CallServiceClient),
            storage_service=MagicMock(spec=StorageService),
            i18n_service=MagicMock(spec=I18nService),
            secret_provider=MagicMock(spec=SecretProvider),
        )

    def test_call_endpoint_suppresses_error_logging_when_requested(self):
        self.service.call_service.post.return_value = ({"error": "503 Service Unavailable"}, 503)

        with patch("iatoolkit.services.inference_service.logging.error") as mock_log_error:
            with pytest.raises(ValueError, match="Inference Endpoint Error 503"):
                self.service._call_endpoint(
                    "https://hf.endpoint",
                    "secret",
                    {"inputs": {"text": "hello"}},
                    suppress_error_logging=True,
                )

        mock_log_error.assert_not_called()

    def test_call_endpoint_keeps_normal_error_logging_by_default(self):
        self.service.call_service.post.return_value = ({"error": "503 Service Unavailable"}, 503)

        with patch("iatoolkit.services.inference_service.logging.error") as mock_log_error:
            with pytest.raises(ValueError, match="Inference Endpoint Error 503"):
                self.service._call_endpoint(
                    "https://hf.endpoint",
                    "secret",
                    {"inputs": {"text": "hello"}},
                )

        assert mock_log_error.call_count == 2
