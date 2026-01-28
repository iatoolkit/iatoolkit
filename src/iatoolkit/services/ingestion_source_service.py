# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject, singleton
from iatoolkit.repositories.models import Company, IngestionSource, IngestionStatus
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.common.exceptions import IAToolkitException


@singleton
class IngestionSourceService:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 document_repo: DocumentRepo):
        self.config_service = config_service
        self.document_repo = document_repo

    def list_sources(self, company: Company) -> list[IngestionSource]:
        return self.document_repo.list_ingestion_sources(company.id)

    def get_source(self, company: Company, source_id: int) -> IngestionSource:
        source = self.document_repo.get_ingestion_source_by_id(company.id, source_id)
        if not source:
            raise IAToolkitException(IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND, "Ingestion Source not found")
        return source

    def create_source(self, company: Company, data: dict) -> IngestionSource:
        required_fields = ["name", "connector_name", "configuration", "collection_name"]
        for field in required_fields:
            if field not in data:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MISSING_PARAMETER,
                    f"Missing required field: {field}"
                )

        collection_type = self.document_repo.get_collection_type_by_name(company.id, data["collection_name"])
        if not collection_type:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Invalid collection name: {data['collection_name']}"
            )

        connector_name = data.get("connector_name") or "iatoolkit_storage"

        configuration = data.get("configuration", {})
        if not isinstance(configuration, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "configuration must be an object"
            )

        if not configuration.get("root") or not isinstance(configuration.get("root"), str):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "configuration.root is required and must be a string"
            )

        connector_config = dict(configuration)
        connector_config["collection"] = data["collection_name"]

        new_source = IngestionSource(
            company_id=company.id,
            name=data["name"],
            connector_name=connector_name,
            collection_type_id=collection_type.id,
            configuration=connector_config,
            schedule_cron=data.get("schedule_cron"),
            status=IngestionStatus.ACTIVE
        )

        return self.document_repo.create_or_update_ingestion_source(new_source)

    def update_source(self, company: Company, source_id: int, data: dict) -> IngestionSource:
        source = self.get_source(company, source_id)

        is_status_update_only = len(data) == 1 and "status" in data

        if source.status == IngestionStatus.RUNNING and not is_status_update_only:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_STATE, "Cannot edit configuration of a RUNNING source")

        if "name" in data:
            source.name = data["name"]

        if "schedule_cron" in data:
            source.schedule_cron = data["schedule_cron"]

        if "status" in data:
            try:
                new_status = IngestionStatus(data["status"])
                source.status = new_status

                # if we reset to ACTIVE manually, clear the previous error
                if new_status == IngestionStatus.ACTIVE:
                    source.last_error = None

            except ValueError:
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, "Invalid status")

        if "collection_name" in data:
            collection_type = self.document_repo.get_collection_type_by_name(company.id, data["collection_name"])
            if not collection_type:
                raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, "Invalid collection name")
            source.collection_type_id = collection_type.id

            # mantener configuration.collection alineado si existe configuration
            if isinstance(source.configuration, dict):
                source.configuration["collection"] = data["collection_name"]

        if "configuration" in data:
            if not isinstance(data["configuration"], dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "configuration must be an object"
                )

            new_configuration = data["configuration"]

            # Aseguramos que el collection_name persista en la configuración
            target_collection_name = data.get("collection_name")
            if not target_collection_name and source.collection_type:
                target_collection_name = source.collection_type.name

            if target_collection_name:
                new_configuration["collection"] = target_collection_name

            source.configuration = new_configuration

        if "connector_name" in data:
            source.connector_name = data["connector_name"]

        return self.document_repo.create_or_update_ingestion_source(source)

    def delete_source(self, company: Company, source_id: int) -> None:
        source = self.get_source(company, source_id)

        if source.status == IngestionStatus.RUNNING:
            raise IAToolkitException(IAToolkitException.ErrorType.INVALID_STATE, "Cannot delete a RUNNING source")

        self.document_repo.delete_ingestion_source(source)