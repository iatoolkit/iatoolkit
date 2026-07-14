import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.inference_service import InferenceService
from iatoolkit.common.interfaces.secret_provider import SecretProvider


class TestInferenceServiceConfigResolution:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_call_service = MagicMock(spec=CallServiceClient)
        self.mock_storage_service = MagicMock(spec=StorageService)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_secret_provider = MagicMock(spec=SecretProvider)

        self.service = InferenceService(
            config_service=self.mock_config_service,
            call_service=self.mock_call_service,
            storage_service=self.mock_storage_service,
            i18n_service=self.mock_i18n_service,
            secret_provider=self.mock_secret_provider,
        )

    def test_get_tool_config_merges_defaults(self):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }

        cfg = self.service._get_tool_config("acme", "text_embeddings")

        assert cfg["endpoint_url"] == "https://hf.endpoint"
        assert cfg["api_key_name"] == "HF_TOKEN"
        assert cfg["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"

    def test_get_tool_config_resolves_endpoint_url_env(self):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url_env": "HF_INFERENCE_ENDPOINT_URL",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }
        self.mock_secret_provider.get_secret.return_value = "https://env.endpoint"

        cfg = self.service._get_tool_config("acme", "text_embeddings")

        assert cfg["endpoint_url"] == "https://env.endpoint"
        assert cfg["endpoint_url_env"] == "HF_INFERENCE_ENDPOINT_URL"
        assert cfg["api_key_name"] == "HF_TOKEN"

    def test_predict_uses_defaults_and_endpoint_url_env(self):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url_env": "HF_INFERENCE_ENDPOINT_URL",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }
        self.mock_call_service.post.return_value = ({"ok": True}, 200)
        self.mock_secret_provider.get_secret.side_effect = (
            lambda _company, name, default=None: {
                "HF_INFERENCE_ENDPOINT_URL": "https://env.endpoint",
                "HF_TOKEN": "super-secret-token",
            }.get(name, default)
        )

        result = self.service.predict(
            company_short_name="acme",
            tool_name="text_embeddings",
            input_data={"mode": "text", "text": "hello"},
        )

        assert result == {"ok": True}
        self.mock_call_service.post.assert_called_once_with(
            "https://env.endpoint",
            json_dict={
                "inputs": {"mode": "text", "text": "hello"},
                "parameters": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
            },
            headers={
                "Authorization": "Bearer super-secret-token",
                "Content-Type": "application/json",
            },
            timeout=(5, 300.0),
        )

    def test_predict_raises_when_endpoint_env_is_missing(self):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url_env": "HF_INFERENCE_ENDPOINT_URL",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }
        self.mock_secret_provider.get_secret.return_value = None

        with pytest.raises(ValueError, match="HF_INFERENCE_ENDPOINT_URL"):
            self.service.predict(
                company_short_name="acme",
                tool_name="text_embeddings",
                input_data={"mode": "text", "text": "hello"},
            )

    def test_predict_uses_configured_request_timeouts(self):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "connect_timeout_seconds": 7,
                "read_timeout_seconds": 45,
            },
        }
        self.mock_call_service.post.return_value = ({"ok": True}, 200)
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"

        result = self.service.predict(
            company_short_name="acme",
            tool_name="text_embeddings",
            input_data={"mode": "text", "text": "hello"},
        )

        assert result == {"ok": True}
        self.mock_call_service.post.assert_called_once_with(
            "https://hf.endpoint",
            json_dict={
                "inputs": {"mode": "text", "text": "hello"},
                "parameters": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
            },
            headers={
                "Authorization": "Bearer super-secret-token",
                "Content-Type": "application/json",
            },
            timeout=(7.0, 45.0),
        )

    def test_predict_retries_retryable_http_status_until_success(self, monkeypatch):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "retry_budget_seconds": 30,
            },
        }
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"
        self.mock_call_service.post.side_effect = [
            ({"error": "Model loading"}, 503),
            ({"ok": True}, 200),
        ]
        sleep_calls = []
        monkeypatch.setattr("iatoolkit.services.inference_service.time.sleep", sleep_calls.append)

        result = self.service.predict(
            company_short_name="acme",
            tool_name="text_embeddings",
            input_data={"mode": "text", "text": "hello"},
        )

        assert result == {"ok": True}
        assert self.mock_call_service.post.call_count == 2
        assert sleep_calls == [5.0]

    def test_predict_retries_transient_internal_server_error_with_default_budget(self, monkeypatch):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"
        self.mock_call_service.post.side_effect = [
            ("500 Internal Server Error", 500),
            ({"embedding": [0.1, 0.2]}, 200),
        ]
        sleep_calls = []
        monkeypatch.setattr("iatoolkit.services.inference_service.time.sleep", sleep_calls.append)

        result = self.service.predict(
            company_short_name="acme",
            tool_name="text_embeddings",
            input_data={"mode": "text", "text": "network connectivity in depression"},
        )

        assert result == {"embedding": [0.1, 0.2]}
        assert self.mock_call_service.post.call_count == 2
        assert sleep_calls == [5.0]

    def test_retry_budget_can_be_disabled_per_tool(self):
        assert self.service._resolve_retry_budget_seconds({"retry_budget_seconds": 0}) == 0.0

    def test_predict_does_not_start_retry_after_budget_is_consumed_by_sleep(self, monkeypatch):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "retry_budget_seconds": 10,
            },
        }
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"
        clock = {"now": 0.0}
        sleep_calls = []

        def fake_post(*args, **kwargs):
            clock["now"] += 9.0
            return "500 Internal Server Error", 500

        def fake_sleep(seconds):
            sleep_calls.append(seconds)
            clock["now"] += seconds

        self.mock_call_service.post.side_effect = fake_post
        monkeypatch.setattr("iatoolkit.services.inference_service.time.monotonic", lambda: clock["now"])
        monkeypatch.setattr("iatoolkit.services.inference_service.time.sleep", fake_sleep)

        with pytest.raises(ValueError, match="Inference Endpoint Error 500"):
            self.service.predict(
                company_short_name="acme",
                tool_name="text_embeddings",
                input_data={"mode": "text", "text": "hello"},
            )

        assert self.mock_call_service.post.call_count == 1
        assert sleep_calls == [1.0]

    def test_predict_does_not_retry_non_transient_http_status(self, monkeypatch):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        }
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"
        self.mock_call_service.post.return_value = ({"error": "Invalid input"}, 400)
        sleep_calls = []
        monkeypatch.setattr("iatoolkit.services.inference_service.time.sleep", sleep_calls.append)

        with pytest.raises(ValueError, match="Inference Endpoint Error 400"):
            self.service.predict(
                company_short_name="acme",
                tool_name="text_embeddings",
                input_data={"mode": "text", "text": "hello"},
            )

        assert self.mock_call_service.post.call_count == 1
        assert sleep_calls == []

    def test_predict_retries_request_errors_until_success(self, monkeypatch):
        self.mock_config_service.get_configuration.return_value = {
            "_defaults": {
                "endpoint_url": "https://hf.endpoint",
                "api_key_name": "HF_TOKEN",
            },
            "text_embeddings": {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "retry_budget_seconds": 30,
            },
        }
        self.mock_secret_provider.get_secret.return_value = "super-secret-token"
        self.mock_call_service.post.side_effect = [
            IAToolkitException(IAToolkitException.ErrorType.REQUEST_ERROR, "connection reset"),
            ({"ok": True}, 200),
        ]
        sleep_calls = []
        monkeypatch.setattr("iatoolkit.services.inference_service.time.sleep", sleep_calls.append)

        result = self.service.predict(
            company_short_name="acme",
            tool_name="text_embeddings",
            input_data={"mode": "text", "text": "hello"},
        )

        assert result == {"ok": True}
        assert self.mock_call_service.post.call_count == 2
        assert sleep_calls == [5.0]
