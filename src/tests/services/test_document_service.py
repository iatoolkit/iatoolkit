# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import patch, MagicMock

from iatoolkit.services.parsers.providers.legacy_provider import LegacyParsingProvider
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.parsers.contracts import ParseRequest


class TestLegacyParsingProvider:

    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        monkeypatch.setenv("MAX_DOC_PAGES", "10")

        self.mock_excel_service = MagicMock(spec=ExcelService)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.provider = LegacyParsingProvider(
            excel_service=self.mock_excel_service,
            i18n_service=self.mock_i18n_service,
        )

    def test_file_txt_when_binary_content(self):
        result = self.provider.file_to_txt("test.txt", b"dummy_content")
        assert result == "dummy_content"

    def test_file_txt_when_binary_content_and_error_decoding(self):
        with pytest.raises(IAToolkitException) as excinfo:
            self.provider.file_to_txt("test.txt", b'\xff\xfe\xff')
        assert "FILE_FORMAT_ERROR" == excinfo.value.error_type.name

    def test_file_excel_when_excel_content(self):
        self.mock_excel_service.read_excel.return_value = 'json_content'
        result = self.provider.file_to_txt("test.xlsx", "dummy_content")
        assert result == 'json_content'

    @patch("iatoolkit.services.parsers.providers.legacy_provider.LegacyParsingProvider.is_scanned_pdf")
    @patch("iatoolkit.services.parsers.providers.legacy_provider.LegacyParsingProvider.read_scanned_pdf", return_value="Scanned text")
    @patch("iatoolkit.services.parsers.providers.legacy_provider.LegacyParsingProvider.read_pdf", return_value="PDF text")
    def test_extension_file_detection(self, mock_read_pdf, mock_read_scanned_pdf, mock_is_scanned_pdf):
        mock_is_scanned_pdf.return_value = True
        result = self.provider.file_to_txt("test.pdf", "dummy_content")
        assert result == "Scanned text"

        mock_is_scanned_pdf.return_value = False
        result = self.provider.file_to_txt("test.pdf", "dummy_content")
        assert result == "PDF text"

    def test_parse_builds_text_result(self):
        with patch.object(self.provider, "extract_text", return_value="hello world"):
            result = self.provider.parse(ParseRequest(
                company_short_name="acme",
                filename="a.txt",
                content=b"abc",
            ))

        assert result.provider == "legacy"
        assert len(result.texts) == 1
        assert result.texts[0].text == "hello world"
        assert len(result.images) == 0

    @patch("iatoolkit.services.parsers.providers.legacy_provider.LegacyParsingProvider.pdf_to_images", return_value=[])
    def test_parse_pdf_without_images(self, _):
        with patch.object(self.provider, "extract_text", return_value="pdf text"):
            result = self.provider.parse(ParseRequest(
                company_short_name="acme",
                filename="a.pdf",
                content=b"pdf",
            ))

        assert len(result.texts) == 1
        assert len(result.images) == 0
