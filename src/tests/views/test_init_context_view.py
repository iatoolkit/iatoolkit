import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from iatoolkit.views.init_context_view import InitContextView
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.common.auth import IAuthentication
from iatoolkit.services.user_session_context_service import UserSessionContextService

# --- Constantes para los Tests ---
MOCK_COMPANY_SHORT_NAME = "test-comp"
MOCK_EXTERNAL_USER_ID = "ext-user-123"
MOCK_LOCAL_USER_ID = 456


class TestInitContextView:
    """
    Pruebas para la vista InitContextView, que fuerza la reconstrucción del contexto.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura un entorno de prueba limpio antes de cada test."""
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        # Mocks para los servicios inyectados
        self.mock_iauthentication = MagicMock(spec=IAuthentication)
        self.mock_query_service = MagicMock(spec=QueryService)
        self.mock_profile_service = MagicMock(spec=ProfileService)

        # --- CORRECCIÓN: Crear un mock para session_context y adjuntarlo a query_service ---
        self.mock_session_context = MagicMock(spec=UserSessionContextService)
        self.mock_query_service.session_context = self.mock_session_context

        # Configuración común de mocks
        self.mock_iauthentication.verify.return_value = {"success": True}

        # Registrar la vista con las dependencias correctas
        view_func = InitContextView.as_view(
            'init_context',
            iauthentication=self.mock_iauthentication,
            query_service=self.mock_query_service,
            profile_service=self.mock_profile_service
        )
        self.app.add_url_rule('/<company_short_name>/init-context', view_func=view_func, methods=['GET'])

    def test_rebuild_for_local_user_from_webapp(self):
        """
        Prueba el flujo de un usuario LOCAL logueado que hace clic en el botón de recarga.
        """
        # Arrange
        self.mock_profile_service.get_current_user_profile.return_value = {'id': MOCK_LOCAL_USER_ID}

        with patch('iatoolkit.views.init_context_view.render_template') as mock_render:
            mock_render.return_value = "<html>Success Page</html>"

            # Act
            response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/init-context?source=webapp')

        # Assert
        assert response.status_code == 200
        self.mock_iauthentication.verify.assert_not_called()

        # --- CORRECCIÓN: La aserción ahora apunta al mock correcto ---
        self.mock_query_service.session_context.clear_all_context.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                                          str(MOCK_LOCAL_USER_ID))

        self.mock_query_service.prepare_context.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            external_user_id=None,
            local_user_id=MOCK_LOCAL_USER_ID
        )
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME,
            external_user_id=None,
            local_user_id=MOCK_LOCAL_USER_ID
        )
        mock_render.assert_called_once_with('context_reloaded.html',
                                            message="El contexto ha sido recargado exitosamente.")

    def test_rebuild_for_external_user_from_webapp(self):
        """
        Prueba el flujo de un usuario EXTERNO logueado que hace clic en el botón de recarga.
        """
        # Arrange
        self.mock_profile_service.get_current_user_profile.return_value = {}

        with patch('iatoolkit.views.init_context_view.render_template') as mock_render:
            mock_render.return_value = "<html>Success Page</html>"

            # Act
            response = self.client.get(
                f'/{MOCK_COMPANY_SHORT_NAME}/init-context?source=webapp&external_user_id={MOCK_EXTERNAL_USER_ID}')

        # Assert
        assert response.status_code == 200
        self.mock_query_service.session_context.clear_all_context.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                                          MOCK_EXTERNAL_USER_ID)
        self.mock_query_service.prepare_context.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, external_user_id=MOCK_EXTERNAL_USER_ID, local_user_id=None
        )
        self.mock_query_service.finalize_context_rebuild.assert_called_once_with(
            company_short_name=MOCK_COMPANY_SHORT_NAME, external_user_id=MOCK_EXTERNAL_USER_ID, local_user_id=None
        )
        mock_render.assert_called_once_with('context_reloaded.html',
                                            message="El contexto ha sido recargado exitosamente.")

    def test_rebuild_for_external_user_from_api(self):
        """
        Prueba el flujo de una llamada de API pura para un usuario externo.
        """
        # Arrange
        self.mock_profile_service.get_current_user_profile.return_value = {}

        # Act
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/init-context?external_user_id={MOCK_EXTERNAL_USER_ID}')

        # Assert
        assert response.status_code == 200
        assert response.json == {'status': 'OK'}
        self.mock_iauthentication.verify.assert_called_once_with(MOCK_COMPANY_SHORT_NAME)
        self.mock_query_service.session_context.clear_all_context.assert_called_once_with(MOCK_COMPANY_SHORT_NAME,
                                                                                          MOCK_EXTERNAL_USER_ID)
        self.mock_query_service.prepare_context.assert_called_once()
        self.mock_query_service.finalize_context_rebuild.assert_called_once()

    def test_rebuild_fails_if_no_user_identified(self):
        """
        Prueba que la vista devuelve un error 400 si no se puede identificar al usuario.
        """
        # Arrange
        self.mock_profile_service.get_current_user_profile.return_value = {}

        # Act
        response = self.client.get(f'/{MOCK_COMPANY_SHORT_NAME}/init-context')

        # Assert
        assert response.status_code == 400
        assert "No se pudo identificar al usuario" in response.json['error']
        self.mock_query_service.prepare_context.assert_not_called()