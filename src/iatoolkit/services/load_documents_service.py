# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from iatoolkit.repositories.models import Company
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.services.file_processor_service import FileProcessorConfig, FileProcessor
from iatoolkit.common.exceptions import IAToolkitException
import logging
from injector import inject, singleton
import os


@singleton
class LoadDocumentsService:
    """
    Orchestrates the discovery and loading of documents from configured sources.
    Delegates the processing and ingestion logic to KnowledgeBaseService.
    """
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 file_connector_factory: FileConnectorFactory,
                 knowledge_base_service: KnowledgeBaseService
                 ):
        self.config_service = config_service
        self.file_connector_factory = file_connector_factory
        self.knowledge_base_service = knowledge_base_service

        logging.getLogger().setLevel(logging.ERROR)

    def load_sources(self,
                     company: Company,
                     sources_to_load: list[str] = None,
                     filters: dict = None) -> int:
        """
        Loads documents from one or more configured sources for a company.

        Args:
            company (Company): The company to load files for.
            sources_to_load (list[str], optional): A list of specific source names to load.
                                                  If None, all configured sources will be loaded.
            filters (dict, optional): Filters to apply when listing files (e.g., file extension).

        Returns:
            int: The total number of processed files.
        """
        knowledge_base_config = self.config_service.get_configuration(company.short_name, 'knowledge_base')
        if not knowledge_base_config:
            raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR,
                                     f"Missing 'knowledge_base' configuration for company '{company.short_name}'.")

        if not sources_to_load:
            raise IAToolkitException(IAToolkitException.ErrorType.PARAM_NOT_FILLED,
                                     f"Missing sources to load for company '{company.short_name}'.")

        base_connector_config = self._get_base_connector_config(knowledge_base_config)
        all_sources = knowledge_base_config.get('document_sources', {})

        total_processed_files = 0
        for source_name in sources_to_load:
            source_config = all_sources.get(source_name)
            if not source_config:
                logging.warning(f"Source '{source_name}' not found in configuration for company '{company.short_name}'. Skipping.")
                continue

            try:
                logging.info(f"Processing source '{source_name}' for company '{company.short_name}'...")

                # Combine the base connector configuration with the specific path from the source.
                full_connector_config = base_connector_config.copy()
                full_connector_config['path'] = source_config.get('path')

                # Prepare the context for the callback function.
                context = {
                    'company': company,
                    'metadata': source_config.get('metadata', {})
                }

                processor_config = FileProcessorConfig(
                    callback=self._file_processing_callback,
                    context=context,
                    filters=filters or {"filename_contains": ".pdf"},
                    continue_on_error=True,
                    echo=True
                )

                connector = self.file_connector_factory.create(full_connector_config)
                processor = FileProcessor(connector, processor_config)
                processor.process_files()

                total_processed_files += processor.processed_files
                logging.info(f"Finished processing source '{source_name}'. Processed {processor.processed_files} files.")

            except Exception as e:
                logging.exception(f"Failed to process source '{source_name}' for company '{company.short_name}': {e}")

        return total_processed_files

    def _get_base_connector_config(self, knowledge_base_config: dict) -> dict:
        """Determines and returns the appropriate base connector configuration (dev vs prod)."""
        connectors = knowledge_base_config.get('connectors', {})
        env = os.getenv('FLASK_ENV', 'dev')

        if env == 'dev':
            return connectors.get('development', {'type': 'local'})
        else:
            prod_config = connectors.get('production')
            if not prod_config:
                raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR,
                                         "Production connector configuration is missing.")
            # The S3 connector itself is responsible for reading AWS environment variables.
            # No need to pass credentials explicitly here.
            return prod_config

    def _file_processing_callback(self, company: Company, filename: str, content: bytes, context: dict = None):
        """
        Callback method to process a single file.
        Delegates the actual ingestion (storage, vectorization) to KnowledgeBaseService.
        """
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER, "Missing company object in callback.")

        try:
            # Get predefined metadata from the context passed by the processor.
            predefined_metadata = context.get('metadata', {}) if context else {}

            # Delegate heavy lifting to KnowledgeBaseService
            new_document = self.knowledge_base_service.ingest_document_sync(
                company=company,
                filename=filename,
                content=content,
                metadata=predefined_metadata
            )

            return new_document

        except Exception as e:
            # We log here but re-raise to let FileProcessor handle the error counting/continue logic
            logging.exception(f"Error processing file '{filename}': {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR,
                                     f"Error while processing file: {filename}")