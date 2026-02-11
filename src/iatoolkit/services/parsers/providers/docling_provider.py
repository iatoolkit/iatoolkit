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
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False
            pipeline_options.force_backend_text = True
            pipeline_options.generate_picture_images = True
            pipeline_options.do_table_structure = True
            pipeline_options.generate_table_images = True

            # Keep current feature set (tables/images/captions), but reduce memory peaks on small workers.
            pipeline_options.table_structure_options.mode = TableFormerMode.FAST
            pipeline_options.layout_batch_size = self._get_int_env("DOCLING_LAYOUT_BATCH_SIZE", 1)
            pipeline_options.table_batch_size = self._get_int_env("DOCLING_TABLE_BATCH_SIZE", 1)
            pipeline_options.ocr_batch_size = self._get_int_env("DOCLING_OCR_BATCH_SIZE", 1)
            pipeline_options.queue_max_size = self._get_int_env("DOCLING_QUEUE_MAX_SIZE", 12)
            pipeline_options.accelerator_options = AcceleratorOptions(
                num_threads=self._get_int_env("DOCLING_NUM_THREADS", 1),
                device=os.getenv("DOCLING_DEVICE", "cpu"),
            )

            logging.info(
                "Docling low-memory profile: table_mode=%s layout_batch=%s table_batch=%s ocr_batch=%s queue_max=%s threads=%s device=%s",
                pipeline_options.table_structure_options.mode,
                pipeline_options.layout_batch_size,
                pipeline_options.table_batch_size,
                pipeline_options.ocr_batch_size,
                pipeline_options.queue_max_size,
                pipeline_options.accelerator_options.num_threads,
                pipeline_options.accelerator_options.device,
            )

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
            tables = self._extract_tables(doc, doc_dict)
            images = self._extract_images(doc, request.filename, doc_dict)

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

    def _extract_tables(self, doc, doc_dict: dict | None = None) -> list[ParsedTable]:
        tables: list[ParsedTable] = []
        if not hasattr(doc, "tables"):
            return []
        caption_finder = self._build_caption_finder(doc_dict or {})

        for index, tbl in enumerate(doc.tables, start=1):
            try:
                md = tbl.export_to_markdown(doc) if hasattr(tbl, "export_to_markdown") else ""

                data = {}
                if hasattr(tbl, "export_to_dict"):
                    data = tbl.export_to_dict()
                elif hasattr(tbl, "data"):
                    data = tbl.data.dict() if hasattr(tbl.data, "dict") else tbl.data

                page_no = self._extract_page_from_prov(getattr(tbl, "prov", None))
                title, caption_source = self._resolve_table_caption(
                    table_obj=tbl,
                    doc=doc,
                    table_dict=data if isinstance(data, dict) else {},
                    page_no=page_no,
                    table_index=index,
                    caption_finder=caption_finder,
                )

                table_text = md or (str(data) if data else "")
                if not table_text:
                    continue

                meta = {
                    "source_type": "table",
                    "table_index": index,
                    "page": page_no,
                    "title": title,
                    "caption_text": title,
                    "caption_source": caption_source,
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

    def _extract_images(self, doc, filename: str, doc_dict: dict | None = None) -> list[ParsedImage]:
        images: list[ParsedImage] = []
        base_name, _ = os.path.splitext(filename)

        if not hasattr(doc, "pictures"):
            return []
        caption_finder = self._build_caption_finder(doc_dict or {})

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

                page_no = self._extract_page_from_prov(getattr(pic, "prov", None))
                caption_text, caption_source = self._resolve_image_caption(
                    picture_obj=pic,
                    doc=doc,
                    page_no=page_no,
                    image_index=i,
                    caption_finder=caption_finder,
                )

                meta = {
                    "source_type": "image",
                    "page": page_no,
                    "image_index": i,
                    "caption_text": caption_text,
                    "caption_source": caption_source,
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

    def _resolve_table_caption(self,
                               table_obj,
                               doc,
                               table_dict: dict,
                               page_no: Optional[int],
                               table_index: int,
                               caption_finder) -> tuple[Optional[str], str]:
        # 1) Direct caption from docling object
        caption = self._extract_caption_from_obj(table_obj, doc=doc, candidate_fields=("caption_text", "caption", "captions"))
        if caption:
            return caption, "extracted"

        # 2) Caption from exported table dict
        caption = self._extract_caption_from_mapping(
            table_dict,
            candidate_fields=("caption_text", "caption", "title", "name", "captions")
        )
        if caption:
            return caption, "extracted"

        # 3) Fallback from global doc_dict caption blocks (same page / table-like labels)
        caption = caption_finder(kind="table", page_no=page_no, item_index=table_index)
        if caption:
            return caption, "inferred"

        return None, "none"

    def _resolve_image_caption(self,
                               picture_obj,
                               doc,
                               page_no: Optional[int],
                               image_index: int,
                               caption_finder) -> tuple[Optional[str], str]:
        # 1) Direct caption from docling object
        caption = self._extract_caption_from_obj(picture_obj, doc=doc, candidate_fields=("caption_text", "caption", "captions"))
        if caption:
            return caption, "extracted"

        # 2) Fallback from global doc_dict caption blocks (same page / image-like labels)
        caption = caption_finder(kind="image", page_no=page_no, item_index=image_index)
        if caption:
            return caption, "inferred"

        return None, "none"

    def _build_caption_finder(self, doc_dict: dict):
        caption_entries = []
        for pos, item in enumerate(self._walk_items(doc_dict)):
            if not isinstance(item, dict):
                continue

            label = str(item.get("label") or item.get("type") or "").lower()
            text_candidate = self._extract_caption_from_mapping(
                item,
                candidate_fields=("caption_text", "caption", "text", "content")
            )
            if not text_candidate:
                continue

            # keep only likely caption nodes to avoid random body text
            if "caption" not in label:
                continue

            page_no = self._extract_page_from_prov(item.get("prov"))
            kind = "unknown"
            if "table" in label:
                kind = "table"
            elif any(token in label for token in ("figure", "image", "picture")):
                kind = "image"

            caption_entries.append({
                "text": text_candidate,
                "page": page_no,
                "kind": kind,
                "pos": pos,
                "used": False,
            })

        def _find(kind: str, page_no: Optional[int], item_index: int) -> Optional[str]:
            if not caption_entries:
                return None

            # Preferred: same kind + same page
            for entry in caption_entries:
                if entry["used"]:
                    continue
                if entry["kind"] not in (kind, "unknown"):
                    continue
                if page_no is not None and entry["page"] != page_no:
                    continue
                entry["used"] = True
                return entry["text"]

            # Fallback: same kind regardless of page
            for entry in caption_entries:
                if entry["used"]:
                    continue
                if entry["kind"] not in (kind, "unknown"):
                    continue
                entry["used"] = True
                return entry["text"]

            return None

        return _find

    @staticmethod
    def _extract_page_from_prov(prov_value) -> Optional[int]:
        if not prov_value:
            return None
        if isinstance(prov_value, list) and prov_value:
            first = prov_value[0]
        else:
            first = prov_value

        if isinstance(first, dict):
            page = first.get("page_no") or first.get("page")
            return page if isinstance(page, int) else None

        page = getattr(first, "page_no", None)
        return page if isinstance(page, int) else None

    def _extract_caption_from_obj(self, obj, doc, candidate_fields: tuple[str, ...]) -> Optional[str]:
        for field in candidate_fields:
            if not hasattr(obj, field):
                continue
            raw = getattr(obj, field)
            if callable(raw):
                try:
                    raw = raw(doc)
                except TypeError:
                    try:
                        raw = raw()
                    except Exception:
                        continue
                except Exception:
                    continue
            normalized = self._normalize_caption_value(raw)
            if normalized:
                return normalized
        return None

    def _extract_caption_from_mapping(self, mapping: dict, candidate_fields: tuple[str, ...]) -> Optional[str]:
        if not isinstance(mapping, dict):
            return None
        for field in candidate_fields:
            if field not in mapping:
                continue
            normalized = self._normalize_caption_value(mapping.get(field))
            if normalized:
                return normalized
        return None

    def _normalize_caption_value(self, value) -> Optional[str]:
        if value is None:
            return None

        if isinstance(value, str):
            text = value.strip()
            return text if text else None

        if isinstance(value, (int, float, bool)):
            return str(value)

        if isinstance(value, list):
            parts = [self._normalize_caption_value(v) for v in value]
            parts = [p for p in parts if p]
            return " ".join(parts).strip() if parts else None

        if isinstance(value, dict):
            # Common patterns in nested structures
            for key in ("text", "caption_text", "caption", "content", "title", "name"):
                if key in value:
                    normalized = self._normalize_caption_value(value.get(key))
                    if normalized:
                        return normalized
            return None

        return None

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

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            logging.warning("Invalid value for %s=%r. Using default=%s", name, value, default)
            return default
