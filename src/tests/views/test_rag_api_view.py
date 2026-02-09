# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask
from unittest.mock import MagicMock
from datetime import datetime

from iatoolkit.views.rag_api_view import RagApiView
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility
from iatoolkit.repositories.models import Document, DocumentStatus


class TestRagApiView:
    """Test suite for RagApiView endpoints."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.app.secret_key = "test-secret"

        # Mock dependencies
        self.mock_kb_service = MagicMock(spec=KnowledgeBaseService)
        self.mock_visual_kb_service = MagicMock(spec=VisualKnowledgeBaseService)
        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_utility = MagicMock(spec=Utility)
        self.mock_i8n_service = MagicMock(spec=I18nService)

        self.mock_i8n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        # Register the view
        rag_view = RagApiView.as_view(
            'rag_api',
            knowledge_base_service=self.mock_kb_service,
            visual_kb_service=self.mock_visual_kb_service,
            auth_service=self.mock_auth_service,
            i18n_service=self.mock_i8n_service,
            utility=self.mock_utility
        )

        # 1. List Files
        self.app.add_url_rule(
            '/<company_short_name>/api/rag/files',
            view_func=rag_view,
            methods=['POST'],
            defaults={'action': 'list_files'}
        )

        # 2. Delete File
        self.app.add_url_rule(
            '/<company_short_name>/api/rag/files/<int:document_id>',
            view_func=rag_view,
            methods=['DELETE'],
            defaults={'action': 'delete_file'}
        )

        # 3. Search
        self.app.add_url_rule(
            '/<company_short_name>/api/rag/search',
            view_func=rag_view,
            methods=['POST'],
            defaults={'action': 'search'}
        )

        self.app.add_url_rule(
            '/<company_short_name>/api/rag/search/text',
            view_func=rag_view,
            methods=['POST'],
            defaults={'action': 'search_text'}
        )

        self.app.add_url_rule(
            '/<company_short_name>/api/rag/search/image',
            view_func=rag_view,
            methods=['POST'],
            defaults={'action': 'search_image'}
        )

        self.app.add_url_rule(
            '/<company_short_name>/api/rag/search/visual',
            view_func=rag_view,
            methods=['POST'],
            defaults={'action': 'search_visual'}
        )

        # 4. Get Content (New route)
        self.app.add_url_rule(
            '/<company_short_name>/api/rag/files/<int:document_id>/content',
            view_func=rag_view,
            methods=['GET'],
            defaults={'action': 'get_file_content'}
        )

        self.company_short_name = "acme"

        # Setup Auth Success by default
        self.mock_auth_service.verify.return_value = {
            "success": True,
            "user_identifier": "test@acme.com",
            "company_short_name": "acme"
        }

    # --- List Files Tests ---

    def test_list_files_success(self):
        """Should return a list of documents formatted as JSON."""
        # Arrange
        mock_doc = Document(
            id=1,
            filename="contract.pdf",
            status=DocumentStatus.ACTIVE,
            created_at=datetime(2024, 1, 1),
            meta={"type": "contract"},
            error_message=None
        )
        self.mock_kb_service.list_documents.return_value = [mock_doc]

        payload = {
            "user_identifier": "fl",
            "status": "active",
            "limit": 10,
        }

        # Act
        response = self.client.post(f'/{self.company_short_name}/api/rag/files', json=payload)

        # Assert
        assert response.status_code == 200
        data = response.get_json()
        assert data['result'] == 'success'
        assert data['count'] == 1
        assert data['documents'][0]['filename'] == 'contract.pdf'

        # Verify service call params
        self.mock_kb_service.list_documents.assert_called_with(
            company_short_name=self.company_short_name,
            status='active',
            user_identifier='fl',
            filename_keyword=None,
            collection='',
            from_date=None,
            to_date=None,
            limit=10,
            offset=0
        )
        self.mock_auth_service.verify.assert_called_once()

    def test_list_files_auth_error(self):
        """Should return error if auth verify fails."""
        self.mock_auth_service.verify.return_value = {
            "success": False,
            "status_code": 401,
            "error_message": "Auth failed"
        }

        response = self.client.post(f'/{self.company_short_name}/api/rag/files', json={})

        assert response.status_code == 401
        assert response.get_json()['error_message'] == 'Auth failed'
        self.mock_kb_service.list_documents.assert_not_called()

    # --- Get File Content Tests ---

    def test_get_file_content_success(self):
        """Should stream the file content with correct headers."""
        # Arrange
        file_bytes = b"%PDF-1.4..."
        filename = "manual.pdf"
        self.mock_kb_service.get_document_content.return_value = (file_bytes, filename)

        # Act
        response = self.client.get(f'/{self.company_short_name}/api/rag/files/10/content')

        # Assert
        assert response.status_code == 200
        assert response.data == file_bytes
        # Flask send_file sets mimetype based on filename guess or default
        assert response.mimetype == 'application/pdf'
        # Check for inline disposition
        assert 'inline' in response.headers.get('Content-Disposition', '')

        self.mock_kb_service.get_document_content.assert_called_with(10)

    def test_get_file_content_not_found(self):
        """Should return 404 if service returns None."""
        # Arrange
        self.mock_kb_service.get_document_content.return_value = (None, None)

        # Act
        response = self.client.get(f'/{self.company_short_name}/api/rag/files/999/content')

        # Assert
        assert response.status_code == 404
        assert response.get_json()['result'] == 'error'

    def test_get_file_content_auth_fail(self):
        """Should return 401 if auth fails."""
        self.mock_auth_service.verify.return_value = {"success": False, "status_code": 401}

        response = self.client.get(f'/{self.company_short_name}/api/rag/files/10/content')

        assert response.status_code == 401
        self.mock_kb_service.get_document_content.assert_not_called()

    # --- Delete File Tests ---

    def test_delete_file_success(self):
        """Should return success message when document is deleted."""
        self.mock_kb_service.delete_document.return_value = True

        response = self.client.delete(f'/{self.company_short_name}/api/rag/files/123')

        assert response.status_code == 200
        assert 'translated:rag.management.delete_success' in  response.get_json()['message']
        self.mock_kb_service.delete_document.assert_called_with(123)

    def test_delete_file_not_found(self):
        """Should return 404 if document does not exist."""
        self.mock_kb_service.delete_document.return_value = False

        response = self.client.delete(f'/{self.company_short_name}/api/rag/files/999')

        assert response.status_code == 404
        assert response.get_json()['result'] == 'error'

    # --- Search Tests ---

    def test_search_success(self):
        """Should return structured search results."""
        # Arrange
        mock_doc = {
            'id': 10,
            'filename': 'guide.pdf',
            'text': 'This is a relevant chunk',
            'meta': {'page': 5},
            'count': 1
        }

        self.mock_kb_service.search.return_value = [mock_doc]

        payload = {
            "query": "how to install",
            "k": 3
        }

        # Act
        response = self.client.post(f'/{self.company_short_name}/api/rag/search', json=payload)

        # Assert
        assert response.status_code == 200
        data = response.get_json()
        assert data['result'] == 'success'
        assert data['chunks'][0]['text'] == "This is a relevant chunk"

        self.mock_kb_service.search.assert_called_with(
            company_short_name=self.company_short_name,
            query="how to install",
            n_results=3,
            collection=None,
            metadata_filter=None
        )

    def test_list_files_with_collection_filter(self):
        """Should pass collection filter to service."""
        # Arrange
        self.mock_kb_service.list_documents.return_value = []
        payload = {
            "collection": "Legal"
        }

        # Act
        self.client.post(f'/{self.company_short_name}/api/rag/files', json=payload)

        # Assert
        self.mock_kb_service.list_documents.assert_called_with(
            company_short_name=self.company_short_name,
            status=[],
            user_identifier=None,
            filename_keyword=None,
            from_date=None,
            to_date=None,
            limit=100,
            offset=0,
            collection="Legal" # Verify new param
        )

    def test_search_with_collection(self):
        """Should pass collection filter to service search."""
        # Arrange
        self.mock_kb_service.search.return_value = []
        payload = {
            "query": "test",
            "collection": "Technical"
        }

        # Act
        self.client.post(f'/{self.company_short_name}/api/rag/search', json=payload)

        # Assert
        self.mock_kb_service.search.assert_called_with(
            company_short_name=self.company_short_name,
            query="test",
            n_results=5,
            metadata_filter=None,
            collection="Technical" # Verify new param
        )

    def test_search_with_metadata_filter(self):
        self.mock_kb_service.search.return_value = []
        payload = {
            "query": "tables",
            "metadata_filter": {
                "chunk.source_type": "table",
                "doc.type": "invoice",
            }
        }

        self.client.post(f'/{self.company_short_name}/api/rag/search', json=payload)

        self.mock_kb_service.search.assert_called_with(
            company_short_name=self.company_short_name,
            query="tables",
            n_results=5,
            metadata_filter={
                "chunk.source_type": "table",
                "doc.type": "invoice",
            },
            collection=None
        )

    def test_search_missing_query(self):
        """Should return 400 if query is missing."""
        response = self.client.post(f'/{self.company_short_name}/api/rag/search', json={"k": 5})
        assert response.status_code == 400
        assert 'translated:rag.search.query_required' in response.get_json()['message']

    def test_search_text_endpoint_success(self):
        self.mock_kb_service.search.return_value = [{
            "id": 11,
            "document_id": 3,
            "filename": "contract.pdf",
            "url": "https://signed/doc",
            "text": "payment terms",
            "chunk_meta": {"source_type": "text", "page_start": 2},
            "meta": {"type": "contract"},
        }]

        response = self.client.post(f'/{self.company_short_name}/api/rag/search/text', json={
            "query": "payment terms",
            "collection": "legal",
            "n_results": 3,
            "metadata_filter": [{"key": "source_type", "value": "text"}]
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["result"] == "success"
        assert data["mode"] == "text"
        assert data["count"] == 1
        assert data["results"][0]["filename_link"] == "[contract.pdf](https://signed/doc)"
        assert "serialized_context" in data

        self.mock_kb_service.search.assert_called_with(
            company_short_name=self.company_short_name,
            query="payment terms",
            n_results=3,
            collection="legal",
            metadata_filter=[{"key": "source_type", "value": "text"}],
        )

    def test_search_image_endpoint_success(self):
        self.mock_visual_kb_service.search_images.return_value = [{
            "id": 9,
            "image_id": 44,
            "filename": "manual.pdf",
            "document_url": "https://signed/manual",
            "filename_link": "[manual.pdf](https://signed/manual)",
            "url": "https://signed/image",
            "score": 0.92,
            "page": 1,
            "image_index": 1,
            "meta": {"caption_text": "front page"},
            "document_meta": {"type": "manual"},
        }]

        response = self.client.post(f'/{self.company_short_name}/api/rag/search/image', json={
            "query": "front page",
            "n_results": 4
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["result"] == "success"
        assert data["mode"] == "image"
        assert data["count"] == 1
        assert data["results"][0]["image_url"] == "https://signed/image"
        assert data["results"][0]["filename_link"] == "[manual.pdf](https://signed/manual)"

        self.mock_visual_kb_service.search_images.assert_called_with(
            company_short_name=self.company_short_name,
            query="front page",
            n_results=4,
            collection=None,
            metadata_filter=None,
        )

    def test_search_visual_endpoint_success(self):
        self.mock_utility.normalize_base64_payload.return_value = b"img-bytes"
        self.mock_visual_kb_service.search_similar_images.return_value = [{
            "id": 15,
            "image_id": 77,
            "filename": "invoice.pdf",
            "document_url": "https://signed/invoice",
            "filename_link": "[invoice.pdf](https://signed/invoice)",
            "url": "https://signed/invoice-img",
            "score": 0.81,
            "page": 2,
            "image_index": 3,
            "meta": {},
            "document_meta": {},
        }]

        response = self.client.post(f'/{self.company_short_name}/api/rag/search/visual', json={
            "image_base64": "aGVsbG8=",
            "collection": "invoices",
            "n_results": 2
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["result"] == "success"
        assert data["mode"] == "visual"
        assert data["count"] == 1
        assert data["results"][0]["filename"] == "invoice.pdf"
        assert data["results"][0]["image_url"] == "https://signed/invoice-img"

        self.mock_visual_kb_service.search_similar_images.assert_called_with(
            company_short_name=self.company_short_name,
            image_content=b"img-bytes",
            n_results=2,
            collection="invoices",
            metadata_filter=None,
        )

    def test_search_visual_missing_image_base64(self):
        response = self.client.post(f'/{self.company_short_name}/api/rag/search/visual', json={})
        assert response.status_code == 400
        data = response.get_json()
        assert data["result"] == "error"
        assert data["error_code"] == "INVALID_REQUEST"

    def test_search_text_invalid_n_results(self):
        response = self.client.post(f'/{self.company_short_name}/api/rag/search/text', json={
            "query": "x",
            "n_results": 99
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data["result"] == "error"
        assert data["error_code"] == "INVALID_REQUEST"
