# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch, MagicMock, call

from googleapiclient.errors import HttpError

from iatoolkit.infra.connectors.google_drive_connector import DriveFile, GoogleDriveConnector


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
        self.credentials_info_patch = patch('iatoolkit.infra.connectors.google_drive_connector.Credentials.from_service_account_info')
        self.mock_credentials_info = self.credentials_info_patch.start()

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
        self.credentials_info_patch.stop()

    def test_authenticate_when_success(self):
        self.mock_credentials.assert_called_once_with(
            self.service_account_path,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        self.mock_build.assert_called_once_with(
            'drive',
            'v3',
            credentials=self.mock_credentials.return_value,
            cache_discovery=False,
        )
        self.assertEqual(self.connector.drive_service, self.mock_build.return_value)

    def test_authenticate_when_service_account_info_is_provided(self):
        connector = GoogleDriveConnector(
            folder_id=self.folder_id,
            service_account_info={"client_email": "svc@example.com"},
        )

        self.mock_credentials_info.assert_called_with(
            {"client_email": "svc@example.com"},
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        self.mock_build.assert_called_with(
            'drive',
            'v3',
            credentials=self.mock_credentials_info.return_value,
            cache_discovery=False,
        )
        self.assertEqual(connector.drive_service, self.mock_build.return_value)

    LIST_FIELDS = (
        "nextPageToken, files(id, name, mimeType, parents, md5Checksum, modifiedTime, size, trashed, headRevisionId)"
    )

    def list_call(self, folder_id, page_token=None):
        return call(
            q=f"'{folder_id}' in parents and trashed=false",
            fields=self.LIST_FIELDS,
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )

    def test_list_files_empty(self):
        self.mock_drive_service.files().list().execute.return_value = {'files': []}

        result = self.connector.list_files()

        self.assertEqual(self.mock_drive_service.files().list.call_args, self.list_call(self.folder_id))
        self.assertEqual(result, [])

    def test_list_files_follows_every_page(self):
        self.mock_drive_service.files().list().execute.side_effect = [
            {'files': [{'id': 'file1-id', 'name': 'file1.txt', 'mimeType': 'text/plain', 'md5Checksum': 'a'}],
             'nextPageToken': 'page-2'},
            {'files': [{'id': 'file2-id', 'name': 'file2.txt', 'mimeType': 'text/plain', 'size': '12'}]},
        ]

        result = self.connector.list_files()

        self.assertEqual([item['path'] for item in result], ['file1-id', 'file2-id'])
        self.assertEqual(result[0]['metadata']['md5_checksum'], 'a')
        self.assertEqual(result[1]['metadata']['size'], 12)
        self.assertEqual(self.mock_drive_service.files().list.call_args, self.list_call(self.folder_id, 'page-2'))

    def test_walk_enters_folders_with_their_path_and_skips_shortcuts(self):
        listings = {
            "root": [
                {'id': 'f1', 'name': 'precios.pdf', 'mimeType': 'application/pdf'},
                {'id': 'd1', 'name': 'Contratos', 'mimeType': 'application/vnd.google-apps.folder'},
                {'id': 's1', 'name': 'atajo', 'mimeType': 'application/vnd.google-apps.shortcut'},
            ],
            "d1": [
                {'id': 'd2', 'name': '2026', 'mimeType': 'application/vnd.google-apps.folder'},
            ],
            "d2": [
                {'id': 'f2', 'name': 'acme.docx', 'mimeType': 'application/msword'},
            ],
        }
        self.connector.list_children = lambda folder_id: iter(
            [DriveFile.from_api(payload) for payload in listings.get(folder_id, [])]
        )

        files = list(self.connector.walk("root"))

        self.assertEqual([(item.id, item.path) for item in files], [('f1', ''), ('f2', 'Contratos/2026')])

    def test_get_file_content_success(self):
        mock_request = MagicMock()
        self.mock_drive_service.files().get_media.return_value = mock_request

        mock_downloader = MagicMock()
        with patch('iatoolkit.infra.connectors.google_drive_connector.MediaIoBaseDownload', return_value=mock_downloader):
            mock_file_buffer = MagicMock()
            mock_downloader.next_chunk.side_effect = [(None, False), (None, True)]
            mock_file_buffer.getvalue.return_value = b"mock file content"

            with patch('io.BytesIO', return_value=mock_file_buffer):
                result = self.connector.download('mock-file-id', 'application/pdf')

        self.mock_drive_service.files().get_media.assert_called_with(fileId='mock-file-id', supportsAllDrives=True)
        self.assertEqual(result, (b"mock file content", None, 'application/pdf'))

    def test_google_docs_are_exported_to_a_format_the_parsers_read(self):
        with patch.object(self.connector, '_read', return_value=b"DOCX"):
            content, extension, mime = self.connector.download(
                'doc-id', 'application/vnd.google-apps.document')

        self.mock_drive_service.files().export_media.assert_called_with(
            fileId='doc-id',
            mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertEqual((content, extension), (b"DOCX", ".docx"))

    def test_google_formats_without_export_cannot_be_downloaded(self):
        with self.assertRaises(ValueError):
            self.connector.download('form-id', 'application/vnd.google-apps.form')

    def test_get_file_content_when_error(self):
        self.mock_drive_service.files().get_media.side_effect = Exception("Mock download error")

        with self.assertRaises(Exception) as context:
            self.connector.download('invalid-file-id', 'application/pdf')

        self.assertIn("Mock download error", str(context.exception))

    def test_get_file_is_none_when_not_shared_or_missing(self):
        response = MagicMock(status=404)
        self.mock_drive_service.files().get().execute.side_effect = HttpError(response, b"not found")

        self.assertIsNone(self.connector.get_file('missing'))

    def test_changes_pages_report_files_removals_and_the_next_token(self):
        self.mock_drive_service.changes().list().execute.return_value = {
            'changes': [
                {'fileId': 'f1', 'removed': False, 'file': {'id': 'f1', 'name': 'a.pdf', 'mimeType': 'application/pdf',
                                                              'parents': ['root'], 'md5Checksum': 'x'}},
                {'fileId': 'f2', 'removed': True},
            ],
            'newStartPageToken': 'token-2',
        }

        page = self.connector.list_changes('token-1')

        self.assertEqual([(change.file_id, change.removed) for change in page.changes], [('f1', False), ('f2', True)])
        self.assertEqual(page.changes[0].file.parents, ('root',))
        self.assertEqual(page.new_start_page_token, 'token-2')
        self.assertIsNone(page.next_page_token)

    def test_read_only_asks_only_for_the_read_only_scope(self):
        GoogleDriveConnector(folder_id='x', service_account_info={"client_email": "svc@example.com"}, read_only=True)

        self.mock_credentials_info.assert_called_with(
            {"client_email": "svc@example.com"},
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )

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



class TestGoogleDriveConnectorRetries(TestGoogleDriveConnector):
    def test_reads_retry_transient_google_errors(self):
        self.mock_drive_service.changes().list().execute.return_value = {"changes": [], "newStartPageToken": "2"}
        self.mock_drive_service.changes().getStartPageToken().execute.return_value = {"startPageToken": "1"}
        self.mock_drive_service.files().list().execute.return_value = {"files": []}

        self.connector.list_changes("1")
        self.connector.get_start_page_token()
        list(self.connector.list_children("folder"))

        for call in (self.mock_drive_service.changes().list().execute,
                     self.mock_drive_service.changes().getStartPageToken().execute,
                     self.mock_drive_service.files().list().execute):
            self.assertEqual(call.call_args.kwargs, {"num_retries": GoogleDriveConnector.NUM_RETRIES})
