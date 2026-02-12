import pytest
from unittest.mock import MagicMock, call, patch

from iatoolkit.services.warmup_service import WarmupService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.embedding_service import EmbeddingService


class TestWarmupService:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)
        self.service = WarmupService(
            config_service=self.mock_config_service,
            embedding_service=self.mock_embedding_service,
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

        self.mock_embedding_service.embed_text.assert_called_once_with("acme", "hello")

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
