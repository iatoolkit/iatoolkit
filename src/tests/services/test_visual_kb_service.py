# tests/services/test_visual_kb_service.py
import pytest
from unittest.mock import MagicMock, patch
import hashlib
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.vs_repo import VSRepo
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.models import Company, Document, VSImage, DocumentStatus
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.profile_repo import ProfileRepo

class TestVisualKnowledgeBaseService:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_doc_repo = MagicMock(spec=DocumentRepo)
        self.mock_vs_repo = MagicMock(spec=VSRepo)
        self.mock_embedding_service = MagicMock(spec=EmbeddingService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)

        # MOCK StorageService: Explicitly attach methods to avoid AttributeError
        self.mock_storage_service = MagicMock(spec=StorageService)
        self.mock_storage_service.upload_document = MagicMock()
        self.mock_storage_service.generate_presigned_url = MagicMock()

        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.service = VisualKnowledgeBaseService(
            document_repo=self.mock_doc_repo,
            vs_repo=self.mock_vs_repo,
            embedding_service=self.mock_embedding_service,
            storage_service=self.mock_storage_service,
            i18n_service=self.mock_i18n_service,
            profile_repo=self.mock_profile_repo
        )

        self.company = Company(id=1, short_name='test_co')
        self.image_content = b'\x89PNG\r\n\x1a\n...' # Fake PNG header
        self.filename = "photo.png"
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company

    def test_ingest_image_skips_duplicates(self):
        """Should return existing document if hash matches."""
        # Arrange
        file_hash = hashlib.sha256(self.image_content).hexdigest()
        existing_doc = Document(id=99, filename=self.filename)
        self.mock_doc_repo.get_by_hash.return_value = existing_doc

        # Act
        result = self.service.ingest_image_sync(self.company, self.filename, self.image_content)

        # Assert
        assert result == existing_doc
        self.mock_doc_repo.insert.assert_not_called()
        self.mock_storage_service.upload_document.assert_not_called()

    def test_ingest_image_success_flow(self):
        """Should upload to storage, embed, and save records."""
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage_service.upload_document.return_value = "s3://bucket/photo.png"
        self.mock_storage_service.generate_presigned_url.return_value = "https://signed.url/photo.png"

        expected_vector = [0.1, 0.2, 0.3]
        self.mock_embedding_service.embed_image.return_value = expected_vector

        # Mock PIL behavior inside _extract_image_meta
        with patch("PIL.Image.open") as mock_img_open:
            mock_img = MagicMock()
            mock_img.width = 800
            mock_img.height = 600
            mock_img.format = "PNG"
            mock_img_open.return_value.__enter__.return_value = mock_img

            # Act
            doc = self.service.ingest_image_sync(
                self.company,
                self.filename,
                self.image_content,
                metadata={'category': 'logo'}
            )

            # Assert
            # 1. Storage Upload
            self.mock_storage_service.upload_document.assert_called_with(
                company_short_name='test_co',
                file_content=self.image_content,
                filename=self.filename,
                mime_type='image/png'
            )

            # 2. Embed Image
            self.mock_embedding_service.embed_image.assert_called_with(
                'test_co', "https://signed.url/photo.png"
            )

            # 3. Save Document
            self.mock_doc_repo.insert.assert_called_once()
            saved_doc = self.mock_doc_repo.insert.call_args[0][0]
            assert saved_doc.status == DocumentStatus.ACTIVE
            assert saved_doc.storage_key == "s3://bucket/photo.png"
            assert saved_doc.meta['width'] == 800
            assert saved_doc.meta['category'] == 'logo'

            # 4. Save VSImage
            self.mock_vs_repo.add_image.assert_called_once()
            saved_vs = self.mock_vs_repo.add_image.call_args[0][0]
            assert saved_vs.embedding == expected_vector
            assert saved_vs.document_id == saved_doc.id

    def test_ingest_image_handles_pil_missing(self):
        """Should gracefully handle missing PIL library or invalid image."""
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage_service.upload_document.return_value = "key"
        self.mock_embedding_service.embed_image.return_value = [0.1]

        # Patch PIL import to fail
        with patch.dict('sys.modules', {'PIL': None}):
            # Act
            doc = self.service.ingest_image_sync(self.company, self.filename, self.image_content)

            # Assert
            saved_doc = self.mock_doc_repo.insert.call_args[0][0]
            assert 'width' not in saved_doc.meta

    def test_ingest_image_error_handling(self):
        """Should raise IAToolkitException on failure."""
        # Arrange
        self.mock_doc_repo.get_by_hash.return_value = None
        self.mock_storage_service.upload_document.side_effect = Exception("S3 Down")

        # Act & Assert
        with pytest.raises(IAToolkitException) as exc:
            self.service.ingest_image_sync(self.company, self.filename, self.image_content)

        assert exc.value.error_type == IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR
        assert "S3 Down" in str(exc.value)

    # --- Search Tests ---

    def test_search_images_success(self):
        """Should return formatted results with signed URLs."""
        # Arrange
        mock_results = [{
            'document_id': 1,
            'filename': 'pic.jpg',
            'storage_key': 'key1',
            'meta': {},
            'score': 0.95
        }]
        self.mock_vs_repo.query_images.return_value = mock_results
        self.mock_storage_service.generate_presigned_url.return_value = "https://signed.url/pic.jpg"
        self.mock_doc_repo.get_collection_type_by_name.return_value = MagicMock(id=99)
        # Act
        results = self.service.search_images('test_co', 'dog', collection='riesgo')

        # Assert
        self.mock_vs_repo.query_images.assert_called_with(
            company_short_name='test_co',
            query_text='dog',
            n_results=5,
            collection_id=99
        )
        assert len(results) == 1
        assert results[0]['url'] == "https://signed.url/pic.jpg"
        assert results[0]['score'] == 0.95

    def test_search_similar_images_success(self):
        """Should return formatted results for image-to-image search."""
        # Arrange
        mock_results = [{
            'document_id': 2,
            'filename': 'similar.jpg',
            'storage_key': 'key2',
            'meta': {},
            'score': 0.88
        }]
        self.mock_vs_repo.query_images_by_image.return_value = mock_results
        self.mock_storage_service.generate_presigned_url.return_value = "https://signed.url/similar.jpg"

        query_image_bytes = b"fake_image_data"

        # Act
        results = self.service.search_similar_images('test_co', query_image_bytes)

        # Assert
        self.mock_vs_repo.query_images_by_image.assert_called_with(
            company_short_name='test_co',
            image_bytes=query_image_bytes,
            n_results=5
        )
        assert len(results) == 1
        assert results[0]['url'] == "https://signed.url/similar.jpg"
        assert results[0]['score'] == 0.88

    def test_search_images_empty_query(self):
        """Should return empty list for empty query."""
        results = self.service.search_images('test_co', '')
        assert results == []
        self.mock_vs_repo.query_images.assert_not_called()