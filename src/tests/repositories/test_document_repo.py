# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from iatoolkit.repositories.models import Document, Company, CollectionType
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.common.exceptions import IAToolkitException
import base64
from typing import List, Optional


class TestDocumentRepo:
    def setup_method(self):
        # Mock the DatabaseManager
        self.mock_db_manager = MagicMock()
        self.session = self.mock_db_manager.get_session()

        # Initialize DocumentRepo with the mocked DatabaseManager
        self.repo = DocumentRepo(self.mock_db_manager)
        self.mock_document = Document(company_id=1,
                                 filename='test.txt',
                                 storage_key='iatoolkit/document-key',
                                 meta={'repertorio_id': 10})
        self.mock_company = Company(name='company')


    def test_insert_when_ok(self):
        self.repo.insert(self.mock_document)

        # Assert
        self.session.add.assert_called()
        self.session.commit.assert_called()

    def test_get_missing_company(self):
        # Act & Assert
        with pytest.raises(IAToolkitException) as exc_info:
            self.repo.get(None, filename="test_file.txt")

        assert exc_info.value.error_type == IAToolkitException.ErrorType.PARAM_NOT_FILLED

    def test_get_document_by_filename(self):
        self.session.query.return_value.filter_by.return_value.first.return_value = self.mock_document

        # Act
        result = self.repo.get(self.mock_company, filename="test_file.txt")

        # Assert
        assert result == self.mock_document
        self.session.query.assert_called()

    def test_get_by_id_when_id_is_none(self):
        result = self.repo.get_by_id(0)

        assert result is None
        self.session.query.assert_not_called()

    def test_get_by_id_when_document_not_found(self):
        self.session.query.return_value.filter_by.return_value.first.return_value = None

        result = self.repo.get_by_id(999)

        assert result is None
        self.session.query.assert_called()

    def test_get_by_id_when_document_exists(self):
        self.session.query.return_value.filter_by.return_value.first.return_value = self.mock_document

        result = self.repo.get_by_id(1)

        assert result == self.mock_document
        self.session.query.assert_called()

    def test_get_by_hash_scopes_by_collection(self):
        self.session.query.return_value.filter_by.return_value.first.return_value = self.mock_document

        result = self.repo.get_by_hash(1, "abc123", 7)

        assert result == self.mock_document
        self.session.query.return_value.filter_by.assert_called_once_with(
            company_id=1,
            hash="abc123",
            collection_type_id=7,
        )

    def test_get_by_hash_scopes_null_collection(self):
        self.session.query.return_value.filter_by.return_value.first.return_value = self.mock_document

        result = self.repo.get_by_hash(1, "abc123", None)

        assert result == self.mock_document
        self.session.query.return_value.filter_by.assert_called_once_with(
            company_id=1,
            hash="abc123",
            collection_type_id=None,
        )

    def test_get_collection_ids_by_name_normalizes_and_deduplicates(self):
        legal = CollectionType(id=10, name="legal")
        contracts = CollectionType(id=20, name="contracts")
        self.session.query.return_value.join.return_value.filter.return_value.all.return_value = [
            contracts,
            legal,
        ]

        result = self.repo.get_collection_ids_by_name(
            "acme",
            [" Legal ", "contracts", "LEGAL", "", "contracts"],
        )

        assert result == [10, 20]

    def test_get_collection_ids_by_name_returns_empty_for_empty_input(self):
        result = self.repo.get_collection_ids_by_name("acme", [])

        assert result == []
        self.session.query.assert_not_called()
