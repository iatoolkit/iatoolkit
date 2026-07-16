# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from sqlalchemy.sql.elements import BinaryExpression
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.services.parsers.parsing_service import ParsingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import Company, Document, DocumentImage, DocumentStatus, CollectionType, VSDoc
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.parsers.contracts import ParseResult, ParsedText
from iatoolkit.common.exceptions import IAToolkitException


class TestKnowledgeBaseService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.mock_doc_repo = MagicMock(spec=DocumentRepo)
        self.mock_vs_repo = MagicMock(spec=VSRepo)
        self.mock_parsing_service = MagicMock(spec=ParsingService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_storage = MagicMock(spec=StorageService)
        self.mock_visual_kb = MagicMock(spec=VisualKnowledgeBaseService)

        self.mock_session = MagicMock()
        self.mock_doc_repo.session = self.mock_session

        self.service = KnowledgeBaseService(
            document_repo=self.mock_doc_repo,
            vs_repo=self.mock_vs_repo,
            parsing_service=self.mock_parsing_service,
            profile_service=self.mock_profile_service,
            i18n_service=self.mock_i18n_service,
            storage_service=self.mock_storage,
            visual_kb_service=self.mock_visual_kb,
        )

        self.company = Company(id=1, short_name='acme', name='Acme Corp')
        self.filename = 'contract.pdf'
        self.content = b'PDF content'
        self.metadata = {'type': 'contract'}

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"
        self.mock_doc_repo.get_collection_id_by_name.return_value = None
        self.mock_parsing_service.parse_document.return_value = ParseResult(
            provider="basic",
            provider_version="1.0",
            texts=[ParsedText(text="New fresh content", meta={"source_type": "text"})],
            tables=[],
            images=[],
        )

    def test_ingest_document_sync_skips_if_exists(self):
        existing_doc = Document(id=99, filename=self.filename)
        self.mock_doc_repo.get_by_hash.return_value = existing_doc

        result = self.service.ingest_document_sync(self.company, self.filename, self.content)

        assert result == existing_doc
        self.mock_doc_repo.get_by_hash.assert_called_once_with(
            self.company.id,
            "7e7f04c8b5646f7ad29b1cb0c8085d4ff9c6b08f2a632f496641b31f524c7b98",
            None,
        )
        self.mock_doc_repo.insert.assert_not_called()
        self.mock_storage.upload_document.assert_not_called()

    def test_ingest_document_sync_reprocesses_failed_document(self):
        existing_doc = Document(
            id=99,
            filename=self.filename,
            status=DocumentStatus.FAILED,
            storage_key="old/path/failed.pdf"
        )
        existing_doc.company = self.company

        self.mock_doc_repo.get_by_hash.return_value = existing_doc
        self.mock_doc_repo.get_by_id.return_value = existing_doc

        self.mock_storage.upload_document.return_value = "new/path/success.pdf"

        new_doc = self.service.ingest_document_sync(self.company, self.filename, self.content)

        self.mock_storage.delete_file.assert_called_with('acme', "old/path/failed.pdf")
        self.mock_session.delete.assert_called_with(existing_doc)
        self.mock_doc_repo.insert.assert_called()

        assert new_doc.status == DocumentStatus.ACTIVE
        assert new_doc.storage_key == "new/path/success.pdf"

    def test_ingest_document_sync_success_flow(self):
        self.mock_doc_repo.get_by_hash.return_value = None

        fake_key = "companies/acme/docs/123/contract.pdf"
        self.mock_storage.upload_document.return_value = fake_key

        new_doc = self.service.ingest_document_sync(self.company, self.filename, self.content, self.metadata)

        self.mock_storage.upload_document.assert_called_once()
        upload_args = self.mock_storage.upload_document.call_args.kwargs
        assert upload_args['company_short_name'] == 'acme'
        assert upload_args['filename'] == self.filename

        self.mock_doc_repo.insert.assert_called_once()
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.ACTIVE
        assert inserted_doc.storage_key == fake_key

        self.mock_parsing_service.parse_document.assert_called_once()

        self.mock_vs_repo.add_document.assert_called_once()
        args, _ = self.mock_vs_repo.add_document.call_args
        assert args[0] == 'acme'
        assert len(args[1]) > 0

        assert self.mock_session.commit.call_count >= 2

    def test_ingest_document_sync_handles_processing_error(self):
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage.upload_document.return_value = "key"
        self.mock_parsing_service.parse_document.side_effect = Exception("OCR Failed")

        with pytest.raises(IAToolkitException) as exc:
            self.service.ingest_document_sync(self.company, self.filename, self.content)

        assert exc.value.error_type == IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR

        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.FAILED
        assert "OCR Failed" in inserted_doc.error_message

    def test_ingest_document_assigns_collection_id(self):
        metadata = {'collection': 'Legal'}
        self.mock_doc_repo.get_collection_id_by_name.return_value = 99

        self.mock_storage.upload_document.return_value = "key"
        self.mock_doc_repo.get_by_hash.return_value = None

        self.service.ingest_document_sync(self.company, "file.pdf", b"data", metadata=metadata)

        self.mock_doc_repo.get_by_hash.assert_called_once_with(
            self.company.id,
            "3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7",
            99,
        )
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.collection_type_id == 99

    def test_ingest_compacts_small_text_units_before_embedding(self):
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage.upload_document.return_value = "key"
        self.mock_parsing_service.parse_document.return_value = ParseResult(
            provider="docling",
            provider_version="1.0",
            texts=[
                ParsedText(text="Introduccion", meta={"source_type": "text", "source_label": "title", "section_title": "Intro"}),
                ParsedText(text="Linea corta uno.", meta={"source_type": "text", "source_label": "text", "section_title": "Intro", "page_start": 1, "page_end": 1}),
                ParsedText(text="Linea corta dos.", meta={"source_type": "text", "source_label": "text", "section_title": "Intro", "page_start": 1, "page_end": 1}),
            ],
            tables=[],
            images=[],
        )

        self.service.ingest_document_sync(self.company, "file.pdf", b"data")

        vs_docs = self.mock_vs_repo.add_document.call_args[0][1]
        assert len(vs_docs) == 1
        assert "Introduccion" in vs_docs[0].text
        assert "Linea corta uno." in vs_docs[0].text
        assert "Linea corta dos." in vs_docs[0].text

    def test_get_document_content_from_storage(self):
        mock_doc = Document(id=1, filename="test.pdf", storage_key="path/to/file")
        mock_doc.company = self.company
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        expected_bytes = b"Storage Content"
        self.mock_storage.get_document_content.return_value = expected_bytes

        content, filename = self.service.get_document_content(1)

        self.mock_storage.get_document_content.assert_called_once_with('acme', "path/to/file")
        assert content == expected_bytes
        assert filename == "test.pdf"

    def test_get_document_images_returns_persisted_images_by_document_id(self):
        mock_doc = Document(id=1, filename="test.pdf")
        mock_doc.company = self.company
        self.mock_doc_repo.get_by_id.return_value = mock_doc
        image = DocumentImage(
            id=11,
            document_id=1,
            page=3,
            image_index=2,
            storage_key="companies/acme/images/brain.png",
            meta={"width": 640, "height": 480, "format": "PNG"},
        )
        self.mock_doc_repo.get_document_images.return_value = [image]
        self.mock_storage.get_document_content.return_value = b"PNG bytes"

        payload = self.service.get_document_images("acme", 1, limit=10)

        self.mock_doc_repo.get_document_images.assert_called_once_with(1, limit=10)
        self.mock_storage.get_document_content.assert_called_once_with(
            "acme",
            "companies/acme/images/brain.png",
        )
        assert payload == [
            {
                "image_id": 11,
                "document_id": 1,
                "page": 3,
                "image_index": 2,
                "filename": "brain.png",
                "mime_type": "image/png",
                "width": 640,
                "height": 480,
                "metadata": {"width": 640, "height": 480, "format": "PNG"},
                "content": b"PNG bytes",
            }
        ]

    def test_get_document_images_rejects_wrong_company(self):
        other_company = Company(id=2, short_name="other", name="Other")
        mock_doc = Document(id=1, filename="test.pdf")
        mock_doc.company = other_company
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        with pytest.raises(IAToolkitException) as exc:
            self.service.get_document_images("acme", 1)

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION
        self.mock_doc_repo.get_document_images.assert_not_called()

    def test_get_document_tables_returns_persisted_table_chunks(self):
        mock_doc = Document(id=1, filename="test.pdf")
        mock_doc.company = self.company
        self.mock_doc_repo.get_by_id.return_value = mock_doc
        table = VSDoc(
            id=21,
            document_id=1,
            text="| Group | Mean |\n|---|---|\n| Control | 12.4 |",
            meta={
                "source_type": "table",
                "table_index": 2,
                "block_index": 14,
                "page": 6,
                "caption_text": "Demographics",
                "table_json": '{"rows": 2}',
            },
        )
        self.mock_vs_repo.get_document_tables.return_value = [table]

        payload = self.service.get_document_tables("acme", 1, limit=50)

        self.mock_vs_repo.get_document_tables.assert_called_once_with(1, limit=50)
        assert payload == [
            {
                "chunk_id": 21,
                "document_id": 1,
                "table_index": 2,
                "block_index": 14,
                "page": 6,
                "page_start": None,
                "page_end": None,
                "title": "Demographics",
                "text": "| Group | Mean |\n|---|---|\n| Control | 12.4 |",
                "table_json": '{"rows": 2}',
            }
        ]

    def test_get_document_tables_rejects_wrong_company(self):
        other_company = Company(id=2, short_name="other", name="Other")
        mock_doc = Document(id=1, filename="test.pdf")
        mock_doc.company = other_company
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        with pytest.raises(IAToolkitException) as exc:
            self.service.get_document_tables("acme", 1)

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION
        self.mock_vs_repo.get_document_tables.assert_not_called()

    def test_get_document_descriptor_returns_download_metadata(self):
        mock_doc = Document(id=1, filename="test.pdf", storage_key="path/to/file", meta={"topic": "legal"})
        mock_doc.company = self.company
        mock_doc.collection_type = CollectionType(name="contracts")
        mock_doc.status = DocumentStatus.ACTIVE
        self.mock_doc_repo.get_by_id.return_value = mock_doc
        self.mock_storage.generate_presigned_url.return_value = "https://files.example/test.pdf"

        payload = self.service.get_document_descriptor("acme", 1, collection_name="contracts")

        self.mock_storage.generate_presigned_url.assert_called_once_with("acme", "path/to/file")
        assert payload["document_id"] == 1
        assert payload["collection_name"] == "contracts"
        assert payload["filename"] == "test.pdf"
        assert payload["mime_type"] == "application/pdf"
        assert payload["download_url"] == "https://files.example/test.pdf"
        assert payload["content_available"] is True
        assert payload["metadata"] == {"topic": "legal"}

    def test_get_document_descriptor_rejects_wrong_company(self):
        other_company = Company(id=2, short_name="other", name="Other")
        mock_doc = Document(id=1, filename="test.pdf", storage_key="path/to/file")
        mock_doc.company = other_company
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        with pytest.raises(IAToolkitException) as exc:
            self.service.get_document_descriptor("acme", 1)

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION

    def test_get_document_descriptor_rejects_wrong_collection(self):
        mock_doc = Document(id=1, filename="test.pdf", storage_key="path/to/file")
        mock_doc.company = self.company
        mock_doc.collection_type = CollectionType(name="contracts")
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        with pytest.raises(IAToolkitException) as exc:
            self.service.get_document_descriptor("acme", 1, collection_name="invoices")

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_OPERATION

    def test_delete_document_success_cleans_storage(self):
        doc = Document(id=1, storage_key="path/key")
        doc.company = self.company
        self.mock_doc_repo.get_by_id.return_value = doc

        result = self.service.delete_document(1)

        assert result is True
        self.mock_storage.delete_file.assert_called_once_with('acme', "path/key")
        self.mock_session.delete.assert_called_with(doc)
        self.mock_session.commit.assert_called()

    def test_delete_document_not_found(self):
        self.mock_doc_repo.get_by_id.return_value = None
        result = self.service.delete_document(999)
        assert result is False
        self.mock_storage.delete_file.assert_not_called()

    def test_sync_collection_types_accepts_object_format(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_session.query.return_value.filter_by.return_value.all.return_value = []

        self.service.sync_collection_types("acme", [
            {"name": "Invoices", "parser_provider": "docling", "description": "AP invoices and billing support docs"},
            {"name": "Contracts"},
            "legacy_collection",
        ])

        assert self.mock_session.add.call_count == 3
        inserted = [c[0][0] for c in self.mock_session.add.call_args_list]
        inserted_names = sorted([item.name for item in inserted])
        assert inserted_names == ["contracts", "invoices", "legacy_collection"]
        invoices = [item for item in inserted if item.name == "invoices"][0]
        assert invoices.parser_provider == "docling"
        assert invoices.description == "AP invoices and billing support docs"

    def test_sync_collection_types_updates_existing_description(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        existing = SimpleNamespace(name="invoices", parser_provider=None, description=None)
        self.mock_session.query.return_value.filter_by.return_value.all.return_value = [existing]

        self.service.sync_collection_types("acme", [
            {"name": "Invoices", "description": "Accounts payable and billing records"}
        ])

        assert existing.description == "Accounts payable and billing records"
        self.mock_session.add.assert_not_called()
        self.mock_session.commit.assert_called()

    def test_get_collection_descriptors_returns_description_and_parser_provider(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        collection = SimpleNamespace(name="legal", description="Contracts and annexes", parser_provider="docling")
        self.mock_session.query.return_value.filter_by.return_value.all.return_value = [collection]

        result = self.service.get_collection_descriptors("acme")

        assert result == [
            {
                "name": "legal",
                "description": "Contracts and annexes",
                "parser_provider": "docling",
            }
        ]

    def test_search_passes_metadata_filter_to_vs_repo(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_doc_repo.get_collection_id_by_name.return_value = 7
        self.mock_vs_repo.query.return_value = []

        self.service.search(
            company_short_name="acme",
            query="find invoice",
            collection="invoices",
            metadata_filter={"source_type": "table", "doc.category": "finance"}
        )

        self.mock_vs_repo.query.assert_called_with(
            company_short_name="acme",
            query_text="find invoice",
            n_results=5,
            metadata_filter={"source_type": "table", "doc.category": "finance"},
            collection_ids=[7],
            include_urls=True,
        )

    def test_search_resolves_multiple_collection_ids(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_doc_repo.get_collection_ids_by_name.return_value = [7, 8]
        self.mock_vs_repo.query.return_value = []

        self.service.search(
            company_short_name="acme",
            query="find contract",
            collection=["Legal", "Contracts"],
        )

        self.mock_doc_repo.get_collection_ids_by_name.assert_called_once_with(
            "acme",
            ["Legal", "Contracts"],
        )
        self.mock_vs_repo.query.assert_called_with(
            company_short_name="acme",
            query_text="find contract",
            n_results=5,
            metadata_filter=None,
            collection_ids=[7, 8],
            include_urls=True,
        )

    def test_build_documents_query_filters_collection_case_insensitively(self):
        base_query = MagicMock(name="base_query")
        company_query = MagicMock(name="company_query")
        collection_query = MagicMock(name="collection_query")
        self.mock_session.query.return_value = base_query
        base_query.join.return_value.filter.return_value = company_query
        company_query.join.return_value.filter.return_value = collection_query

        result = self.service._build_documents_query(
            company_short_name="acme",
            collection="Contracts",
        )

        assert result == collection_query
        company_query.join.assert_called_once_with(Document.collection_type)
        filter_expression = company_query.join.return_value.filter.call_args[0][0]
        assert isinstance(filter_expression, BinaryExpression)
        assert "lower(" in str(filter_expression).lower()
        assert getattr(filter_expression.right, "value", None) == "contracts"

    def test_search_with_empty_collection_list_does_not_filter(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_vs_repo.query.return_value = []

        self.service.search(
            company_short_name="acme",
            query="find policy",
            collection=[],
        )

        self.mock_doc_repo.get_collection_ids_by_name.assert_not_called()
        self.mock_vs_repo.query.assert_called_with(
            company_short_name="acme",
            query_text="find policy",
            n_results=5,
            metadata_filter=None,
            collection_ids=None,
            include_urls=True,
        )

    def test_search_can_skip_presigned_urls_for_internal_resolution(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_vs_repo.query.return_value = []

        self.service.search(
            company_short_name="acme",
            query="find policy",
            include_urls=False,
        )

        assert self.mock_vs_repo.query.call_args.kwargs["include_urls"] is False

    def test_search_with_unknown_collection_list_returns_no_results(self):
        self.mock_profile_service.get_company_by_short_name.return_value = self.company
        self.mock_doc_repo.get_collection_ids_by_name.return_value = []

        result = self.service.search(
            company_short_name="acme",
            query="find policy",
            collection=["MissingA", "MissingB"],
        )

        assert result == []
        self.mock_vs_repo.query.assert_not_called()

    def test_ingest_document_sync_strips_nul_chars_from_chunks_and_metadata(self):
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage.upload_document.return_value = "key"
        self.mock_parsing_service.parse_document.return_value = ParseResult(
            provider="basic",
            provider_version="1.0",
            warnings=["warn\x00ing"],
            texts=[ParsedText(text="Hello\x00 world", meta={"section_title": "Intro\x00", "source_type": "text"})],
            tables=[],
            images=[],
        )

        self.service.ingest_document_sync(
            self.company,
            self.filename,
            self.content,
            metadata={"type": "contr\x00act"},
        )

        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.meta["type"] == "contract"
        assert inserted_doc.meta["parser_warnings"] == ["warning"]

        vs_docs = self.mock_vs_repo.add_document.call_args[0][1]
        assert len(vs_docs) == 1
        assert "\x00" not in vs_docs[0].text
        assert vs_docs[0].text == "Hello world"
        assert vs_docs[0].meta["type"] == "contract"
        assert vs_docs[0].meta["section_title"] == "Intro"
