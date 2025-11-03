# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock, ANY
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.user_feedback_service import UserFeedbackService
from iatoolkit.repositories.models import Company, UserFeedback
from iatoolkit.infra.google_chat_app import GoogleChatApp
from iatoolkit.infra.mail_app import MailApp


class TestUserFeedbackService:
    def setup_method(self):
        """Set up a fresh service instance and mocks for each test."""
        self.profile_repo = MagicMock(ProfileRepo)
        self.google_chat_app = MagicMock(GoogleChatApp)
        self.mail_app = MagicMock(MailApp)

        # Init the service with all required mocks
        self.service = UserFeedbackService(
            profile_repo=self.profile_repo,
            google_chat_app=self.google_chat_app,
            mail_app=self.mail_app
        )

        # A base company object; params can be overridden in each test
        self.company = Company(
            id=1,
            name='My Company',
            short_name='my_company',
            parameters={}  # Start with no feedback config
        )

        # Mock the repo to return our test company
        self.profile_repo.get_company_by_short_name.return_value = self.company
        # Mock a successful feedback save by default
        self.profile_repo.save_feedback.return_value = UserFeedback(id=123)

    def test_new_feedback_saves_correctly(self):
        """Test that feedback is saved with the correct data."""
        response = self.service.new_feedback(
            company_short_name='my_company',
            message='A test message',
            user_identifier='test_user',
            rating=5
        )

        assert response == {'success': True, 'message': 'Feedback guardado correctamente'}
        self.profile_repo.save_feedback.assert_called_once()
        saved_feedback_arg = self.profile_repo.save_feedback.call_args[0][0]
        assert isinstance(saved_feedback_arg, UserFeedback)
        assert saved_feedback_arg.company_id == self.company.id
        assert saved_feedback_arg.message == 'A test message'
        assert saved_feedback_arg.user_identifier == 'test_user'
        assert saved_feedback_arg.rating == 5

    def test_sends_google_chat_notification_on_correct_config(self):
        """Test that a Google Chat notification is sent when configured."""
        self.company.parameters = {
            'user_feedback': {
                'channel': 'google_chat',
                'destination': 'spaces/test-space'
            }
        }

        self.service.new_feedback(
            company_short_name='my_company',
            message='A message for Google Chat',
            user_identifier='chat_user',
            rating=4
        )

        self.google_chat_app.send_message.assert_called_once()
        call_args = self.google_chat_app.send_message.call_args[1]['message_data']
        assert call_args['space']['name'] == 'spaces/test-space'
        assert '*Nuevo feedback de my_company*' in call_args['message']['text']
        assert '*Usuario:* chat_user' in call_args['message']['text']
        assert '*Mensaje:* A message for Google Chat' in call_args['message']['text']
        assert '*Calificación:* 4' in call_args['message']['text']
        self.mail_app.send_email.assert_not_called()

    def test_sends_email_notification_on_correct_config(self):
        """Test that an email notification is sent when configured for 'rmail'."""
        self.company.parameters = {
            'user_feedback': {
                'channel': 'email',
                'destination': 'test@example.com'
            }
        }

        self.service.new_feedback(
            company_short_name='my_company',
            message='A message for email',
            user_identifier='email_user',
            rating=3
        )

        self.mail_app.send_email.assert_called_once_with(
            to='test@example.com',
            subject='Nuevo Feedback de my_company',
            body=ANY  # Check body content separately if needed
        )
        call_body = self.mail_app.send_email.call_args[1]['body']
        assert 'Nuevo feedback de my_company' in call_body
        assert 'Usuario:* email_user' in call_body
        assert 'Mensaje:* A message for email' in call_body
        assert 'Calificación:* 3' in call_body
        self.google_chat_app.send_message.assert_not_called()

    def test_no_notification_if_config_is_missing(self):
        """Test that no notification is sent if 'user_feedback' config is absent."""
        self.company.parameters = {}  # Explicitly no config

        self.service.new_feedback(
            company_short_name='my_company',
            message='No notification message',
            user_identifier='no_config_user',
            rating=5
        )

        self.google_chat_app.send_message.assert_not_called()
        self.mail_app.send_email.assert_not_called()

    def test_no_notification_if_config_is_incomplete(self):
        """Test that no notification is sent if 'channel' or 'destination' is missing."""
        # Case 1: Missing destination
        self.company.parameters = {'user_feedback': {'channel': 'google_chat'}}
        self.service.new_feedback('my_company', 'msg', 'user', 1)

        # Case 2: Missing channel
        self.company.parameters = {'user_feedback': {'destination': 'test@example.com'}}
        self.service.new_feedback('my_company', 'msg', 'user', 1)

        self.google_chat_app.send_message.assert_not_called()
        self.mail_app.send_email.assert_not_called()

    def test_notification_failure_does_not_prevent_saving_feedback(self):
        """Test that if a notification fails (e.g., raises an exception), feedback is still saved."""
        self.company.parameters = {
            'user_feedback': {
                'channel': 'google_chat',
                'destination': 'spaces/failing-space'
            }
        }
        self.google_chat_app.send_message.side_effect = Exception("Network Error")

        response = self.service.new_feedback(
            company_short_name='my_company',
            message='A message',
            user_identifier='a_user',
            rating=5
        )

        # The notification was attempted
        self.google_chat_app.send_message.assert_called_once()
        # But the feedback was still saved and the operation succeeded
        self.profile_repo.save_feedback.assert_called_once()

    def test_feedback_when_company_not_exist(self):
        """Test error handling when the company does not exist."""
        self.profile_repo.get_company_by_short_name.return_value = None
        response = self.service.new_feedback(
            company_short_name='unknown_company',
            message='any',
            user_identifier='any',
            rating=5
        )
        assert response == {'error': 'No existe la empresa: unknown_company'}

    def test_feedback_when_error_saving_in_database(self):
        """Test error handling when saving to the database fails."""
        self.profile_repo.save_feedback.return_value = None
        response = self.service.new_feedback(
            company_short_name='my_company',
            message='any',
            user_identifier='any',
            rating=2
        )
        assert response == {'error': 'No se pudo guardar el feedback'}