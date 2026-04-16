# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import logging
import os
import shutil

import fitz
import pytesseract
from docx import Document
from injector import inject, singleton
from PIL import Image

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.parsers.contracts import ParseRequest, ParseResult, ParsedImage, ParsedText
from iatoolkit.services.parsers.image_normalizer import normalize_image
from iatoolkit.services.parsers.pdf_ocr_detection import analyze_pdf_ocr_need


@singleton
class BasicParsingProvider:
    name = "basic"
    version = "1.0"

    @inject
    def __init__(self,
                 excel_service: ExcelService,
                 i18n_service: I18nService):
        self.excel_service = excel_service
        self.i18n_service = i18n_service
        self.max_doc_pages = int(os.getenv("MAX_DOC_PAGES", "200"))

    def supports(self, request: ParseRequest) -> bool:
        return True

    def parse(self, request: ParseRequest) -> ParseResult:
        allow_ocr = self._should_use_ocr(request)
        pdf_needs_ocr = self._resolve_pdf_needs_ocr(request)
        self._raise_if_ocr_required_but_unavailable(request, pdf_needs_ocr)
        text = self.extract_text(
            request.filename,
            request.content,
            allow_ocr=allow_ocr,
            pdf_needs_ocr=pdf_needs_ocr,
        )

        result = ParseResult(
            provider=self.name,
            provider_version=self.version,
            metrics={"used_ocr": allow_ocr},
        )

        if text and text.strip():
            result.texts.append(ParsedText(
                text=text,
                meta={
                    "source_type": "text",
                    "source_label": "basic",
                }
            ))

        if request.filename.lower().endswith('.pdf'):
            figures = self.pdf_to_figure_entries(request.content)
            for index, figure in enumerate(figures or [], start=1):
                try:
                    pix = figure["pixmap"]
                    content, filename, mime_type, color_mode, width, height = normalize_image(
                        pix,
                        filename_hint=f"{request.filename}_img_{index}",
                        output_format="PNG",
                    )
                    result.images.append(ParsedImage(
                        content=content,
                        filename=filename,
                        mime_type=mime_type,
                        color_mode=color_mode,
                        width=width,
                        height=height,
                        meta={
                            "source_type": "image",
                            "page": figure.get("page"),
                            "image_index": index,
                            "caption_text": None,
                            "caption_source": "none",
                        }
                    ))
                except Exception as e:
                    result.warnings.append(f"Failed to normalize fallback image {index}: {e}")

        if allow_ocr and request.filename.lower().endswith(".pdf"):
            result.metrics["ocr_engine"] = "tesseract"

        return result

    def _should_use_ocr(self, request: ParseRequest) -> bool:
        if not request.filename.lower().endswith(".pdf"):
            return False

        provider_config = request.provider_config or {}
        if "allow_ocr" in provider_config:
            return self._as_bool(provider_config.get("allow_ocr"), default=False)

        metadata = request.metadata or {}
        if metadata.get("source") == "prompt_task_attachment":
            return False

        return self._can_use_tesseract()

    @staticmethod
    def _can_use_tesseract() -> bool:
        return BasicParsingProvider._get_tesseract_status()[0]

    @staticmethod
    def _get_tesseract_status() -> tuple[bool, str]:
        env_value = os.getenv("TESSERACT_ENABLED")
        if env_value is None or env_value.strip().lower() not in {"1", "true", "yes", "on"}:
            return False, "env_disabled"
        if shutil.which("tesseract") is None:
            return False, "binary_not_found"
        return True, "available"

    def extract_text(self, filename, file_content, allow_ocr: bool = False, pdf_needs_ocr: bool | None = None):
        return self.file_to_txt(filename, file_content, allow_ocr=allow_ocr, pdf_needs_ocr=pdf_needs_ocr)

    def file_to_txt(self, filename, file_content, allow_ocr: bool = False, pdf_needs_ocr: bool | None = None):
        try:
            if filename.lower().endswith('.docx'):
                return self.read_docx(file_content)
            if filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
                if isinstance(file_content, bytes):
                    try:
                        file_content = file_content.decode('utf-8')
                    except UnicodeDecodeError:
                        raise IAToolkitException(
                            IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                            self.i18n_service.t('errors.services.no_text_file'),
                        )

                return file_content
            if filename.lower().endswith('.pdf'):
                if self.is_scanned_pdf(file_content, precomputed=pdf_needs_ocr):
                    return self.read_scanned_pdf(file_content) if allow_ocr else ""
                return self.read_pdf(file_content)
            if filename.lower().endswith(('.xlsx', '.xls')):
                return self.excel_service.read_excel(file_content)
            if filename.lower().endswith('.csv'):
                return self.excel_service.read_csv(file_content)
            raise IAToolkitException(
                IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                "Formato de archivo desconocido",
            )
        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(
                IAToolkitException.ErrorType.FILE_IO_ERROR,
                f"Error processing file: {e}",
            ) from e

    def read_docx(self, file_content):
        try:
            file_like_object = io.BytesIO(file_content)
            doc = Document(file_like_object)

            md_content = ""
            for para in doc.paragraphs:
                if para.style.name.startswith("Heading"):
                    level = int(para.style.name.replace("Heading ", ""))
                    md_content += f"{'#' * level} {para.text}\n\n"
                elif para.style.name in ["List Bullet", "List Paragraph"]:
                    md_content += f"- {para.text}\n"
                elif para.style.name in ["List Number"]:
                    md_content += f"1. {para.text}\n"
                else:
                    md_content += f"{para.text}\n\n"
            return md_content
        except Exception as e:
            raise ValueError(f"Error reading .docx file: {e}")

    def read_pdf(self, file_content):
        try:
            with fitz.open(stream=file_content, filetype="pdf") as pdf:
                text = ""
                for page in pdf:
                    text += page.get_text()
                return text
        except Exception as e:
            raise ValueError(f"Error reading .pdf file: {e}")

    def is_scanned_pdf(self, file_content, precomputed: bool | None = None):
        if precomputed is not None:
            return precomputed

        decision = analyze_pdf_ocr_need(file_content)
        logging.debug(
            "PDF OCR decision for basic provider: needs_ocr=%s reason=%s pages=%s image_pages=%s meaningful_pages=%s sparse_image_pages=%s total_text_chars=%s",
            decision.needs_ocr,
            decision.reason,
            decision.page_count,
            decision.image_page_count,
            decision.meaningful_text_page_count,
            decision.sparse_text_image_page_count,
            decision.total_text_char_count,
        )
        return decision.needs_ocr

    def _resolve_pdf_needs_ocr(self, request: ParseRequest) -> bool | None:
        if not request.filename.lower().endswith(".pdf"):
            return None

        provider_config = request.provider_config or {}
        if "pdf_needs_ocr" in provider_config:
            return self._as_bool(provider_config.get("pdf_needs_ocr"), default=False)

        return None

    def _raise_if_ocr_required_but_unavailable(self, request: ParseRequest, pdf_needs_ocr: bool | None) -> None:
        if not pdf_needs_ocr:
            return

        provider_config = request.provider_config or {}
        if self._as_bool(provider_config.get("suppress_ocr_required_error"), default=False):
            return

        can_use_tesseract, reason = self._get_tesseract_status()
        if can_use_tesseract:
            return

        raise IAToolkitException(
            IAToolkitException.ErrorType.CONFIG_ERROR,
            f"PDF '{request.filename}' requires OCR but Tesseract is unavailable ({reason}).",
        )

    def read_scanned_pdf(self, file_content):
        images = self.pdf_to_images(file_content)
        if not images:
            return ''

        document_text = ''
        for image in images:
            document_text += self.image_to_text(image)

        return document_text

    def pdf_to_images(self, file_content):
        figures = self.pdf_to_figure_entries(file_content)
        return [figure["pixmap"] for figure in figures or []]

    def pdf_to_figure_entries(self, file_content):
        figures = []

        pdf_document = fitz.open(stream=io.BytesIO(file_content), filetype='pdf')
        if pdf_document.page_count > self.max_doc_pages:
            pdf_document.close()
            return None

        try:
            for page_number in range(len(pdf_document)):
                page = pdf_document[page_number]

                images_on_page = page.get_images(full=True)
                for img in images_on_page:
                    xref = img[0]
                    pix = fitz.Pixmap(pdf_document, xref)
                    figures.append({
                        "page": page_number + 1,
                        "pixmap": pix,
                    })
        finally:
            pdf_document.close()
        return figures

    def image_to_text(self, image):
        if image.n == 1:
            pil_mode = "L"
        elif image.n == 2:
            pil_mode = "LA"
        elif image.n == 3:
            pil_mode = "RGB"
        elif image.n == 4:
            pil_mode = "RGBA"
        else:
            raise ValueError(f"Canales desconocidos: {image.n}")

        img = Image.frombytes(pil_mode, (image.width, image.height), image.samples)
        return pytesseract.image_to_string(img, lang="spa")

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
