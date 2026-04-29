from unittest.mock import MagicMock

from iatoolkit.services.telemetry_service import TelemetryService


class TestTelemetryService:
    def test_resolve_execution_request_normalizes_company_label_for_braintrust(self):
        configuration_service = MagicMock()
        configuration_service.get_llm_telemetry_config.return_value = {
            "enabled": True,
            "provider": "braintrust",
            "braintrust": {
                "project": "bt-project",
                "api_key": "BRAINTRUST_API_KEY",
            },
        }
        secret_provider = MagicMock()
        secret_provider.get_secret.return_value = "secret-value"

        service = TelemetryService(
            configuration_service=configuration_service,
            secret_provider=secret_provider,
        )

        request = service.resolve_execution_request(
            company_short_name="ent_company_prod",
            prompt_output_contract={
                "prompt_name": "sales_prompt",
                "llm_request_options": {"telemetry_enabled": True},
            },
            model="gpt-5",
            provider="openai",
            task_id=7,
            user_identifier="user-1",
        )

        assert request["metadata"]["company"] == "ent_company_prod"
        assert request["metadata"]["agent_name"] == "sales_prompt"
        assert "company_short_name" not in request["metadata"]
        assert "prompt_name" not in request["metadata"]
