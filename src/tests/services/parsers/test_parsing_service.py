from unittest.mock import MagicMock

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
        metrics={},
    )
    provider_resolver.resolve.return_value = provider
    service = ParsingService(provider_resolver=provider_resolver, provider_factory=provider_factory)

    with caplog.at_level("INFO"):
        result = service.parse_document(
            company_short_name="acme",
            filename="contract.pdf",
            content=b"%PDF-1",
        )

    assert result.provider == "docling"
    assert "Parsed document company=acme filename=contract.pdf provider=docling" in caplog.text
    assert "texts=1 tables=1 images=0 warnings=1" in caplog.text
