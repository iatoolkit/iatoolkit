# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
import os
from unittest.mock import patch, mock_open, call
from iatoolkit.infra.connectors.local_file_connector import LocalFileConnector
from iatoolkit.common.exceptions import IAToolkitException
from datetime import datetime


class TestLocalFileConnector:
    def setup_method(self):
        self.mock_directory = "/mock/directory"
        self.file_connector = LocalFileConnector(self.mock_directory)

    @patch("os.listdir", side_effect=Exception("Error al listar directorio"))
    def test_list_files_error(self, mock_listdir):
        with pytest.raises(IAToolkitException) as excinfo:
            self.file_connector.list_files()

        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "Error procesando el directorio" in str(excinfo.value)
        mock_listdir.assert_called_once_with(self.mock_directory)

    @patch("os.path.getmtime")
    @patch("os.path.getsize")
    @patch("os.listdir")
    @patch("os.path.isfile")
    def test_list_files_success(self, mock_isfile, mock_listdir,
                                mock_getsize, mock_getmtime):
        # Configurar mocks
        mock_listdir.return_value = ["file1.txt", "file2.pdf", "subdir"]
        mock_isfile.side_effect = lambda path: not path.endswith("subdir")
        mock_getsize.return_value = 100
        mock_getmtime.return_value = datetime(2024, 2, 19, 15, 30)

        expected_return = [
            {
                'name': "file1.txt", 'path': '/mock/directory/file1.txt',
                'metadata': {'size': 100, 'last_modified': mock_getmtime.return_value}
            },
            {
                'name': "file2.pdf", 'path': '/mock/directory/file2.pdf',
                'metadata': {'size': 100, 'last_modified': mock_getmtime.return_value}
            }
        ]


        result = self.file_connector.list_files()

        assert result == expected_return
        mock_listdir.assert_called_once_with(self.mock_directory)
        mock_isfile.assert_has_calls([
            call(os.path.join(self.mock_directory, "file1.txt")),
            call(os.path.join(self.mock_directory, "file2.pdf")),
            call(os.path.join(self.mock_directory, "subdir")),
        ])


    @patch("builtins.open", side_effect=Exception("Error al abrir el archivo"))
    def test_get_file_content_error(self, mock_open_file):
        """Prueba para verificar que `get_file_content` lanza una excepción en caso de error."""
        mock_file_path = os.path.join(self.mock_directory, "file1.txt")

        # Verificar que se lanza la excepción esperada
        with pytest.raises(IAToolkitException) as excinfo:
            self.file_connector.get_file_content(mock_file_path)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "Error leyendo el archivo" in str(excinfo.value)
        mock_open_file.assert_called_once_with(mock_file_path, "rb")

    @patch("builtins.open", new_callable=mock_open, read_data=b"file content")
    def test_get_file_content_success(self, mock_open_file):
        mock_file_path = os.path.join(self.mock_directory, "file1.txt")

        result = self.file_connector.get_file_content(mock_file_path)

        # Verificaciones
        assert result == b"file content"
        mock_open_file.assert_called_once_with(mock_file_path, "rb")

    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_delete_file_success(self, mock_remove, mock_exists):
        """Prueba que delete_file elimine el archivo si existe."""
        mock_file_path = "subdir/file_to_delete.txt"
        full_path = os.path.join(self.mock_directory, mock_file_path)

        self.file_connector.delete_file(mock_file_path)

        mock_exists.assert_called_once_with(full_path)
        mock_remove.assert_called_once_with(full_path)

    @patch("os.path.exists", return_value=False)
    @patch("os.remove")
    def test_delete_file_ignored_if_not_exists(self, mock_remove, mock_exists):
        """Prueba que delete_file no haga nada si el archivo no existe."""
        self.file_connector.delete_file("ghost.txt")

        mock_remove.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("os.remove", side_effect=OSError("Permission denied"))
    def test_delete_file_error(self, mock_remove, mock_exists):
        """Prueba que delete_file lance IAToolkitException ante errores de OS."""
        with pytest.raises(IAToolkitException) as exc:
            self.file_connector.delete_file("protected.txt")

        assert exc.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "Error eliminando el archivo" in str(exc.value)
