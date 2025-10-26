import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
import os

from iatoolkit.views.login_simulation_view import LoginSimulationView
from iatoolkit.services.profile_service import ProfileService


class TestLoginSimulationView:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura una aplicación Flask mínima y los mocks necesarios para cada prueba."""
        self.app = Flask(__name__)
        self.client = self.app.test_client()

        # 1. Mock del servicio que la vista necesita
        self.profile_service = MagicMock(spec=ProfileService)

        # --- INICIO DE LA SOLUCIÓN ---
        # 2. Creamos la función de la vista, inyectando nuestro mock directamente.
        # El nombre del argumento (profile_service) debe coincidir con el del __init__ de la vista.
        view_func = LoginSimulationView.as_view(
            'login_simulation',
            profile_service=self.profile_service
        )

        # 3. Registramos la vista ya configurada en la aplicación de prueba.
        self.app.add_url_rule(
            "/simulation/<string:company_short_name>",
            view_func=view_func
        )
        # --- FIN DE LA SOLUCIÓN ---

    @patch("iatoolkit.views.login_simulation_view.render_template")
    @patch.dict(os.environ, {"IATOOLKIT_API_KEY": "test-api-key"})
    def test_get_renders_simulation_template_with_correct_context(self, mock_render_template):
        """
        Prueba que una petición GET a la vista renderice la plantilla 'login_simulation.html'
        con el company_short_name y la api_key correctos en el contexto.
        """
        # Configurar el mock para que devuelva un HTML simple
        mock_render_template.return_value = "<html>Renderizado OK</html>"

        company = "acme_corp"

        # Ejecutar la petición a la vista
        response = self.client.get(f'/simulation/{company}')

        # Verificar que la respuesta es exitosa
        assert response.status_code == 200
        assert response.data == b"<html>Renderizado OK</html>"

        # La aserción más importante: verificar que render_template fue llamado
        # una vez y con los argumentos exactos que esperamos.
        mock_render_template.assert_called_once_with(
            'login_simulation.html',
            company_short_name=company,
            api_key='test-api-key'
        )
