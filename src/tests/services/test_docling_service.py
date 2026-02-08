import pytest
from unittest.mock import MagicMock, patch
import os
import sys

from iatoolkit.services.parsers.providers.docling_provider import DoclingParsingProvider
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException


class TestDoclingParsingProvider:

    @pytest.fixture
    def mock_i18n(self):
        service = MagicMock(spec=I18nService)
        service.t.side_effect = lambda key, **kwargs: key
        return service

    @pytest.fixture
    def provider(self, mock_i18n):
        with patch.dict(os.environ, {"DOCLING_ENABLED": "true"}):
            return DoclingParsingProvider(i18n_service=mock_i18n)

    def test_supports(self, provider):
        request_pdf = MagicMock(filename="file.pdf")
        request_png = MagicMock(filename="image.png")
        assert provider.supports(request_pdf) is True
        assert provider.supports(request_png) is False

    def test_parse_raises_if_disabled(self, mock_i18n):
        with patch.dict(os.environ, {"DOCLING_ENABLED": "false"}):
            provider = DoclingParsingProvider(i18n_service=mock_i18n)
        with pytest.raises(IAToolkitException):
            provider.parse(MagicMock(filename="a.pdf", content=b"x"))

    @patch("iatoolkit.services.parsers.providers.docling_provider.tempfile.NamedTemporaryFile")
    def test_parse_success_flow(self, mock_temp, provider):
        mock_converter_cls = MagicMock()
        mock_options_cls = MagicMock()

        mock_docling_mod = MagicMock()
        mock_docling_mod.document_converter.DocumentConverter = mock_converter_cls
        mock_docling_mod.datamodel.pipeline_options.PdfPipelineOptions = mock_options_cls

        with patch.dict(sys.modules, {
            "docling": mock_docling_mod,
            "docling.document_converter": mock_docling_mod.document_converter,
            "docling.datamodel.base_models": MagicMock(),
            "docling.datamodel.pipeline_options": mock_docling_mod.datamodel.pipeline_options,
        }):
            mock_converter = mock_converter_cls.return_value

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
