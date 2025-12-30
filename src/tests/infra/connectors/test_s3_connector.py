# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch, MagicMock
from iatoolkit.infra.connectors.s3_connector import S3Connector


class TestS3Connector(unittest.TestCase):
    def setUp(self):
        # Mock de `boto3.client`
        self.boto3_client_patch = patch('iatoolkit.infra.connectors.s3_connector.boto3.client')
        self.mock_boto3_client = self.boto3_client_patch.start()

        # Mock del cliente S3
        self.mock_s3_client = MagicMock()
        self.mock_boto3_client.return_value = self.mock_s3_client

        # Configuración básica
        self.bucket = "test-bucket"
        self.prefix = "test-prefix/"
        self.folder = "test-folder/"
        self.auth = {
            "aws_access_key_id": "mock-key",
            "aws_secret_access_key": "mock-secret",
            "region_name": "us-east-1"
        }

        # Crear una instancia del conector con los mocks
        self.connector = S3Connector(bucket=self.bucket, prefix=self.prefix, folder=self.folder, auth=self.auth)

    def tearDown(self):
        self.boto3_client_patch.stop()

    def test_init_when_boto3_client_error(self):
        self.mock_boto3_client.side_effect = Exception("Failed to create boto3 client")

        with self.assertRaises(Exception) as context:
            S3Connector(bucket=self.bucket, prefix=self.prefix, folder=self.folder, auth=self.auth)

        # Validar que el mensaje de la excepción coincide
        self.assertEqual(str(context.exception), "Failed to create boto3 client")

    def test_list_files_empty(self):
        self.mock_s3_client.list_objects_v2.return_value = {}

        result = self.connector.list_files()
        self.assertEqual(result, [])

    def test_list_files_success(self):
        # Simulación de respuesta de `list_objects_v2`
        self.mock_s3_client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "test-prefix/file1.txt",
                    "Size": 1024,
                    "LastModified": "2023-01-01T12:00:00.000Z"
                },
                {
                    "Key": "test-prefix/file2.txt",
                    "Size": 2048,
                    "LastModified": "2023-01-02T12:00:00.000Z"
                }
            ]
        }

        result = self.connector.list_files()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['path'], "test-prefix/file1.txt")
        self.assertEqual(result[0]['name'], "file1.txt")
        self.assertEqual(result[0]['metadata']['size'], 1024)
        self.assertEqual(result[0]['metadata']['last_modified'], "2023-01-01T12:00:00.000Z")


    def test_get_file_content_not_found(self):
        # Simulación de excepción de archivo no encontrado
        self.mock_s3_client.get_object.side_effect = Exception("NoSuchKey")

        # Llamada al método y capturar excepción
        with self.assertRaises(Exception) as context:
            self.connector.get_file_content("test-prefix/nonexistent.txt")

        # Validar la excepción
        self.assertEqual(str(context.exception), "NoSuchKey")

    def test_get_file_content_success(self):
        # Simulación de respuesta de `get_object`
        mock_body = MagicMock()
        mock_body.read.return_value = b"mock file content"
        self.mock_s3_client.get_object.return_value = {"Body": mock_body}

        result = self.connector.get_file_content("test-prefix/file1.txt")
        self.assertEqual(result, b"mock file content")
