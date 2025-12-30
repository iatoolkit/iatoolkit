# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock, patch, call
from iatoolkit.services.load_documents_service import LoadDocumentsService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.repositories.models import Company
from iatoolkit.common.exceptions import IAToolkitException

# Mock configuration to simulate the 'knowledge_base' section of company.yaml
MOCK_KNOWLEDGE_BASE_CONFIG = {
    'connectors': {
        'development': {'type': 'local'},
        'production': {'type': 's3', 'bucket': 'prod_bucket', 'prefix': 'prod_prefix'}
    },
    'document_sources': {
        'contracts': {'path': 'data/contracts', 'metadata': {'category': 'legal'}},
        'manuals': {'path': 'data/manuals', 'metadata': {'category': 'guide'}}
    }
}


class TestLoadDocumentsService:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks for all dependencies and instantiate the service."""
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_file_connector_factory = MagicMock(spec=FileConnectorFactory)
        self.mock_kb_service = MagicMock(spec=KnowledgeBaseService)

        self.service = LoadDocumentsService(
            config_service=self.mock_config_service,
            file_connector_factory=self.mock_file_connector_factory,
            knowledge_base_service=self.mock_kb_service
        )
        self.company = Company(id=1, short_name='acme')

    def test_load_sources_raises_exception_if_knowledge_base_config_is_missing(self):
        self.mock_config_service.get_configuration.return_value = None
        with pytest.raises(IAToolkitException) as excinfo:
            self.service.load_sources(self.company, sources_to_load=['contracts'])
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR

    @patch('iatoolkit.services.load_documents_service.os.getenv', return_value='dev')
    @patch('iatoolkit.services.load_documents_service.FileProcessor')
    def test_load_sources_uses_dev_connector_in_development(self, MockFileProcessor, mock_getenv):
        self.mock_config_service.get_configuration.return_value = MOCK_KNOWLEDGE_BASE_CONFIG
        self.service.load_sources(self.company, sources_to_load=['contracts'])
        self.mock_file_connector_factory.create.assert_called_once_with({
            'type': 'local',
            'path': 'data/contracts'
        })
        MockFileProcessor.assert_called_once()

    @patch('iatoolkit.services.load_documents_service.os.getenv', return_value='production')
    @patch('iatoolkit.services.load_documents_service.FileProcessor')
    def test_load_sources_uses_prod_connector_in_production(self, MockFileProcessor, mock_getenv):
        self.mock_config_service.get_configuration.return_value = MOCK_KNOWLEDGE_BASE_CONFIG
        self.service.load_sources(self.company, sources_to_load=['manuals'])
        self.mock_file_connector_factory.create.assert_called_once_with({
            'type': 's3',
            'bucket': 'prod_bucket',
            'prefix': 'prod_prefix',
            'path': 'data/manuals'
        })

    def test_load_sources_raises_exception_if_no_sources_provided(self):
        """
        GIVEN sources_to_load is None or empty
        WHEN load_company_sources is called
        THEN it should raise a parameter error.
        """
        self.mock_config_service.get_configuration.return_value = MOCK_KNOWLEDGE_BASE_CONFIG
        with pytest.raises(IAToolkitException) as excinfo:
            self.service.load_sources(self.company)
        assert excinfo.value.error_type == IAToolkitException.ErrorType.PARAM_NOT_FILLED

    def test_callback_delegates_to_knowledge_base_service(self):
        """
        GIVEN a file callback trigger
        WHEN _file_processing_callback is called
        THEN it should delegate ingestion to KnowledgeBaseService.
        """
        # Arrange
        filename = 'doc.pdf'
        content = b'pdf_content'
        context = {'metadata': {'type': 'manual'}}

        # Act
        self.service._file_processing_callback(self.company, filename, content, context)

        # Assert
        self.mock_kb_service.ingest_document_sync.assert_called_once_with(
            company=self.company,
            filename=filename,
            content=content,
            collection=None,
            metadata={'type': 'manual'}
        )

    def test_callback_handles_exception_from_knowledge_base(self):
        """
        GIVEN KnowledgeBaseService raises an exception
        WHEN _file_processing_callback is called
        THEN it should catch and re-raise as IAToolkitException.
        """
        # Arrange
        self.mock_kb_service.ingest_document_sync.side_effect = Exception("Ingestion failed")

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.service._file_processing_callback(self.company, 'fail.pdf', b'content')

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR
        assert "Error while processing file" in str(excinfo.value)