import pytest
from unittest.mock import MagicMock, call, patch

from iatoolkit.services.warmup_service import WarmupService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.common.interfaces.secret_provider import SecretProvider


class TestWarmupService:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)
        self.mock_secret_provider = MagicMock(spec=SecretProvider)
        self.service = WarmupService(
            config_service=self.mock_config_service,
            embedding_service=self.mock_embedding_service,
            secret_provider=self.mock_secret_provider,
        )

    def test_warmup_company_calls_embed_text_for_remote_hf(self):
        def config_side_effect(company_short_name, key):
            if key == "embedding_provider":
                return {"provider": "huggingface", "tool_name": "text_embeddings"}
            if key == "inference_tools":
                return {"text_embeddings": {"endpoint_url": "https://hf.endpoint"}}
            return None

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        self.service.warmup_company("acme", trigger="test")

        self.mock_embedding_service.embed_text.assert_called_once_with(
            "acme",
            "hello",
            model_type="text",
            suppress_error_logging=True,
        )

    def test_warmup_company_skips_when_provider_is_not_huggingface(self):
        self.mock_config_service.get_configuration.return_value = {"provider": "openai"}

        self.service.warmup_company("acme", trigger="test")

        self.mock_embedding_service.embed_text.assert_not_called()

    def test_warmup_company_skips_when_tool_has_no_endpoint(self):
        def config_side_effect(company_short_name, key):
            if key == "embedding_provider":
                return {"provider": "huggingface", "tool_name": "text_embeddings"}
            if key == "inference_tools":
                return {"text_embeddings": {}}
            return None

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        self.service.warmup_company("acme", trigger="test")

        self.mock_embedding_service.embed_text.assert_not_called()

    def test_warmup_company_uses_defaults_endpoint_url_env(self):
        def config_side_effect(company_short_name, key):
            if key == "embedding_provider":
                return {"provider": "huggingface", "tool_name": "text_embeddings"}
            if key == "inference_tools":
                return {
                    "_defaults": {"endpoint_url_env": "HF_INFERENCE_ENDPOINT_URL"},
                    "text_embeddings": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
                }
            return None

        self.mock_config_service.get_configuration.side_effect = config_side_effect
        self.mock_secret_provider.get_secret.return_value = "https://hf.endpoint"

        self.service.warmup_company("acme", trigger="test")

        self.mock_embedding_service.embed_text.assert_called_once_with(
            "acme",
            "hello",
            model_type="text",
            suppress_error_logging=True,
        )

    def test_warmup_company_primes_remote_embedding_profiles_with_text_last(self):
        def config_side_effect(company_short_name, key):
            if key == "embedding_provider":
                return {"provider": "huggingface", "tool_name": "text_embeddings"}
            if key == "embedding_providers":
                return {
                    "routing": {"provider": "huggingface", "tool_name": "routing_embeddings"},
                    "local": {"provider": "openai", "model": "text-embedding-3-small"},
                }
            if key == "inference_tools":
                return {
                    "_defaults": {"endpoint_url": "https://hf.endpoint"},
                    "text_embeddings": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
                    "routing_embeddings": {"model_id": "BAAI/bge-m3"},
                }
            return None

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        self.service.warmup_company("acme", trigger="test")

        self.mock_embedding_service.embed_text.assert_has_calls(
            [
                call("acme", "hello", model_type="routing", suppress_error_logging=True),
                call("acme", "hello", model_type="text", suppress_error_logging=True),
            ]
        )

    def test_warmup_registered_companies_calls_each_company(self):
        self.service.warmup_company = MagicMock()

        with patch(
            "iatoolkit.services.warmup_service.get_registered_companies",
            return_value={"acme": object(), "beta": object()},
        ):
            self.service.warmup_registered_companies(trigger="startup")

        self.service.warmup_company.assert_has_calls(
            [call("acme", trigger="startup"), call("beta", trigger="startup")],
            any_order=True,
        )

    def test_warmup_startup_configured_companies_only_warms_enabled_embedding_providers(self):
        def config_side_effect(company_short_name, key):
            configs = {
                "acme": {
                    "embedding_provider": {
                        "provider": "huggingface",
                        "tool_name": "text_embeddings",
                        "warmup_on_startup": True,
                    },
                    "embedding_providers": {},
                },
                "beta": {
                    "embedding_provider": {
                        "provider": "huggingface",
                        "tool_name": "text_embeddings",
                    },
                    "embedding_providers": {},
                },
                "gamma": {
                    "embedding_provider": {
                        "provider": "huggingface",
                        "tool_name": "text_embeddings",
                    },
                    "embedding_providers": {
                        "routing": {
                            "provider": "huggingface",
                            "tool_name": "routing_embeddings",
                            "warmup_on_startup": True,
                        },
                    },
                },
            }
            if key == "inference_tools":
                return {
                    "_defaults": {"endpoint_url": "https://hf.endpoint"},
                    "text_embeddings": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
                    "routing_embeddings": {"model_id": "BAAI/bge-m3"},
                }
            return configs.get(company_short_name, {}).get(key)

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        with patch(
            "iatoolkit.services.warmup_service.get_registered_companies",
            return_value={"acme": object(), "beta": object(), "gamma": object()},
        ):
            woken = self.service.warmup_startup_configured_companies(trigger="core_startup")

        # acme and gamma share one endpoint, so it is knocked on once, not twice.
        # beta is skipped: it never enabled warmup_on_startup.
        assert woken == ["hf.endpoint"]
        self.mock_embedding_service.embed_text.assert_called_once_with(
            "acme", "hello", model_type="text", suppress_error_logging=True
        )

    def test_startup_warmup_knocks_once_per_endpoint_not_once_per_tenant(self):
        """The whole point: N tenants on one endpoint is one wake-up call.

        Calling per tenant multiplied requests against a container that was
        already starting, each willing to spend the tool's full retry budget.
        """
        def config_side_effect(company_short_name, key):
            if key == "inference_tools":
                return {
                    "_defaults": {"endpoint_url": "https://shared.endpoint"},
                    "text_embeddings": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
                }
            if key == "embedding_provider":
                return {
                    "provider": "huggingface",
                    "tool_name": "text_embeddings",
                    "warmup_on_startup": True,
                }
            return {}

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        with patch(
            "iatoolkit.services.warmup_service.get_registered_companies",
            return_value={"one": object(), "two": object(), "three": object()},
        ):
            woken = self.service.warmup_startup_configured_companies(trigger="core_startup")

        assert woken == ["shared.endpoint"]
        assert self.mock_embedding_service.embed_text.call_count == 1

    def test_startup_warmup_still_wakes_every_distinct_endpoint(self):
        """Dedup must not cost coverage: two endpoints are two wake-up calls."""
        def config_side_effect(company_short_name, key):
            if key == "inference_tools":
                url = "https://one.endpoint" if company_short_name == "acme" else "https://two.endpoint"
                return {
                    "_defaults": {"endpoint_url": url},
                    "text_embeddings": {"model_id": "sentence-transformers/all-MiniLM-L6-v2"},
                }
            if key == "embedding_provider":
                return {
                    "provider": "huggingface",
                    "tool_name": "text_embeddings",
                    "warmup_on_startup": True,
                }
            return {}

        self.mock_config_service.get_configuration.side_effect = config_side_effect

        with patch(
            "iatoolkit.services.warmup_service.get_registered_companies",
            return_value={"acme": object(), "beta": object()},
        ):
            woken = self.service.warmup_startup_configured_companies(trigger="core_startup")

        assert sorted(woken) == ["one.endpoint", "two.endpoint"]
        assert self.mock_embedding_service.embed_text.call_count == 2

    def test_a_failed_wake_up_does_not_stop_the_other_endpoints(self):
        """One unreachable endpoint must not leave the others cold."""
        def config_side_effect(company_short_name, key):
            if key == "inference_tools":
                url = "https://down.endpoint" if company_short_name == "acme" else "https://up.endpoint"
                return {
                    "_defaults": {"endpoint_url": url},
                    "text_embeddings": {"model_id": "m"},
                }
            if key == "embedding_provider":
                return {
                    "provider": "huggingface",
                    "tool_name": "text_embeddings",
                    "warmup_on_startup": True,
                }
            return {}

        self.mock_config_service.get_configuration.side_effect = config_side_effect
        self.mock_embedding_service.embed_text.side_effect = [RuntimeError("cold"), "ok"]

        with patch(
            "iatoolkit.services.warmup_service.get_registered_companies",
            return_value={"acme": object(), "beta": object()},
        ):
            woken = self.service.warmup_startup_configured_companies(trigger="core_startup")

        assert woken == ["up.endpoint"]
        assert self.mock_embedding_service.embed_text.call_count == 2
