from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider


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
        return DoclingParsingProvider(i18n_service=mock_i18n, config_service=mock_config)

    def test_supports(self, provider):
        request_pdf = MagicMock(filename="file.pdf")
        request_png = MagicMock(filename="image.png")
        assert provider.supports(request_pdf) is True
        assert provider.supports(request_png) is False

    def test_parse_raises_if_provider_is_marked_unavailable(self, mock_i18n):
        provider = DoclingParsingProvider(i18n_service=mock_i18n, config_service=MagicMock(spec=ConfigurationService))
        provider.enabled = False
        with pytest.raises(IAToolkitException):
            provider.parse(MagicMock(filename="a.pdf", content=b"x", provider_config={}))

    @patch("iatoolkit.services.parsers.providers.docling_provider.tempfile.NamedTemporaryFile")
    def test_parse_success_flow_without_tables(self, mock_temp, provider):
        mock_tmp_file = MagicMock()
        mock_tmp_file.name = "/tmp/test.pdf"
        mock_temp.return_value.__enter__.return_value = mock_tmp_file

        mock_converter = MagicMock()
        provider._converter_cache[(False, False)] = mock_converter

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
        mock_doc.tables = [MagicMock()]
        mock_doc.pictures = []

        request = MagicMock(filename="test.pdf", content=b"fake_content", provider_config={})
        with patch.object(provider, "_should_enable_ocr", return_value=False):
            result = provider.parse(request)

        assert result.provider == "docling"
        assert len(result.texts) == 1
        assert result.texts[0].text == "Texto extraido"
        assert result.texts[0].meta.get("source_label") == "text"
        assert len(result.tables) == 0
        assert result.metrics["detect_tables"] is False
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

    def test_resolve_detect_tables_uses_provider_config(self, provider):
        request = MagicMock(provider_config={"detect_tables": True})
        assert provider._resolve_detect_tables(request) is True

    def test_should_enable_ocr_only_for_scanned_pdfs(self, provider):
        request = MagicMock(filename="scan.pdf", content=b"fake-content")
        with patch.object(provider, "_pdf_needs_ocr", return_value=True):
            assert provider._should_enable_ocr(request) is True

    def test_init_uses_rapidocr_with_onnxruntime_when_ocr_is_enabled(self, provider):
        pytest.importorskip("docling")

        with patch("docling.document_converter.DocumentConverter") as mock_converter_cls:
            provider.init(use_ocr=True, detect_tables=False)

            format_options = mock_converter_cls.call_args.kwargs["format_options"]
            pdf_option = next(iter(format_options.values()))
            pipeline_options = pdf_option.pipeline_options

            assert pipeline_options.do_ocr is True
            assert pipeline_options.ocr_options.kind == "rapidocr"
            assert pipeline_options.ocr_options.backend == "onnxruntime"
