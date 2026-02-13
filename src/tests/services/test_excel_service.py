# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.services.excel_service import ExcelService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.common.util import Utility
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from flask import Flask
import pandas as pd
import io
import json
from iatoolkit.common.exceptions import IAToolkitException


class TestExcelService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = Flask(__name__)
        self.app.testing = True

        # Create real temporary directory structure
        self.temp_dir_base = tempfile.mkdtemp()
        self.app.root_path = self.temp_dir_base
        self.temp_dir = os.path.join(self.temp_dir_base, 'static', 'temp')
        os.makedirs(self.temp_dir, exist_ok=True)

        # Mocks of services
        self.util = MagicMock(spec=Utility)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_storage_service = MagicMock(spec=StorageService)
        self.excel_service = ExcelService(
            util=self.util,
            i18n_service=self.mock_i18n_service,
            storage_service=self.mock_storage_service
        )

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        yield

        # Cleanup after test
        shutil.rmtree(self.temp_dir_base)

    def _create_excel_bytes(self, sheets_data: dict) -> bytes:
        """Helper to create an in-memory Excel file with one or more sheets."""
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, data in sheets_data.items():
                df = pd.DataFrame(data)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return output.getvalue()

    def test_read_excel_single_sheet(self):
        """
        GIVEN a valid Excel file with a single sheet
        WHEN read_excel is called
        THEN it should return a JSON string of that sheet's records.
        """
        # Arrange
        sheet_data = [{'col1': 1, 'col2': 'A'}, {'col1': 2, 'col2': 'B'}]
        excel_bytes = self._create_excel_bytes({'Sheet1': sheet_data})

        # Act
        json_output = self.excel_service.read_excel(excel_bytes)

        # Assert
        parsed_data = json.loads(json_output)
        assert parsed_data == sheet_data

    def test_read_excel_multiple_sheets(self):
        """
        GIVEN a valid Excel file with multiple sheets
        WHEN read_excel is called
        THEN it should return a JSON string where keys are sheet names.
        """
        # Arrange
        sheet1_data = [{'col1': 1, 'col2': 'A'}]
        sheet2_data = [{'colA': 3, 'colB': 'C'}]
        sheets_data = {'MySheet1': sheet1_data, 'MySheet2': sheet2_data}
        excel_bytes = self._create_excel_bytes(sheets_data)

        # Act
        json_output = self.excel_service.read_excel(excel_bytes)

        # Assert
        parsed_data = json.loads(json_output)

        # Check that top-level keys are sheet names
        assert 'MySheet1' in parsed_data
        assert 'MySheet2' in parsed_data

        # Check content of each sheet
        assert json.loads(parsed_data['MySheet1']) == sheet1_data
        assert json.loads(parsed_data['MySheet2']) == sheet2_data

    def test_read_excel_invalid_file_raises_exception(self):
        """
        GIVEN invalid byte content (not an Excel file)
        WHEN read_excel is called
        THEN it should raise an IAToolkitException with a specific error type.
        """
        # Arrange
        invalid_bytes = b"this is not an excel file"
        self.mock_i18n_service.t.return_value = "Cannot read Excel file."

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.excel_service.read_excel(invalid_bytes)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_FORMAT_ERROR
        self.mock_i18n_service.t.assert_called_with('errors.services.cannot_read_excel')

    def test_read_csv_valid_file(self):
        """
        GIVEN a valid CSV file content
        WHEN read_csv is called
        THEN it should return a JSON string of the records.
        """
        # Arrange
        csv_content = b"col1,col2\n1,A\n2,B"
        expected_data = [{'col1': 1, 'col2': 'A'}, {'col1': 2, 'col2': 'B'}]

        # Act
        json_output = self.excel_service.read_csv(csv_content)

        # Assert
        parsed_data = json.loads(json_output)
        assert parsed_data == expected_data

    def test_read_csv_invalid_file_raises_exception(self):
        """
        GIVEN invalid content that fails CSV parsing (simulated via pandas error)
        WHEN read_csv is called
        THEN it should raise an IAToolkitException.
        """
        # Arrange
        # Note: pandas is very forgiving with CSVs, so simpler strings often pass as single columns.
        # We mock pandas to force an error for a robust test of the exception handling block.
        invalid_bytes = b"some random bytes"
        self.mock_i18n_service.t.return_value = "Cannot read CSV file."

        with patch('pandas.read_csv', side_effect=Exception("Pandas error")):
            # Act & Assert
            with pytest.raises(IAToolkitException) as excinfo:
                self.excel_service.read_csv(invalid_bytes)

            assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_FORMAT_ERROR
            self.mock_i18n_service.t.assert_called_with('errors.services.cannot_read_csv')

    def create_test_file(self, filename, content=b'test content'):
        file_path = os.path.join(self.temp_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(content)
        return file_path

    def test_validate_file_access_valid_file(self):
        filename = 'valid_file.xlsx'
        self.create_test_file(filename)

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is None

    def test_validate_file_access_path_traversal_dotdot(self):
        filename = '../../../etc/passwd'

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_validate_file_access_path_traversal_absolute_unix(self):
        filename = '/etc/passwd'

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_validate_file_access_path_traversal_backslash(self):
        filename = 'folder\\..\\sensitive_file.txt'

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_validate_file_access_file_not_found(self):
        filename = 'non_existent_file.xlsx'

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.file_not_exist'

    def test_validate_file_access_is_directory(self):
        dirname = 'test_directory'
        dir_path = os.path.join(self.temp_dir, dirname)
        os.makedirs(dir_path)

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(dirname)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.path_is_not_a_file'

    def test_validate_file_access_exception_handling(self):
        filename = 'test_file.xlsx'

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                with patch('iatoolkit.services.excel_service.os.path.exists', side_effect=Exception("Test exception")):
                    result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.file_validation_error'

    def test_validate_file_access_logs_exception(self):
        filename = 'test_file.xlsx'

        with patch('iatoolkit.services.excel_service.logging') as mock_logging:
            with patch('iatoolkit.services.excel_service.os.path.exists', side_effect=Exception("Test exception")):
                with self.app.app_context():
                    with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                        mock_current_app.root_path = self.temp_dir_base
                        self.excel_service.validate_file_access(filename)

        mock_logging.error.assert_called_once()
        error_msg = mock_logging.error.call_args[0][0]
        assert 'File validation error test_file.xlsx' in error_msg
        assert 'Test exception' in error_msg

    def test_validate_file_access_various_valid_filenames(self):
        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base

                valid_filenames = [
                    'simple.xlsx',
                    'file_with_underscores.xlsx',
                    'file-with-dashes.xlsx',
                    'file with spaces.xlsx',
                    'file123.xlsx',
                    'UPPERCASE.XLSX',
                    'file.with.dots.xlsx'
                ]

                for filename in valid_filenames:
                    self.create_test_file(filename)
                    result = self.excel_service.validate_file_access(filename)
                    assert result is None, f"Filename '{filename}' should be valid"

    def test_validate_file_access_various_invalid_filenames(self):
        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base

                invalid_filenames = [
                    '../file.xlsx',
                    '../../file.xlsx',
                    '/absolute/path/file.xlsx',
                    'folder\\file.xlsx',
                    '..\\file.xlsx',
                    'file..xlsx/../other.xlsx',
                    '/etc/passwd',
                    'C:\\Windows\\System32\\config'
                ]

                for filename in invalid_filenames:
                    result = self.excel_service.validate_file_access(filename)
                    assert result is not None, f"Filename '{filename}' should be invalid"
                    data = result.get_json()
                    assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_validate_file_access_empty_filename(self):
        filename = ''

        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(filename)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_validate_file_access_none_filename(self):
        with self.app.app_context():
            with patch('iatoolkit.services.excel_service.current_app') as mock_current_app:
                mock_current_app.root_path = self.temp_dir_base
                result = self.excel_service.validate_file_access(None)

        assert result is not None
        data = result.get_json()
        assert data['error'] == 'translated:errors.services.invalid_filename'

    def test_excel_generator_uploads_to_storage_and_returns_signed_download_link(self):
        self.mock_storage_service.upload_generated_download.return_value = "companies/acme/generated_downloads/1/generated.xlsx"
        self.mock_storage_service.create_download_token.return_value = "signed-token"

        with self.app.app_context():
            self.app.config["SECRET_KEY"] = "test-secret"
            result = self.excel_service.excel_generator(
                "acme",
                filename="report.xlsx",
                data=[{"id": 1, "name": "Alice"}],
                sheet_name="Sheet1"
            )

        assert result["filename"] == "report.xlsx"
        assert result["attachment_token"] == "signed-token"
        assert result["download_link"] == "/download/signed-token"
        assert result["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        self.mock_storage_service.upload_generated_download.assert_called_once()
        upload_kwargs = self.mock_storage_service.upload_generated_download.call_args.kwargs
        assert upload_kwargs["company_short_name"] == "acme"
        assert upload_kwargs["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert upload_kwargs["filename"].endswith(".xlsx")
        assert isinstance(upload_kwargs["file_content"], (bytes, bytearray))
        assert len(upload_kwargs["file_content"]) > 0

        self.mock_storage_service.create_download_token.assert_called_once_with(
            company_short_name="acme",
            storage_key="companies/acme/generated_downloads/1/generated.xlsx",
            filename="report.xlsx"
        )
