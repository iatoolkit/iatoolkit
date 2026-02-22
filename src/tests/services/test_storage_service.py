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
from iatoolkit.common.interfaces.secret_provider import SecretProvider

# ... existing code ...
class TestStorageService(unittest.TestCase):

    def setUp(self):
        # 1. Mock ConfigurationService
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_secret_provider = MagicMock(spec=SecretProvider)

        # 2. Patch FileConnectorFactory to intercept connector creation
        self.factory_patch = patch('iatoolkit.services.storage_service.FileConnectorFactory')
        self.mock_factory = self.factory_patch.start()

        # 3. Create a generic Mock Connector that the factory will return
        self.mock_connector_instance = MagicMock(spec=FileConnector)
        self.mock_factory.create.return_value = self.mock_connector_instance

        # 4. Instantiate Service with dependencies
        self.service = StorageService(
            config_service=self.mock_config_service,
            secret_provider=self.mock_secret_provider,
        )

        self.company_name = "test_co"

        # 5. Default connectors config used by most tests
        self.mock_config_service.get_configuration.return_value = {
            "iatoolkit_storage": {"type": "s3", "bucket": "bucket-x", "auth_env": {}}
        }

    def tearDown(self):
        self.factory_patch.stop()

    def test_connector_is_cached(self):
        # StorageService does not cache connectors anymore.
        self.service._get_connector(self.company_name)
        self.service._get_connector(self.company_name)

        self.assertEqual(self.mock_factory.create.call_count, 2)

    def test_store_generated_image_success(self):
        # Arrange
        raw_base64 = "aGVsbG8="  # "hello"
        mime_type = "image/png"
        expected_url = "https://signed-url.com/image.png"

        # Mock the connector behavior
        self.mock_connector_instance.generate_presigned_url.return_value = expected_url

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

        # Act
        self.service.store_generated_image(self.company_name, base64_with_header, "image/jpeg")

        # Assert
        upload_args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(upload_args['content'], b"hello")

    def test_store_generated_image_handles_error(self):
        # Arrange
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

        # Act
        url = self.service.generate_presigned_url(self.company_name, key)

        # Assert
        self.assertEqual(url, expected_url)
        self.mock_connector_instance.generate_presigned_url.assert_called_once_with(key)

    def test_upload_document(self):
        # Arrange
        content = b"pdf content"
        filename = "contract.pdf"
        mime = "application/pdf"

        # Act
        storage_key = self.service.upload_document(self.company_name, content, filename, mime)

        # Assert
        self.assertTrue(storage_key.startswith(f"companies/{self.company_name}/documents/"))
        self.assertTrue(storage_key.endswith(filename))

        self.mock_connector_instance.upload_file.assert_called_once()
        args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(args['content'], content)
        self.assertEqual(args['content_type'], mime)

    def test_upload_generated_download(self):
        content = b"excel content"
        filename = "report.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        storage_key = self.service.upload_generated_download(self.company_name, content, filename, mime)

        self.assertTrue(storage_key.startswith(f"companies/{self.company_name}/generated_downloads/"))
        self.assertTrue(storage_key.endswith(filename))

        self.mock_connector_instance.upload_file.assert_called_once()
        args = self.mock_connector_instance.upload_file.call_args.kwargs
        self.assertEqual(args['content'], content)
        self.assertEqual(args['content_type'], mime)
