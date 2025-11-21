# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import unittest
from unittest.mock import patch
from flask import Flask
from iatoolkit.common.session_manager import SessionManager


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        """
        Configura los patches y mocks comunes para las pruebas.
        """
        # Crear un contexto de aplicación y de solicitud de Flask
        self.app = Flask(__name__)
        self.app.secret_key = "super-secret"  # Necesario para el manejo de sesiones
        self.ctx = self.app.test_request_context()
        self.ctx.push()

        # Parchear el objeto 'session' como un diccionario en todos los tests
        self.session_patcher = patch("iatoolkit.common.session_manager.session", new_callable=dict)
        self.mock_session = self.session_patcher.start()  # Iniciar el patch y obtener el mock

    def tearDown(self):
        """
        Detiene todos los patches después de cada prueba.
        """
        patch.stopall()
        self.ctx.pop()

    def test_set(self):
        """Prueba que el método set almacena un valor en la sesión."""
        SessionManager.set("key", "value")
        self.assertEqual(self.mock_session["key"], "value")

    def test_get_existing_key(self):
        """Prueba que el método get devuelve el valor correcto si la clave existe."""
        self.mock_session["key"] = "value"
        result = SessionManager.get("key")
        self.assertEqual(result, "value")

    def test_get_non_existing_key_with_default(self):
        """Prueba que el método get devuelve el valor predeterminado si la clave no existe."""
        result = SessionManager.get("non_existing_key", default="default_value")
        self.assertEqual(result, "default_value")

    def test_remove_existing_key(self):
        """Prueba que el método remove elimina correctamente una clave existente."""
        self.mock_session["key"] = "value"
        SessionManager.remove("key")
        self.assertNotIn("key", self.mock_session)

    def test_remove_non_existing_key(self):
        """Prueba que el método remove no lanza errores si la clave no existe."""
        SessionManager.remove("non_existing_key")
        # No debería hacer nada, y la sesión debe permanecer vacía
        self.assertEqual(len(self.mock_session), 0)

    def test_clear(self):
        """Prueba que el método clear elimina todos los elementos de la sesión."""
        self.mock_session.update({"key1": "value1", "key2": "value2"})
        SessionManager.clear()
        self.assertEqual(len(self.mock_session), 0)
