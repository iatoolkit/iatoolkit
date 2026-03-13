import pytest
from flask import Flask
from unittest.mock import MagicMock

from iatoolkit.views.connectors_api_view import ConnectorsApiView
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService


class TestConnectorsApiView:
    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()

        self.configuration_service = MagicMock(spec=ConfigurationService)
        self.profile_service = MagicMock(spec=ProfileService)
        self.auth_service = MagicMock(spec=AuthService)

        self.company_short_name = "test_company"
        self.base_url = f"/{self.company_short_name}/api/connectors"

        # Default: auth OK + company exists
        self.auth_service.verify_for_company.return_value = {"success": True}
        self.profile_service.get_company_by_short_name.return_value = MagicMock()

        connectors_view = ConnectorsApiView.as_view(
            "connectors",
            configuration_service=self.configuration_service,
            profile_service=self.profile_service,
            auth_service=self.auth_service,
        )

        self.app.add_url_rule(
            "/<company_short_name>/api/connectors",
            view_func=connectors_view,
            methods=["GET"],
        )

    def test_get_connectors_auth_error(self):
        self.auth_service.verify_for_company.return_value = {
            "success": False,
            "error_message": "Authentication token is invalid",
            "status_code": 401,
        }

        response = self.client.get(self.base_url)

        assert response.status_code == 401
        assert response.json["error_message"] == "Authentication token is invalid"
        self.configuration_service.get_configuration.assert_not_called()

    def test_get_connectors_company_not_found(self):
        self.profile_service.get_company_by_short_name.return_value = None

        response = self.client.get(self.base_url)

        assert response.status_code == 404
        assert response.json["error"] == "company not found."
        self.configuration_service.get_configuration.assert_not_called()

    def test_get_connectors_empty_when_missing_block(self):
        self.configuration_service.get_configuration.return_value = None

        response = self.client.get(self.base_url)

        assert response.status_code == 200
        assert response.json == {"connectors": []}
        self.configuration_service.get_configuration.assert_called_once_with(self.company_short_name, "connectors")

    def test_get_connectors_success_sorted_and_filtered(self):
        self.configuration_service.get_configuration.return_value = {
            "zeta": {"type": "s3"},
            "alpha": {"type": "gcs"},
            "broken": "not-a-dict",
            "beta": {"type": "s3"},
        }

        response = self.client.get(self.base_url)

        assert response.status_code == 200
        assert response.json == {
            "connectors": [
                {"name": "alpha", "type": "gcs"},
                {"name": "beta", "type": "s3"},
                {"name": "zeta", "type": "s3"},
            ]
        }

        self.configuration_service.get_configuration.assert_called_once_with(self.company_short_name, "connectors")
        self.profile_service.get_company_by_short_name.assert_called_once_with(self.company_short_name)
        self.auth_service.verify_for_company.assert_called_once_with(self.company_short_name, anonymous=True)

    def test_get_connectors_returns_500_on_unexpected_error(self):
        self.configuration_service.get_configuration.side_effect = Exception("Boom")

        response = self.client.get(self.base_url)

        assert response.status_code == 500
        assert response.json["status"] == "error"
        assert "Boom" in response.json["message"]
