import abc


class WebSearchProvider(abc.ABC):
    @abc.abstractmethod
    def search(self,
               company_short_name: str,
               request: dict,
               provider_config: dict,
               web_search_config: dict) -> list[dict]:
        """
        Execute a web search and return normalized results.
        """
        pass
