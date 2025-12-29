# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
import base64
from unittest.mock import MagicMock, call
from datetime import datetime

from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import (Company, Document,
                                           DocumentStatus, CollectionType)
from iatoolkit.common.exceptions import IAToolkitException


class TestKnowledgeBaseService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # Mocks for dependencies
        self.mock_doc_repo = MagicMock(spec=DocumentRepo)
        self.mock_vs_repo = MagicMock(spec=VSRepo)
        self.mock_doc_service = MagicMock(spec=DocumentService)
        self.mock_profile_service = MagicMock(spec=ProfileService)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        # Mock session for DocumentRepo (crucial for commits/rollbacks)
        self.mock_session = MagicMock()
        self.mock_doc_repo.session = self.mock_session

        # Instantiate service
        self.service = KnowledgeBaseService(
            document_repo=self.mock_doc_repo,
            vs_repo=self.mock_vs_repo,
            document_service=self.mock_doc_service,
            profile_service=self.mock_profile_service,
            i18n_service=self.mock_i18n_service
        )

        # Common test data
        self.company = Company(id=1, short_name='acme', name='Acme Corp')
        self.filename = 'contract.pdf'
        self.content = b'PDF content'
        self.metadata = {'type': 'contract'}

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"


    # --- Ingestion Tests ---

    def test_ingest_document_sync_skips_if_exists(self):
        """
        GIVEN a document that already exists in the repo
        WHEN ingest_document_sync is called
        THEN it should return the existing document without processing.
        """
        # Arrange
        existing_doc = Document(id=99, filename=self.filename)
        self.mock_doc_repo.get_by_hash.return_value = existing_doc

        # Act
        result = self.service.ingest_document_sync(self.company, self.filename, self.content)

        # Assert
        assert result == existing_doc
        self.mock_doc_repo.insert.assert_not_called()
        self.mock_doc_service.file_to_txt.assert_not_called()

    def test_ingest_document_sync_success_flow(self):
        """
        GIVEN a new file
        WHEN ingest_document_sync is called
        THEN it should extraction text, split it, and save vectors.
        """
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None

        # Mock file processing
        extracted_text = "Part 1. Part 2. Part 3."
        self.mock_doc_service.file_to_txt.return_value = extracted_text

        # Act
        new_doc = self.service.ingest_document_sync(self.company, self.filename, self.content, self.metadata)

        # Assert
        # 1. Verify initial insert
        self.mock_doc_repo.insert.assert_called_once()
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.ACTIVE  # Should end as ACTIVE
        assert inserted_doc.filename == self.filename
        assert inserted_doc.content == extracted_text

        # 2. Verify text extraction
        self.mock_doc_service.file_to_txt.assert_called_with(self.filename, self.content)

        # 3. Verify vector storage
        # We expect add_document to be called with the company short name and a list of VSDocs
        self.mock_vs_repo.add_document.assert_called_once()
        args, _ = self.mock_vs_repo.add_document.call_args
        assert args[0] == 'acme' # company_short_name
        assert isinstance(args[1], list) # vs_docs list
        assert len(args[1]) > 0
        assert args[1][0].text in extracted_text

        # 4. Verify commits (Insert + Processing + Finalize)
        assert self.mock_session.commit.call_count >= 2

    def test_ingest_document_sync_handles_processing_error(self):
        """
        GIVEN a file that fails during text extraction
        WHEN ingest_document_sync is called
        THEN it should mark the document as FAILED and raise exception.
        """
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_doc_service.file_to_txt.side_effect = Exception("OCR Failed")

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc:
            self.service.ingest_document_sync(self.company, self.filename, self.content)

        assert exc.value.error_type == IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR

        # Verify Document was inserted but ended up FAILED
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.FAILED
        assert "OCR Failed" in inserted_doc.error_message

        # Verify rollback was called for the processing transaction
        self.mock_session.rollback.assert_called()

    def test_ingest_document_assigns_collection_id(self):
        """
        GIVEN metadata contains a valid collection name
        WHEN ingest_document_sync is called
        THEN the created document should have the correct collection_type_id.
        """
        # Arrange
        metadata = {'collection': 'Legal'}

        # Mock finding the collection ID
        mock_collection_type = CollectionType(id=55, name='Legal')
        self.mock_session.query.return_value.filter_by.return_value.first.return_value = mock_collection_type

        # Mock processing
        self.mock_doc_service.file_to_txt.return_value = "content"
        self.mock_doc_repo.get_by_hash.return_value = None

        # Act
        new_doc = self.service.ingest_document_sync(self.company, "file.pdf", b"data", metadata=metadata)

        # Assert
        self.mock_doc_repo.insert.assert_called()
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.collection_type_id == 55

    def test_ingest_document_ignores_invalid_collection(self):
        """
        GIVEN metadata contains a non-existent collection name
        WHEN ingest_document_sync is called
        THEN collection_type_id should be None.
        """
        # Arrange
        metadata = {'collection': 'Unknown'}
        # Mock finding nothing
        self.mock_session.query.return_value.filter_by.return_value.first.return_value = None
        self.mock_doc_service.file_to_txt.return_value = "content"
        self.mock_doc_repo.get_by_hash.return_value = None

        # Act
        new_doc = self.service.ingest_document_sync(self.company, "file.pdf", b"data", metadata=metadata)

        # Assert
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.collection_type_id is None

    # --- Search Tests ---

    def test_search_returns_formatted_context(self):
        """
        GIVEN a search query
        WHEN search is called
        THEN it should return a string with concatenated results from VSRepo.
        """
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = self.company

        doc1 = {'id': 1, 'filename': 'doc1.txt', 'text': 'Content 1'}
        doc2 = {'id': 2, 'filename': 'doc2.txt', 'text': 'Content 2', 'meta': {'document_type': 'guide'}}

        self.mock_vs_repo.query.return_value = [doc1, doc2]

        # Act
        result = self.service.search('acme', "some query")

        # Assert
        self.mock_vs_repo.query.assert_called_with(
            company_short_name='acme',
            query_text="some query",
            n_results=5,
            metadata_filter=None
        )
        assert 'document "doc1.txt": Content 1' in result
        assert 'document "doc2.txt" type: guide: Content 2' in result

    def test_search_returns_error_if_company_not_found(self):
        self.mock_profile_service.get_company_by_short_name.return_value = None
        result = self.service.search('unknown', 'query')
        assert 'translated:rag.search.company_not_found' in result

    # --- Search Raw Tests ---

    def test_search_raw_returns_list_of_results(self):
        """
        GIVEN a valid company and query
        WHEN search_raw is called
        THEN it should delegate to vs_repo and return the result list directly.
        """
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = self.company

        # Simulating results (can be objects or dicts depending on repo impl, testing passthrough)
        mock_results = [{'id': 1, 'text': 'match'}, {'id': 2, 'text': 'match2'}]
        self.mock_vs_repo.query.return_value = mock_results

        # Act
        result = self.service.search_raw('acme', "my query", n_results=10)

        # Assert
        assert result == mock_results
        self.mock_vs_repo.query.assert_called_with(
            company_short_name='acme',
            query_text="my query",
            n_results=10,
            metadata_filter=None,
            collection_id=None,
        )

    def test_search_raw_returns_empty_if_company_not_found(self):
        """
        GIVEN a non-existent company
        WHEN search_raw is called
        THEN it should return an empty list (safe fallback).
        """
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = None

        # Act
        result = self.service.search_raw('unknown_corp', "query")

        # Assert
        assert result == []
        self.mock_vs_repo.query.assert_not_called()

    def test_search_raw_passes_collection_id(self):
        """
        GIVEN a search request with a collection name
        WHEN search_raw is called
        THEN it should resolve the ID and pass it to vs_repo.
        """
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = self.company

        # Mock resolving 'Legal' -> ID 55
        mock_collection_type = CollectionType(id=55, name='Legal')
        self.mock_session.query.return_value.filter_by.return_value.first.return_value = mock_collection_type

        # Act
        self.service.search_raw('acme', "query", collection='Legal')

        # Assert
        self.mock_vs_repo.query.assert_called_with(
            company_short_name='acme',
            query_text="query",
            n_results=5,
            metadata_filter=None,
            collection_id=55  # New param check
        )

    # --- List Documents Tests ---

    def test_list_documents_builds_correct_query(self):
        """
        GIVEN filter parameters
        WHEN list_documents is called
        THEN it should construct a SQLAlchemy query with joins and filters.
        """
        # Arrange - Mock the chaining of sqlalchemy query object
        mock_query = self.mock_session.query.return_value
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = []

        # Act
        self.service.list_documents(
            company_short_name='acme',
            status='active',
            filename_keyword='report',
            limit=10,
            offset=0
        )

        # Assert
        # 1. Check join with Company
        self.mock_session.query.assert_called_with(Document)
        mock_query.join.assert_called_with(Company)

        # 2. Check filters are applied (we can't easily check exact SQL expression equality
        # with simple mocks, but we verify .filter() calls count)
        # We expect at least: Company name, Status, Keyword
        assert mock_query.filter.call_count >= 3

        # 3. Check pagination
        mock_query.limit.assert_called_with(10)
        mock_query.offset.assert_called_with(0)

    def test_list_documents_filters_by_collection(self):
        """
        GIVEN list_documents is called with a collection name
        THEN it should join with CollectionType and filter by name.
        """
        # Arrange mocks for query chaining
        mock_query = self.mock_session.query.return_value
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.all.return_value = []

        # Act
        self.service.list_documents('acme', collection='Legal')

        # Assert
        # Verify join called (we expect at least 2 joins: Company and CollectionType)
        assert mock_query.join.call_count >= 2
        # Verify filtering logic (hard to check exact args with chained mocks, but ensure it filters)
        assert mock_query.filter.call_count >= 1

    # --- Delete Tests ---

    def test_delete_document_success(self):
        """
        GIVEN an existing document ID
        WHEN delete_document is called
        THEN it should delete the document from session.
        """
        # Arrange
        doc = Document(id=1)
        self.mock_doc_repo.get_by_id.return_value = doc

        # Act
        result = self.service.delete_document(1)

        # Assert
        assert result is True
        self.mock_session.delete.assert_called_with(doc)
        self.mock_session.commit.assert_called()

    def test_delete_document_not_found(self):
        self.mock_doc_repo.get_by_id.return_value = None
        result = self.service.delete_document(999)
        assert result is False
        self.mock_session.delete.assert_not_called()

    def test_delete_document_exception_handling(self):
        # Arrange
        self.mock_doc_repo.get_by_id.return_value = Document(id=1)
        self.mock_session.delete.side_effect = Exception("DB Error")

        # Act & Assert
        with pytest.raises(IAToolkitException):
            self.service.delete_document(1)

        self.mock_session.rollback.assert_called()

    def test_get_document_content_success(self):
        """
        GIVEN an existing document ID with valid base64 content
        WHEN get_document_content is called
        THEN it should return the decoded bytes and the filename.
        """
        # Arrange
        original_content = b"Hello World PDF"
        b64_content = base64.b64encode(original_content).decode('utf-8')

        mock_doc = Document(id=1, filename="test.pdf", content_b64=b64_content)
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        # Act
        content, filename = self.service.get_document_content(1)

        # Assert
        assert content == original_content
        assert filename == "test.pdf"
        self.mock_doc_repo.get_by_id.assert_called_with(1)

    def test_get_document_content_not_found(self):
        """
        GIVEN a non-existent document ID
        WHEN get_document_content is called
        THEN it should return (None, None).
        """
        self.mock_doc_repo.get_by_id.return_value = None

        content, filename = self.service.get_document_content(999)

        assert content is None
        assert filename is None

    def test_get_document_content_no_b64_data(self):
        """
        GIVEN a document that exists but has no content_b64
        WHEN get_document_content is called
        THEN it should return (None, None).
        """
        mock_doc = Document(id=1, filename="empty.pdf", content_b64=None)
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        content, filename = self.service.get_document_content(1)

        assert content is None
        assert filename is None

    def test_get_document_content_invalid_base64(self):
        """
        GIVEN a document with corrupted base64 data
        WHEN get_document_content is called
        THEN it should raise an IAToolkitException.
        """
        # Arrange
        mock_doc = Document(id=1, filename="corrupt.pdf", content_b64="not-a-valid-base64!!")
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc:
            self.service.get_document_content(1)

        assert exc.value.error_type == IAToolkitException.ErrorType.FILE_FORMAT_ERROR

    def test_sync_collection_types_creates_new_types(self):
        """
        GIVEN configuration has collection categories
        WHEN sync_collection_types is called
        THEN it should create missing CollectionType records in DB.
        """
        # Arrange
        self.mock_profile_service.get_company_by_short_name.return_value = self.company

        # Simulate that 'Legal' already exists but 'Technical' does not
        existing_type = CollectionType(name='Legal', company_id=self.company.id)
        self.mock_session.query.return_value.filter_by.return_value.all.return_value = [existing_type]

        # Act
        self.service.sync_collection_types('test_company', ['Legal', 'Technical'])

        # Assert
        # Should add 'Technical'
        self.mock_session.add.assert_called_once()
        added_obj = self.mock_session.add.call_args[0][0]
        assert isinstance(added_obj, CollectionType)
        assert added_obj.name == 'Technical'
        assert added_obj.company_id == self.company.id
        self.mock_session.commit.assert_called()
