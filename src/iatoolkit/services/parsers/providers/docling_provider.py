# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Optional

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.parsers.contracts import ParseRequest, ParseResult, ParsedImage, ParsedTable, ParsedText
from iatoolkit.services.parsers.image_normalizer import normalize_image


class DoclingParsingProvider:
    name = "docling"
    version = "1.0"

    @inject
    def __init__(self,
                 i18n_service: I18nService):
        self.i18n_service = i18n_service
        self.enabled = os.getenv("DOCLING_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        self.converter = None

    def init(self):
        if not self.enabled:
            logging.info("DoclingParsingProvider is disabled via environment variables.")
            return

        try:
            logging.info("Initializing Docling models...")

            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            pipeline_options = PdfPipelineOptions()
            pipeline_options.generate_picture_images = True
            pipeline_options.do_table_structure = True
            pipeline_options.generate_table_images = True

            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
            logging.info("Docling models successfully loaded.")
        except Exception as e:
            logging.error(f"Failed to initialize DoclingParsingProvider: {e}")
            self.enabled = False

    def supports(self, request: ParseRequest) -> bool:
        filename = request.filename
        if not filename:
            return False
        _, ext = os.path.splitext(filename.lower())
        return ext in {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}

    def parse(self, request: ParseRequest) -> ParseResult:
        if not self.enabled:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                self.i18n_service.t("errors.services.docling_disabled")
                if self.i18n_service else "Docling is disabled"
            )

        if self.converter is None:
            self.init()
            if self.converter is None:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    "Docling converter failed to initialize."
                )

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(request.filename)[1]) as tmp:
            tmp.write(request.content)
            tmp_path = tmp.name

        try:
            conversion_result = self.converter.convert(tmp_path)
            doc = conversion_result.document

            markdown = ""
            try:
                markdown = doc.export_to_markdown()
            except Exception:
                markdown = ""

            doc_dict: dict[str, Any] = {}
            try:
                doc_dict = doc.export_to_dict()
            except Exception:
                doc_dict = {}

            texts = self._extract_texts(doc_dict, markdown)
            tables = self._extract_tables(doc)
            images = self._extract_images(doc, request.filename)

            return ParseResult(
                provider=self.name,
                provider_version=self.version,
                texts=texts,
                tables=tables,
                images=images,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _extract_texts(self, doc_dict: dict, markdown: str) -> list[ParsedText]:
        if not doc_dict:
            return [ParsedText(text=markdown, meta={"source_type": "text", "source_label": "markdown"})] if markdown else []

        texts: list[ParsedText] = []
        current_section_title = None

        for item in self._walk_items(doc_dict):
            if not isinstance(item, dict):
                continue

            label = (item.get("label") or item.get("type") or "").lower()
            text = item.get("text") or item.get("content") or ""
            if not text:
                continue

            if label in ("title", "section_header", "page_header", "header"):
                current_section_title = text

            # by design we do not emit list_item or section_header as embeddable units
            if label not in ("text", "paragraph", "body_text", "title"):
                continue

            page_start, page_end = self._extract_pages(item.get("prov", []))

            meta = {
                "source_type": "text",
                "source_label": label,
                "page_start": page_start,
                "page_end": page_end,
                "section_title": current_section_title,
                "caption_text": None,
                "caption_source": "none",
            }
            meta.update(self._extract_meta(item, exclude_keys={"text", "content", "prov", "orig", "children"}))
            texts.append(ParsedText(text=text, meta=meta))

        if not texts and markdown:
            texts.append(ParsedText(text=markdown, meta={"source_type": "text", "source_label": "markdown"}))

        return texts

    def _extract_tables(self, doc) -> list[ParsedTable]:
        tables: list[ParsedTable] = []
        if not hasattr(doc, "tables"):
            return []

        for index, tbl in enumerate(doc.tables, start=1):
            try:
                md = tbl.export_to_markdown(doc) if hasattr(tbl, "export_to_markdown") else ""

                data = {}
                if hasattr(tbl, "export_to_dict"):
                    data = tbl.export_to_dict()
                elif hasattr(tbl, "data"):
                    data = tbl.data.dict() if hasattr(tbl.data, "dict") else tbl.data

                page_no = None
                if hasattr(tbl, "prov") and tbl.prov:
                    page_no = getattr(tbl.prov[0], "page_no", None)

                title = None
                if hasattr(tbl, "caption_text"):
                    if callable(tbl.caption_text):
                        try:
                            title = tbl.caption_text(doc)
                        except Exception:
                            title = None
                    else:
                        title = tbl.caption_text
                if not title and hasattr(tbl, "name"):
                    title = tbl.name

                table_text = md or (str(data) if data else "")
                if not table_text:
                    continue

                meta = {
                    "source_type": "table",
                    "table_index": index,
                    "page": page_no,
                    "title": title,
                    "caption_text": title,
                    "caption_source": "extracted" if title else "none",
                }
                meta.update(self._extract_meta(data, exclude_keys={'data', 'grid', 'cells', 'table_cells', 'rows', 'children', 'tokens'}))

                tables.append(ParsedTable(
                    text=table_text,
                    table_json=data,
                    meta=meta,
                ))
            except Exception as e:
                logging.warning(f"Error extracting table: {e}")
                continue

        return tables

    def _extract_images(self, doc, filename: str) -> list[ParsedImage]:
        images: list[ParsedImage] = []
        base_name, _ = os.path.splitext(filename)

        if not hasattr(doc, "pictures"):
            return []

        for i, pic in enumerate(doc.pictures, start=1):
            try:
                img_obj = None
                if hasattr(pic, "get_image"):
                    img_obj = pic.get_image(doc)
                elif hasattr(pic, "image") and pic.image is not None:
                    img_obj = pic.image

                if not img_obj:
                    continue

                content, normalized_filename, mime_type, color_mode, width, height = normalize_image(
                    img_obj,
                    filename_hint=f"{base_name}_img_{i}",
                    output_format="PNG",
                )

                page_no = None
                if hasattr(pic, "prov") and pic.prov:
                    page_no = getattr(pic.prov[0], "page_no", None)

                meta = {
                    "source_type": "image",
                    "page": page_no,
                    "image_index": i,
                    "caption_text": None,
                    "caption_source": "none",
                }

                images.append(ParsedImage(
                    content=content,
                    filename=normalized_filename,
                    mime_type=mime_type,
                    color_mode=color_mode,
                    width=width,
                    height=height,
                    meta=meta,
                ))
            except Exception as e:
                logging.warning(f"Error extracting image {i}: {e}")
                continue

        return images

    @staticmethod
    def _extract_pages(provs: list) -> tuple[Optional[int], Optional[int]]:
        page_start = None
        page_end = None
        if provs and isinstance(provs, list):
            try:
                page_start = provs[0].get("page_no")
                page_end = provs[-1].get("page_no")
            except Exception:
                pass
        return page_start, page_end

    def _extract_meta(self, item: dict, exclude_keys: set[str]) -> dict:
        meta = {}
        for key, value in item.items():
            if key in exclude_keys:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                meta[key] = value
        return meta

    def _walk_items(self, node: Any):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from self._walk_items(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._walk_items(value)
