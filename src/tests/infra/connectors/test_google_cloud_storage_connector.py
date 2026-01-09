# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import MagicMock, patch
from iatoolkit.infra.connectors.google_cloud_storage_connector import GoogleCloudStorageConnector

class TestGoogleCloudStorageConnector(unittest.TestCase):

    def setUp(self):
        # 1. Patch de la clase Client de la librería google.cloud.storage
        self.mock_storage_patch = patch('iatoolkit.infra.connectors.google_cloud_storage_connector.storage.Client')
        self.mock_storage_client_class = self.mock_storage_patch.start()

        # 2. Mock de la instancia del cliente
        self.mock_client_instance = MagicMock()
        self.mock_storage_client_class.from_service_account_json.return_value = self.mock_client_instance

        # 3. Mock del bucket
        self.mock_bucket = MagicMock()
        self.mock_client_instance.bucket.return_value = self.mock_bucket

        # 4. Datos de prueba
        self.bucket_name = "test-bucket"
        self.service_account = "test.json"

        # 5. Inicializar conector
        self.connector = GoogleCloudStorageConnector(self.bucket_name, self.service_account)

    def tearDown(self):
        self.mock_storage_patch.stop()

    def test_init_authenticates_correctly(self):
        """Verifica que se llama a la API de Google con las credenciales correctas."""
        self.mock_storage_client_class.from_service_account_json.assert_called_with(self.service_account)
        self.mock_client_instance.bucket.assert_called_with(self.bucket_name)

    def test_list_files_success(self):
        """Prueba el listado y mapeo de blobs."""
        # Arrange
        blob1 = MagicMock()
        blob1.name = "folder/file1.txt"
        blob1.size = 1024

        blob2 = MagicMock()
        blob2.name = "image.png"
        blob2.size = 2048

        self.mock_bucket.list_blobs.return_value = [blob1, blob2]

        # Act
        files = self.connector.list_files()

        # Assert
        self.assertEqual(len(files), 2)

        self.assertEqual(files[0]['name'], "file1.txt")
        self.assertEqual(files[0]['path'], "folder/file1.txt")
        self.assertEqual(files[0]['metadata']['size'], 1024)

        self.assertEqual(files[1]['name'], "image.png")

    def test_get_file_content_success(self):
        """Prueba la descarga de contenido."""
        # Arrange
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = b"file content"
        self.mock_bucket.blob.return_value = mock_blob

        # Act
        content = self.connector.get_file_content("path/doc.pdf")

        # Assert
        self.mock_bucket.blob.assert_called_with("path/doc.pdf")
        mock_blob.download_as_bytes.assert_called_once()
        self.assertEqual(content, b"file content")

    def test_upload_file_success(self):
        """Prueba la subida de archivos."""
        # Arrange
        mock_blob = MagicMock()
        self.mock_bucket.blob.return_value = mock_blob

        file_path = "uploads/data.csv"
        content = b"csv,data"
        content_type = "text/csv"

        # Act
        self.connector.upload_file(file_path, content, content_type)

        # Assert
        self.mock_bucket.blob.assert_called_with(file_path)
        mock_blob.upload_from_string.assert_called_with(content, content_type=content_type)

    def test_delete_file_success(self):
        """Prueba la eliminación de archivos."""
        # Arrange
        mock_blob = MagicMock()
        self.mock_bucket.blob.return_value = mock_blob

        # Act
        self.connector.delete_file("old/file.txt")

        # Assert
        self.mock_bucket.blob.assert_called_with("old/file.txt")
        mock_blob.delete.assert_called_once()