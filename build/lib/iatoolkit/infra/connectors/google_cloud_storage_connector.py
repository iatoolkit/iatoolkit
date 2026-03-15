# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.connectors.file_connector import FileConnector
from google.cloud import storage
from typing import List


class GoogleCloudStorageConnector(FileConnector):
    def __init__(self, bucket_name: str, service_account_path: str = "service_account.json"):
        """
        Inicializa el conector de Google Cloud Storage utilizando la API oficial de Google.
        :param bucket_name: Nombre del bucket en Google Cloud Storage.
        :param service_account_path: Ruta al archivo JSON de la cuenta de servicio.
        """
        self.bucket_name = bucket_name
        self.service_account_path = service_account_path
        self.storage_client = self._authenticate()
        self.bucket = self.storage_client.bucket(bucket_name)

    def _authenticate(self):
        """
        Autentica en Google Cloud Storage utilizando una cuenta de servicio.
        """
        # Crear cliente de GCS con las credenciales
        client = storage.Client.from_service_account_json(self.service_account_path)
        return client

    def list_files(self) -> List[dict]:
        """
        Lista todos los archivos en el bucket de GCS como diccionarios con claves 'path', 'name' y 'metadata'.
        """
        blobs = self.bucket.list_blobs()

        return [
            {
                "path": blob.name,  # Nombre o "ruta" del blob en el bucket
                "name": blob.name.split("/")[-1],  # Nombre del archivo (última parte del path)
                "metadata": {"size": blob.size}  # Incluye tamaño como metadata (u otros metadatos relevantes)
            }
            for blob in blobs
        ]

    def get_file_content(self, file_path: str) -> bytes:
        """
        Descarga el contenido de un archivo en GCS dado su path (nombre del blob).
        """
        blob = self.bucket.blob(file_path)
        file_buffer = blob.download_as_bytes()  # Descarga el contenido como bytes

        return file_buffer

    def delete_file(self, file_path: str) -> None:
        """
        Elimina un archivo del bucket dado su path.
        """
        blob = self.bucket.blob(file_path)
        blob.delete()

    def upload_file(self, file_path: str, content: bytes, content_type: str = None) -> None:
        """
        Sube un archivo al bucket.
        """
        blob = self.bucket.blob(file_path)
        blob.upload_from_string(content, content_type=content_type)

    def generate_presigned_url(self, file_path: str, expiration: int = 3600) -> str:
        raise NotImplementedError("not implemented yet")
