# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask
from unittest.mock import MagicMock, patch
from services.profile_service import ProfileService
from repositories.models import Company
from views.chat_view import ChatView
from common.session_manager import SessionManager
from datetime import datetime, timezone
from common.auth import IAuthentication
from services.prompt_manager_service import PromptService


class TestChatView:
    @staticmethod
    def create_app():
        """Configura la aplicación Flask para pruebas."""
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura el cliente y los mocks antes de cada test."""
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.profile_service = MagicMock(spec=ProfileService)
        self.iauthentication = MagicMock(spec=IAuthentication)
        self.prompt_service = MagicMock(spec=PromptService)

        self.iauthentication.verify.return_value = {
            'success': True,
            'company_id': 101,
            'external_user_id': 'test_user_id'
        }

        @self.app.route('/login')
        def login():
            return "Login Page", 200

        self.test_company = Company(
            id=1,
            name="Empresa de Prueba",
            short_name="test_company",
            logo_file="test_logo.png"
        )
        self.profile_service.get_company_by_short_name.return_value = self.test_company

        # Registrar la vista
        view = ChatView.as_view("chat",
                                profile_service=self.profile_service,
                                iauthentication=self.iauthentication,
                                prompt_service=self.prompt_service,
                                )
        self.app.add_url_rule("/<company_short_name>/chat", view_func=view, methods=["GET"])

        # Mock values
        mock_values = {
            'user': {'id': 1, 'username': 'test_user'},
            'user_id': 1,
            'company_id': 100,
            'company_short_name': 'test_company',
            'last_activity': datetime.now(timezone.utc).timestamp()
        }

        # Mockear SessionManager.get
        mock_session_manager = MagicMock(spec=SessionManager)  # <- Mock de la clase
        mock_session_manager.get.side_effect = lambda key, default=None: mock_values.get(key, default)

        with patch('common.auth.SessionManager', new=mock_session_manager):  # <-  Aplicar el mock
            with self.app.test_request_context():  # Necesario para Flask
                yield

    def test_get_missing_auth(self):
        self.iauthentication.verify.return_value = {'error_message': 'error in authentication'}
        response = self.client.get("/test_company/chat")
        assert response.status_code == 401

    @patch("views.chat_view.render_template")
    def test_get_invalid_company(self, mock_render):
        self.profile_service.get_company_by_short_name.return_value = None
        response = self.client.get("/test_company/chat")
        assert response.status_code == 404


    @patch("views.chat_view.render_template")
    def test_get_chat(self, mock_render_template):
        mock_render_template.return_value = "<html><body><h1>Home Page</h1></body></html>"
        response = self.client.get("/test_company/chat")

        # Asegúrate de que se llame a render_template correctamente
        mock_render_template.assert_called_once()
        assert response.status_code == 200
        assert b"<h1>Home Page</h1>" in response.data
