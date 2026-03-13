import pytest
from flask import Flask
from unittest.mock import MagicMock
from iatoolkit.views.users_api_view import UsersApiView
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService

class TestUsersApiView:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.client = self.app.test_client()

        self.mock_auth_service = MagicMock(spec=AuthService)
        self.mock_profile_service = MagicMock(spec=ProfileService)

        view_func = UsersApiView.as_view(
            "company-users",
            auth_service=self.mock_auth_service,
            profile_service=self.mock_profile_service
        )
        self.app.add_url_rule('/<company_short_name>/api/company-users', view_func=view_func, methods=['GET'])
        self.url = '/acme/api/company-users'

    def test_get_users_success(self):
        # Arrange
        self.mock_auth_service.verify_for_company.return_value = {"success": True}

        expected_users = [
            {"email": "a@a.com", "role": "admin"},
            {"email": "b@b.com", "role": "user"}
        ]
        self.mock_profile_service.get_company_users.return_value = expected_users

        # Act
        resp = self.client.get(self.url)

        # Assert
        assert resp.status_code == 200
        assert resp.json == expected_users
        self.mock_profile_service.get_company_users.assert_called_once_with('acme')

    def test_get_users_auth_failure(self):
        # Arrange
        self.mock_auth_service.verify_for_company.return_value = {"success": False, "status_code": 401}

        # Act
        resp = self.client.get(self.url)

        # Assert
        assert resp.status_code == 401
        self.mock_profile_service.get_company_users.assert_not_called()

    def test_get_users_exception_handling(self):
        # Arrange
        self.mock_auth_service.verify_for_company.return_value = {"success": True}
        self.mock_profile_service.get_company_users.side_effect = Exception("DB Error")

        # Act
        resp = self.client.get(self.url)

        # Assert
        assert resp.status_code == 500
        assert "Unexpected error" in resp.json['error']
