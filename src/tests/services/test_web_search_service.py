import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.web_search_service import WebSearchService
from iatoolkit.services.web_search.provider_factory import WebSearchProviderFactory
from iatoolkit.services.configuration_service import ConfigurationService


class TestWebSearchService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.config_service = MagicMock(spec=ConfigurationService)
        self.provider_factory = MagicMock(spec=WebSearchProviderFactory)
        self.provider = MagicMock()
        self.provider_factory.get_provider.return_value = self.provider

        self.service = WebSearchService(
            config_service=self.config_service,
            provider_factory=self.provider_factory,
        )

    def test_search_success(self):
        self.config_service.get_configuration.return_value = {
            "enabled": True,
            "provider": "brave",
            "max_results": 5,
            "timeout_ms": 10000,
            "providers": {
                "brave": {
                    "secret_ref": "BRAVE_SEARCH_API_KEY"
                }
            }
        }
        self.provider.search.return_value = [
            {"title": "A", "url": "https://example.com", "snippet": "x", "source": "example.com", "published_at": None}
        ]

        result = self.service.search(
            company_short_name="acme",
            query="openai",
            include_domains=["openai.com"],
        )

        self.provider_factory.get_provider.assert_called_once_with("brave")
        self.provider.search.assert_called_once()
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["provider"] == "brave"

    def test_search_missing_configuration_raises(self):
        self.config_service.get_configuration.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.service.search(company_short_name="acme", query="openai")

        assert exc.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR

    def test_search_disabled_raises(self):
        self.config_service.get_configuration.return_value = {
            "enabled": False,
            "provider": "brave",
            "providers": {"brave": {"secret_ref": "BRAVE_SEARCH_API_KEY"}}
        }

        with pytest.raises(IAToolkitException) as exc:
            self.service.search(company_short_name="acme", query="openai")

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION

    def test_search_rejects_invalid_domains(self):
        self.config_service.get_configuration.return_value = {
            "enabled": True,
            "provider": "brave",
            "providers": {"brave": {"secret_ref": "BRAVE_SEARCH_API_KEY"}}
        }

        with pytest.raises(IAToolkitException) as exc:
            self.service.search(company_short_name="acme", query="openai", include_domains="openai.com")

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
