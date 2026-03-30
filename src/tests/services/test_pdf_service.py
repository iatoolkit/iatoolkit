# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.pdf_service import PDF_MIME, PdfService
from iatoolkit.services.storage_service import StorageService


class TestPdfService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.util = MagicMock(spec=Utility)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_storage_service = MagicMock(spec=StorageService)
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.pdf_service = PdfService(
            util=self.util,
            i18n_service=self.mock_i18n_service,
            storage_service=self.mock_storage_service,
        )

        yield

    def test_pdf_generator_uploads_to_storage_and_returns_signed_download_link(self):
        self.mock_storage_service.upload_generated_download.return_value = "companies/acme/generated_downloads/1/generated.pdf"
        self.mock_storage_service.create_download_token.return_value = "signed-token"

        result = self.pdf_service.pdf_generator(
            "acme",
            filename="informe.pdf",
            content="# Resumen\n\nTodo OK",
            input_format="markdown",
            template="report",
            page_size="A4",
            orientation="portrait",
        )

        assert result["filename"] == "informe.pdf"
        assert result["attachment_token"] == "signed-token"
        assert result["download_link"] == "/download/signed-token"
        assert result["content_type"] == PDF_MIME

        self.mock_storage_service.upload_generated_download.assert_called_once()
        upload_kwargs = self.mock_storage_service.upload_generated_download.call_args.kwargs
        assert upload_kwargs["company_short_name"] == "acme"
        assert upload_kwargs["mime_type"] == PDF_MIME
        assert upload_kwargs["filename"].endswith(".pdf")
        assert upload_kwargs["file_content"].startswith(b"%PDF")

        self.mock_storage_service.create_download_token.assert_called_once_with(
            company_short_name="acme",
            storage_key="companies/acme/generated_downloads/1/generated.pdf",
            filename="informe.pdf",
        )

    def test_pdf_generator_accepts_html_content(self):
        self.mock_storage_service.upload_generated_download.return_value = "companies/acme/generated_downloads/2/generated.pdf"
        self.mock_storage_service.create_download_token.return_value = "tok-html"

        result = self.pdf_service.pdf_generator(
            "acme",
            filename="carta.pdf",
            content="<h1>Carta</h1><p>Hola</p>",
            input_format="html",
            template="letter",
            page_size="LETTER",
            orientation="landscape",
        )

        assert result["download_link"] == "/download/tok-html"
        upload_kwargs = self.mock_storage_service.upload_generated_download.call_args.kwargs
        assert upload_kwargs["file_content"].startswith(b"%PDF")

    def test_pdf_generator_returns_error_when_content_is_missing(self):
        result = self.pdf_service.pdf_generator(
            "acme",
            filename="informe.pdf",
            content="",
            input_format="markdown",
            template="simple",
            page_size="A4",
            orientation="portrait",
        )

        assert result == "translated:errors.services.no_content_for_pdf"

    def test_pdf_generator_returns_error_when_input_format_is_invalid(self):
        result = self.pdf_service.pdf_generator(
            "acme",
            filename="informe.pdf",
            content="hola",
            input_format="rst",
            template="simple",
            page_size="A4",
            orientation="portrait",
        )

        assert result == "translated:errors.services.unsupported_pdf_input_format"

    def test_pdf_generator_raises_when_content_is_too_large(self):
        with pytest.raises(IAToolkitException) as excinfo:
            self.pdf_service.pdf_generator(
                "acme",
                filename="informe.pdf",
                content="a" * 200_001,
                input_format="markdown",
                template="simple",
                page_size="A4",
                orientation="portrait",
            )

        assert excinfo.value.error_type == IAToolkitException.ErrorType.CALL_ERROR
