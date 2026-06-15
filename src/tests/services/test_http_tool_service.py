import pytest
from unittest.mock import MagicMock, patch

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

    def test_execute_applies_model_output_extract(self):
        self.call_service.get.return_value = ({
            "status": "ok",
            "data": {
                "customer": {
                    "id": "cus_123",
                    "name": "Acme S.L.",
                    "debug": {"trace_id": "abc-999"},
                }
            },
        }, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_customer",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/customer"
                },
                "response": {
                    "model_output": {
                        "mode": "extract",
                        "path": "data.customer"
                    }
                }
            },
            input_data={}
        )

        assert result["data"] == {
            "id": "cus_123",
            "name": "Acme S.L.",
            "debug": {"trace_id": "abc-999"},
        }

    def test_execute_applies_model_output_map_object(self):
        self.call_service.get.return_value = ({
            "status": "ok",
            "data": {
                "customer": {
                    "id": "cus_123",
                    "name": "Acme S.L.",
                    "account": {"status": "ACTIVE"},
                    "billing": {"pendingAmount": 142.3},
                    "debug": {"trace_id": "abc-999"},
                }
            },
        }, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_customer",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/customer"
                },
                "response": {
                    "model_output": {
                        "mode": "map",
                        "root": "data.customer",
                        "fields": {
                            "customer_id": "id",
                            "customer_name": "name",
                            "status": "account.status",
                            "amount_due": {
                                "path": "billing.pendingAmount",
                                "description": "Amount due in EUR"
                            }
                        },
                        "exclude_nulls": True
                    }
                }
            },
            input_data={}
        )

        assert result["data"] == {
            "customer_id": "cus_123",
            "customer_name": "Acme S.L.",
            "status": "ACTIVE",
            "amount_due": 142.3,
        }

    def test_execute_applies_model_output_map_list_with_limit_and_null_exclusion(self):
        self.call_service.get.return_value = ({
            "data": {
                "items": [
                    {"id": "a", "name": "Alpha", "meta": {"status": "ACTIVE"}},
                    {"id": "b", "name": "Beta", "meta": {}},
                    {"id": "c", "name": "Gamma", "meta": {"status": "BLOCKED"}},
                ]
            },
        }, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_customers",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/customers"
                },
                "response": {
                    "model_output": {
                        "mode": "map",
                        "root": "data.items",
                        "fields": {
                            "customer_id": "id",
                            "customer_name": "name",
                            "status": "meta.status",
                        },
                        "exclude_nulls": True,
                        "max_items": 2,
                    }
                }
            },
            input_data={}
        )

        assert result["data"] == [
            {
                "customer_id": "a",
                "customer_name": "Alpha",
                "status": "ACTIVE",
            },
            {
                "customer_id": "b",
                "customer_name": "Beta",
            },
        ]

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

    def test_execute_applies_builtin_user_agent_header(self):
        self.call_service.get.return_value = ({"ok": True}, 200)

        self.service.execute(
            company_short_name="acme",
            tool_name="http_status",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/status"
                }
            },
            input_data={}
        )

        _, kwargs = self.call_service.get.call_args
        assert kwargs["headers"]["User-Agent"] == "IAToolkit-HTTPTool/1.0 (company=acme)"

    def test_execute_applies_company_default_headers(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "default_headers": {
                    "User-Agent": "TenantBot/1.0 (ops@example.com)",
                    "Accept-Language": "es"
                }
            }
        }
        self.call_service.get.return_value = ({"ok": True}, 200)

        self.service.execute(
            company_short_name="acme",
            tool_name="http_wiki",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://es.wikipedia.org/w/api.php"
                }
            },
            input_data={}
        )

        _, kwargs = self.call_service.get.call_args
        assert kwargs["headers"]["User-Agent"] == "TenantBot/1.0 (ops@example.com)"
        assert kwargs["headers"]["Accept-Language"] == "es"

    def test_execute_applies_host_specific_headers(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "host_headers": {
                    "*.wikipedia.org": {
                        "User-Agent": "WikiBot/1.0 (ops@example.com)",
                        "Accept-Language": "es"
                    }
                }
            }
        }
        self.call_service.get.return_value = ({"ok": True}, 200)

        self.service.execute(
            company_short_name="acme",
            tool_name="http_wiki",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://es.wikipedia.org/w/api.php"
                }
            },
            input_data={}
        )

        _, kwargs = self.call_service.get.call_args
        assert kwargs["headers"]["User-Agent"] == "WikiBot/1.0 (ops@example.com)"
        assert kwargs["headers"]["Accept-Language"] == "es"

    def test_execute_tool_headers_override_company_headers_case_insensitively(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "default_headers": {
                    "User-Agent": "TenantBot/1.0 (ops@example.com)",
                    "Accept-Language": "es"
                }
            }
        }
        self.call_service.get.return_value = ({"ok": True}, 200)

        self.service.execute(
            company_short_name="acme",
            tool_name="http_wiki",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "https://es.wikipedia.org/w/api.php",
                    "headers": {
                        "user-agent": "PerToolBot/2.0 (dev@example.com)"
                    }
                }
            },
            input_data={}
        )

        _, kwargs = self.call_service.get.call_args
        assert kwargs["headers"]["user-agent"] == "PerToolBot/2.0 (dev@example.com)"
        assert "User-Agent" not in kwargs["headers"]
        assert kwargs["headers"]["Accept-Language"] == "es"

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

    def test_execute_allows_private_ip_target_when_explicitly_enabled_and_allowlisted(self):
        self.call_service.get.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_private",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "http://10.0.0.8/data"
                },
                "security": {
                    "allow_private_network": True,
                    "allowed_hosts": ["10.0.0.8"]
                }
            },
            input_data={}
        )

        assert result["status"] == "success"
        _, kwargs = self.call_service.get.call_args
        assert kwargs["allow_redirects"] is False

    @patch("iatoolkit.services.http_tool_service.socket.getaddrinfo")
    def test_execute_allows_private_dns_target_when_explicitly_enabled_and_allowlisted(
            self,
            mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (None, None, None, None, ("10.0.0.8", 0))
        ]
        self.call_service.get.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_private",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "http://internal-api.local/data"
                },
                "security": {
                    "allow_private_network": True,
                    "allowed_hosts": ["internal-api.local"]
                }
            },
            input_data={}
        )

        assert result["status"] == "success"
        self.call_service.get.assert_called_once()

    def test_execute_allows_private_ip_target_without_allowed_hosts_when_enabled(self):
        self.call_service.get.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_private",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "http://10.0.0.8/data"
                },
                "security": {
                    "allow_private_network": True
                }
            },
            input_data={}
        )

        assert result["status"] == "success"

    def test_execute_private_network_does_not_inherit_company_allowed_hosts(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "allowed_hosts": ["api.allowed.com"]
            }
        }
        self.call_service.get.return_value = ({"ok": True}, 200)

        result = self.service.execute(
            company_short_name="acme",
            tool_name="http_private",
            execution_config={
                "version": 1,
                "request": {
                    "method": "GET",
                    "url": "http://10.0.0.8/data"
                },
                "security": {
                    "allow_private_network": True
                }
            },
            input_data={}
        )

        assert result["status"] == "success"

    def test_execute_rejects_private_ip_target_outside_tool_allowlist(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_private",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "http://10.0.0.8/data"
                    },
                    "security": {
                        "allow_private_network": True,
                        "allowed_hosts": ["10.0.0.9"]
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_keeps_link_local_blocked_when_private_network_is_enabled(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_metadata",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "http://169.254.169.254/latest/meta-data"
                    },
                    "security": {
                        "allow_private_network": True,
                        "allowed_hosts": ["169.254.169.254"]
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR

    def test_execute_rejects_public_http_even_when_private_network_is_enabled(self):
        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_public",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "http://8.8.8.8/data"
                    },
                    "security": {
                        "allow_private_network": True,
                        "allowed_hosts": ["8.8.8.8"]
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

    def test_execute_rejects_invalid_company_default_headers(self):
        self.config_service.get_configuration.return_value = {
            "http_tools": {
                "default_headers": ["bad"]
            }
        }

        with pytest.raises(IAToolkitException) as exc:
            self.service.execute(
                company_short_name="acme",
                tool_name="http_wiki",
                execution_config={
                    "version": 1,
                    "request": {
                        "method": "GET",
                        "url": "https://es.wikipedia.org/w/api.php"
                    }
                },
                input_data={}
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
