from unittest.mock import MagicMock

from iatoolkit.services.parsers.provider_resolver import ParsingProviderResolver
from iatoolkit.services.parsers.contracts import ParseRequest


class TestParsingProviderResolver:

    def setup_method(self):
        self.mock_config_service = MagicMock()
        self.mock_document_repo = MagicMock()
        self.mock_factory = MagicMock()
        self.resolver = ParsingProviderResolver(
            config_service=self.mock_config_service,
            document_repo=self.mock_document_repo,
            provider_factory=self.mock_factory,
        )

    def test_resolve_uses_collection_provider_override(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "legacy",
        }
        self.mock_document_repo.get_collection_by_name.return_value = MagicMock(parser_provider="docling")

        mock_docling = MagicMock()
        self.mock_factory.get_provider.return_value = mock_docling

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
            collection_name="Invoices",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("docling")
        assert result == mock_docling

    def test_resolve_uses_global_provider_when_collection_has_no_override(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "legacy",
        }
        self.mock_document_repo.get_collection_by_name.return_value = MagicMock(parser_provider=None)

        mock_legacy = MagicMock()
        self.mock_factory.get_provider.return_value = mock_legacy

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
            collection_name="contracts",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("legacy")
        assert result == mock_legacy

    def test_resolve_auto_falls_back_to_legacy_when_docling_disabled(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "auto",
        }
        self.mock_document_repo.get_collection_by_name.return_value = None

        mock_docling = MagicMock(enabled=False)
        mock_legacy = MagicMock()
        self.mock_factory.get_provider.side_effect = [mock_docling, mock_legacy]

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
        )
        result = self.resolver.resolve(request)

        assert result == mock_legacy

    def test_resolve_accepts_document_service_alias(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "document_service",
        }
        self.mock_document_repo.get_collection_by_name.return_value = None

        mock_legacy = MagicMock()
        self.mock_factory.get_provider.return_value = mock_legacy

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("legacy")
        assert result == mock_legacy
