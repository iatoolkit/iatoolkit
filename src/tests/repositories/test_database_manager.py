# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import patch, MagicMock
from iatoolkit.repositories.database_manager import DatabaseManager
import pytest

class TestDatabaseManager:
    def setup_method(self):
        self.mock_engine = MagicMock()
        self.mock_sessionmaker = MagicMock()
        self.mock_scoped_session = MagicMock()
        self.mock_base_metadata = MagicMock()
        self.mock_inspect = MagicMock()

        self.database_url = "sqlite:///:memory:"

        # Lista para almacenar todos los patches
        self.patchers = []

        # Crear y agregar patches a la lista
        patcher_engine = patch('iatoolkit.repositories.database_manager.create_engine', return_value=self.mock_engine)
        patcher_sessionmaker = patch('iatoolkit.repositories.database_manager.sessionmaker', return_value=self.mock_sessionmaker)
        patcher_scoped_session = patch('iatoolkit.repositories.database_manager.scoped_session',
                                       return_value=self.mock_scoped_session)
        patcher_metadata = patch('iatoolkit.repositories.database_manager.Base.metadata', self.mock_base_metadata)
        patcher_inspect = patch('iatoolkit.repositories.database_manager.inspect', self.mock_inspect)

        self.patchers.extend(
            [patcher_engine, patcher_sessionmaker, patcher_scoped_session, patcher_metadata, patcher_inspect])

        # Inicia todos los patches y almacena los mocks retornados si es necesario
        self.mock_create_engine = patcher_engine.start()
        self.mock_sessionmaker_function = patcher_sessionmaker.start()
        self.mock_scoped_session_function = patcher_scoped_session.start()
        self.mock_inspect = patcher_inspect.start()
        patcher_metadata.start()

        self.db_manager = DatabaseManager(self.database_url)

    def teardown_method(self):
        for patcher in self.patchers:
            patcher.stop()

    def test_get_session_returns_scoped_session(self):
        session = self.db_manager.get_session()
        assert session == self.mock_scoped_session()

    def test_create_all_calls_metadata_create_all(self):
        self.db_manager.create_all()
        assert self.mock_base_metadata.create_all.call_count == 1

    def test_drop_all_calls_metadata_drop_all(self):
        self.db_manager.drop_all()
        self.mock_base_metadata.drop_all.assert_called_once_with(self.mock_engine)

    def test_remove_session_calls_scoped_session_remove(self):
        self.db_manager.remove_session()
        self.mock_scoped_session.remove.assert_called_once()

    def test_get_table_schema_table_exists(self):
        """Prueba get_table_schema cuando la tabla existe"""
        self.mock_inspect.return_value.get_table_names.return_value = ['test_table']
        self.mock_inspect.return_value.get_columns.return_value = [
            {"name": "id", "type": "INTEGER"},
            {"name": "name", "type": "VARCHAR"}
        ]

        result = self.db_manager.get_table_schema('test_table')

        # Verificar que el resultado contiene la información esperada
        assert "{'table': 'test_table', 'description': 'Definición de la tabla test_table.', 'fields': [{'name': 'id', 'type': 'INTEGER'}, {'name': 'name', 'type': 'VARCHAR'}]}" == result.strip()

    def test_get_table_schema_table_not_exists(self):
        """Prueba get_table_schema cuando la tabla no existe"""
        self.mock_inspect.return_value.get_table_names.return_value = []

        with pytest.raises(RuntimeError) as exc_info:
            self.db_manager.get_table_schema('non_existent_table')

        assert "Table 'non_existent_table' does not exist." in str(exc_info.value)
