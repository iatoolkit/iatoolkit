# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.infra.call_service import CallServiceClient
import logging
import os
from typing import Dict, Any


class GoogleChatApp:
    @inject
    def __init__(self, call_service: CallServiceClient):
        self.call_service = call_service

    def send_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends a message to Google Chat.

        Args:
            message_data: Complete message data structure with type, space, and message

        Returns:
            Dict with the service response
        """
        try:
            # get the bot URL from environment variables
            bot_url = os.getenv('GOOGLE_CHAT_BOT_URL')
            if not bot_url:
                raise Exception('GOOGLE_CHAT_BOT_URL no está configurada en las variables de entorno')

            # send the POST request with the complete message data
            response, status_code = self.call_service.post(bot_url, message_data)

            if status_code == 200:
                return {
                    "success": True,
                    "message": "Mensaje enviado correctamente",
                    "response": response
                }
            else:
                logging.error(f"Error al enviar mensaje a Google Chat. Status: {status_code}, Response: {response}")
                return {
                    "success": False,
                    "message": f"Error al enviar mensaje. Status: {status_code}",
                    "response": response
                }

        except Exception as e:
            logging.exception(f"Error inesperado al enviar mensaje a Google Chat: {e}")
            return {
                "success": False,
                "message": f"Error interno del servidor: {str(e)}",
                "response": None
            }