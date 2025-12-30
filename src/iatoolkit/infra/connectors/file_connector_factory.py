# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.connectors.file_connector import FileConnector
from iatoolkit.infra.connectors.local_file_connector import LocalFileConnector
from iatoolkit.infra.connectors.s3_connector import S3Connector
from iatoolkit.infra.connectors.google_drive_connector import GoogleDriveConnector
from iatoolkit.infra.connectors.google_cloud_storage_connector import GoogleCloudStorageConnector
from typing import Dict
import os


class FileConnectorFactory:
    @staticmethod
    def create(config: Dict) -> FileConnector:
        """
        Configuración esperada:
        {
            "type": "local" | "s3" | "gdrive" | "gcs",
            "path": "/ruta/local",  # solo para local
            "bucket": "mi-bucket", "prefix": "datos/", "auth": {...},  # solo para S3
            "folder_id": "xxxxxxx",  # solo para Google Drive
            "bucket": "mi-bucket", "service_account": "/ruta/service_account.json"  # solo para GCS
        }
        """
        connector_type = config.get('type')

        if connector_type == 'local':
            return LocalFileConnector(config['path'])

        elif connector_type == 's3':
            auth = {
                'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
                'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
                'region_name': os.getenv('AWS_REGION', 'us-east-1')
            }

            return S3Connector(
                bucket=config['bucket'],
                prefix=config.get('prefix', ''),
                folder=config.get('folder', ''),
                auth=auth
            )

        elif connector_type == 'gdrive':
            return GoogleDriveConnector(config['folder_id'],
                    'service_account.json')

        elif connector_type == 'gcs':
            return GoogleCloudStorageConnector(
                bucket_name=config['bucket'],
                service_account_path=config.get('service_account', 'service_account.json')
            )

        else:
            raise ValueError(f"Unknown connector type: {connector_type}")
