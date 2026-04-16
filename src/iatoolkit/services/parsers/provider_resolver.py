# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject, singleton

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.services.parsers.contracts import ParseRequest
from iatoolkit.services.parsers.provider_factory import ParsingProviderFactory


@singleton
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
        provider_name = self.resolve_provider_name(request)
        if provider_name == "auto":
            return self.provider_factory.get_provider("basic")
        return self.provider_factory.get_provider(provider_name)

    def resolve_provider_name(self, request: ParseRequest) -> str:
        kb_config = self.config_service.get_configuration(request.company_short_name, "knowledge_base") or {}
        return self._resolve_provider_name_for_request(kb_config, request)

    def _resolve_provider_name_for_request(self, kb_config: dict, request: ParseRequest) -> str:
        config_provider = self._resolve_provider_name_from_request_config(request.provider_config)
        if config_provider:
            return config_provider

        metadata_provider = self._resolve_metadata_provider(request.metadata)
        if metadata_provider:
            return metadata_provider

        collection_provider = self._resolve_collection_provider_from_db(
            request.company_short_name,
            request.collection_name,
        )
        if collection_provider:
            return collection_provider

        global_provider = kb_config.get("parsing_provider")
        if isinstance(global_provider, str) and global_provider.strip():
            return self._normalize_provider_alias(global_provider.strip().lower())

        return "auto"

    def _resolve_provider_name_from_request_config(self, provider_config: dict | None) -> str | None:
        if not isinstance(provider_config, dict):
            return None

        provider_name = provider_config.get("provider")
        if not isinstance(provider_name, str) or not provider_name.strip():
            provider_name = provider_config.get("parser_provider")
        if isinstance(provider_name, str) and provider_name.strip():
            return self._normalize_provider_alias(provider_name.strip().lower())
        return None

    def _resolve_metadata_provider(self, metadata: dict | None) -> str | None:
        if not isinstance(metadata, dict):
            return None

        provider_name = metadata.get("parser_provider")
        if isinstance(provider_name, str) and provider_name.strip():
            return self._normalize_provider_alias(provider_name.strip().lower())
        return None

    def _resolve_collection_provider_from_db(self, company_short_name: str, collection_name: str | None) -> str | None:
        if not collection_name:
            return None

        collection = self.document_repo.get_collection_by_name(company_short_name, collection_name)
        if not collection:
            return None

        parser_provider = getattr(collection, "parser_provider", None)
        if isinstance(parser_provider, str) and parser_provider.strip():
            return self._normalize_provider_alias(parser_provider.strip().lower())
        return None

    @staticmethod
    def _normalize_provider_alias(provider_name: str) -> str:
        aliases = {
            "legacy": "basic",
        }
        return aliases.get(provider_name, provider_name)
