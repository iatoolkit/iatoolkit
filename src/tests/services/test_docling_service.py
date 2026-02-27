import pytest
from unittest.mock import MagicMock, patch
import os
from PIL import Image

from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException


class TestDoclingParsingProvider:

    @pytest.fixture
    def mock_i18n(self):
        service = MagicMock(spec=I18nService)
        service.t.side_effect = lambda key, **kwargs: key
        return service

    @pytest.fixture
    def mock_config(self):
        config = MagicMock(spec=ConfigurationService)
        config.get_configuration.return_value = {}
        return config

    @pytest.fixture
    def provider(self, mock_i18n, mock_config):
        with patch.dict(os.environ, {"DOCLING_ENABLED": "true"}):
            return DoclingParsingProvider(i18n_service=mock_i18n, config_service=mock_config)

    def test_supports(self, provider):
        request_pdf = MagicMock(filename="file.pdf")
        request_png = MagicMock(filename="image.png")
        assert provider.supports(request_pdf) is True
        assert provider.supports(request_png) is False

    def test_parse_raises_if_disabled(self, mock_i18n):
        with patch.dict(os.environ, {"DOCLING_ENABLED": "false"}):
            provider = DoclingParsingProvider(i18n_service=mock_i18n, config_service=MagicMock(spec=ConfigurationService))
        with pytest.raises(IAToolkitException):
            provider.parse(MagicMock(filename="a.pdf", content=b"x"))

    @patch("iatoolkit.services.parsers.providers.docling_provider.tempfile.NamedTemporaryFile")
    def test_parse_success_flow(self, mock_temp, provider):
        mock_tmp_file = MagicMock()
        mock_tmp_file.name = "/tmp/test.pdf"
        mock_temp.return_value.__enter__.return_value = mock_tmp_file

        mock_converter = MagicMock()
        provider.converter = mock_converter

        mock_doc = MagicMock()
        mock_res = MagicMock()
        mock_res.document = mock_doc
        mock_converter.convert.return_value = mock_res

        mock_doc.export_to_markdown.return_value = "Contenido Markdown"
        mock_doc.export_to_dict.return_value = {
            "body": [
                {"type": "text", "text": "Texto extraido", "prov": [{"page_no": 1}]},
                {"type": "list_item", "text": "item"},
                {"type": "section_header", "text": "Sec"}
            ]
        }

        mock_table_obj = MagicMock()
        mock_table_obj.export_to_markdown.return_value = "| A | B |"
        mock_table_obj.export_to_dict.return_value = {"grid": []}
        mock_table_obj.prov = [MagicMock(page_no=1)]
        mock_doc.tables = [mock_table_obj]
        mock_doc.pictures = []

        request = MagicMock(filename="test.pdf", content=b"fake_content")
        result = provider.parse(request)

        assert result.provider == "docling"
        assert len(result.texts) == 1
        assert result.texts[0].text == "Texto extraido"
        assert result.texts[0].meta.get("source_label") == "text"
        assert len(result.tables) == 1
        mock_converter.convert.assert_called_once_with("/tmp/test.pdf")

    def test_extract_texts_skips_list_item_and_section_header(self, provider):
        doc_dict = {
            "body": [
                {"type": "section_header", "text": "Seccion"},
                {"type": "list_item", "text": "A"},
                {"type": "text", "text": "B"}
            ]
        }
        texts = provider._extract_texts(doc_dict, markdown="")
        assert len(texts) == 1
        assert texts[0].text == "B"

    def test_extract_tables_fallback_caption_from_table_dict(self, provider):
        class FakeTable:
            prov = [{"page_no": 2}]

            @staticmethod
            def export_to_markdown(_doc):
                return "| col | val |"

            @staticmethod
            def export_to_dict():
                return {"caption": "Tabla de costos", "cells": []}

        doc = MagicMock()
        doc.tables = [FakeTable()]

        tables = provider._extract_tables(doc, doc_dict={})
        assert len(tables) == 1
        assert tables[0].meta.get("caption_text") == "Tabla de costos"
        assert tables[0].meta.get("caption_source") == "extracted"

    @patch("iatoolkit.services.parsers.providers.docling_provider.normalize_image")
    def test_extract_images_fallback_caption_from_doc_dict(self, mock_normalize, provider):
        class FakePicture:
            prov = [{"page_no": 3}]

            @staticmethod
            def get_image(_doc):
                return Image.new("RGB", (20, 20), "white")

        mock_normalize.return_value = (b"pngbytes", "img.png", "image/png", "rgb", 20, 20)

        doc = MagicMock()
        doc.pictures = [FakePicture()]
        doc_dict = {
            "body": [
                {"type": "figure_caption", "text": "Figura 3: Diagrama general", "prov": [{"page_no": 3}]}
            ]
        }

        images = provider._extract_images(doc, "test.pdf", doc_dict=doc_dict)
        assert len(images) == 1
        assert images[0].meta.get("caption_text") == "Figura 3: Diagrama general"
        assert images[0].meta.get("caption_source") == "inferred"


    def test_resolve_do_ocr_uses_company_config_flag(self, provider):
        provider.config_service.get_configuration.return_value = {
            "docling": {
                "do_ocr": True,
            }
        }

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DOCLING_DO_OCR", None)
            assert provider._resolve_do_ocr("sample_company") is True

    def test_resolve_do_ocr_env_override_has_precedence(self, provider):
        provider.config_service.get_configuration.return_value = {
            "docling": {
                "do_ocr": False,
            }
        }

        with patch.dict(os.environ, {"DOCLING_DO_OCR": "true"}):
            assert provider._resolve_do_ocr("sample_company") is True

        with patch.dict(os.environ, {"DOCLING_DO_OCR": "false"}):
            assert provider._resolve_do_ocr("sample_company") is False
