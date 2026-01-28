# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from datetime import datetime
from injector import inject, singleton

from iatoolkit.repositories.models import Company, IngestionSource, IngestionStatus, IngestionRun
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.file_processor_service import FileProcessorConfig, FileProcessor
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.common.exceptions import IAToolkitException
import os


@singleton
class IngestionRunnerService:
    @inject
    def __init__(self,
                 file_connector_factory: FileConnectorFactory,
                 knowledge_base_service: KnowledgeBaseService,
                 document_repo: DocumentRepo,
                 config_service: ConfigurationService):
        self.file_connector_factory = file_connector_factory
        self.knowledge_base_service = knowledge_base_service
        self.document_repo = document_repo
        self.config_service = config_service


    def run_ingestion(self, company: Company, source_id: int, user_identifier: str | None = None, filters: dict | None = None) -> int:
        filters = filters or {}

        source = self.document_repo.get_ingestion_source_by_id(company.id, source_id)
        if not source:
            raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND, "Ingestion Source not found")

        if source.status == IngestionStatus.RUNNING:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_STATE, "Ingestion already running")

        run = IngestionRun(
            company_id=company.id,
            source_id=source.id,
            triggered_by=user_identifier,
            started_at=datetime.now(),
            status=IngestionStatus.RUNNING
        )
        self.document_repo.create_ingestion_run(run)

        processed_count = 0
        try:
            processed_count = self._trigger_ingestion_logic(source, filters=filters)
            run.status = IngestionStatus.ACTIVE
            run.processed_files = processed_count
            run.finished_at = datetime.now()
            self.document_repo.update_ingestion_run(run)
            return processed_count

        except Exception as e:
            run.status = IngestionStatus.ERROR
            run.error_message = str(e)
            run.finished_at = datetime.now()
            self.document_repo.update_ingestion_run(run)
            raise

    def _trigger_ingestion_logic(self, source: IngestionSource, filters: dict | None = None) -> int:
        filters = filters or {}

        source.status = IngestionStatus.RUNNING
        source.last_error = None
        self.document_repo.create_or_update_ingestion_source(source)

        failed = False
        try:
            logging.info(f"Starting ingestion for source '{source.name}'")

            if not source.connector_name:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    "Ingestion source is missing connector_name"
                )

            ingestion_cfg = source.configuration or {}

            # Canonical location field
            root = ingestion_cfg.get("root")
            if not root or not isinstance(root, str):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    "Ingestion source is missing configuration.root"
                )

            connectors = self.config_service.get_configuration(source.company.short_name, "connectors") or {}
            base_cfg = connectors.get(source.connector_name)
            if not base_cfg or not isinstance(base_cfg, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    f"Connector alias not found: {source.connector_name}"
                )

            connector_type = base_cfg.get("type")
            if not connector_type or not isinstance(connector_type, str):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    f"Connector '{source.connector_name}' is missing 'type'"
                )

            connector_config = dict(base_cfg)

            # Map canonical "root" into connector-specific params
            if connector_type in ["s3", "gcs", "google_cloud_storage"]:
                # These connectors in this codebase use prefix/folder for scoping.
                # We use root as the full prefix and keep folder empty.
                connector_config["prefix"] = root
                connector_config["folder"] = ""

            elif connector_type == "gdrive":
                connector_config["folder_id"] = root

            elif connector_type == "local":
                connector_config["path"] = root

            else:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.CONFIG_ERROR,
                    f"Unsupported connector type for ingestion: {connector_type}"
                )

            # add filters if are defined in configuration
            filters.update(ingestion_cfg.get("filters") or {})

            context = {
                "company": source.company,
                "collection": source.collection_type.name if source.collection_type else None,
                "metadata": ingestion_cfg.get("metadata") or {}
            }

            processor_config = FileProcessorConfig(
                callback=self._file_processing_callback,
                context=context,
                filters=filters,
                continue_on_error=True,
                echo=False
            )

            connector = self.file_connector_factory.create(connector_config)
            processor = FileProcessor(connector, processor_config)
            processor.process_files()

            processed_count = processor.processed_files

            source.last_run_at = datetime.now()
            source.status = IngestionStatus.ACTIVE

        except BaseException as e:
            failed = True

            # in case the user wants to cancel the ingestion.
            if isinstance(e, KeyboardInterrupt):
                logging.warning(f"Ingestion INTERRUPTED (Ctrl+C) for source {source.name}")
                source.last_error = "Process interrupted by user (Ctrl+C)"
            else:
                logging.exception(f"Ingestion failed for source {source.name}")
                source.last_error = str(e)

            source.status = IngestionStatus.ERROR
            raise
        finally:
            # make sure we set the status to ERROR or ACTIVE depending on the outcome of the ingestion
            if source.status == IngestionStatus.RUNNING:
                if failed:
                    source.status = IngestionStatus.ERROR
                    if not source.last_error:
                        source.last_error = "Ingestion failed (unknown error)"
                else:
                    pass

            self.document_repo.create_or_update_ingestion_source(source)

        return processed_count

    def _file_processing_callback(self,
                                  company: Company,
                                  filename: str,
                                  content: bytes,
                                  metadata: dict = None,
                                  context: dict = None):
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER, "Missing company object in callback.")

        try:
            predefined_metadata = context.get('metadata', {}) if context else {}
            if metadata:
                predefined_metadata.update(metadata)

            new_document = self.knowledge_base_service.ingest_document_sync(
                company=company,
                filename=filename,
                content=content,
                collection=context.get('collection'),
                metadata=predefined_metadata
            )
            return new_document

        except Exception as e:
            logging.exception(f"Error processing file '{filename}': {e}")
            raise IAToolkitException(IAToolkitException.ErrorType.LOAD_DOCUMENT_ERROR,
                                     f"Error while processing file: {filename}")