# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from flask import Flask
from unittest.mock import patch


class TestRoutes:
    def setup_method(self):
        # Configurar la aplicación Flask para pruebas
        self.app = Flask(__name__)
        self.app.config['VERSION'] = "1.0.0"
        self.app.secret_key = 'test_secret'

        # Concentramos todos los mocks y patches aquí:

        # Patch para el SessionManager (por ejemplo para evitar lecturas de sesión reales)
        self.session_manager_patch = patch("common.routes.SessionManager")
        self.mock_session_manager = self.session_manager_patch.start()
        # Para este ejemplo, no es necesario configurar un return_value, pero se podría definir según se requiera

        # Patch para la función flash, reemplazándola para que no intente enviar mensajes reales
        self.flash_patch = patch("common.routes.flash")
        self.mock_flash = self.flash_patch.start()

        # Patch para render_template, que es usado por la ruta "/about" y otros
        self.render_template_patch = patch("common.routes.render_template", return_value="<html>About</html>")
        self.mock_render_template = self.render_template_patch.start()

        # Registrar las rutas en la aplicación
        from common.routes import register_routes
        register_routes(self.app)

        # Crear el cliente de pruebas
        self.client = self.app.test_client()

    def teardown_method(self, method):
        patch.stopall()


