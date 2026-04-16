# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import fitz
import markdown2
from injector import inject
from jinja2 import Environment, FileSystemLoader
from markupsafe import escape

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService

PDF_MIME = "application/pdf"
DEFAULT_MARGIN = 36
DEFAULT_TEMPLATE = "simple"
DEFAULT_PAGE_SIZE = "A4"
DEFAULT_ORIENTATION = "portrait"
MAX_CONTENT_CHARS = 200_000


class PdfService:
    @inject
    def __init__(self,
                 util: Utility,
                 config_service: ConfigurationService,
                 i18n_service: I18nService,
                 storage_service: StorageService):
        self.util = util
        self.config_service = config_service
        self.i18n_service = i18n_service
        self.storage_service = storage_service

    def pdf_generator(self, company_short_name: str, **kwargs) -> dict | str:
        try:
            filename = (kwargs.get("filename") or "").strip()
            if not filename:
                return self.i18n_service.t("errors.services.no_output_file")
            if not self._is_valid_filename(filename):
                return self.i18n_service.t("errors.services.invalid_filename")

            content = kwargs.get("content")
            if not isinstance(content, str) or not content.strip():
                return self.i18n_service.t("errors.services.no_content_for_pdf")
            if len(content) > MAX_CONTENT_CHARS:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CALL_ERROR,
                    self.i18n_service.t("errors.services.pdf_content_too_large"),
                )

            input_format = self._normalize_input_format(kwargs.get("input_format"))
            if input_format is None:
                return self.i18n_service.t("errors.services.unsupported_pdf_input_format")

            template_name = self._normalize_template(kwargs.get("template"))
            page_size = self._normalize_page_size(kwargs.get("page_size"))
            orientation = self._normalize_orientation(kwargs.get("orientation"))
            title = self._clean_text(kwargs.get("title"))
            subtitle = self._clean_text(kwargs.get("subtitle"))
            company_name = self._resolve_company_name(company_short_name)
            footer_text = self._resolve_generated_by_text()
            generated_date = datetime.now().strftime("%d-%m-%Y")

            body_html = self._content_to_html(content=content, input_format=input_format)
            document_html = self._wrap_html(
                body_html=body_html,
                input_format=input_format,
                template_name=template_name,
                company_name=company_name,
                footer_text=footer_text,
                generated_date=generated_date,
                title=title,
                subtitle=subtitle,
            )
            pdf_bytes = self._render_html_to_pdf(
                html=document_html,
                page_size=page_size,
                orientation=orientation,
            )

            storage_filename = f"{uuid4()}.pdf"
            storage_key = self.storage_service.upload_generated_download(
                company_short_name=company_short_name,
                file_content=pdf_bytes,
                filename=storage_filename,
                mime_type=PDF_MIME,
            )
            attachment_token = self.storage_service.create_download_token(
                company_short_name=company_short_name,
                storage_key=storage_key,
                filename=filename,
            )
            download_link = f"/download/{attachment_token}"

            logging.info(
                "Generated PDF company=%s filename=%s input_format=%s template=%s page_size=%s orientation=%s bytes=%s",
                company_short_name,
                filename,
                input_format,
                template_name,
                page_size,
                orientation,
                len(pdf_bytes),
            )

            return {
                "filename": filename,
                "attachment_token": attachment_token,
                "content_type": PDF_MIME,
                "download_link": download_link,
                "html_download": self._build_download_html(filename, download_link),
            }
        except IAToolkitException:
            raise
        except Exception as exc:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CALL_ERROR,
                self.i18n_service.t("errors.services.cannot_create_pdf"),
            ) from exc

    @staticmethod
    def _is_valid_filename(filename: str) -> bool:
        lowered = filename.lower()
        if not lowered.endswith(".pdf"):
            return False
        return "/" not in filename and "\\" not in filename

    @staticmethod
    def _normalize_input_format(value) -> str | None:
        normalized = str(value or "markdown").strip().lower()
        if normalized in {"md", "markdown"}:
            return "markdown"
        if normalized == "html":
            return "html"
        return None

    @staticmethod
    def _normalize_template(value) -> str:
        normalized = str(value or DEFAULT_TEMPLATE).strip().lower()
        return normalized if normalized in {"simple", "report", "letter"} else DEFAULT_TEMPLATE

    @staticmethod
    def _normalize_page_size(value) -> str:
        normalized = str(value or DEFAULT_PAGE_SIZE).strip().upper()
        return normalized if normalized in {"A4", "LETTER"} else DEFAULT_PAGE_SIZE

    @staticmethod
    def _normalize_orientation(value) -> str:
        normalized = str(value or DEFAULT_ORIENTATION).strip().lower()
        return normalized if normalized in {"portrait", "landscape"} else DEFAULT_ORIENTATION

    @staticmethod
    def _clean_text(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _content_to_html(self, content: str, input_format: str) -> str:
        if input_format == "markdown":
            return markdown2.markdown(
                content,
                extras=["tables", "fenced-code-blocks", "strike", "task_list", "break-on-newline"],
            )
        return self._sanitize_html(content)

    def _wrap_html(self,
                   body_html: str,
                   input_format: str,
                   template_name: str,
                   company_name: str,
                   footer_text: str,
                   generated_date: str,
                   title: str | None,
                   subtitle: str | None) -> str:
        safe_body_html = self._sanitize_html(body_html)
        extra_css = ""
        content_class = ""
        if input_format == "html":
            extra_css = self._load_chat_llm_output_css()
            content_class = "llm-output"

        template = self._get_template_environment().get_template(f"pdf/{template_name}.html")
        return template.render(
            body_html=safe_body_html,
            extra_css=extra_css,
            content_class=content_class,
            company_name=escape(company_name),
            footer_text=escape(footer_text),
            generated_date=escape(generated_date),
            title=escape(title) if title else None,
            subtitle=escape(subtitle) if subtitle else None,
        )

    def _sanitize_html(self, html: str) -> str:
        sanitized = html or ""
        sanitized = re.sub(r"(?is)<script.*?>.*?</script>", "", sanitized)
        sanitized = re.sub(r'(?i)\son\w+\s*=\s*"[^"]*"', "", sanitized)
        sanitized = re.sub(r"(?i)\son\w+\s*=\s*'[^']*'", "", sanitized)
        sanitized = re.sub(r"(?i)\s(src|href)\s*=\s*([\"'])javascript:[^\"']*\2", "", sanitized)
        return sanitized

    def _render_html_to_pdf(self, html: str, page_size: str, orientation: str) -> bytes:
        story = fitz.Story(html=html)
        output = io.BytesIO()
        writer = fitz.DocumentWriter(output)
        mediabox = self._resolve_paper_rect(page_size=page_size, orientation=orientation)
        content_rect = mediabox + (DEFAULT_MARGIN, DEFAULT_MARGIN, -DEFAULT_MARGIN, -DEFAULT_MARGIN)

        def rectfn(rect_num, filled):
            return mediabox, content_rect, fitz.Identity

        try:
            story.write(writer, rectfn)
        finally:
            writer.close()

        pdf_bytes = output.getvalue()
        if not pdf_bytes.startswith(b"%PDF"):
            raise IAToolkitException(
                IAToolkitException.ErrorType.CALL_ERROR,
                self.i18n_service.t("errors.services.cannot_create_pdf"),
            )
        return pdf_bytes

    @staticmethod
    def _resolve_paper_rect(page_size: str, orientation: str) -> fitz.Rect:
        paper_name = "letter" if page_size == "LETTER" else "a4"
        paper_rect = fitz.paper_rect(paper_name)
        if orientation == "landscape":
            return fitz.Rect(0, 0, paper_rect.height, paper_rect.width)
        return fitz.Rect(paper_rect)

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_chat_llm_output_css() -> str:
        css_path = Path(__file__).resolve().parent.parent / "static" / "styles" / "llm_output.css"
        try:
            return css_path.read_text(encoding="utf-8")
        except Exception:
            logging.warning("Could not load chat LLM output CSS for PDF rendering: %s", css_path)
            return ""

    def _resolve_company_name(self, company_short_name: str) -> str:
        company_name = self.config_service.get_configuration(company_short_name, "name")
        if isinstance(company_name, str) and company_name.strip():
            return company_name.strip()
        return company_short_name

    def _resolve_generated_by_text(self) -> str:
        translation = self.i18n_service.t("services.generated_by_iatoolkit")
        if translation and translation != "services.generated_by_iatoolkit":
            return translation
        return "Documento generado por IAToolkit"

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_template_environment() -> Environment:
        template_root = Path(__file__).resolve().parent.parent / "templates"
        return Environment(
            loader=FileSystemLoader(str(template_root)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @staticmethod
    def _build_download_html(filename: str, download_link: str) -> str:
        return (
            f"<p>✅ Tu archivo {escape(filename)} ha sido generado:</p>\n"
            f"<a href=\"{escape(download_link)}\" download>\n"
            "    📥 Descargar\n"
            "</a>"
        )
