# tests/repositories/test_vs_repo.py

import pytest
from unittest.mock import MagicMock, call
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.vs_repo import VSRepo, VSImage
from iatoolkit.repositories.models import VSDoc, Document, Company
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.repositories.database_manager import DatabaseManager


class TestVSRepo:
    MOCK_COMPANY_SHORT_NAME = "test-corp"
    MOCK_COMPANY_ID = 123
    MOCK_EMBEDDING_VECTOR = [0.1, 0.2, 0.3]

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks and instantiate VSRepo before each test."""
        # Mock dependencies
        self.mock_db_manager = MagicMock(spec=DatabaseManager)
        self.mock_session = self.mock_db_manager.get_session.return_value
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)

        # Instantiate the class under test
        self.vs_repo = VSRepo(
            db_manager=self.mock_db_manager,
            embedding_service=self.mock_embedding_service
        )

        # Default mock behavior
        self.mock_embedding_service.embed_text.return_value = self.MOCK_EMBEDDING_VECTOR

    def test_add_document_success(self):
        """Tests that add_document correctly generates embeddings and commits to the DB."""
        # Arrange
        vs_chunk_list = [
            VSDoc(id=1, text="Documento de prueba 1"),
            VSDoc(id=2, text="Documento de prueba 2")
        ]

        # Act
        self.vs_repo.add_document(self.MOCK_COMPANY_SHORT_NAME, vs_chunk_list)

        # Assert
        # Check that embed_text was called for each document with the correct context
        expected_calls = [
            call(self.MOCK_COMPANY_SHORT_NAME, "Documento de prueba 1" ),
            call(self.MOCK_COMPANY_SHORT_NAME, "Documento de prueba 2")
        ]
        self.mock_embedding_service.embed_text.assert_has_calls(expected_calls)

        # Check database interactions
        assert self.mock_session.add.call_count == 2
        self.mock_session.commit.assert_called_once()
        self.mock_session.rollback.assert_not_called()

    def test_add_document_rollback_on_embedding_error(self):
        """Tests that a DB rollback occurs if the embedding service fails."""
        # Arrange
        self.mock_embedding_service.embed_text.side_effect = Exception("Embedding service unavailable")
        vs_chunk_list = [VSDoc(id=1, text="Documento con error")]

        # Act & Assert
        with pytest.raises(IAToolkitException):
            self.vs_repo.add_document(self.MOCK_COMPANY_SHORT_NAME, vs_chunk_list)

        self.mock_session.rollback.assert_called_once()
        self.mock_session.commit.assert_not_called()

    def test_query_success(self):
        """Tests the happy path for the query method."""
        # Arrange
        # Mock the lookup for company_id from company_short_name
        mock_company = Company(id=self.MOCK_COMPANY_ID, short_name=self.MOCK_COMPANY_SHORT_NAME)
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_company

        # Mock the final DB query result
        db_rows = [(1, "file1.txt", "content1", "b64_1", {}, 77), (2, "file2.txt", "content2", "b64_2", {}, 88)]
        self.mock_session.execute.return_value.fetchall.return_value = db_rows

        # Act
        result_docs = self.vs_repo.query(company_short_name=self.MOCK_COMPANY_SHORT_NAME, query_text="test query")

        # Assert
        # 1. Check embedding service was called
        self.mock_embedding_service.embed_text.assert_called_once_with(self.MOCK_COMPANY_SHORT_NAME, "test query")

        # 2. Check company lookup
        self.mock_session.query.assert_called_once_with(Company)

        # 3. Check final results
        assert len(result_docs) == 2
        assert result_docs[0]['id'] == 1
        assert result_docs[0]['filename'] == "file1.txt"
        assert result_docs[0]['text'] == "content1"
        assert result_docs[0]['document_id'] == 77

    def test_query_raises_exception_on_db_error(self):
        """Tests that an IAToolkitException is raised if the DB query fails."""
        # Arrange
        mock_company = Company(id=self.MOCK_COMPANY_ID, short_name=self.MOCK_COMPANY_SHORT_NAME)
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_company
        self.mock_session.execute.side_effect = Exception("Database connection failed")

        # Act & Assert
        with pytest.raises(IAToolkitException, match="Error en la consulta"):
            self.vs_repo.query(company_short_name=self.MOCK_COMPANY_SHORT_NAME, query_text="test query")

    # --- Image Tests (Repository Layer) ---

    def test_add_image_success(self):
        """Tests adding a VSImage record."""
        vs_image = MagicMock(spec=VSImage)
        self.vs_repo.add_image(vs_image)
        self.mock_session.add.assert_called_once_with(vs_image)
        self.mock_session.commit.assert_called_once()

    def test_query_images_success(self):
        """Tests the visual search flow."""
        # Arrange
        # 1. Company lookup
        mock_company = Company(id=self.MOCK_COMPANY_ID, short_name=self.MOCK_COMPANY_SHORT_NAME)
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_company

        # 2. Embedding mock (must use model_type='image')
        self.mock_embedding_service.embed_text.return_value = [0.9] # Vector query

        # 3. DB Result (doc_id, filename, key, meta, distance)
        db_rows = [(10, "img.jpg", "path/img.jpg", {"w": 100}, 0.1)]
        self.mock_session.execute.return_value.fetchall.return_value = db_rows

        # Act
        results = self.vs_repo.query_images(self.MOCK_COMPANY_SHORT_NAME, "cat")

        # Assert
        # Verify correct embedding call
        self.mock_embedding_service.embed_text.assert_called_with(
            self.MOCK_COMPANY_SHORT_NAME, "cat", model_type='image'
        )

        # Verify result formatting
        assert len(results) == 1
        assert results[0]['filename'] == "img.jpg"
        assert results[0]['score'] == 0.9 # 1 - 0.1 distance

    def test_query_images_company_not_found(self):
        """Should return empty list if company doesn't exist."""
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = None
        results = self.vs_repo.query_images("unknown", "query")
        assert results == []

    def test_query_images_embedding_failure(self):
        """Should raise IAToolkitException if embedding fails."""
        self.mock_embedding_service.embed_text.side_effect = Exception("Model down")
        with pytest.raises(IAToolkitException) as exc:
            self.vs_repo.query_images("co", "q")
        assert exc.value.error_type == IAToolkitException.ErrorType.VECTOR_STORE_ERROR

    def test_query_images_by_image_success(self):
        """Tests the visual search flow using an image as query."""
        # Arrange
        # 1. Company lookup
        mock_company = Company(id=self.MOCK_COMPANY_ID, short_name=self.MOCK_COMPANY_SHORT_NAME)
        self.mock_session.query.return_value.filter.return_value.one_or_none.return_value = mock_company

        # 2. Embedding mock (must use embed_image)
        self.mock_embedding_service.embed_image_from_bytes.return_value = [0.8, 0.1, 0.1] # Visual vector

        # 3. DB Result (doc_id, filename, key, meta, distance)
        db_rows = [(20, "similar_photo.png", "path/photo.png", {"w": 500}, 0.05)]
        self.mock_session.execute.return_value.fetchall.return_value = db_rows

        fake_image_bytes = b"fake_content"

        # Act
        results = self.vs_repo.query_images_by_image(self.MOCK_COMPANY_SHORT_NAME, fake_image_bytes)

        # Assert
        # Verify correct embedding call: embed_image, NOT embed_text
        self.mock_embedding_service.embed_image_from_bytes.assert_called_with(
            self.MOCK_COMPANY_SHORT_NAME, fake_image_bytes
        )
        self.mock_embedding_service.embed_text.assert_not_called()

        # Verify result formatting
        assert len(results) == 1
        assert results[0]['filename'] == "similar_photo.png"
        assert results[0]['score'] == 0.95 # 1 - 0.05 distance

    def test_query_images_by_image_embedding_failure(self):
        """Should raise IAToolkitException if image embedding fails."""
        self.mock_embedding_service.embed_image_from_bytes.side_effect = Exception("Vision Model Error")
        with pytest.raises(IAToolkitException) as exc:
            self.vs_repo.query_images_by_image("co", b"img")
        assert exc.value.error_type == IAToolkitException.ErrorType.VECTOR_STORE_ERROR
