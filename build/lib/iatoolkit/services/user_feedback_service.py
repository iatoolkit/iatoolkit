# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import UserFeedback, Company
from injector import inject
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.infra.google_chat_app import GoogleChatApp
from iatoolkit.services.mail_service import MailService
import logging


class UserFeedbackService:
    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService,
                 google_chat_app: GoogleChatApp,
                 mail_service: MailService):
        self.profile_repo = profile_repo
        self.i18n_service = i18n_service
        self.google_chat_app = google_chat_app
        self.mail_service = mail_service

    def _send_google_chat_notification(self, space_name: str, message_text: str):
        """Envía una notificación de feedback a un espacio de Google Chat."""
        try:
            chat_data = {
                "type": "MESSAGE_TRIGGER",
                "space": {"name": space_name},
                "message": {"text": message_text}
            }
            chat_result = self.google_chat_app.send_message(message_data=chat_data)
            if not chat_result.get('success'):
                logging.warning(f"error sending notification to Google Chat: {chat_result.get('message')}")
        except Exception as e:
            logging.exception(f"error sending notification to Google Chat: {e}")

    def _send_email_notification(self,
                                 company_short_name: str,
                                 destination_email: str,
                                 company_name: str,
                                 message_text: str):
        """Envía una notificación de feedback por correo electrónico."""
        try:
            subject = f"Nuevo Feedback de {company_name}"
            # Convertir el texto plano a un HTML simple para mantener los saltos de línea
            html_body = message_text.replace('\n', '<br>')
            self.mail_service.send_mail(
                company_short_name=company_short_name,
                to=destination_email,
                subject=subject,
                body=html_body)
        except Exception as e:
            logging.exception(f"error sending email de feedback: {e}")

    def _handle_notification(self, company: Company, message_text: str):
        """Lee la configuración de la empresa y envía la notificación al canal correspondiente."""
        feedback_params = company.parameters.get('user_feedback')
        if not isinstance(feedback_params, dict):
            logging.warning(f"missing 'user_feedback' configuration for company: {company.short_name}.")
            return

        # get channel and destination
        channel = feedback_params.get('channel')
        destination = feedback_params.get('destination')
        if not channel or not destination:
            logging.warning(f"invalid 'user_feedback' configuration for: {company.short_name}. Faltan 'channel' o 'destination'.")
            return

        if channel == 'google_chat':
            self._send_google_chat_notification(space_name=destination, message_text=message_text)
        elif channel == 'email':
            self._send_email_notification(
                company_short_name=company.short_name,
                destination_email=destination,
                company_name=company.short_name,
                message_text=message_text)
        else:
            logging.warning(f"unknown feedback channel: '{channel}' for company {company.short_name}.")

    def new_feedback(self,
                     company_short_name: str,
                     message: str,
                     user_identifier: str,
                     rating: int = None) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {'error': self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name)}

            # 2. send notification using company configuration
            notification_text = (f"*Nuevo feedback de {company_short_name}*:\n"
                                 f"*Usuario:* {user_identifier}\n"
                                 f"*Mensaje:* {message}\n"
                                 f"*Calificación:* {rating if rating is not None else 'N/A'}")
            self._handle_notification(company, notification_text)

            # 3. always save the feedback in the database
            new_feedback_obj = UserFeedback(
                company_id=company.id,
                message=message,
                user_identifier=user_identifier,
                rating=rating
            )
            saved_feedback = self.profile_repo.save_feedback(new_feedback_obj)
            if not saved_feedback:
                logging.error(f"can't save feedback for user {user_identifier}/{company_short_name}")
                return {'error': 'can not save the feedback'}

            return {'success': True, 'message': 'Feedback guardado correctamente'}

        except Exception as e:
            logging.exception(f"Error crítico en el servicio de feedback: {e}")
            return {'error': str(e)}