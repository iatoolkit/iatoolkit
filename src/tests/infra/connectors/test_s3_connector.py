# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch, MagicMock
from iatoolkit.infra.connectors.s3_connector import S3Connector


class TestS3Connector(unittest.TestCase):
    def setUp(self):
        # 1. Patch de `boto3.client`
        self.boto3_client_patch = patch('iatoolkit.infra.connectors.s3_connector.boto3.client')
        self.mock_boto3_client = self.boto3_client_patch.start()

        # 2. Configurar el objeto cliente mock que devuelve boto3
        self.mock_s3_client = MagicMock()
        self.mock_boto3_client.return_value = self.mock_s3_client

        # 3. Datos de configuración comunes
        self.bucket = "test-bucket"
        self.prefix = "test-prefix"
        self.folder = "test-folder"
        self.auth = {
            "aws_access_key_id": "mock-key",
            "aws_secret_access_key": "mock-secret",
            "region_name": "us-east-1"
        }

        # 4. Instancia del conector a probar
        self.connector = S3Connector(
            bucket=self.bucket,
            prefix=self.prefix,
            folder=self.folder,
            auth=self.auth
        )

    def tearDown(self):
        self.boto3_client_patch.stop()

    def test_init_creates_boto3_client_correctly(self):
        """Verifica que el cliente boto3 se inicializa con las credenciales pasadas."""
        self.mock_boto3_client.assert_called_with('s3', **self.auth)

    def test_list_files_returns_mapped_objects(self):
        """Verifica que list_files mapea correctamente la respuesta de S3 a la estructura interna."""
        # Arrange
        self.mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "test-prefix/test-folder/doc1.pdf",
                    "Size": 1024,
                    "LastModified": "2023-01-01"
                },
                {
                    "Key": "test-prefix/test-folder/img.png",
                    "Size": 2048,
                    "LastModified": "2023-01-02"
                }
            ]
        }

        # Act
        result = self.connector.list_files()

        # Assert
        # Verificar llamada a S3 con prefijo correcto
        expected_prefix = f"{self.prefix}/{self.folder}/"
        self.mock_s3_client.list_objects_v2.assert_called_with(Bucket=self.bucket, Prefix=expected_prefix)

        # Verificar mapeo
        self.assertEqual(len(result), 2)

        self.assertEqual(result[0]['path'], "test-prefix/test-folder/doc1.pdf")
        self.assertEqual(result[0]['name'], "doc1.pdf")
        self.assertEqual(result[0]['metadata']['size'], 1024)

        self.assertEqual(result[1]['name'], "img.png")

    def test_list_files_returns_empty_list_when_no_contents(self):
        """Verifica que retorna lista vacía si S3 no devuelve 'Contents'."""
        self.mock_s3_client.list_objects_v2.return_value = {} # Sin clave 'Contents'

        result = self.connector.list_files()

        self.assertEqual(result, [])

    def test_get_file_content_success(self):
        """Verifica la descarga de contenido."""
        # Arrange
        mock_streaming_body = MagicMock()
        mock_streaming_body.read.return_value = b"file content bytes"
        self.mock_s3_client.get_object.return_value = {"Body": mock_streaming_body}

        path = "path/to/file.txt"

        # Act
        content = self.connector.get_file_content(path)

        # Assert
        self.mock_s3_client.get_object.assert_called_with(Bucket=self.bucket, Key=path)
        self.assertEqual(content, b"file content bytes")

    def test_upload_file_with_content_type(self):
        """Verifica subida de archivo pasando ContentType."""
        # Act
        self.connector.upload_file("path/image.png", b"data", "image/png")

        # Assert
        self.mock_s3_client.put_object.assert_called_once_with(
            Bucket=self.bucket,
            Key="path/image.png",
            Body=b"data",
            ContentType="image/png"
        )

    def test_upload_file_without_content_type(self):
        """Verifica subida de archivo sin ContentType."""
        # Act
        self.connector.upload_file("path/data.bin", b"raw_data")

        # Assert
        self.mock_s3_client.put_object.assert_called_once_with(
            Bucket=self.bucket,
            Key="path/data.bin",
            Body=b"raw_data"
        )

    def test_delete_file_success(self):
        """Verifica que delete_file llama a delete_object con los parámetros correctos."""
        # Act
        self.connector.delete_file("path/to/delete.txt")

        # Assert
        self.mock_s3_client.delete_object.assert_called_once_with(
            Bucket=self.bucket,
            Key="path/to/delete.txt"
        )

    def test_generate_presigned_url_defaults(self):
        """Verifica la generación de URL firmada con expiración por defecto."""
        # Arrange
        self.mock_s3_client.generate_presigned_url.return_value = "https://s3.aws.com/signed"

        # Act
        url = self.connector.generate_presigned_url("path/doc.pdf")

        # Assert
        self.assertEqual(url, "https://s3.aws.com/signed")
        self.mock_s3_client.generate_presigned_url.assert_called_with(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': "path/doc.pdf"},
            ExpiresIn=3600 # Default
        )

    def test_generate_presigned_url_custom_expiration(self):
        """Verifica la generación de URL firmada con expiración personalizada."""
        self.connector.generate_presigned_url("path/doc.pdf", expiration=60)

        self.mock_s3_client.generate_presigned_url.assert_called_with(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': "path/doc.pdf"},
            ExpiresIn=60
        )