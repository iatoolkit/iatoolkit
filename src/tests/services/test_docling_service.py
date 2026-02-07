# tests/services/test_docling_service.py

import pytest
from unittest.mock import MagicMock, patch
import os
import sys
from iatoolkit.services.docling_service import DoclingService, DoclingResult, DoclingTable
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException

class TestDoclingService:

    @pytest.fixture
    def mock_i18n(self):
        service = MagicMock(spec=I18nService)
        service.t.side_effect = lambda key, **kwargs: key
        return service

    @pytest.fixture
    def service(self, mock_i18n):
        # Forzamos enabled=True para las pruebas
        with patch.dict(os.environ, {"DOCLING_ENABLED": "true"}):
            return DoclingService(i18n_service=mock_i18n)

    def test_supports(self, service):
        assert service.supports("file.pdf") is True
        assert service.supports("image.png") is False

    @patch("iatoolkit.services.docling_service.tempfile.NamedTemporaryFile")
    def test_convert_success_flow(self, mock_temp, service):
        """
        Prueba el flujo completo de conversión parcheando las librerías externas
        donde realmente residen (sys.modules o paths absolutos).
        """
        # 1. Mocks de Docling
        mock_converter_cls = MagicMock()
        mock_options_cls = MagicMock()

        # Mockeamos el módulo donde reside DocumentConverter y PipelineOptions
        # Usamos patch.dict en sys.modules para interceptar los imports locales
        mock_docling_mod = MagicMock()
        mock_docling_mod.document_converter.DocumentConverter = mock_converter_cls
        mock_docling_mod.datamodel.pipeline_options.PdfPipelineOptions = mock_options_cls

        with patch.dict(sys.modules, {
            "docling": mock_docling_mod,
            "docling.document_converter": mock_docling_mod.document_converter,
            "docling.datamodel.base_models": MagicMock(),
            "docling.datamodel.pipeline_options": mock_docling_mod.datamodel.pipeline_options,
        }):
            # Setup de mocks
            mock_converter = mock_converter_cls.return_value
            mock_pipeline_opts = mock_options_cls.return_value

            mock_doc = MagicMock()
            mock_res = MagicMock()
            mock_res.document = mock_doc
            mock_converter.convert.return_value = mock_res

            # Datos del documento mock
            mock_doc.export_to_markdown.return_value = "Contenido Markdown"
            # Estructura devuelta por export_to_dict
            mock_doc.export_to_dict.return_value = {
                "body": [
                    {"type": "text", "text": "Texto extraido", "page_start": 1},
                    {"type": "table", "data": {"grid": []}, "caption": "Tabla 1"}
                ]
            }
            # Listas de objetos (Tablas e Imágenes)
            mock_table_obj = MagicMock()
            mock_table_obj.export_to_markdown.return_value = "| A | B |"
            mock_table_obj.export_to_dict.return_value = {"grid": []}
            mock_doc.tables = [mock_table_obj]
            mock_doc.pictures = [] # Sin imágenes por simplicidad en este test

            # Ejecución
            result = service.convert("test.pdf", b"fake_content")

            # Aserciones
            assert isinstance(result, DoclingResult)
            # Verificar configuración de opciones
            assert mock_pipeline_opts.generate_picture_images is True
            assert mock_pipeline_opts.do_table_structure is True
            # Verificar extracción
            assert len(result.text_blocks) == 1
            assert result.text_blocks[0].text == "Texto extraido"
            assert len(result.tables) == 1  # 1 del dict (implementación actual)

    def test_extract_tables_from_object_success(self, service):
        """
        GIVEN a document object with tables
        WHEN _extract_tables_from_object is called
        THEN it should extract markdown, json and page number correctly.
        """
        # Arrange
        mock_doc = MagicMock()
        mock_table = MagicMock()

        # Configure table behavior (Simulate Docling v2 API)
        mock_table.export_to_markdown.return_value = "| Col1 | Col2 |\n|---|---|\n| Val1 | Val2 |"
        mock_table.export_to_dict.return_value = {"grid": [["Col1", "Col2"], ["Val1", "Val2"]]}

        # Configure provenance (Page number)
        mock_prov = MagicMock()
        mock_prov.page_no = 42
        mock_table.prov = [mock_prov]

        mock_doc.tables = [mock_table]

        # Act
        tables = service._extract_tables_from_object(mock_doc)

        # Assert
        assert len(tables) == 1
        table = tables[0]

        assert table.markdown == "| Col1 | Col2 |\n|---|---|\n| Val1 | Val2 |"
        assert table.table_json == {"grid": [["Col1", "Col2"], ["Val1", "Val2"]]}
        assert table.page == 42

        # Verify export_to_markdown was called with the doc instance (as per your implementation)
        mock_table.export_to_markdown.assert_called_with(mock_doc)

    def test_extract_images_from_object(self, service):
        """Prueba la estrategia de extracción de imágenes desde objetos."""
        mock_doc = MagicMock()

        # Imagen válida con método get_image (v2)
        pic1 = MagicMock()
        pil_image = MagicMock()
        # Simulamos que save escribe bytes en el buffer
        pil_image.save.side_effect = lambda fp, format: fp.write(b"PNG_BYTES")
        pic1.get_image.return_value = pil_image
        pic1.prov = [MagicMock(page_no=1)]

        # Imagen inválida/error
        pic2 = MagicMock()
        pic2.get_image.side_effect = Exception("Error")

        mock_doc.pictures = [pic1, pic2]

        images = service._extract_images_from_object(mock_doc, "archivo.pdf")

        assert len(images) == 1
        assert images[0].content == b"PNG_BYTES"
        assert images[0].page == 1
        assert "archivo_img_1.png" in images[0].filename