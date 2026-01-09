# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch, MagicMock
from iatoolkit.infra.connectors.google_drive_connector import GoogleDriveConnector


class TestGoogleDriveConnector(unittest.TestCase):
    def setUp(self):
        # Parchar la función `build` de la API de Google Drive
        self.build_patch = patch('iatoolkit.infra.connectors.google_drive_connector.build')
        self.mock_build = self.build_patch.start()

        # Mock del servicio de Google Drive
        self.mock_drive_service = MagicMock()
        self.mock_build.return_value = self.mock_drive_service

        # Parchar las credenciales de Google
        self.credentials_patch = patch('iatoolkit.infra.connectors.google_drive_connector.Credentials.from_service_account_file')
        self.mock_credentials = self.credentials_patch.start()

        # Datos de configuración
        self.folder_id = "mock-folder-id"
        self.service_account_path = "mock-service-account.json"

        # Crear una instancia del conector utilizando la configuración
        self.connector = GoogleDriveConnector(
            folder_id=self.folder_id,
            service_account_path=self.service_account_path
        )

    def tearDown(self):
        self.build_patch.stop()
        self.credentials_patch.stop()

    def test_authenticate_when_success(self):
        self.mock_credentials.assert_called_once_with(
            self.service_account_path,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        self.mock_build.assert_called_once_with('drive', 'v3', credentials=self.mock_credentials.return_value)
        self.assertEqual(self.connector.drive_service, self.mock_build.return_value)

    def test_list_files_empty(self):
        self.mock_drive_service.files().list().execute.return_value = {'files': []}

        result = self.connector.list_files()

        self.mock_drive_service.files().list.assert_called_with(
            q=f"'{self.folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        )
        self.assertEqual(result, [])

    def test_list_files_success(self):
        # Simulación de la respuesta de la API
        fake_files = [
            {'id': 'file1-id', 'name': 'file1.txt'},
            {'id': 'file2-id', 'name': 'file2.txt'}
        ]
        self.mock_drive_service.files().list().execute.return_value = {'files': fake_files}

        result = self.connector.list_files()

        self.mock_drive_service.files().list.assert_called_with(
            q=f"'{self.folder_id}' in parents and trashed=false",
            fields="files(id, name)"
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['path'], 'file1-id')
        self.assertEqual(result[0]['name'], 'file1.txt')
        self.assertEqual(result[1]['path'], 'file2-id')
        self.assertEqual(result[1]['name'], 'file2.txt')


    def test_get_file_content_success(self):
        # Mock del flujo de descarga de archivo
        mock_request = MagicMock()
        self.mock_drive_service.files().get_media.return_value = mock_request

        mock_downloader = MagicMock()
        with patch('iatoolkit.infra.connectors.google_drive_connector.MediaIoBaseDownload', return_value=mock_downloader):
            # Configurar el buffer simulado
            mock_file_buffer = MagicMock()
            mock_downloader.next_chunk.side_effect = [(None, False), (None, True)]  # Simula dos "chunks"
            mock_file_buffer.getvalue.return_value = b"mock file content"

            with patch('io.BytesIO', return_value=mock_file_buffer):
                # Llamada al método
                result = self.connector.get_file_content('mock-file-id')

        self.mock_drive_service.files().get_media.assert_called_with(fileId='mock-file-id')
        mock_downloader.next_chunk.assert_called()
        self.assertEqual(result, b"mock file content")

    def test_get_file_content_when_error(self):
        self.mock_drive_service.files().get_media.side_effect = Exception("Mock download error")

        with self.assertRaises(Exception) as context:
            self.connector.get_file_content('invalid-file-id')

        self.mock_drive_service.files().get_media.assert_called_once_with(fileId='invalid-file-id')
        self.assertIn("Mock download error", str(context.exception))

    def test_upload_file_success(self):
        # Arrange
        file_name = "new_doc.pdf"
        content = b"PDF DATA"
        content_type = "application/pdf"

        mock_create = self.mock_drive_service.files().create
        mock_create.return_value.execute.return_value = {'id': 'new-file-id'}

        # Patch MediaIoBaseUpload since it's used internally
        with patch('iatoolkit.infra.connectors.google_drive_connector.MediaIoBaseUpload') as mock_media:
            # Act
            self.connector.upload_file(file_name, content, content_type)

            # Assert
            # Verify metadata
            call_args = mock_create.call_args.kwargs
            assert call_args['body']['name'] == file_name
            assert call_args['body']['parents'] == [self.folder_id]
            assert call_args['media_body'] == mock_media.return_value

    def test_delete_file_success(self):
        # Act
        self.connector.delete_file('file-id-to-delete')

        # Assert
        self.mock_drive_service.files().delete.assert_called_with(fileId='file-id-to-delete')