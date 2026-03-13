# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from flask import Flask
from iatoolkit.views.user_feedback_api_view import UserFeedbackApiView
from iatoolkit.services.user_feedback_service import UserFeedbackService
from iatoolkit.services.auth_service import AuthService


class TestUserFeedbackView:
    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.feedback_service = MagicMock(spec=UserFeedbackService)
        self.mock_auth = MagicMock(spec=AuthService)

        # Mock a successful authentication by default for most tests
        self.mock_auth.verify_for_company.return_value = {"success": True,
                                              'user_identifier': 'an_user'}

        # Register the view with mocked dependencies
        feedback_view = UserFeedbackApiView.as_view("feedback",
                                                     user_feedback_service=self.feedback_service,
                                                     auth_service=self.mock_auth)
        self.app.add_url_rule('/<company_short_name>/api/feedback',
                              view_func=feedback_view,
                              methods=["POST"])
        self.url = '/my_company/api/feedback'

    def test_post_when_auth_error(self):
        """Test that an auth error returns a 401 status."""
        self.mock_auth.verify_for_company.return_value = {"success": False,
                                              'error_message': 'error in authentication',
                                              'status_code': 401}
        response = self.client.post(self.url, json={'message': 'any', 'rating': 1})

        assert response.status_code == 401
        assert response.json["error_message"] == 'error in authentication'
        self.feedback_service.new_feedback.assert_not_called()


    def test_post_when_service_raises_exception(self):
        """Test that a 500 is returned if the service throws an unexpected exception."""
        self.feedback_service.new_feedback.side_effect = Exception('Database connection failed')

        response = self.client.post(self.url, json={'message': 'feedback message', 'rating': 4})

        assert response.status_code == 500
        assert 'Database connection failed' in response.json['error_message']

    def test_post_when_service_returns_error(self):
        """Test that a 402 is returned if the service reports a business logic error."""
        self.feedback_service.new_feedback.return_value = {'error': 'Company has no credits'}

        response = self.client.post(self.url, json={'message': 'feedback message', 'rating': 3})

        # Assuming 402 is used for business logic failures (like payment required)
        assert response.status_code == 402
        assert response.json == {'error_message': 'Company has no credits'}

    def test_post_when_ok(self):
        """Test the successful path, returning a 200 status."""
        self.feedback_service.new_feedback.return_value = {'message': "Feedback guardado correctamente"}

        response = self.client.post(self.url, json={'message': 'feedback message', 'rating': 5})

        assert response.status_code == 200
        assert response.json == {'message': "Feedback guardado correctamente"}

    def test_post_calls_service_with_correct_parameters(self):
        """
        Crucial Test: Verify the service is called with the correct, refactored signature,
        ignoring extra parameters from the JSON body if any.
        """
        self.feedback_service.new_feedback.return_value = {'message': "Feedback guardado correctamente"}

        # Payload now only needs message and rating.
        # We can even include old params to ensure they are ignored.
        test_data = {
            'message': 'test feedback message',
            'rating': 4,
            'type': 'this_is_also_obsolete'  # This should also be ignored
        }

        response = self.client.post(self.url, json=test_data)
        assert response.status_code == 200

        # Verify the service was called with the NEW, simpler signature
        self.feedback_service.new_feedback.assert_called_once_with(
            company_short_name='my_company',
            message='test feedback message',
            user_identifier='an_user',
            rating=4
        )
