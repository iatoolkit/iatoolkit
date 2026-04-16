from unittest.mock import MagicMock, patch

from iatoolkit.services.parsers.contracts import ParseResult, ParsedTable, ParsedText
from iatoolkit.services.parsers.parsing_service import ParsingService


def test_parse_document_logs_effective_provider(caplog):
    provider_resolver = MagicMock()
    provider_factory = MagicMock()
    provider = MagicMock()
    provider.name = "docling"
    provider.parse.return_value = ParseResult(
        provider="docling",
        provider_version="1.2.3",
        texts=[ParsedText(text="hello")],
        tables=[ParsedTable(text="| a |")],
        warnings=["fallback_from:something"],
        metrics={"used_ocr": True, "ocr_engine": "tesseract"},
    )
    provider_resolver.resolve_provider_name.return_value = "docling"
    provider_factory.get_provider.return_value = provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    with caplog.at_level("INFO"):
        result = service.parse_document(
            company_short_name="acme",
            filename="contract.pdf",
            content=b"%PDF-1",
        )

    assert result.provider == "docling"
    assert "requested_provider=docling provider=docling" in caplog.text
    assert "texts=1 tables=1 images=0 warnings=1" in caplog.text
    assert "used_ocr=True ocr_engine=tesseract" in caplog.text



def test_parse_document_auto_keeps_basic_when_text_is_sufficient():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "auto"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.return_value = ParseResult(
        provider="basic",
        texts=[ParsedText(text="A" * 120)],
    )
    provider_factory.get_provider.side_effect = lambda name: basic_provider if name == "basic" else MagicMock()

    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)
    result = service.parse_document(
        company_short_name="acme",
        filename="contract.pdf",
        content=b"%PDF-1",
    )

    assert result.provider == "basic"
    assert basic_provider.parse.call_count == 1


def test_parse_document_auto_uses_tesseract_when_basic_text_is_insufficient():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "auto"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.side_effect = [
        ParseResult(provider="basic", texts=[]),
        ParseResult(provider="basic", texts=[ParsedText(text="B" * 120)]),
    ]
    docling_provider = MagicMock(enabled=True)
    docling_provider.supports.return_value = True

    def get_provider(name):
        if name == "basic":
            return basic_provider
        if name == "docling":
            return docling_provider
        raise AssertionError(name)

    provider_factory.get_provider.side_effect = get_provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    with patch("iatoolkit.services.parsers.parsing_service.shutil.which", return_value="/usr/bin/tesseract"):
        with patch.dict("os.environ", {"TESSERACT_ENABLED": "true"}):
            result = service.parse_document(
                company_short_name="acme",
                filename="scan.pdf",
                content=b"%PDF-1",
            )

    assert result.provider == "basic"
    assert result.metrics["ocr_engine"] == "tesseract"
    assert basic_provider.parse.call_count == 2


def test_parse_document_auto_falls_back_to_docling_when_tesseract_is_unavailable():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "auto"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.return_value = ParseResult(provider="basic", texts=[])

    docling_provider = MagicMock(enabled=True)
    docling_provider.supports.return_value = True
    docling_provider.parse.return_value = ParseResult(
        provider="docling",
        texts=[ParsedText(text="D" * 120)],
    )

    def get_provider(name):
        if name == "basic":
            return basic_provider
        if name == "docling":
            return docling_provider
        raise AssertionError(name)

    provider_factory.get_provider.side_effect = get_provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    with patch("iatoolkit.services.parsers.parsing_service.shutil.which", return_value=None):
        with patch.dict("os.environ", {"TESSERACT_ENABLED": "true"}):
            result = service.parse_document(
                company_short_name="acme",
                filename="scan.pdf",
                content=b"%PDF-1",
                provider_config={"detect_tables": True},
            )

    assert result.provider == "docling"
    assert result.metrics["detect_tables"] is True
    assert docling_provider.parse.call_count == 1


def test_parse_document_auto_reuses_single_pdf_ocr_decision_for_all_provider_attempts():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "auto"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.side_effect = [
        ParseResult(provider="basic", texts=[]),
        ParseResult(provider="basic", texts=[ParsedText(text="B" * 120)]),
    ]
    docling_provider = MagicMock(enabled=True)
    docling_provider.supports.return_value = True

    def get_provider(name):
        if name == "basic":
            return basic_provider
        if name == "docling":
            return docling_provider
        raise AssertionError(name)

    provider_factory.get_provider.side_effect = get_provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    fake_decision = MagicMock(
        needs_ocr=True,
        reason="majority_pages_image_first_with_sparse_text",
        page_count=3,
        image_page_count=3,
        meaningful_text_page_count=0,
        sparse_text_image_page_count=3,
        total_text_char_count=30,
    )

    with patch("iatoolkit.services.parsers.parsing_service.analyze_pdf_ocr_need", return_value=fake_decision) as mock_analyze:
        with patch("iatoolkit.services.parsers.parsing_service.shutil.which", return_value="/usr/bin/tesseract"):
            with patch.dict("os.environ", {"TESSERACT_ENABLED": "true"}):
                result = service.parse_document(
                    company_short_name="acme",
                    filename="scan.pdf",
                    content=b"%PDF-1",
                )

    assert result.provider == "basic"
    assert mock_analyze.call_count == 1
    first_request = basic_provider.parse.call_args_list[0].args[0]
    second_request = basic_provider.parse.call_args_list[1].args[0]
    assert first_request.provider_config["pdf_needs_ocr"] is True
    assert second_request.provider_config["pdf_needs_ocr"] is True
    assert first_request.provider_config["suppress_ocr_required_error"] is True


def test_parse_document_auto_suppresses_basic_ocr_required_error_on_first_pass():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "auto"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.return_value = ParseResult(provider="basic", texts=[])

    docling_provider = MagicMock(enabled=True)
    docling_provider.supports.return_value = True
    docling_provider.parse.return_value = ParseResult(
        provider="docling",
        texts=[ParsedText(text="D" * 120)],
    )

    def get_provider(name):
        if name == "basic":
            return basic_provider
        if name == "docling":
            return docling_provider
        raise AssertionError(name)

    provider_factory.get_provider.side_effect = get_provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    fake_decision = MagicMock(
        needs_ocr=True,
        reason="mixed_meaningful_and_sparse_image_pages",
        page_count=4,
        image_page_count=4,
        meaningful_text_page_count=2,
        sparse_text_image_page_count=2,
        total_text_char_count=200,
    )

    with patch("iatoolkit.services.parsers.parsing_service.analyze_pdf_ocr_need", return_value=fake_decision):
        with patch("iatoolkit.services.parsers.parsing_service.shutil.which", return_value=None):
            with patch.dict("os.environ", {}, clear=False):
                result = service.parse_document(
                    company_short_name="acme",
                    filename="scan.pdf",
                    content=b"%PDF-1",
                )

    assert result.provider == "docling"
    first_request = basic_provider.parse.call_args.args[0]
    assert first_request.provider_config["suppress_ocr_required_error"] is True


def test_parse_document_basic_keeps_ocr_disabled_for_prompt_attachments():
    provider_resolver = MagicMock()
    provider_resolver.resolve_provider_name.return_value = "basic"
    provider_factory = MagicMock()

    basic_provider = MagicMock()
    basic_provider.parse.return_value = ParseResult(provider="basic", texts=[ParsedText(text="x")])
    provider_factory.get_provider.return_value = basic_provider

    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)
    service.parse_document(
        company_short_name="acme",
        filename="scan.pdf",
        content=b"%PDF-1",
        metadata={"source": "prompt_task_attachment"},
        provider_config={"provider": "basic"},
    )

    request = basic_provider.parse.call_args.args[0]
    assert request.provider_config == {"provider": "basic"}
    assert request.metadata["source"] == "prompt_task_attachment"
