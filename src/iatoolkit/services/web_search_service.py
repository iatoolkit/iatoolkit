from __future__ import annotations

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.web_search.provider_factory import WebSearchProviderFactory


class WebSearchService:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 provider_factory: WebSearchProviderFactory):
        self.config_service = config_service
        self.provider_factory = provider_factory

    def search(self,
               company_short_name: str,
               query: str,
               n_results: int | None = None,
               recency_days: int | None = None,
               include_domains: list[str] | None = None,
               exclude_domains: list[str] | None = None,
               **kwargs) -> dict:
        _ = kwargs
        web_search_config = self.config_service.get_configuration(company_short_name, "web_search")
        if not isinstance(web_search_config, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "Missing or invalid 'web_search' configuration."
            )

        if web_search_config.get("enabled") is False:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_OPERATION,
                "web_search is disabled for this company."
            )

        provider_name = str(web_search_config.get("provider", "")).strip().lower()
        if not provider_name:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.provider is required."
            )

        if not isinstance(query, str) or not query.strip():
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                "query is required."
            )

        default_results = web_search_config.get("max_results", 5)
        if not isinstance(default_results, int) or default_results <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.max_results must be a positive integer."
            )
        requested_results = default_results if n_results is None else n_results
        if not isinstance(requested_results, int) or requested_results <= 0:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "n_results must be a positive integer."
            )

        if recency_days is not None and (not isinstance(recency_days, int) or recency_days <= 0):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "recency_days must be a positive integer."
            )

        include_domains = self._normalize_domains(include_domains, "include_domains")
        exclude_domains = self._normalize_domains(exclude_domains, "exclude_domains")

        provider_cfg = self._resolve_provider_config(web_search_config, provider_name)
        provider = self.provider_factory.get_provider(provider_name)
        results = provider.search(
            company_short_name=company_short_name,
            request={
                "query": query.strip(),
                "n_results": requested_results,
                "recency_days": recency_days,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
            },
            provider_config=provider_cfg,
            web_search_config=web_search_config,
        )

        return {
            "status": "success",
            "provider": provider_name,
            "query": query.strip(),
            "count": len(results),
            "results": results,
        }

    @staticmethod
    def _resolve_provider_config(web_search_config: dict, provider_name: str) -> dict:
        providers_cfg = web_search_config.get("providers", {})
        if not isinstance(providers_cfg, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "web_search.providers must be a dictionary."
            )

        provider_cfg = providers_cfg.get(provider_name)
        if not isinstance(provider_cfg, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"web_search.providers.{provider_name} must be configured."
            )
        return provider_cfg

    @staticmethod
    def _normalize_domains(domains: list[str] | None, field_name: str) -> list[str]:
        if domains is None:
            return []
        if not isinstance(domains, list):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"{field_name} must be a list of domains."
            )

        normalized = []
        for domain in domains:
            if not isinstance(domain, str) or not domain.strip():
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"{field_name} must contain non-empty strings."
                )
            normalized.append(domain.strip())
        return normalized
