from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.web_search.providers.brave_provider import BraveWebSearchProvider


class WebSearchProviderFactory:
    @inject
    def __init__(self, brave_provider: BraveWebSearchProvider):
        self._providers = {
            "brave": brave_provider,
        }

    def get_provider(self, provider_name: str):
        name = (provider_name or "").strip().lower()
        provider = self._providers.get(name)
        if provider is None:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Unsupported web_search provider '{provider_name}'"
            )
        return provider
