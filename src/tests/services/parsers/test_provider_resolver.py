from unittest.mock import MagicMock

from iatoolkit.services.parsers.contracts import ParseRequest
from iatoolkit.services.parsers.provider_resolver import ParsingProviderResolver


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

    def test_resolve_provider_name_uses_request_config_override_first(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "docling",
        }
        self.mock_document_repo.get_collection_by_name.return_value = MagicMock(parser_provider="docling")

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
            collection_name="Invoices",
            provider_config={"provider": "basic"},
        )

        assert self.resolver.resolve_provider_name(request) == "basic"

    def test_resolve_uses_collection_provider_override(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "basic",
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

    def test_resolve_uses_metadata_provider_override_before_collection_and_global(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "docling",
        }
        self.mock_document_repo.get_collection_by_name.return_value = MagicMock(parser_provider="docling")

        mock_basic = MagicMock()
        self.mock_factory.get_provider.return_value = mock_basic

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
            collection_name="Invoices",
            metadata={"parser_provider": "basic"},
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("basic")
        assert result == mock_basic

    def test_resolve_uses_global_provider_when_collection_has_no_override(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "basic",
        }
        self.mock_document_repo.get_collection_by_name.return_value = MagicMock(parser_provider=None)

        mock_basic = MagicMock()
        self.mock_factory.get_provider.return_value = mock_basic

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
            collection_name="contracts",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("basic")
        assert result == mock_basic

    def test_resolve_auto_maps_to_basic_provider_instance(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "auto",
        }
        self.mock_document_repo.get_collection_by_name.return_value = None

        mock_basic = MagicMock()
        self.mock_factory.get_provider.return_value = mock_basic

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("basic")
        assert result == mock_basic

    def test_resolve_accepts_legacy_alias(self):
        self.mock_config_service.get_configuration.return_value = {
            "parsing_provider": "legacy",
        }
        self.mock_document_repo.get_collection_by_name.return_value = None

        mock_basic = MagicMock()
        self.mock_factory.get_provider.return_value = mock_basic

        request = ParseRequest(
            company_short_name="acme",
            filename="a.pdf",
            content=b"x",
        )
        result = self.resolver.resolve(request)

        self.mock_factory.get_provider.assert_called_with("basic")
        assert result == mock_basic
