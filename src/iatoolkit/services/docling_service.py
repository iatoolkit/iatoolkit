# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Any
import base64
import logging
import os
import tempfile

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.configuration_service import ConfigurationService


@dataclass
class DoclingTextBlock:
    text: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    block_type: str = "text"
    section_title: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class DoclingTable:
    markdown: str
    table_json: dict
    page: Optional[int] = None
    title: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class DoclingImage:
    content: bytes
    filename: str
    page: Optional[int] = None
    image_index: Optional[int] = None
    caption_text: Optional[str] = None
    caption_source: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class DoclingResult:
    text_blocks: List[DoclingTextBlock]
    tables: List[DoclingTable]
    images: List[DoclingImage]
    full_text: str


class DoclingService:
    @inject
    def __init__(self,
                 i18n_service: I18nService):
        self.i18n_service = i18n_service
        self.enabled = os.getenv("DOCLING_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
        self.converter = None

    def init(self):
        """
        Preloads Docling models and configuration to avoid latency on the first request.
        Called by IAToolkit core during startup.
        """
        if not self.enabled:
            logging.info("DoclingService is disabled via environment variables.")
            return

        try:
            logging.info("🚀 Initializing Docling models (this may take a while)...")

            # Import here to avoid slowing down imports if service is disabled
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            # Configure standard options for the singleton converter
            pipeline_options = PdfPipelineOptions()
            pipeline_options.generate_picture_images = True
            pipeline_options.do_table_structure = True
            pipeline_options.generate_table_images = True

            # Instantiate the converter (loads PyTorch models into RAM)
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
            logging.info("✅ Docling models successfully loaded.")
        except Exception as e:
            logging.error(f"❌ Failed to initialize DoclingService: {e}")
            # We explicitly disable the service if models fail to load to prevent runtime errors later
            self.enabled = False

    def supports(self, filename: str) -> bool:
        if not filename:
            return False
        _, ext = os.path.splitext(filename.lower())
        return ext in {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}

    def convert(self, filename: str, content: bytes) -> DoclingResult:
        if not self.enabled:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                self.i18n_service.t("errors.services.docling_disabled")
                if self.i18n_service else "Docling is disabled"
            )

        # Lazy initialization safeguard if init() wasn't called manually or failed silently
        if self.converter is None:
            self.init()
            if self.converter is None:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    "Docling converter failed to initialize."
                )

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
            tmp.write(content)
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

            text_blocks = self._extract_text_blocks(doc_dict, markdown)
            tables = self._extract_tables_from_object(doc)
            images = self._extract_images_from_object(doc, filename)

            full_text = markdown or "\n\n".join([block.text for block in text_blocks if block.text])

            return DoclingResult(
                text_blocks=text_blocks,
                tables=tables,
                images=images,
                full_text=full_text
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _extract_text_blocks(self, doc_dict: dict, markdown: str) -> List[DoclingTextBlock]:
        if not doc_dict:
            return [DoclingTextBlock(text=markdown)] if markdown else []

        blocks: List[DoclingTextBlock] = []

        # Variable de estado para rastrear el título de la sección actual mientras bajamos por el doc
        current_section_title = None

        for item in self._walk_items(doc_dict):
            if not isinstance(item, dict):
                continue

            # Normalizamos el tipo de etiqueta
            label = (item.get("label") or item.get("type") or "").lower()
            text = item.get("text") or item.get("content") or ""

            if not text:
                continue

            # 1. Gestión de Títulos de Sección
            # Si el item actual es un encabezado, actualizamos el estado actual
            if label in ("title", "section_header", "page_header", "header"):
                current_section_title = text

            # 2. Extracción de Página (Proveniencia)
            # Docling guarda esto en 'prov': [{'page_no': 1, ...}]
            page_start = None
            page_end = None
            provs = item.get("prov", [])
            if provs and isinstance(provs, list):
                page_start = provs[0].get("page_no")
                page_end = provs[-1].get("page_no")

            # Solo procesamos si es texto, párrafo o encabezado
            if label in ("text", "paragraph", "body_text", "list_item", "section_header", "title"):
                blocks.append(DoclingTextBlock(
                    text=text,
                    page_start=page_start,
                    page_end=page_end,
                    block_type=label,
                    section_title=current_section_title, # Asignamos el título rastreado
                    meta=self._extract_meta(item, exclude_keys={"text", "content", "prov", "orig", "children"})
                ))

        if not blocks and markdown:
            blocks.append(DoclingTextBlock(text=markdown))

        return blocks

    def _extract_tables_from_object(self, doc) -> List[DoclingTable]:
        """Extrae tablas usando el modelo de objetos de Docling."""
        tables: List[DoclingTable] = []
        if not hasattr(doc, "tables"):
            return []

        for tbl in doc.tables:
            try:
                # INTENTO 1: Usar export_to_markdown directamente del objeto tabla
                if hasattr(tbl, "export_to_markdown"):
                    md = tbl.export_to_markdown(doc)
                else:
                    md = ""

                # Obtener representación en diccionario/json
                data = {}
                if hasattr(tbl, "export_to_dict"):
                    data = tbl.export_to_dict()
                elif hasattr(tbl, "data"):
                    # Algunas versiones guardan la grid en .data
                    data = tbl.data.dict() if hasattr(tbl.data, "dict") else tbl.data

                # 1. Obtener Página correctamente desde 'prov' en el objeto
                page_no = None
                if hasattr(tbl, "prov") and tbl.prov:
                    # tbl.prov es una lista de celdas/tokens, tomamos el primero
                    page_no = tbl.prov[0].page_no

                # 2. Obtener Título (Caption)
                # En versiones recientes es una propiedad 'caption_text'
                title = None
                if hasattr(tbl, "caption_text"):
                    # A veces requiere pasar el doc como contexto, a veces es string
                    if callable(tbl.caption_text):
                        try:
                            title = tbl.caption_text(doc)
                        except:
                            pass
                    else:
                        title = tbl.caption_text

                # Fallback si no hay caption_text
                if not title and hasattr(tbl, "name"):
                    title = tbl.name

                # Extract simple metadata
                meta = self._extract_meta(data, exclude_keys={'data', 'grid', 'cells', 'table_cells', 'rows', 'children', 'tokens'})

                tables.append(DoclingTable(
                    markdown=md,
                    table_json=data,
                    page=page_no,
                    title=title,
                    meta=meta
                ))
            except Exception as e:
                logging.warning(f"Error extracting table: {e}")
                continue

        return tables

    def _extract_images_from_object(self, doc, filename: str) -> List[DoclingImage]:
        """Extrae imágenes (PIL) directamente del objeto Docling."""
        images: List[DoclingImage] = []
        base_name, _ = os.path.splitext(filename)

        if not hasattr(doc, "pictures"):
            return []

        # Iterar sobre las imágenes detectadas y generadas
        for i, pic in enumerate(doc.pictures):
            try:
                img_obj = None

                # ESTRATEGIA 1: Obtener imagen via get_image(doc) -> Estándar v2
                if hasattr(pic, "get_image"):
                    img_obj = pic.get_image(doc)

                # ESTRATEGIA 2: Si la imagen está en el atributo .image (PIL Image directo)
                elif hasattr(pic, "image") and pic.image is not None:
                    img_obj = pic.image

                # ESTRATEGIA 3: Buscar en doc.resources usando la URI si existe
                elif hasattr(pic, "image") and hasattr(pic.image, "uri"):
                    # A veces pic.image es una referencia con URI, no el PIL
                    # Esto depende de cómo Docling gestione internamente los recursos
                    pass

                if img_obj:
                    import io
                    img_byte_arr = io.BytesIO()
                    # Convertir PIL Image a bytes PNG
                    img_obj.save(img_byte_arr, format='PNG')
                    content = img_byte_arr.getvalue()

                    # Obtener metadatos
                    page_no = None
                    if hasattr(pic, "prov") and pic.prov:
                        page_no = pic.prov[0].page_no

                    images.append(DoclingImage(
                        content=content,
                        filename=f"{base_name}_img_{i+1}.png",
                        page=page_no,
                        image_index=i+1,
                        caption_text=None,
                        meta={}
                    ))
                else:
                    logging.debug(f"Image {i} found but no bitmap data available.")

            except Exception as e:
                logging.warning(f"Error extracting image {i}: {e}")
                continue

        return images

    def _extract_meta(self, item: dict, exclude_keys: set[str]) -> dict:
        """Helper para extraer metadatos planos de un diccionario."""
        meta = {}
        for key, value in item.items():
            if key in exclude_keys:
                continue
            # Solo guardamos tipos de datos simples para metadatos
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
