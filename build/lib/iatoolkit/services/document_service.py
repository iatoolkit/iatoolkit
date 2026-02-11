# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from docx import Document
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import pytesseract
from injector import inject
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.excel_service import ExcelService
import logging

class DocumentService:
    @inject
    def __init__(self,
                 excel_service: ExcelService,
                 i18n_service: I18nService):
        self.excel_service = excel_service
        self.i18n_service = i18n_service

        # max number of pages to load
        self.max_doc_pages = int(os.getenv("MAX_DOC_PAGES", "200"))

    def file_to_txt(self, filename, file_content):
        try:
            if filename.lower().endswith('.docx'):
                return self.read_docx(file_content)
            elif filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
                if isinstance(file_content, bytes):
                    try:
                        # decode using UTF-8
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
        except IAToolkitException as e:
            # Si es una excepción conocida, simplemente la relanzamos
            raise
        except Exception as e:
            logging.exception(e)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR,
                                   f"Error processing file: {e}") from e

    def read_docx(self, file_content):
        try:
            # Crear un archivo en memoria desde el contenido en bytes
            file_like_object = io.BytesIO(file_content)
            doc = Document(file_like_object)

            # to Markdown
            md_content = ""
            for para in doc.paragraphs:
                # headings ...
                if para.style.name.startswith("Heading"):
                    level = int(para.style.name.replace("Heading ", ""))
                    md_content += f"{'#' * level} {para.text}\n\n"
                # lists ...
                elif para.style.name in ["List Bullet", "List Paragraph"]:
                    md_content += f"- {para.text}\n"
                elif para.style.name in ["List Number"]:
                    md_content += f"1. {para.text}\n"
                # normal text
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

    # Determina  es un documento escaneado (imagen) o contiene prompt_llm.txt seleccionable.
    def is_scanned_pdf(self, file_content):
        doc = fitz.open(stream=io.BytesIO(file_content), filetype='pdf')

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Intenta extraer prompt_llm.txt directamente
            text = page.get_text()
            if text.strip():  # Si hay prompt_llm.txt, no es escaneado
                return False

            # Busca imágenes en la página
            images = page.get_images(full=True)
            if images:  # Si hay imágenes pero no hay prompt_llm.txt, puede ser un escaneo
                continue

        # Si no se encontró prompt_llm.txt en ninguna página
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
        images = []             # list of images to return

        pdf_document = fitz.open(stream=io.BytesIO(file_content), filetype='pdf')
        if pdf_document.page_count > self.max_doc_pages:
            return None

        for page_number in range(len(pdf_document)):
            page = pdf_document[page_number]

            images_on_page = page.get_images(full=True)  # Obtiene todas las imágenes de la página
            for img in images_on_page:
                xref = img[0]  # Referencia de la imagen en el PDF
                pix = fitz.Pixmap(pdf_document, xref)  # Crear el Pixmap de la imagen

                # Si la imagen está en CMYK, conviértela a RGB para mayor compatibilidad
                if pix.n > 4:  # CMYK tiene más de 4 canales
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                images.append(pix)

        pdf_document.close()
        return images

    def image_to_text(self, image):
        # Determinar el modo PIL en base a pix.n
        if image.n == 1:
            pil_mode = "L"
        elif image.n == 2:
            pil_mode = "LA"
        elif image.n == 3:
            pil_mode = "RGB"
        elif image.n == 4:
            pil_mode = "RGBA"
        else:
            # Caso especial (conversion previa debería evitarlos)
            raise ValueError(f"Canales desconocidos: {image.n}")

        img = Image.frombytes(pil_mode, (image.width, image.height), image.samples)
        return pytesseract.image_to_string(img, lang="spa")




