# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.parsers.contracts import ParseRequest
from iatoolkit.services.parsers.provider_factory import ParsingProviderFactory


class ParsingProviderResolver:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 provider_factory: ParsingProviderFactory):
        self.config_service = config_service
        self.provider_factory = provider_factory

    def resolve(self, request: ParseRequest):
        kb_config = self.config_service.get_configuration(request.company_short_name, "knowledge_base") or {}
        configured_provider = (kb_config.get("parsing_provider") or "auto").strip().lower()

        if configured_provider == "auto":
            docling_provider = self.provider_factory.get_provider("docling")
            if docling_provider.enabled and docling_provider.supports(request):
                return docling_provider
            return self.provider_factory.get_provider("legacy")

        return self.provider_factory.get_provider(configured_provider)
