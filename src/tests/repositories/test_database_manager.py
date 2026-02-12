# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import patch, MagicMock
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.interfaces.database_provider import DatabaseProvider
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

    def test_implements_interface(self):
        """Verify that DatabaseManager implements DatabaseProvider"""
        assert isinstance(self.db_manager, DatabaseProvider)

    def test_get_session_returns_scoped_session(self):
        session = self.db_manager.get_session()
        assert session == self.mock_scoped_session

    def test_create_all_calls_metadata_create_all(self):
        self.db_manager.create_all()
        assert self.mock_base_metadata.create_all.call_count == 1

    def test_drop_all_calls_metadata_drop_all(self):
        self.db_manager.drop_all()
        self.mock_base_metadata.drop_all.assert_called_once_with(self.mock_engine)

    def test_remove_session_calls_scoped_session_remove(self):
        self.db_manager.remove_session()
        self.mock_scoped_session.remove.assert_called_once()
    # --- Tests for Execution Methods (New Interface) ---

    def test_execute_query_returns_rows_as_dict(self):
        """
        GIVEN a SELECT query
        WHEN execute_query is called
        THEN it should return a list of dictionaries.
        """
        # Arrange
        mock_session = self.mock_scoped_session
        mock_result = mock_session.execute.return_value
        mock_result.returns_rows = True
        mock_result.keys.return_value = ['id', 'val']
        mock_result.fetchall.return_value = [(1, 'a'), (2, 'b')]

        # Act
        result = self.db_manager.execute_query(query="SELECT * FROM t")

        # Assert
        assert result == [{'id': 1, 'val': 'a'}, {'id': 2, 'val': 'b'}]
        assert mock_session.execute.call_count >= 1

    def test_execute_query_no_rows_returns_rowcount(self):
        """
        GIVEN an UPDATE/DELETE query
        WHEN execute_query is called
        THEN it should return {'rowcount': N}.
        """
        # Arrange
        mock_session = self.mock_scoped_session
        mock_result = mock_session.execute.return_value
        mock_result.returns_rows = False
        mock_result.rowcount = 5

        # Act
        result = self.db_manager.execute_query(query="UPDATE t SET val='x'")

        # Assert
        assert result == {'rowcount': 5}

    def test_execute_query_with_commit(self):
        """
        GIVEN commit=True
        WHEN execute_query is called
        THEN it should call session.commit().
        """
        mock_session = self.mock_scoped_session
        mock_result = mock_session.execute.return_value
        mock_result.returns_rows = False

        self.db_manager.execute_query(query="INSERT INTO ...", commit=True)

        mock_session.commit.assert_called_once()

    def test_commit_and_rollback(self):
        """Test wrapper methods"""
        mock_session = self.mock_scoped_session

        self.db_manager.commit()
        mock_session.commit.assert_called()

        self.db_manager.rollback()
        mock_session.rollback.assert_called()

        # --- Tests for Schema Methods ---

        def test_get_database_structure_success(self):
            """
            GIVEN a database with tables
            WHEN get_database_structure is called
            THEN it should return the correct dictionary structure.
            """
            # Arrange
            # Configure the inspector instance (returned by calling inspect())
            inspector_mock = self.mock_inspect.return_value
            inspector_mock.get_table_names.return_value = ['users', 'orders']

            # Mock columns for 'users'
            inspector_mock.get_columns.side_effect = [
                [
                    {'name': 'id', 'type': 'INTEGER', 'nullable': False},
                    {'name': 'name', 'type': 'VARCHAR', 'nullable': True}
                ],
                [
                    {'name': 'id', 'type': 'INTEGER', 'nullable': False},
                    {'name': 'user_id', 'type': 'INTEGER', 'nullable': False}
                ]
            ]

            # Mock PKs
            inspector_mock.get_pk_constraint.side_effect = [
                {'constrained_columns': ['id']},  # users PK
                {'constrained_columns': ['id']}  # orders PK
            ]

            # Act
            structure = self.db_manager.get_database_structure()

            # Assert
            assert 'users' in structure
            assert 'orders' in structure

            # Check users structure
            users_cols = structure['users']['columns']
            assert len(users_cols) == 2
            assert users_cols[0]['name'] == 'id'
            assert users_cols[0]['pk'] is True
            assert users_cols[0]['nullable'] is False
            assert users_cols[1]['name'] == 'name'
            assert users_cols[1]['pk'] is False

            # Verify inspect calls
            inspector_mock.get_table_names.assert_called_with(schema='public')
            assert inspector_mock.get_columns.call_count == 2

        def test_get_database_structure_handles_introspection_error(self):
            """
            GIVEN an error occurs during column introspection for a table
            WHEN get_database_structure is called
            THEN it should log the error and return partial structure (empty columns for that table).
            """
            # Arrange
            inspector_mock = self.mock_inspect.return_value
            inspector_mock.get_table_names.return_value = ['broken_table']
            inspector_mock.get_columns.side_effect = Exception("DB Error")

            with patch('iatoolkit.repositories.database_manager.logging') as mock_logging:
                # Act
                structure = self.db_manager.get_database_structure()

                # Assert
                assert 'broken_table' in structure
                assert structure['broken_table']['columns'] == []  # Should be empty list on error

                # Check that warning was logged
                mock_logging.warning.assert_called_once()
                assert "Could not inspect columns" in mock_logging.warning.call_args[0][0]
