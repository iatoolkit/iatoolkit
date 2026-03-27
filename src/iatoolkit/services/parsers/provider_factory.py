# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject, singleton

from iatoolkit.services.parsers.providers.basic_provider import BasicParsingProvider
from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider

@singleton
class ParsingProviderFactory:
    @inject
    def __init__(self,
                 docling_provider: DoclingParsingProvider,
                 basic_provider: BasicParsingProvider):
        self.docling_provider = docling_provider
        self.basic_provider = basic_provider
        self._providers = {
            "docling": self.docling_provider,
            "basic": self.basic_provider,
            "legacy": self.basic_provider,
        }

    def get_provider(self, provider_name: str):
        if not provider_name:
            raise ValueError("Provider name is required")

        key = provider_name.strip().lower()
        if key not in self._providers:
            raise NotImplementedError(f"Parsing provider '{provider_name}' is not implemented")

        return self._providers[key]
