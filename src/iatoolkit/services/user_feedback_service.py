# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import UserFeedback
from injector import inject
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.infra.google_chat_app import GoogleChatApp
import logging


class UserFeedbackService:
    @inject
    def __init__(self, profile_repo: ProfileRepo, google_chat_app: GoogleChatApp):
        self.profile_repo = profile_repo
        self.google_chat_app = google_chat_app

    def new_feedback(self,
                     company_short_name: str,
                     message: str,
                     user_identifier: str,
                     space: str = None,
                     type: str = None,
                     rating: int = None) -> dict:
        try:
            # validate company
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {'error': f'No existe la empresa: {company_short_name}'}

            # send notification to Google Chat
            chat_message = f"*Nuevo feedback de {company_short_name}*:\n*Usuario:* {user_identifier}\n*Mensaje:* {message}\n*Calificación:* {rating}"

            # TO DO: get the space and type from the input data
            chat_data = {
                "type": type,
                "space": {
                    "name": space
                },
                "message": {
                    "text": chat_message
                }
            }

            chat_result = self.google_chat_app.send_message(message_data=chat_data)
            if not chat_result.get('success'):
                logging.warning(f"Error al enviar notificación a Google Chat: {chat_result.get('message')}")

            # create the UserFeedback object
            new_feedback = UserFeedback(
                company_id=company.id,
                message=message,
                user_identifier=user_identifier,
                rating=rating
            )
            new_feedback = self.profile_repo.save_feedback(new_feedback)
            if not new_feedback:
                return {'error': 'No se pudo guardar el feedback'}

            return {'message': 'Feedback guardado correctamente'}

        except Exception as e:
            return {'error': str(e)}