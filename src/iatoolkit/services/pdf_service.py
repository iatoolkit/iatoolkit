# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import logging
import re
from uuid import uuid4

import fitz
import markdown2
from injector import inject
from jinja2 import Template
from markupsafe import escape

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService

PDF_MIME = "application/pdf"
DEFAULT_MARGIN = 36
DEFAULT_TEMPLATE = "simple"
DEFAULT_PAGE_SIZE = "A4"
DEFAULT_ORIENTATION = "portrait"
MAX_CONTENT_CHARS = 200_000

BASE_HTML_TEMPLATE = Template("""
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      @page { size: auto; margin: 0; }
      body {
        font-family: Helvetica, Arial, sans-serif;
        font-size: 11pt;
        line-height: 1.45;
        color: #222;
      }
      h1, h2, h3, h4, h5, h6 {
        color: #111;
        margin: 0.6em 0 0.35em;
      }
      p, ul, ol {
        margin: 0.35em 0 0.7em;
      }
      code, pre {
        font-family: Courier, monospace;
        font-size: 10pt;
      }
      pre {
        white-space: pre-wrap;
        border: 1px solid #ddd;
        padding: 10px;
        background: #f7f7f7;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        margin: 0.5em 0 1em;
      }
      th, td {
        border: 1px solid #cfcfcf;
        padding: 6px 8px;
        vertical-align: top;
      }
      th {
        background: #f1f1f1;
        text-align: left;
      }
      blockquote {
        border-left: 3px solid #d0d0d0;
        padding-left: 12px;
        color: #555;
      }
      .document-title {
        margin-bottom: 18px;
      }
      .document-title h1 {
        margin: 0;
        font-size: {% if template == 'letter' %}18pt{% elif template == 'report' %}20pt{% else %}19pt{% endif %};
      }
      .document-title p {
        margin: 6px 0 0;
        color: #666;
      }
      {% if template == 'letter' %}
      .content {
        font-size: 11.5pt;
      }
      {% elif template == 'report' %}
      .content h2 {
        border-bottom: 1px solid #ddd;
        padding-bottom: 4px;
      }
      {% endif %}
    </style>
  </head>
  <body>
    {% if title %}
    <div class="document-title">
      <h1>{{ title }}</h1>
      {% if subtitle %}<p>{{ subtitle }}</p>{% endif %}
    </div>
    {% endif %}
    <div class="content">
      {{ body_html }}
    </div>
  </body>
</html>
""")


class PdfService:
    @inject
    def __init__(self,
                 util: Utility,
                 i18n_service: I18nService,
                 storage_service: StorageService):
        self.util = util
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

            body_html = self._content_to_html(content=content, input_format=input_format)
            document_html = self._wrap_html(
                body_html=body_html,
                template_name=template_name,
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
                "download_link": f"/download/{attachment_token}",
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
                   template_name: str,
                   title: str | None,
                   subtitle: str | None) -> str:
        safe_body_html = self._sanitize_html(body_html)
        return BASE_HTML_TEMPLATE.render(
            body_html=safe_body_html,
            template=template_name,
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
