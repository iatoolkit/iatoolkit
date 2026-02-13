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
from flask import current_app, has_app_context
from itsdangerous import URLSafeSerializer, BadSignature

from iatoolkit.infra.connectors.file_connector import FileConnector
from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.configuration_service import ConfigurationService

DOWNLOAD_TOKEN_SALT = "iatoolkit-download-token-v1"


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
        Retrieves a connector using the fixed 'iatoolkit_storage' alias.
        """
        connectors = self.config_service.get_configuration(company_short_name, "connectors") or {}
        storage_alias = "iatoolkit_storage"

        connector_config = connectors.get(storage_alias)
        if not connector_config:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"Missing connector alias '{storage_alias}' in company configuration."
            )

        try:
            return FileConnectorFactory.create(connector_config)
        except Exception as e:
            error_msg = f"Failed to initialize storage connector '{storage_alias}' for '{company_short_name}': {str(e)}"
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

    def generate_presigned_url(self, company_short_name: str, storage_key: str) -> str:
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

    def upload_generated_download(self,
                                  company_short_name: str,
                                  file_content: bytes,
                                  filename: str,
                                  mime_type: str) -> str:
        """
        Uploads a generated file intended for user download.
        Uses a dedicated prefix to make cleanup/retention easier.
        """
        try:
            unique_id = uuid.uuid4()
            storage_key = f"companies/{company_short_name}/generated_downloads/{unique_id}/{filename}"

            connector = self._get_connector(company_short_name)
            connector.upload_file(
                file_path=storage_key,
                content=file_content,
                content_type=mime_type
            )
            return storage_key

        except Exception as e:
            error_msg = f"Error uploading generated download: {str(e)}"
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

    def create_download_token(self,
                              company_short_name: str,
                              storage_key: str,
                              filename: str | None = None) -> str:
        """
        Creates a signed token that can be used to download or re-read a file from storage.
        """
        if not company_short_name or not storage_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, "Invalid download token payload.")

        payload = {
            "v": 1,
            "company": company_short_name,
            "storage_key": storage_key,
        }
        if filename:
            payload["filename"] = filename

        serializer = self._get_download_serializer()
        return serializer.dumps(payload)

    def resolve_download_token(self, token: str) -> Dict[str, str]:
        """
        Resolves and validates a signed download token.
        """
        if not token:
            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, "Invalid download token.")

        serializer = self._get_download_serializer()
        try:
            payload = serializer.loads(token)
        except BadSignature as e:
            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, "Invalid download token.") from e

        company_short_name = payload.get("company")
        storage_key = payload.get("storage_key")
        if not company_short_name or not storage_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, "Invalid download token payload.")
        return payload

    def _get_download_serializer(self) -> URLSafeSerializer:
        """
        Returns the serializer used for signed download tokens.
        """
        secret_key = os.getenv("IATOOLKIT_SECRET_KEY")
        if not secret_key:
            raise IAToolkitException(IAToolkitException.ErrorType.CONFIG_ERROR, "SECRET_KEY is not configured.")

        return URLSafeSerializer(secret_key=secret_key, salt=DOWNLOAD_TOKEN_SALT)
