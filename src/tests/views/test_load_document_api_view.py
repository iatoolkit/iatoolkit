# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from flask import Flask
from iatoolkit.views.load_document_api_view import LoadDocumentApiView
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.auth_service import AuthService
from iatoolkit.repositories.models import Document
import base64


class TestLoadDocumentView:

    def setup_method(self):
        self.app = Flask(__name__)
        self.client = self.app.test_client()
        self.url = '/api/load-document'

        # Mock the services
        self.mock_kb_service = MagicMock(spec=KnowledgeBaseService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_auth = MagicMock(spec=AuthService)

        # Instantiate the view with mocked services
        self.file_store_view = LoadDocumentApiView.as_view("load",
                                                           knowledge_base_service=self.mock_kb_service,
                                                           profile_repo=self.mock_profile_repo,
                                                           auth_service=self.mock_auth)
        self.app.add_url_rule(self.url, view_func=self.file_store_view, methods=["POST"])
        self.mock_auth.verify_for_company.return_value = {"success": True}

    @pytest.mark.parametrize("missing_field", ["company", "filename", "content"])
    def test_post_when_missing_required_fields(self, missing_field):
        payload = {
            "company": "test_company",
            "filename": "test_file.txt",
            "content": base64.b64encode(b"test content").decode('utf-8'),
            "metadata": {"key": "value"}
        }
        payload.pop(missing_field)

        response = self.client.post(self.url, json=payload)

        assert response.status_code == 400
        assert response.get_json() == {
            "error": f"El campo {missing_field} es requerido"
        }

        self.mock_kb_service.ingest_document_sync.assert_not_called()

    def test_post_when_company_not_found(self):
        # Mock the profile repo to return None for the company
        self.mock_profile_repo.get_company_by_short_name.return_value = None

        payload = {
            "company": "nonexistent_company",
            "filename": "test_file.txt",
            "content": base64.b64encode(b"test content").decode('utf-8'),
            "metadata": {"key": "value"}
        }

        response = self.client.post(self.url, json=payload)

        assert response.status_code == 400
        assert response.get_json() == {
            "error": "La empresa nonexistent_company no existe"
        }

        self.mock_profile_repo.get_company_by_short_name.assert_called_once_with("nonexistent_company")
        self.mock_kb_service.ingest_document_sync.assert_not_called()


    def test_post_when_company_not_auth(self):
        # Mock auth failure
        self.mock_auth.verify_for_company.return_value = {"success": False, "status_code": 401}

        payload = {
            "company": "nonexistent_company",
            "filename": "test_file.txt",
            "content": base64.b64encode(b"test content").decode('utf-8'),
            "metadata": {"key": "value"}
        }

        response = self.client.post(self.url, json=payload)
        assert response.status_code == 401


        self.mock_kb_service.ingest_document_sync.assert_not_called()

    def test_post_when_internal_exception_error(self):
        # Mock the profile repo to return a company
        mock_company = MagicMock()
        self.mock_profile_repo.get_company_by_short_name.return_value = mock_company

        # Mock the kb service to raise an exception
        self.mock_kb_service.ingest_document_sync.side_effect = Exception("Internal Error")

        payload = {
            "company": "test_company",
            "filename": "test_file.txt",
            "content": base64.b64encode(b"test content").decode('utf-8'),
            "metadata": {"key": "value"}
        }

        response = self.client.post(self.url, json=payload)

        assert response.status_code == 500
        response_json = response.get_json()
        assert response_json is not None, "Expected JSON response, got None"

        assert "error" in response_json
        assert response_json["error"] == "Internal Error"

        self.mock_profile_repo.get_company_by_short_name.assert_called_once_with("test_company")
        self.mock_kb_service.ingest_document_sync.assert_called_once()

    def test_post_when_successful_file_storage(self):
        # Mock the profile repo to return a company
        mock_company = MagicMock()
        self.mock_profile_repo.get_company_by_short_name.return_value = mock_company

        # Mock the document returned by the service
        mock_document = MagicMock(spec=Document)
        mock_document.id = 123
        self.mock_kb_service.ingest_document_sync.return_value = mock_document

        payload = {
            "company": "test_company",
            "filename": "test_file.txt",
            "content": base64.b64encode(b"test content").decode('utf-8'),
            "metadata": {"key": "value"}
        }

        response = self.client.post(self.url, json=payload)

        assert response.status_code == 200
        assert response.get_json() == {
            "document_id": 123,
            "status": "active"
        }

        self.mock_profile_repo.get_company_by_short_name.assert_called_once_with("test_company")
        self.mock_kb_service.ingest_document_sync.assert_called_once_with(
            filename="test_file.txt",
            content=b"test content",
            company=mock_company,
            metadata={"key": "value"}
        )
