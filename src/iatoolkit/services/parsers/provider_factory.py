# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider
from iatoolkit.services.parsers.providers.legacy_provider import LegacyParsingProvider


class ParsingProviderFactory:
    @inject
    def __init__(self,
                 docling_provider: DoclingParsingProvider,
                 legacy_provider: LegacyParsingProvider):
        self.docling_provider = docling_provider
        self.legacy_provider = legacy_provider
        self._providers = {
            "docling": self.docling_provider,
            "legacy": self.legacy_provider,
        }

    def get_provider(self, provider_name: str):
        if not provider_name:
            raise ValueError("Provider name is required")

        key = provider_name.strip().lower()
        if key not in self._providers:
            raise NotImplementedError(f"Parsing provider '{provider_name}' is not implemented")

        return self._providers[key]
