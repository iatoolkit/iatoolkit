# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import uuid
import logging
import mimetypes
import os
from injector import inject
from typing import Dict

from iatoolkit.infra.connectors.file_connector import FileConnector
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService


class StorageService:
    """
    High level service for managing assets storage.
    Delegates the creation of connectors to FileConnectorFactory based on company configuration.
    """

    @inject
    def __init__(self, config_service: ConfigurationService):
        self.config_service = config_service
        # Cache connectors to avoid re-authenticating on every request
        self._connectors: Dict[str, FileConnector] = {}

    def _get_connector(self, company_short_name: str) -> FileConnector:
        """
        Retrieves cached connector or creates a new one using the Factory.
        """
        if company_short_name in self._connectors:
            return self._connectors[company_short_name]

        # 1. Get raw config from YAML
        storage_config = self.config_service.get_configuration(company_short_name, "storage_provider")

        # 2. Build the "Factory Config" dictionary
        factory_config = {}

        if not storage_config:
            # Fallback Legacy: S3 with default env vars
            logging.warning(f"No storage config for '{company_short_name}'. Using default S3.")
            factory_config = {
                "type": "s3",
                "bucket": os.getenv("S3_BUCKET_NAME", "iatoolkit-assets")
                # Factory will pick up default AWS_ env vars since 'auth' is missing
            }
        else:
            provider = storage_config.get("provider", "s3")
            bucket = storage_config.get("bucket")

            if provider == "s3":
                s3_conf = storage_config.get("s3", {})

                # Resolve Env Var NAMES to VALUES
                access_key = os.getenv(s3_conf.get("access_key_env", "AWS_ACCESS_KEY_ID"))
                secret_key = os.getenv(s3_conf.get("secret_key_env", "AWS_SECRET_ACCESS_KEY"))
                region = os.getenv(s3_conf.get("region_env", "AWS_REGION"), "us-east-1")

                factory_config = {
                    "type": "s3",
                    "bucket": bucket,
                    "prefix": s3_conf.get("prefix", ""),
                    "auth": {
                        'aws_access_key_id': access_key,
                        'aws_secret_access_key': secret_key,
                        'region_name': region
                    }
                }

            elif provider == "google_cloud_storage":
                gcs_conf = storage_config.get("google_cloud_storage", {})
                service_account = gcs_conf.get("service_account_path", "service_account.json")

                factory_config = {
                    "type": "gcs",
                    "bucket": bucket,
                    "service_account_path": service_account
                }

        try:
            # 3. Delegate instantiation to Factory
            connector = FileConnectorFactory.create(factory_config)

            # Cache and return
            self._connectors[company_short_name] = connector
            return connector

        except Exception as e:
            error_msg = f"Failed to initialize storage factory for '{company_short_name}': {str(e)}"
            logging.error(error_msg)
            raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR, error_msg)

    def store_generated_image(self,
                              company_short_name: str,
                              base64_data: str,
                              mime_type: str) -> Dict[str, str]:
        """
        Saves an LLM generated image (Base64) to storage.
        """
        try:
            # 1. Clean and Decode Base64
            if "base64," in base64_data:
                base64_data = base64_data.split("base64,")[1]
            image_bytes = base64.b64decode(base64_data)

            # 2. Generate path
            ext = mimetypes.guess_extension(mime_type) or ".png"
            filename = f"{uuid.uuid4()}{ext}"
            storage_key = f"companies/{company_short_name}/generated_images/{filename}"

            # 3. Use abstract connector
            connector = self._get_connector(company_short_name)
            connector.upload_file(
                file_path=storage_key,
                content=image_bytes,
                content_type=mime_type
            )

            logging.info(f"Generated image saved at: {storage_key}")

            return {
                "storage_key": storage_key,
                "url": connector.generate_presigned_url(storage_key)
            }

        except Exception as e:
            error_msg = f"Error saving image to Storage: {str(e)}"
            logging.error(error_msg)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR, error_msg)

    def get_public_url(self, company_short_name: str, storage_key: str) -> str:
        """Gets a fresh signed URL using the configured connector."""
        connector = self._get_connector(company_short_name)
        return connector.generate_presigned_url(storage_key)

    def upload_document(self,
                        company_short_name: str,
                        file_content: bytes,
                        filename: str,
                        mime_type: str) -> str:
        """
        Uploads a generic document via the configured connector.
        """
        try:
            unique_id = uuid.uuid4()
            storage_key = f"companies/{company_short_name}/documents/{unique_id}/{filename}"

            connector = self._get_connector(company_short_name)
            connector.upload_file(
                file_path=storage_key,
                content=file_content,
                content_type=mime_type
            )
            return storage_key

        except Exception as e:
            error_msg = f"Error uploading document: {str(e)}"
            logging.error(error_msg)
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR, error_msg)

    def get_document_content(self, company_short_name: str, storage_key: str) -> bytes:
        """Retrieves raw content via the configured connector."""
        try:
            connector = self._get_connector(company_short_name)
            return connector.get_file_content(storage_key)
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR, str(e))


    def delete_file(self, company_short_name: str, storage_key: str) -> None:
        """
        Deletes a document from the configured storage.
        """
        try:
            connector = self._get_connector(company_short_name)
            connector.delete_file(storage_key)
        except Exception as e:
            raise IAToolkitException(IAToolkitException.ErrorType.FILE_IO_ERROR, f"Error deleting file: {str(e)}")