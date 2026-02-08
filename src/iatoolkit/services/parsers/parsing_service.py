# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging
import mimetypes

from injector import inject

from iatoolkit.services.parsers.contracts import ParseRequest, ParseResult
from iatoolkit.services.parsers.provider_factory import ParsingProviderFactory
from iatoolkit.services.parsers.provider_resolver import ParsingProviderResolver
from iatoolkit.services.parsers.validator import validate_parse_result


class ParsingService:
    @inject
    def __init__(self,
                 provider_resolver: ParsingProviderResolver,
                 provider_factory: ParsingProviderFactory):
        self.provider_resolver = provider_resolver
        self.provider_factory = provider_factory

    def warmup(self):
        docling_provider = self.provider_factory.get_provider("docling")
        if docling_provider.enabled:
            docling_provider.init()

    def parse_document(self,
                       company_short_name: str,
                       filename: str,
                       content: bytes,
                       metadata: dict | None = None,
                       collection_name: str | None = None,
                       collection_id: int | None = None,
                       document_id: int | None = None) -> ParseResult:
        metadata = metadata or {}
        mime_type, _ = mimetypes.guess_type(filename)

        request = ParseRequest(
            company_short_name=company_short_name,
            filename=filename,
            content=content,
            mime_type=mime_type,
            metadata=metadata,
            collection_name=collection_name,
            collection_id=collection_id,
            document_id=document_id,
        )

        provider = self.provider_resolver.resolve(request)

        try:
            result = provider.parse(request)
        except Exception as e:
            if provider.name != "legacy":
                logging.warning(f"Provider '{provider.name}' failed for {filename}, falling back to legacy: {e}")
                legacy_provider = self.provider_factory.get_provider("legacy")
                result = legacy_provider.parse(request)
                result.warnings.append(f"fallback_from:{provider.name}")
            else:
                raise

        validate_parse_result(result)
        return result

    def extract_text_for_context(self,
                                 filename: str,
                                 content: bytes,
                                 company_short_name: str = "default") -> str:
        """
        Context-builder helper: keeps legacy behavior for ad-hoc attachment parsing.
        """
        legacy_provider = self.provider_factory.get_provider("legacy")
        return legacy_provider.extract_text(filename, content)
