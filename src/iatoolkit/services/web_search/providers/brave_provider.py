from __future__ import annotations

from urllib.parse import urlparse

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.interfaces.web_search_provider import WebSearchProvider
from iatoolkit.infra.call_service import CallServiceClient


class BraveWebSearchProvider(WebSearchProvider):
    DEFAULT_API_BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    MAX_RESULTS = 20

    @inject
    def __init__(self,
                 call_service: CallServiceClient,
                 secret_provider: SecretProvider):
        self.call_service = call_service
        self.secret_provider = secret_provider

    def search(self,
               company_short_name: str,
               request: dict,
               provider_config: dict,
               web_search_config: dict) -> list[dict]:
        secret_ref = str(provider_config.get("secret_ref", "")).strip()
        if not secret_ref:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.providers.brave.secret_ref is required"
            )

        api_key = self.secret_provider.get_secret(company_short_name, secret_ref)
        if not api_key:
            raise IAToolkitException(
                IAToolkitException.ErrorType.API_KEY,
                f"Secret '{secret_ref}' not found"
            )

        api_base_url = str(provider_config.get("api_base_url", self.DEFAULT_API_BASE_URL)).strip()
        parsed = urlparse(api_base_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.providers.brave.api_base_url must be an absolute HTTPS URL"
            )

        query_text = self._apply_domain_filters(
            request["query"],
            request.get("include_domains") or [],
            request.get("exclude_domains") or [],
        )
        n_results = min(int(request["n_results"]), self.MAX_RESULTS)
        timeout_ms = web_search_config.get("timeout_ms", 10000)
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.timeout_ms must be a positive integer"
            )

        params = {
            "q": query_text,
            "count": n_results,
        }

        freshness = self._to_freshness(request.get("recency_days"))
        if freshness:
            params["freshness"] = freshness

        response_data, status_code = self.call_service.get(
            api_base_url,
            params=params,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            timeout=(5, float(timeout_ms) / 1000.0),
        )

        if status_code != 200:
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                f"Brave search failed with status {status_code}"
            )

        if not isinstance(response_data, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.REQUEST_ERROR,
                "Brave search response is not a JSON object"
            )

        raw_results = (response_data.get("web") or {}).get("results") or []
        normalized: list[dict] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue

            normalized.append(
                {
                    "title": item.get("title") or url,
                    "url": url,
                    "snippet": item.get("description") or "",
                    "source": ((item.get("meta_url") or {}).get("hostname") or "brave"),
                    "published_at": item.get("age"),
                }
            )

        return normalized[:n_results]

    @staticmethod
    def _apply_domain_filters(query: str, include_domains: list[str], exclude_domains: list[str]) -> str:
        filters = []
        for domain in include_domains:
            filters.append(f"site:{domain}")
        for domain in exclude_domains:
            filters.append(f"-site:{domain}")

        if not filters:
            return query

        return f"{query} {' '.join(filters)}"

    @staticmethod
    def _to_freshness(recency_days: int | None) -> str | None:
        if recency_days is None:
            return None
        if recency_days <= 1:
            return "pd"
        if recency_days <= 7:
            return "pw"
        if recency_days <= 31:
            return "pm"
        return "py"
