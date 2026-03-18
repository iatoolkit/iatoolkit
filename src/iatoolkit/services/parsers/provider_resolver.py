# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.services.parsers.contracts import ParseRequest
from iatoolkit.services.parsers.provider_factory import ParsingProviderFactory


class ParsingProviderResolver:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 document_repo: DocumentRepo,
                 provider_factory: ParsingProviderFactory):
        self.config_service = config_service
        self.document_repo = document_repo
        self.provider_factory = provider_factory

    def resolve(self, request: ParseRequest):
        kb_config = self.config_service.get_configuration(request.company_short_name, "knowledge_base") or {}
        configured_provider = self._resolve_provider_name_for_request(kb_config, request)

        if configured_provider == "auto":
            docling_provider = self.provider_factory.get_provider("docling")
            if docling_provider.enabled and docling_provider.supports(request):
                return docling_provider
            return self.provider_factory.get_provider("basic")

        return self.provider_factory.get_provider(self._normalize_provider_alias(configured_provider))

    def _resolve_provider_name_for_request(self, kb_config: dict, request: ParseRequest) -> str:
        collection_provider = self._resolve_collection_provider_from_db(
            request.company_short_name,
            request.collection_name,
        )
        if collection_provider:
            return collection_provider

        global_provider = kb_config.get("parsing_provider")
        if isinstance(global_provider, str) and global_provider.strip():
            return global_provider.strip().lower()

        return "auto"

    def _resolve_collection_provider_from_db(self, company_short_name: str, collection_name: str | None) -> str | None:
        if not collection_name:
            return None

        collection = self.document_repo.get_collection_by_name(company_short_name, collection_name)
        if not collection:
            return None

        parser_provider = getattr(collection, "parser_provider", None)
        if isinstance(parser_provider, str) and parser_provider.strip():
            return parser_provider.strip().lower()
        return None

    @staticmethod
    def _normalize_provider_alias(provider_name: str) -> str:
        aliases = {
            "legacy": "basic",
        }
        return aliases.get(provider_name, provider_name)
