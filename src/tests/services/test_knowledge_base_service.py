# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
import base64
from unittest.mock import MagicMock, patch
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.models import (Company, Document, DocumentStatus, CollectionType)
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
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
        self.mock_storage = MagicMock(spec=StorageService)
        self.mock_visual_kb = MagicMock(spec=VisualKnowledgeBaseService)

        # Mock session for DocumentRepo (crucial for commits/rollbacks)
        self.mock_session = MagicMock()
        self.mock_doc_repo.session = self.mock_session

        # Instantiate service
        self.service = KnowledgeBaseService(
            document_repo=self.mock_doc_repo,
            vs_repo=self.mock_vs_repo,
            document_service=self.mock_doc_service,
            profile_service=self.mock_profile_service,
            i18n_service=self.mock_i18n_service,
            storage_service=self.mock_storage,
            visual_kb_service=self.mock_visual_kb
        )

        # Common test data
        self.company = Company(id=1, short_name='acme', name='Acme Corp')
        self.filename = 'contract.pdf'
        self.content = b'PDF content'
        self.metadata = {'type': 'contract'}

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

    # --- Ingestion Tests ---

    def test_ingest_document_sync_skips_if_exists(self):
        # Arrange
        existing_doc = Document(id=99, filename=self.filename)
        self.mock_doc_repo.get_by_hash.return_value = existing_doc

        # Act
        result = self.service.ingest_document_sync(self.company, self.filename, self.content)

        # Assert
        assert result == existing_doc
        self.mock_doc_repo.insert.assert_not_called()
        self.mock_storage.upload_document.assert_not_called()

    def test_ingest_document_sync_success_flow(self):
        """
        GIVEN a new file
        WHEN ingest_document_sync is called
        THEN it should upload to storage, extract text, and save vectors.
        """
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None

        # Mock storage returning a key
        fake_key = "companies/acme/docs/123/contract.pdf"
        self.mock_storage.upload_document.return_value = fake_key

        # Mock file processing
        extracted_text = "Part 1. Part 2. Part 3."
        self.mock_doc_service.file_to_txt.return_value = extracted_text

        # Act
        new_doc = self.service.ingest_document_sync(self.company, self.filename, self.content, self.metadata)

        # Assert
        # 1. Verify Storage Upload
        self.mock_storage.upload_document.assert_called_once()
        upload_args = self.mock_storage.upload_document.call_args.kwargs
        assert upload_args['company_short_name'] == 'acme'
        assert upload_args['filename'] == self.filename

        # 2. Verify initial insert with correct storage key
        self.mock_doc_repo.insert.assert_called_once()
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.ACTIVE
        assert inserted_doc.storage_key == fake_key
        assert inserted_doc.content == extracted_text

        # 3. Verify text extraction
        self.mock_doc_service.file_to_txt.assert_called_with(self.filename, self.content)

        # 4. Verify vector storage
        self.mock_vs_repo.add_document.assert_called_once()
        args, _ = self.mock_vs_repo.add_document.call_args
        assert args[0] == 'acme'
        assert len(args[1]) > 0

        # 5. Verify commits
        assert self.mock_session.commit.call_count >= 2


    def test_ingest_document_sync_handles_processing_error(self):
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage.upload_document.return_value = "key"
        self.mock_doc_service.file_to_txt.side_effect = Exception("OCR Failed")

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc:
            self.service.ingest_document_sync(self.company, self.filename, self.content)

        assert exc.value.error_type == IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR

        # Verify Document was inserted but ended up FAILED
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.status == DocumentStatus.FAILED
        assert "OCR Failed" in inserted_doc.error_message

    def test_ingest_document_assigns_collection_id(self):
        # Arrange
        metadata = {'collection': 'Legal'}
        mock_collection_type = CollectionType(id=55, name='Legal')
        self.mock_session.query.return_value.filter_by.return_value.first.return_value = mock_collection_type

        self.mock_storage.upload_document.return_value = "key"
        self.mock_doc_service.file_to_txt.return_value = "content"
        self.mock_doc_repo.get_by_hash.return_value = None

        # Act
        self.service.ingest_document_sync(self.company, "file.pdf", b"data", metadata=metadata)

        # Assert
        inserted_doc = self.mock_doc_repo.insert.call_args[0][0]
        assert inserted_doc.collection_type_id == 55

    # --- Get Content Tests ---

    def test_get_document_content_from_storage(self):
        """
        Tests retrieving content using the new storage_key mechanism.
        """
        # Arrange
        mock_doc = Document(id=1, filename="test.pdf", storage_key="path/to/file")
        mock_doc.company = self.company # Need company for short_name
        self.mock_doc_repo.get_by_id.return_value = mock_doc

        expected_bytes = b"Storage Content"
        self.mock_storage.get_document_content.return_value = expected_bytes

        # Act
        content, filename = self.service.get_document_content(1)

        # Assert
        self.mock_storage.get_document_content.assert_called_once_with('acme', "path/to/file")
        assert content == expected_bytes
        assert filename == "test.pdf"
    # --- Delete Tests ---

    def test_delete_document_success_cleans_storage(self):
        """
        GIVEN a document with storage_key
        WHEN delete_document is called
        THEN it should call storage_service.delete_file and remove from DB.
        """
        # Arrange
        doc = Document(id=1, storage_key="path/key")
        doc.company = self.company # Needed for company.short_name
        self.mock_doc_repo.get_by_id.return_value = doc

        # Act
        result = self.service.delete_document(1)

        # Assert
        assert result is True
        # Verify storage cleanup call
        self.mock_storage.delete_file.assert_called_once_with('acme', "path/key")

        # Verify DB delete
        self.mock_session.delete.assert_called_with(doc)
        self.mock_session.commit.assert_called()

    def test_delete_document_not_found(self):
        self.mock_doc_repo.get_by_id.return_value = None
        result = self.service.delete_document(999)
        assert result is False
        self.mock_storage.delete_file.assert_not_called()