# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import MagicMock, patch
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.infra.connectors.file_connector import FileConnector
from iatoolkit.common.exceptions import IAToolkitException

class TestStorageService(unittest.TestCase):

    def setUp(self):
        # 1. Mock ConfigurationService
        self.mock_config_service = MagicMock(spec=ConfigurationService)

        # 2. Patch FileConnectorFactory to intercept connector creation
        self.factory_patch = patch('iatoolkit.services.storage_service.FileConnectorFactory')
        self.mock_factory = self.factory_patch.start()

        # 3. Create a generic Mock Connector that the factory will return
        self.mock_connector_instance = MagicMock(spec=FileConnector)
        self.mock_factory.create.return_value = self.mock_connector_instance

        # 4. Instantiate Service with dependencies
        self.service = StorageService(config_service=self.mock_config_service)

        self.company_name = "test_co"

    def tearDown(self):
        self.factory_patch.stop()

    def test_get_connector_defaults_to_s3_when_no_config(self):
        # Arrange: No config found for this company
        self.mock_config_service.get_configuration.return_value = None

        # Act
        # Access private method to verify logic
        connector = self.service._get_connector(self.company_name)

        # Assert
        self.mock_factory.create.assert_called_once()
        args, _ = self.mock_factory.create.call_args
        config_passed = args[0]

        self.assertEqual(config_passed['type'], 's3')
        self.assertEqual(connector, self.mock_connector_instance)

    def test_get_connector_uses_gcs_configuration(self):
        # Arrange: Mock configuration for GCS
        self.mock_config_service.get_configuration.return_value = {
            "provider": "google_cloud_storage",
            "bucket": "my-gcs-bucket",
            "google_cloud_storage": {
                "service_account_path": "path/to/key.json"
            }
        }

        # Act
        self.service._get_connector(self.company_name)

        # Assert
        self.mock_factory.create.assert_called_once()
        args, _ = self.mock_factory.create.call_args
        config_passed = args[0]

        self.assertEqual(config_passed['type'], 'gcs')
        self.assertEqual(config_passed['bucket'], 'my-gcs-bucket')
        self.assertEqual(config_passed['service_account_path'], 'path/to/key.json')

    def test_get_connector_uses_s3_explicit_configuration(self):
        # Arrange: Mock configuration for S3
        self.mock_config_service.get_configuration.return_value = {
            "provider": "s3",
            "bucket": "my-s3-bucket",
            "s3": {
                "prefix": "data",
                "access_key_env": "MY_KEY",
                "secret_key_env": "MY_SECRET",
                "region_env": "MY_REGION"
            }
        }

        # Act
        self.service._get_connector(self.company_name)

        # Assert
        self.mock_factory.create.assert_called_once()
        args, _ = self.mock_factory.create.call_args
        config_passed = args[0]

        self.assertEqual(config_passed['type'], 's3')
        self.assertEqual(config_passed['bucket'], 'my-s3-bucket')
        self.assertEqual(config_passed['prefix'], 'data')
        # Check that it resolved environment variables names to values (mocked env vars would be needed for full check)
        self.assertIn('auth', config_passed)

    def test_connector_is_cached(self):
        # Arrange
        self.mock_config_service.get_configuration.return_value = None

        # Act
        # First call
        self.service._get_connector(self.company_name)
        # Second call
        self.service._get_connector(self.company_name)

        # Assert: Factory should be called only once
        self.mock_factory.create.assert_called_once()

    def test_store_generated_image_success(self):
        # Arrange
        raw_base64 = "aGVsbG8=" # "hello"
        mime_type = "image/png"
        expected_url = "https://signed-url.com/image.png"

        # Mock the connector behavior
        self.mock_connector_instance.generate_presigned_url.return_value = expected_url
        self.mock_config_service.get_configuration.return_value = None # Use default

        # Act
        result = self.service.store_generated_image(self.company_name, raw_base64, mime_type)

        # Assert
        self.assertEqual(result['url'], expected_url)
        self.assertTrue(result['storage_key'].startswith(f"companies/{self.company_name}/generated_images/"))

        # Verify upload called on the connector instance
        self.mock_connector_instance.upload_file.assert_called_once()
        upload_args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(upload_args['content'], b"hello")
        self.assertEqual(upload_args['content_type'], mime_type)

    def test_store_generated_image_strips_header(self):
        # Arrange
        base64_with_header = "data:image/jpeg;base64,aGVsbG8="
        self.mock_config_service.get_configuration.return_value = None

        # Act
        self.service.store_generated_image(self.company_name, base64_with_header, "image/jpeg")

        # Assert
        upload_args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(upload_args['content'], b"hello")

    def test_store_generated_image_handles_error(self):
        # Arrange
        self.mock_config_service.get_configuration.return_value = None
        self.mock_connector_instance.upload_file.side_effect = Exception("Upload failed")

        # Act & Assert
        with self.assertRaises(IAToolkitException) as context:
            self.service.store_generated_image(self.company_name, "AAAA", "image/png")

        self.assertEqual(context.exception.error_type, IAToolkitException.ErrorType.FILE_IO_ERROR)
        self.assertIn("Upload failed", str(context.exception))

    def test_get_public_url(self):
        # Arrange
        key = "some/path/file.jpg"
        expected_url = "http://signed-url"
        self.mock_connector_instance.generate_presigned_url.return_value = expected_url
        self.mock_config_service.get_configuration.return_value = None

        # Act
        url = self.service.get_public_url(self.company_name, key)

        # Assert
        self.assertEqual(url, expected_url)
        self.mock_connector_instance.generate_presigned_url.assert_called_once_with(key)

    def test_upload_document(self):
        # Arrange
        content = b"pdf content"
        filename = "contract.pdf"
        mime = "application/pdf"
        self.mock_config_service.get_configuration.return_value = None

        # Act
        storage_key = self.service.upload_document(self.company_name, content, filename, mime)

        # Assert
        self.assertTrue(storage_key.startswith(f"companies/{self.company_name}/documents/"))
        self.assertTrue(storage_key.endswith(filename))

        self.mock_connector_instance.upload_file.assert_called_once()
        args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(args['content'], content)
        self.assertEqual(args['content_type'], mime)