# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch, MagicMock
from iatoolkit.repositories.database_manager import DatabaseManager


class TestDatabaseManager(unittest.TestCase):

    @patch('iatoolkit.repositories.database_manager.create_engine')
    @patch('iatoolkit.repositories.database_manager.sessionmaker')
    @patch('iatoolkit.repositories.database_manager.scoped_session')
    def setUp(self, mock_scoped_session, mock_sessionmaker, mock_create_engine):
        """Configura mocks para las dependencias principales de DatabaseManager."""
        # Mock del motor y las sesiones
        self.mock_engine = MagicMock()
        mock_create_engine.return_value = self.mock_engine

        self.mock_sessionmaker = MagicMock()
        mock_sessionmaker.return_value = self.mock_sessionmaker

        self.mock_scoped_session = MagicMock()
        mock_scoped_session.return_value = self.mock_scoped_session

        # Instanciar el DatabaseManager con un mock de URL de base de datos
        self.db_manager = DatabaseManager("sqlite:///:memory:")

        # Verificaciones iniciales
        mock_create_engine.assert_called_once()
        mock_sessionmaker.assert_called_once()
        mock_scoped_session.assert_called_once_with(self.mock_sessionmaker)

    def test_get_session(self):
        """Prueba que get_session devuelve una nueva sesión."""
        session = self.db_manager.get_session()
        self.mock_scoped_session.assert_called_once()
        self.assertEqual(session, self.mock_scoped_session())

    @patch('iatoolkit.repositories.database_manager.Base.metadata.create_all')
    def test_create_all(self, mock_create_all):
        """Prueba que create_all crea las tablas usando la metadata de Base."""
        self.db_manager.create_all()
        mock_create_all.assert_called_once_with(self.mock_engine)

    @patch('iatoolkit.repositories.database_manager.Base.metadata.drop_all')
    def test_drop_all(self, mock_drop_all):
        """Prueba que drop_all elimina las tablas usando la metadata de Base."""
        self.db_manager.drop_all()
        mock_drop_all.assert_called_once_with(self.mock_engine)

    def test_remove_session(self):
        """Prueba que remove_session limpia la sesión actual."""
        self.db_manager.remove_session()
        self.mock_scoped_session.remove.assert_called_once()


