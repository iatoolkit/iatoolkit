# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from infra.connectors.file_connector import FileConnector
import logging
import os
from typing import Optional, Callable, Dict


class FileProcessorConfig:
    def __init__(
        self,
        filters: Dict,
        action: Callable[[str, bytes], None],
        continue_on_error: bool = True,
        log_file: str = 'file_processor.log',
        echo: bool = False,
        context: dict = None,
    ):
        self.filters = filters
        self.action = action
        self.continue_on_error = continue_on_error
        self.log_file = log_file
        self.echo = echo
        self.context = context or {}
        self.company = None

class FileProcessor:
    def __init__(self,
                 connector: FileConnector,
                 config: FileProcessorConfig,
                 logger: Optional[logging.Logger] = None):
        self.connector = connector
        self.config = config
        self.logger = logger or self._setup_logger()
        self.processed_files = 0

    def _setup_logger(self):
        logging.basicConfig(
            filename=self.config.log_file,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    def process_files(self):
        try:
            files = self.connector.list_files()
        except Exception as e:
            self.logger.error(f"Error fetching files: {e}")
            return False

        if self.config.echo:
            print(f'cargando un total de {len(files)} archivos')

        for file_info in files:
            file_path = file_info['path']
            file_name = file_info['name']

            try:
                if not self._apply_filters(file_name):
                    continue

                if self.config.echo:
                    print(f'loading: {file_name}')

                content = self.connector.get_file_content(file_path)

                # execute the action defined
                filename = os.path.basename(file_name)
                self.config.action(filename, content, self.config.context)
                self.processed_files += 1

                self.logger.info(f"Successfully processed file: {file_path}")

            except Exception as e:
                self.logger.error(f"Error processing {file_path}: {e}")
                if not self.config.continue_on_error:
                    raise e

    def _apply_filters(self, file_path: str) -> bool:
        filters = self.config.filters

        if 'filename_contains' in filters and filters['filename_contains'] not in file_path:
            return False

        if 'custom_filter' in filters and callable(filters['custom_filter']):
            if not filters['custom_filter'](file_path):
                return False

        return True