import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from iatoolkit.repositories.filesystem_asset_repository import FileSystemAssetRepository
from iatoolkit.common.asset_storage import AssetType


class TestFileSystemAssetRepository:
    def setup_method(self):
        self.repo = FileSystemAssetRepository()
        self.company_short_name = "test_company"

    @patch('pathlib.Path.is_file')
    def test_exists_returns_true_when_file_exists(self, mock_is_file):
        # Arrange
        mock_is_file.return_value = True

        # Act
        result = self.repo.exists(self.company_short_name, AssetType.CONFIG, "company.yaml")

        # Assert
        assert result is True
        # Verify constructed path structure: companies/test_company/config/company.yaml
        # We rely on pathlib logic, but checking the call ensures we mapped enums correctly

    @patch('pathlib.Path.is_file')
    def test_exists_returns_false_when_file_missing(self, mock_is_file):
        # Arrange
        mock_is_file.return_value = False

        # Act
        result = self.repo.exists(self.company_short_name, AssetType.PROMPT, "missing.prompt")

        # Assert
        assert result is False

    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.is_file')
    def test_read_text_returns_content(self, mock_is_file, mock_read_text):
        # Arrange
        mock_is_file.return_value = True
        mock_read_text.return_value = "file content"

        # Act
        content = self.repo.read_text(self.company_short_name, AssetType.SCHEMA, "orders.yaml")

        # Assert
        assert content == "file content"
        mock_read_text.assert_called_once()

    @patch('pathlib.Path.is_file')
    def test_read_text_raises_filenotfounderror(self, mock_is_file):
        # Arrange
        mock_is_file.return_value = False

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            self.repo.read_text(self.company_short_name, AssetType.CONFIG, "missing.yaml")

    @patch('pathlib.Path.iterdir')
    @patch('pathlib.Path.exists')
    def test_list_files_returns_filtered_list(self, mock_exists, mock_iterdir):
        # Arrange
        mock_exists.return_value = True

        # Mock file objects returned by iterdir
        # We assign explicit string values to .name so the list comprehension works with strings
        file1 = MagicMock(spec=Path)
        file1.name = "valid.yaml"
        file1.is_file.return_value = True

        file2 = MagicMock(spec=Path)
        file2.name = "other.txt"
        file2.is_file.return_value = True

        dir1 = MagicMock(spec=Path)
        dir1.name = "subdir"
        dir1.is_file.return_value = False

        mock_iterdir.return_value = [file1, file2, dir1]

        # Act
        # 1. List all files
        all_files = self.repo.list_files(self.company_short_name, AssetType.CONTEXT)

        # 2. List with extension filter
        yaml_files = self.repo.list_files(self.company_short_name, AssetType.CONTEXT, extension=".yaml")

        # Assert
        assert len(all_files) == 2
        assert "valid.yaml" in all_files
        assert "other.txt" in all_files

        assert len(yaml_files) == 1
        assert "valid.yaml" in yaml_files

    @patch('pathlib.Path.exists')
    def test_list_files_returns_empty_if_dir_missing(self, mock_exists):
        # Arrange
        mock_exists.return_value = False

        # Act
        result = self.repo.list_files(self.company_short_name, AssetType.CONFIG)

        # Assert
        assert result == []

        @patch('pathlib.Path.write_text')
        @patch('pathlib.Path.mkdir')
        def test_write_text_creates_file(self, mock_mkdir, mock_write_text):
            # Arrange
            content = "new content"

            # Act
            self.repo.write_text(self.company_short_name, AssetType.PROMPT, "new.prompt", content)

            # Assert
            # Verify it tries to create directory structure first
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            # Verify it writes content
            mock_write_text.assert_called_once_with(content, encoding="utf-8")

        @patch('pathlib.Path.unlink')
        @patch('pathlib.Path.exists')
        def test_delete_removes_file_if_exists(self, mock_exists, mock_unlink):
            # Arrange
            mock_exists.return_value = True

            # Act
            self.repo.delete(self.company_short_name, AssetType.CONFIG, "old.yaml")

            # Assert
            mock_unlink.assert_called_once()

        @patch('pathlib.Path.unlink')
        @patch('pathlib.Path.exists')
        def test_delete_does_nothing_if_file_missing(self, mock_exists, mock_unlink):
            # Arrange
            mock_exists.return_value = False

            # Act
            self.repo.delete(self.company_short_name, AssetType.CONFIG, "missing.yaml")

            # Assert
            mock_unlink.assert_not_called()