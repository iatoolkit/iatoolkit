# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.user_feedback_service import UserFeedbackService
from iatoolkit.repositories.models import Company, UserFeedback
from iatoolkit.infra.google_chat_app import GoogleChatApp


class TestUserFeedbackService:
    def setup_method(self):
        self.profile_repo = MagicMock(ProfileRepo)
        self.google_chat_app = MagicMock(GoogleChatApp)

        # init the service with the mocks
        self.service = UserFeedbackService(
            profile_repo=self.profile_repo,
            google_chat_app=self.google_chat_app
        )

        self.company = Company(name='my company', short_name='test_company')

        self.profile_repo.get_company_by_short_name.return_value = self.company

        self.user_feedback = UserFeedback(
                    company_id=self.company.id,
                    message='feedback message for testing',
                    user_identifier='flibedinsky',
                    rating=4)

        # Mock successful Google Chat response
        self.google_chat_app.send_message.return_value = {
            'success': True,
            'message': 'Mensaje enviado correctamente'
        }

    def test_feedback_when_exception(self):
        self.profile_repo.get_company_by_short_name.side_effect = Exception('an error')
        response = self.service.new_feedback(
                        company_short_name='my_company',
                        message='feedback message for testing',
                        user_identifier='flibedinsky',
                        space='spaces/test-space',
                        type='MESSAGE_TRIGGER',
                        rating=3
                        )

        assert 'an error' == response['error']

    def test_feedback_when_company_not_exist(self):
        self.profile_repo.get_company_by_short_name.return_value = None
        response = self.service.new_feedback(
                        company_short_name='my_company',
                        message='feedback message for testing',
                        user_identifier='flibedinsky',
                        space='spaces/test-space',
                        type='MESSAGE_TRIGGER',
                        rating=5
                        )

        assert 'No existe la empresa: my_company' == response['error']

    def test_feedback_when_error_saving_in_database(self):
        self.profile_repo.save_feedback.return_value = None
        response = self.service.new_feedback(
                        company_short_name='my_company',
                        message='feedback message for testing',
                        user_identifier='flibedinsky',
                        space='spaces/test-space',
                        type='MESSAGE_TRIGGER',
                        rating=2
                        )

        assert 'No se pudo guardar el feedback' == response['error']

    def test_feedback_when_ok(self):
        self.profile_repo.save_feedback.return_value = UserFeedback
        response = self.service.new_feedback(
                        company_short_name='my_company',
                        message='feedback message for testing',
                        user_identifier='flibedinsky',
                        space='spaces/test-space',
                        type='MESSAGE_TRIGGER',
                        rating=4
                        )

        assert 'Feedback guardado correctamente' == response['message']

    # Nuevos tests para Google Chat
    def test_feedback_sends_google_chat_notification_success(self):
        """Test that Google Chat notification is sent successfully"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        response = self.service.new_feedback(
            company_short_name='my_company',
            message='feedback message for testing',
            user_identifier='flibedinsky',
            space='spaces/AAQAupQldd4',
            type='MESSAGE_TRIGGER',
            rating=5
        )

        # Verify Google Chat was called
        self.google_chat_app.send_message.assert_called_once()

        # Verify the call arguments
        call_args = self.google_chat_app.send_message.call_args[1]['message_data']
        assert call_args['type'] == 'MESSAGE_TRIGGER'
        assert call_args['space']['name'] == 'spaces/AAQAupQldd4'
        assert '*Nuevo feedback de my_company*' in call_args['message']['text']
        assert '*Usuario:* flibedinsky' in call_args['message']['text']
        assert '*Mensaje:* feedback message for testing' in call_args['message']['text']
        assert '*Calificación:* 5' in call_args['message']['text']

        # Verify feedback was still saved successfully
        assert 'Feedback guardado correctamente' == response['message']

    def test_feedback_google_chat_notification_failure_does_not_affect_save(self):
        """Test that Google Chat failure doesn't prevent feedback from being saved"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        # Mock Google Chat failure
        self.google_chat_app.send_message.return_value = {
            'success': False,
            'message': 'Error al enviar mensaje'
        }

        response = self.service.new_feedback(
            company_short_name='my_company',
            message='feedback message for testing',
            user_identifier='flibedinsky',
            space='spaces/AAQAupQldd4',
            type='MESSAGE_TRIGGER',
            rating=1
        )

        # Verify Google Chat was called
        self.google_chat_app.send_message.assert_called_once()

        # Verify feedback was still saved successfully despite Google Chat failure
        assert 'Feedback guardado correctamente' == response['message']

    def test_feedback_google_chat_exception_returns_error(self):
        """Test that Google Chat exception returns an error response"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        # Mock Google Chat exception
        self.google_chat_app.send_message.side_effect = Exception('Google Chat error')

        response = self.service.new_feedback(
            company_short_name='my_company',
            message='feedback message for testing',
            user_identifier='flibedinsky',
            space='spaces/AAQAupQldd4',
            type='MESSAGE_TRIGGER',
            rating=3
        )

        # Verify Google Chat was called
        self.google_chat_app.send_message.assert_called_once()

        # Verify error response due to Google Chat exception
        assert 'error' in response
        assert 'Google Chat error' in response['error']

    def test_feedback_google_chat_failure_does_not_affect_save(self):
        """Test that Google Chat failure (not exception) doesn't prevent feedback from being saved"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        # Mock Google Chat failure (returns success: false, not exception)
        self.google_chat_app.send_message.return_value = {
            'success': False,
            'message': 'Error al enviar mensaje'
        }

        response = self.service.new_feedback(
            company_short_name='my_company',
            message='feedback message for testing',
            user_identifier='flibedinsky',
            space='spaces/AAQAupQldd4',
            type='MESSAGE_TRIGGER',
            rating=4
        )

        # Verify Google Chat was called
        self.google_chat_app.send_message.assert_called_once()

        # Verify feedback was still saved successfully despite Google Chat failure
        assert 'Feedback guardado correctamente' == response['message']

    def test_feedback_message_format_with_external_user_id(self):
        """Test the format of the Google Chat message """
        self.profile_repo.save_feedback.return_value = UserFeedback

        self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=5
        )

        call_args = self.google_chat_app.send_message.call_args[1]['message_data']
        expected_message = "*Nuevo feedback de test_company*:\n*Usuario:* user123\n*Mensaje:* Test feedback message\n*Calificación:* 5"
        assert call_args['message']['text'] == expected_message
        assert call_args['type'] == 'MESSAGE_TRIGGER'
        assert call_args['space']['name'] == 'spaces/test-space'

    def test_feedback_google_chat_called_before_save(self):
        """Test that Google Chat notification is sent before saving to database"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        # Track the order of calls
        call_order = []

        def mock_send_message(message_data):
            call_order.append('google_chat')
            return {'success': True, 'message': 'Mensaje enviado correctamente'}

        def mock_save_feedback(feedback):
            call_order.append('save_feedback')
            return UserFeedback

        self.google_chat_app.send_message.side_effect = mock_send_message
        self.profile_repo.save_feedback.side_effect = mock_save_feedback

        self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=3
        )

        # Verify Google Chat was called before saving
        assert call_order == ['google_chat', 'save_feedback']

    def test_feedback_with_custom_type_and_space(self):
        """Test that custom type and space values are used correctly"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/custom-space-id',
            type='CUSTOM_TYPE',
            rating=1
        )

        call_args = self.google_chat_app.send_message.call_args[1]['message_data']
        assert call_args['type'] == 'CUSTOM_TYPE'
        assert call_args['space']['name'] == 'spaces/custom-space-id'
        assert '*Nuevo feedback de test_company*' in call_args['message']['text']
        assert '*Calificación:* 1' in call_args['message']['text']

    def test_feedback_save_feedback_called_with_rating(self):
        """Test that save_feedback is called with the rating parameter"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=5
        )

        # Verify save_feedback was called
        self.profile_repo.save_feedback.assert_called_once()

        # Get the UserFeedback object that was passed to save_feedback
        saved_feedback = self.profile_repo.save_feedback.call_args[0][0]

        # Verify the rating was set correctly
        assert saved_feedback.rating == 5
        assert saved_feedback.message == 'Test feedback message'
        assert saved_feedback.user_identifier == 'user123'
        assert saved_feedback.company_id == self.company.id

    def test_feedback_with_different_rating_values(self):
        """Test that different rating values work correctly"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        # Test with rating 1
        response1 = self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=1
        )
        assert 'Feedback guardado correctamente' == response1['message']

        # Test with rating 5
        response2 = self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=5
        )
        assert 'Feedback guardado correctamente' == response2['message']

        # Verify both calls were made
        assert self.profile_repo.save_feedback.call_count == 2

        # Verify the ratings were saved correctly
        calls = self.profile_repo.save_feedback.call_args_list
        assert calls[0][0][0].rating == 1
        assert calls[1][0][0].rating == 5

    def test_feedback_google_chat_message_includes_rating(self):
        """Test that Google Chat message includes the rating in the correct format"""
        self.profile_repo.save_feedback.return_value = UserFeedback

        self.service.new_feedback(
            company_short_name='test_company',
            message='Test feedback message',
            user_identifier='user123',
            space='spaces/test-space',
            type='MESSAGE_TRIGGER',
            rating=4
        )

        call_args = self.google_chat_app.send_message.call_args[1]['message_data']
        message_text = call_args['message']['text']

        # Verify the rating is included in the message
        assert '*Calificación:* 4' in message_text

        # Verify the complete message format
        expected_parts = [
            '*Nuevo feedback de test_company*:',
            '*Usuario:* user123',
            '*Mensaje:* Test feedback message',
            '*Calificación:* 4'
        ]

        for part in expected_parts:
            assert part in message_text