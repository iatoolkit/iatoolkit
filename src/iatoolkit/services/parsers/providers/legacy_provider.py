# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import io
import logging
import os

import fitz
import pytesseract
from docx import Document
from injector import inject
from PIL import Image

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.parsers.contracts import ParseRequest, ParseResult, ParsedImage, ParsedText
from iatoolkit.services.parsers.image_normalizer import normalize_image


class LegacyParsingProvider:
    name = "legacy"
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
        text = self.extract_text(request.filename, request.content)

        result = ParseResult(
            provider=self.name,
            provider_version=self.version,
        )

        if text and text.strip():
            result.texts.append(ParsedText(
                text=text,
                meta={
                    "source_type": "text",
                    "source_label": "legacy",
                }
            ))

        if request.filename.lower().endswith('.pdf'):
            images = self.pdf_to_images(request.content)
            for index, pix in enumerate(images or [], start=1):
                try:
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
                            "image_index": index,
                            "caption_text": None,
                            "caption_source": "none",
                        }
                    ))
                except Exception as e:
                    result.warnings.append(f"Failed to normalize fallback image {index}: {e}")

        return result

    def extract_text(self, filename, file_content):
        return self.file_to_txt(filename, file_content)

    def file_to_txt(self, filename, file_content):
        try:
            if filename.lower().endswith('.docx'):
                return self.read_docx(file_content)
            elif filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
                if isinstance(file_content, bytes):
                    try:
                        file_content = file_content.decode('utf-8')
                    except UnicodeDecodeError:
                        raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                                                 self.i18n_service.t('errors.services.no_text_file'))

                return file_content
            elif filename.lower().endswith('.pdf'):
                if self.is_scanned_pdf(file_content):
                    return self.read_scanned_pdf(file_content)
                else:
                    return self.read_pdf(file_content)
            elif filename.lower().endswith(('.xlsx', '.xls')):
                return self.excel_service.read_excel(file_content)
            elif filename.lower().endswith('.csv'):
                return self.excel_service.read_csv(file_content)
            else:
                raise IAToolkitException(IAToolkitException.ErrorType.FILE_FORMAT_ERROR,
                                         "Formato de archivo desconocido")
        except IAToolkitException:
            raise
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                     f"Error processing file: {e}") from e

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

    def is_scanned_pdf(self, file_content):
        doc = fitz.open(stream=io.BytesIO(file_content), filetype='pdf')

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                return False

            images = page.get_images(full=True)
            if images:
                continue

        return True

    def read_scanned_pdf(self, file_content):
        images = self.pdf_to_images(file_content)
        if not images:
            return ''

        document_text = ''
        for image in images:
            document_text += self.image_to_text(image)

        return document_text

    def pdf_to_images(self, file_content):
        images = []

        pdf_document = fitz.open(stream=io.BytesIO(file_content), filetype='pdf')
        if pdf_document.page_count > self.max_doc_pages:
            return None

        for page_number in range(len(pdf_document)):
            page = pdf_document[page_number]

            images_on_page = page.get_images(full=True)
            for img in images_on_page:
                xref = img[0]
                pix = fitz.Pixmap(pdf_document, xref)
                images.append(pix)

        pdf_document.close()
        return images

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
