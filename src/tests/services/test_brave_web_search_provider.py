import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.web_search.providers.brave_provider import BraveWebSearchProvider


class TestBraveWebSearchProvider:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.call_service = MagicMock(spec=CallServiceClient)
        self.secret_provider = MagicMock(spec=SecretProvider)
        self.provider = BraveWebSearchProvider(
            call_service=self.call_service,
            secret_provider=self.secret_provider,
        )

    def test_search_builds_request_and_normalizes_results(self):
        self.secret_provider.get_secret.return_value = "token-123"
        self.call_service.get.return_value = (
            {
                "web": {
                    "results": [
                        {
                            "title": "OpenAI",
                            "url": "https://openai.com",
                            "description": "OpenAI site",
                            "meta_url": {"hostname": "openai.com"},
                            "age": "1 day ago",
                        }
                    ]
                }
            },
            200
        )

        results = self.provider.search(
            company_short_name="acme",
            request={
                "query": "openai",
                "n_results": 3,
                "recency_days": 2,
                "include_domains": ["openai.com"],
                "exclude_domains": ["example.com"],
            },
            provider_config={"secret_ref": "BRAVE_SEARCH_API_KEY"},
            web_search_config={"timeout_ms": 10000},
        )

        self.call_service.get.assert_called_once()
        _, kwargs = self.call_service.get.call_args
        assert kwargs["params"]["q"] == "openai site:openai.com -site:example.com"
        assert kwargs["params"]["count"] == 3
        assert kwargs["params"]["freshness"] == "pw"
        assert kwargs["headers"]["X-Subscription-Token"] == "token-123"
        assert results[0]["url"] == "https://openai.com"
        assert results[0]["source"] == "openai.com"

    def test_search_missing_secret_raises(self):
        self.secret_provider.get_secret.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.provider.search(
                company_short_name="acme",
                request={"query": "openai", "n_results": 3},
                provider_config={"secret_ref": "BRAVE_SEARCH_API_KEY"},
                web_search_config={},
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.API_KEY

    def test_search_non_200_raises(self):
        self.secret_provider.get_secret.return_value = "token-123"
        self.call_service.get.return_value = ({"error": "rate_limit"}, 429)

        with pytest.raises(IAToolkitException) as exc:
            self.provider.search(
                company_short_name="acme",
                request={"query": "openai", "n_results": 3},
                provider_config={"secret_ref": "BRAVE_SEARCH_API_KEY"},
                web_search_config={},
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.REQUEST_ERROR
