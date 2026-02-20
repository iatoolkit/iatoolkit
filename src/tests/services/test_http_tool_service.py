import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.http_tool_service import HttpToolService


class TestHttpToolService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.call_service = MagicMock(spec=CallServiceClient)
        self.secret_provider = MagicMock(spec=SecretProvider)
        self.config_service = MagicMock(spec=ConfigurationService)
        self.config_service.get_configuration.return_value = {}
        self.service = HttpToolService(
            call_service=self.call_service,
            secret_provider=self.secret_provider,
            config_service=self.config_service,
        )

    def test_execute_get_with_path_query_auth_and_extract(self):
        self.secret_provider.get_secret.return_value = "token-123"
        self.call_service.get.return_value = ({"payload": {"items": [{"id": 99}]}}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_orders",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/orders/{order_id}",
                    "path_params": {"order_id": "order_id"},
                    "query_params": {"expand": "expand"},
                    "headers": {"X-Trace": "1"}
                },
                "auth": {
                    "type": "bearer",
                    "secret_ref": "ORDERS_API_TOKEN"
                },
                "response": {
                    "extract_path": "payload.items.0.id"
                }
            },
            input_data={"order_id": 15, "expand": "items"}
        )

        self.call_service.get.assert_called_once()
        _, kwargs = self.call_service.get.call_args
        assert kwargs["params"] == {"expand": "items"}
        assert kwargs["headers"]["Authorization"] == "Bearer token-123"
        assert kwargs["headers"]["X-Trace"] == "1"
        assert result["status"] == "success"
        assert result["http_status"] == 200
        assert result["data"] == 99

    def test_execute_post_full_args_body(self):
        self.call_service.post.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_create_order",
            execution_config={
                "version": 1,
                "request": {
                    "method": "POST",
                    "url": "https://api.example.com/orders",
                    "body": {
                        "mode": "full_args"
                    }
                }
            },
            input_data={"customer_id": 7, "amount": 10.5}
        )

        self.call_service.post.assert_called_once()
        _, kwargs = self.call_service.post.call_args
        assert kwargs["json_dict"] == {"customer_id": 7, "amount": 10.5}
        assert result["data"] == {"ok": True}

    def test_execute_missing_mapped_body_parameter_raises(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_create_order",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.com/orders",
                        "body": {
                            "mode": "json_map",
                            "json_map": {"customerId": "customer_id"}
                        }
                    }
                },
                input_data={"amount": 10}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.MISSING_PARAMETER

    def test_execute_non_success_status_raises(self):
        self.call_service.get.return_value = ({"error": "bad request"}, 400)

        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_orders",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/orders"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_missing_secret_raises(self):
        self.secret_provider.get_secret.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_orders",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/orders"
                    },
                    "auth": {
                        "type": "bearer",
                        "secret_ref": "ORDERS_API_TOKEN"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.API_KEY

    def test_execute_blocks_localhost_target(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_local",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://localhost/internal"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_blocks_private_ip_target(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_private",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://10.0.0.8/data"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_rejects_host_outside_allowlist(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "allowed_hosts": ["api.allowed.com"]
            }
        }

        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_orders",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://api.not-allowed.com/orders"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_accepts_host_inside_allowlist(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "allowed_hosts": ["*.allowed.com"]
            }
        }
        self.call_service.get.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_orders",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.allowed.com/orders"
                }
            },
            input_data={}
        )

        assert result["status"] == "success"
        self.call_service.get.assert_called_once()
