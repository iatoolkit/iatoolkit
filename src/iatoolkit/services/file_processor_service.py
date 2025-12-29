# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.connectors.file_connector import FileConnector
import logging
import os
from typing import Optional, Callable, Dict
from iatoolkit.repositories.models import Company


class FileProcessorConfig:
    """Configuration class for the FileProcessor."""
    def __init__(
        self,
        filters: Dict,
        callback: Callable[[Company, str, bytes, dict], None],
        continue_on_error: bool = True,
        log_file: str = 'file_processor.log',
        echo: bool = False,
        context: dict = None
    ):
        """
        Initializes the FileProcessor configuration.

        Args:
            filters (Dict): A dictionary of filters to apply to file names.
                Example: {'filename_contains': '.pdf'}
            action (Callable): The function to execute for each processed file.
                It receives filename (str), content (bytes), and context (dict).
            continue_on_error (bool): If True, continues processing other files upon an error.
            log_file (str): The path to the log file.
            echo (bool): If True, prints progress to the console.
            context (dict): A context dictionary passed to the action function.
        """
        self.filters = filters
        self.callback = callback
        self.continue_on_error = continue_on_error
        self.log_file = log_file
        self.echo = echo
        self.context = context or {}

class FileProcessor:
    """
    A generic service to process files from a given data source (connector).
    It lists files, applies filters, and executes a specific action for each one.
    """
    def __init__(self,
                 connector: FileConnector,
                 config: FileProcessorConfig,
                 logger: Optional[logging.Logger] = None):
        self.connector = connector
        self.config = config
        self.processed_files = 0


    def process_files(self):
        # Fetches files from the connector, filters them, and processes them.
        try:
            files = self.connector.list_files()
        except Exception as e:
            logging.error(f"Error fetching files: {e}")
            return False

        if self.config.echo:
            print(f'loading {len(files)} files')

        for file_info in files:
            file_path = file_info['path']
            file_name = file_info['name']

            try:
                if not self._apply_filters(file_name):
                    continue

                content = self.connector.get_file_content(file_path)

                # execute the callback function
                filename = os.path.basename(file_name)
                self.config.callback(company=self.config.context.get('company'),
                                     filename=filename,
                                     content=content,
                                     context=self.config.context)
                self.processed_files += 1

            except Exception as e:
                logging.error(f"Error processing {file_path}: {e}")
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