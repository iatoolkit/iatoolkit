# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from copy import deepcopy
from time import perf_counter

from injector import inject, singleton

from iatoolkit.services.parsers.contracts import ParseRequest, ParseResult
from iatoolkit.services.parsers.pdf_ocr_detection import analyze_pdf_ocr_need
from iatoolkit.services.parsers.provider_factory import ParsingProviderFactory
from iatoolkit.services.parsers.provider_resolver import ParsingProviderResolver
from iatoolkit.services.parsers.validator import validate_parse_result


@singleton
class ParsingService:
    @inject
    def __init__(self,
                 provider_resolver: ParsingProviderResolver,
                 provider_factory: ParsingProviderFactory):
        self.provider_resolver = provider_resolver
        self.provider_factory = provider_factory
        self.auto_min_text_chars = self._get_int_env("PARSING_AUTO_MIN_TEXT_CHARS", 80)

    def warmup(self):
        logging.info("ParsingService warmup skipped: Docling is lazy-loaded.")

    def parse_document(self,
                       company_short_name: str,
                       filename: str,
                       content: bytes,
                       metadata: dict | None = None,
                       collection_name: str | None = None,
                       collection_id: int | None = None,
                       document_id: int | None = None,
                       provider_config: dict | None = None) -> ParseResult:
        metadata = metadata or {}
        effective_provider_config = deepcopy(provider_config or {})
        metadata_provider_config = metadata.get("parse_options") if isinstance(metadata.get("parse_options"), dict) else {}
        if metadata_provider_config:
            effective_provider_config = {**metadata_provider_config, **effective_provider_config}
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
            provider_config=effective_provider_config,
        )

        requested_provider = self.provider_resolver.resolve_provider_name(request)
        started_at = perf_counter()
        result = self._parse_request(request, requested_provider=requested_provider)

        validate_parse_result(result)
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        result.metrics.setdefault("requested_provider", requested_provider)
        result.metrics.setdefault("effective_provider", getattr(result, "provider", requested_provider))
        result.metrics.setdefault("detect_tables", self._resolve_detect_tables(request))
        result.metrics["elapsed_ms"] = elapsed_ms

        logging.info(
            "Parsed document company=%s filename=%s requested_provider=%s provider=%s provider_version=%s elapsed_ms=%s texts=%s tables=%s images=%s warnings=%s",
            company_short_name,
            filename,
            requested_provider,
            getattr(result, "provider", "unknown"),
            getattr(result, "provider_version", None),
            elapsed_ms,
            len(getattr(result, "texts", []) or []),
            len(getattr(result, "tables", []) or []),
            len(getattr(result, "images", []) or []),
            len(getattr(result, "warnings", []) or []),
        )
        return result

    def extract_text_for_context(self,
                                 filename: str,
                                 content: bytes,
                                 company_short_name: str = "default") -> str:
        basic_provider = self.provider_factory.get_provider("basic")
        request = ParseRequest(
            company_short_name=company_short_name,
            filename=filename,
            content=content,
            provider_config={},
        )
        result = basic_provider.parse(request)
        return "\n\n".join(
            (item.text or "").strip()
            for item in getattr(result, "texts", []) or []
            if (item.text or "").strip()
        )

    def _parse_request(self, request: ParseRequest, *, requested_provider: str) -> ParseResult:
        if requested_provider == "auto":
            return self._parse_auto(request)
        return self._parse_with_provider(request, provider_name=requested_provider)

    def _parse_auto(self, request: ParseRequest) -> ParseResult:
        pdf_needs_ocr = self._resolve_pdf_needs_ocr(request)
        basic_result = self._parse_with_provider(
            self._with_provider_overrides(
                request,
                allow_ocr=False,
                pdf_needs_ocr=pdf_needs_ocr,
                suppress_ocr_required_error=True,
            ),
            provider_name="basic",
            allow_basic_fallback=False,
        )
        basic_result.metrics.setdefault("auto_stage", "basic")

        if not self._is_pdf_request(request):
            if self._has_sufficient_text(basic_result):
                return basic_result
            if self._docling_supports(request):
                logging.info(
                    "Auto parsing escalated to Docling for %s because basic output was insufficient.",
                    request.filename,
                )
                docling_result = self._parse_with_provider(
                    self._with_provider_overrides(
                        request,
                        detect_tables=self._resolve_detect_tables(request),
                        pdf_needs_ocr=pdf_needs_ocr,
                    ),
                    provider_name="docling",
                )
                docling_result.metrics.setdefault("auto_stage", "docling")
                return docling_result
            return basic_result

        if self._has_sufficient_text(basic_result):
            return basic_result

        can_use_tesseract, tesseract_reason = self._get_tesseract_status()
        if can_use_tesseract:
            logging.info("Auto parsing escalated to Tesseract OCR for %s.", request.filename)
            tesseract_result = self._parse_with_provider(
                self._with_provider_overrides(request, allow_ocr=True, pdf_needs_ocr=pdf_needs_ocr),
                provider_name="basic",
                allow_basic_fallback=False,
            )
            tesseract_result.metrics["used_ocr"] = True
            tesseract_result.metrics["ocr_engine"] = "tesseract"
            tesseract_result.metrics.setdefault("auto_stage", "tesseract")
            if self._has_sufficient_text(tesseract_result):
                return tesseract_result
            basic_result.warnings.append("auto_ocr_tesseract_insufficient")
        else:
            logging.info(
                "Auto parsing did not escalate to Tesseract OCR for %s: %s",
                request.filename,
                tesseract_reason,
            )
            basic_result.warnings.append(f"auto_ocr_tesseract_unavailable:{tesseract_reason}")

        if self._docling_supports(request):
            logging.info("Auto parsing escalated to Docling for %s.", request.filename)
            docling_result = self._parse_with_provider(
                self._with_provider_overrides(
                    request,
                    detect_tables=self._resolve_detect_tables(request),
                    pdf_needs_ocr=pdf_needs_ocr,
                ),
                provider_name="docling",
            )
            docling_result.metrics.setdefault("auto_stage", "docling")
            return docling_result

        return basic_result

    def _parse_with_provider(self,
                             request: ParseRequest,
                             *,
                             provider_name: str,
                             allow_basic_fallback: bool = True) -> ParseResult:
        provider = self.provider_factory.get_provider(provider_name)
        try:
            return provider.parse(request)
        except Exception as exc:
            if not allow_basic_fallback or provider.name == "basic":
                raise
            logging.warning(
                "Provider '%s' failed for %s, falling back to basic: %s",
                provider.name,
                request.filename,
                exc,
            )
            basic_provider = self.provider_factory.get_provider("basic")
            basic_result = basic_provider.parse(self._with_provider_overrides(request, allow_ocr=False))
            basic_result.warnings.append(f"fallback_from:{provider.name}")
            return basic_result

    def _with_provider_overrides(self,
                                 request: ParseRequest,
                                 *,
                                 allow_ocr: bool | None = None,
                                 detect_tables: bool | None = None,
                                 pdf_needs_ocr: bool | None = None,
                                 suppress_ocr_required_error: bool | None = None) -> ParseRequest:
        provider_config = deepcopy(request.provider_config or {})
        if allow_ocr is not None:
            provider_config["allow_ocr"] = allow_ocr
        if detect_tables is not None:
            provider_config["detect_tables"] = detect_tables
        if pdf_needs_ocr is not None:
            provider_config["pdf_needs_ocr"] = pdf_needs_ocr
        if suppress_ocr_required_error is not None:
            provider_config["suppress_ocr_required_error"] = suppress_ocr_required_error

        return ParseRequest(
            company_short_name=request.company_short_name,
            filename=request.filename,
            content=request.content,
            mime_type=request.mime_type,
            metadata=deepcopy(request.metadata or {}),
            collection_name=request.collection_name,
            collection_id=request.collection_id,
            document_id=request.document_id,
            provider_config=provider_config,
        )

    def _resolve_pdf_needs_ocr(self, request: ParseRequest) -> bool | None:
        if not self._is_pdf_request(request):
            return None

        provider_config = request.provider_config or {}
        if "pdf_needs_ocr" in provider_config:
            return self._as_bool(provider_config.get("pdf_needs_ocr"), default=False)

        decision = analyze_pdf_ocr_need(request.content)
        logging.info(
            "PDF OCR decision for auto parsing: filename=%s needs_ocr=%s reason=%s pages=%s image_pages=%s meaningful_pages=%s sparse_image_pages=%s total_text_chars=%s",
            request.filename,
            decision.needs_ocr,
            decision.reason,
            decision.page_count,
            decision.image_page_count,
            decision.meaningful_text_page_count,
            decision.sparse_text_image_page_count,
            decision.total_text_char_count,
        )
        return decision.needs_ocr

    def _has_sufficient_text(self, result: ParseResult) -> bool:
        text_parts = [
            (item.text or "").strip()
            for item in getattr(result, "texts", []) or []
            if (item.text or "").strip()
        ]
        combined = "\n".join(text_parts).strip()
        if not combined:
            return False
        if len(combined) < self.auto_min_text_chars:
            return False
        printable_chars = sum(1 for char in combined if char.isprintable() and not char.isspace())
        return printable_chars >= min(len(combined.replace(" ", "")), self.auto_min_text_chars)

    def _docling_supports(self, request: ParseRequest) -> bool:
        try:
            docling_provider = self.provider_factory.get_provider("docling")
        except Exception:
            return False
        return bool(getattr(docling_provider, "enabled", False)) and bool(docling_provider.supports(request))

    def _can_use_tesseract(self) -> bool:
        return self._get_tesseract_status()[0]

    def _get_tesseract_status(self) -> tuple[bool, str]:
        env_value = os.getenv("TESSERACT_ENABLED")
        if env_value is None or env_value.strip().lower() not in {"1", "true", "yes", "on"}:
            return False, "env_disabled"
        if shutil.which("tesseract") is None:
            return False, "binary_not_found"
        return True, "available"

    def _resolve_detect_tables(self, request: ParseRequest) -> bool:
        value = (request.provider_config or {}).get("detect_tables")
        return self._as_bool(value, default=False)

    @staticmethod
    def _is_pdf_request(request: ParseRequest) -> bool:
        return str(getattr(request, "filename", "") or "").strip().lower().endswith(".pdf")

    @staticmethod
    def _as_bool(value, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            return default
