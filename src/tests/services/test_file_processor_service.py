# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.file_processor_service import FileProcessor, FileProcessorConfig
from iatoolkit.infra.connectors.file_connector import FileConnector


class TestFileProcessor:
    def setup_method(self):
        # Mock del conector de archivos
        self.mock_connector = MagicMock(spec=FileConnector)

        # Acción de ejemplo para la configuración
        self.mock_callback = MagicMock()
        self.mock_company = MagicMock()

        # Configuración del FileProcessorConfig con validaciones y mocks
        self.mock_config = FileProcessorConfig(
            log_file="mock_log_file.log",  # Archivo de log ficticio
            callback=self.mock_callback,  # Acción mockeada
            filters={
                "filename_contains": "test",
                "custom_filter": lambda x: x.endswith(".txt")  # Solo procesar archivos .txt
            },
            echo=True,
            continue_on_error=True,
            context={'company': self.mock_company,}
        )

        # Creamos la instancia de FileProcessor con los mocks
        self.processor = FileProcessor(
            self.mock_connector,
            self.mock_config
        )

        self.mock_connector.list_files.return_value = [
            {'path': "/mock/directory/test_file.txt",
             'name': 'test_file.txt'}
        ]

    def test_process_files_when_exception_on_list_files(self):
        # Generar un error intencional al abrir un archivo
        self.mock_connector.list_files.side_effect = Exception("list file error")

        status = self.processor.process_files()
        assert status == False


    def test_process_files_filtered_out(self):
        """Prueba que se filtren los archivos que no coincidan con los filtros."""
        self.mock_connector.list_files.return_value = [
            {'path': "/mock/directory/test_file1.doc",
             'name': 'test_file1.doc'},
            {'path': "/mock/directory/test_file2.txt",
             'name': 'test_file2.txt'}
        ]

        self.mock_connector.get_file_content.return_value = b"content of file2"

        self.processor.process_files()

        # Solo debe procesarse test_file2.txt
        self.mock_callback.assert_called_once_with(
            company=self.mock_company,
            filename="test_file2.txt",
            content=b"content of file2",
            context={'company': self.mock_company})
        assert self.mock_callback.call_count == 1
        assert self.mock_connector.get_file_content.call_count == 1

    def test_process_files_stop_on_error(self):
        """Prueba que se detenga el procesamiento si `continue_on_error` es False."""
        self.mock_config.continue_on_error = False  # Configuración para detenerse en errores
        self.mock_connector.get_file_content.side_effect = Exception("Mocked error")

        # Verificar que se lanza la excepción y no continúa procesando
        with pytest.raises(Exception, match="Mocked error"):
            self.processor.process_files()

        # No se debe haber realizado ninguna acción
        self.mock_callback.assert_not_called()

    def test_process_files_success(self):
        self.mock_connector.list_files.return_value = [
            {'path': "/mock/directory/test_file1.txt",
             'name': 'test_file1.txt'},
            {'path': "/mock/directory/test_file2.txt",
             'name': 'test_file2.txt'}
        ]
        self.mock_connector.get_file_content.side_effect = [
            b"content of file1",
            b"content of file2",
        ]

        self.processor.process_files()

        # Verificar que se llamaron las acciones con los archivos correctos
        assert self.mock_callback.call_count == 2  # Solo archivos filtrados

        # Verificar numero de archivos procesados
        assert self.processor.processed_files == 2

        # Verificar las llamadas al logger (si es necesario)
        self.mock_connector.list_files.assert_called_once()
