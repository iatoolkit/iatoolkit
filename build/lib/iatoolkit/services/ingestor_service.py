# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from iatoolkit.repositories.models import Company, IngestionSource, IngestionStatus, IngestionSourceType
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.services.file_processor_service import FileProcessorConfig, FileProcessor
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.common.exceptions import IAToolkitException
import logging
from datetime import datetime
from injector import inject, singleton
import os


@singleton
class IngestorService:
    """
    Service responsible for managing Ingestion Sources (CRUD) and executing
    document ingestion processes (Pipeline orchestration).
    """
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 file_connector_factory: FileConnectorFactory,
                 knowledge_base_service: KnowledgeBaseService,
                 document_repo: DocumentRepo
                 ):
        self.config_service = config_service
        self.file_connector_factory = file_connector_factory
        self.knowledge_base_service = knowledge_base_service
        self.document_repo = document_repo

        logging.getLogger().setLevel(logging.ERROR)

    # --- Public API Methods (CRUD & Management) ---

    def create_source(self, company: Company, data: dict) -> IngestionSource:
        """
        Validates input data and creates a new IngestionSource in the database.
        """
        required_fields = ['name', 'source_type', 'configuration', 'collection_name']
        for field in required_fields:
            if field not in data:
                raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER,
                                         f"Missing required field: {field}")

        try:
            # Validate Source Type enum
            source_type_enum = IngestionSourceType(data['source_type'])
        except ValueError:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                     f"Invalid source type: {data.get('source_type')}")

        collection_id = self.document_repo.get_collection_id_by_name(company.short_name, data['collection_name'])
        if not collection_id:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                     f"Invalid collection name: {data['collection_name']}")

        # 1. Get Storage Configuration from Company Config
        storage_config = self.config_service.get_configuration(company.short_name, "storage_provider")

        if not storage_config:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"Missing storage configuration for company '{company.short_name}'.")

        provider = storage_config.get("provider", "s3")
        connector_config = {}

        # 2. Validate Type & Build Connector Config
        if source_type_enum == IngestionSourceType.S3:
            if provider != "s3":
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                         f"Company storage provider is '{provider}', cannot create source of type 's3'.")

            s3_conf = storage_config.get("s3", {})
            user_logical_bucket = data['configuration'].get('bucket', '')

            # Resolve Env Var NAMES to VALUES (matching StorageService logic)
            access_key = os.getenv(s3_conf.get("access_key_env", "AWS_ACCESS_KEY_ID"))
            secret_key = os.getenv(s3_conf.get("secret_key_env", "AWS_SECRET_ACCESS_KEY"))
            region = os.getenv(s3_conf.get("region_env", "AWS_REGION"), "us-east-1")

            connector_config = {
                "type": "s3",
                "bucket": storage_config.get("bucket"),  # Physical Bucket
                "prefix": user_logical_bucket,           # User's bucket becomes the prefix
                "folder": data['configuration'].get('prefix', ''),
                "auth": {
                    'aws_access_key_id': access_key,
                    'aws_secret_access_key': secret_key,
                    'region_name': region
                }
            }

        elif source_type_enum == IngestionSourceType.GCS:
            if provider != "google_cloud_storage":
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER,
                                         f"Company storage provider is '{provider}', cannot create source of type 'google_cloud_storage'.")

            gcs_conf = storage_config.get("google_cloud_storage", {})
            connector_config = {
                "type": "gcs",
                "bucket": storage_config.get("bucket"),
                "service_account_path": gcs_conf.get("service_account_path", "service_account.json")
            }

        # Merge any other metadata from user configuration if needed
        if 'metadata' in data['configuration']:
            connector_config['metadata'] = data['configuration']['metadata']

        # Ensure collection info is preserved in config for processing context
        connector_config['collection'] = data['collection_name']

        new_source = IngestionSource(
            company_id=company.id,
            name=data['name'],
            source_type=source_type_enum,
            collection_type_id=collection_id,
            configuration=connector_config, # Save the constructed full config
            schedule_cron=data.get('schedule_cron'),
            status=IngestionStatus.ACTIVE
        )

        return self.document_repo.create_or_update_ingestion_source(new_source)

    def run_ingestion(self, company: Company, source_id: int) -> int:
        """
        Validates source state and triggers the ingestion process.
        """
        # We assume validation of ownership happens here via query
        source = self.document_repo.session.query(IngestionSource).filter_by(
            id=source_id,
            company_id=company.id
        ).first()

        if not source:
            raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND, "Ingestion Source not found")

        if source.status == IngestionStatus.RUNNING:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_STATE, "Ingestion already running")

        # Trigger internal logic
        return self._trigger_ingestion_logic(source)

    # --- CLI Legacy Support ---

    def load_sources(self,
                     company: Company,
                     sources_to_load: list[str] = None,
                     filters: dict = None) -> int:
        """
        Legacy Entrypoint for CLI.
        1. Syncs sources from YAML to DB.
        2. Triggers ingestion for the requested sources (by name).
        """
        if not sources_to_load:
            raise IAToolkitException(IAToolkitException.ErrorType.PARAM_NOT_FILLED,
                                     f"Missing sources to load for company '{company.short_name}'.")

        # 1. Sync DB with YAML configuration
        self.sync_sources_from_yaml(company)

        # 2. Retrieve sources from DB using Repo
        sources = self.document_repo.get_active_ingestion_sources(company.id, sources_to_load)

        if not sources:
            logging.warning(f"No active ingestion sources found matching: {sources_to_load}")
            return 0

        total_processed = 0
        for source in sources:
            try:
                total_processed += self._trigger_ingestion_logic(source, filters)
            except Exception as e:
                logging.error(f"Error executing source {source.name}: {e}")

        return total_processed

    # --- Internal Logic ---

    def sync_sources_from_yaml(self, company: Company):
        """
        Reads the company.yaml 'document_sources' and creates/updates IngestionSource records.
        """
        kb_config = self.config_service.get_configuration(company.short_name, 'knowledge_base')
        if not kb_config:
            return

        yaml_sources = kb_config.get('document_sources', {})
        base_connector = self._get_base_connector_config(kb_config)

        for name, config in yaml_sources.items():
            source_type = IngestionSourceType.LOCAL if base_connector.get('type') == 'local' else IngestionSourceType.S3

            full_config = base_connector.copy()
            full_config.update({
                'path': config.get('path'),
                'folder': config.get('folder'),
                'metadata': config.get('metadata', {}),
                'collection': config.get('collection')
            })

            source_record = self.document_repo.get_ingestion_source_by_name(company.id, name)

            if not source_record:
                source_record = IngestionSource(
                    company_id=company.id,
                    name=name,
                    source_type=source_type,
                    status=IngestionStatus.ACTIVE
                )

            source_record.configuration = full_config
            self.document_repo.create_or_update_ingestion_source(source_record)

    def _trigger_ingestion_logic(self, source: IngestionSource, filters: dict = {}) -> int:
        """
        Internal worker: Executes the ingestion for a specific DB Source.
        """
        # 1. Update Status
        source.status = IngestionStatus.RUNNING
        source.last_error = None
        self.document_repo.create_or_update_ingestion_source(source)

        processed_count = 0
        try:
            logging.info(f"🚀 Starting ingestion for source '{source.name}'")

            # 2. Prepare Context
            connector_config = source.configuration
            metadata = connector_config.get('metadata', {})
            collection_name = source.collection_type.name if source.collection_type else connector_config.get('collection')

            context = {
                'company': source.company,
                'collection': collection_name,
                'metadata': metadata
            }

            processor_config = FileProcessorConfig(
                callback=self._file_processing_callback,
                context=context,
                filters=filters,
                continue_on_error=True,
                echo=False
            )

            # 3. Factory & Process
            connector = self.file_connector_factory.create(connector_config)
            processor = FileProcessor(connector, processor_config)
            processor.process_files()

            processed_count = processor.processed_files

            # 4. Success Update
            source.last_run_at = datetime.now()
            source.status = IngestionStatus.ACTIVE
            logging.info(f"✅ Finished source '{source.name}'. Processed: {processed_count}")

        except Exception as e:
            logging.exception(f"❌ Ingestion failed for source {source.name}")
            source.status = IngestionStatus.ERROR
            source.last_error = str(e)
            raise e
        finally:
            self.document_repo.create_or_update_ingestion_source(source)

        return processed_count

    def _get_base_connector_config(self, knowledge_base_config: dict) -> dict:
        connectors = knowledge_base_config.get('connectors', {})
        env = os.getenv('FLASK_ENV', 'dev')
        if env == 'dev':
            return connectors.get('development', {'type': 'local'})
        else:
            return connectors.get('production', {})

    def _file_processing_callback(self, company: Company, filename: str, content: bytes, context: dict = None):
        if not company:
            raise IAToolkitException(IAToolkitException.ErrorType.MISSING_PARAMETER, "Missing company object in callback.")

        try:
            predefined_metadata = context.get('metadata', {}) if context else {}
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