# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from iatoolkit.services.user_feedback_service import UserFeedbackService
from iatoolkit.services.auth_service import AuthService
from injector import inject
import logging


class UserFeedbackApiView(MethodView):
    @inject
    def __init__(self,
                 iauthentication: AuthService,
                 user_feedback_service: UserFeedbackService ):
        self.iauthentication = iauthentication
        self.user_feedback_service = user_feedback_service

    def post(self, company_short_name):
        # get access credentials
        iaut = self.iauthentication.verify()
        if not iaut.get("success"):
            return jsonify(iaut), 401

        user_identifier = iaut.get('user_identifier')
        if not user_identifier:
            return jsonify({"error": "Could not identify user from session or payload"}), 400

        data = request.get_json()
        if not data:
            return jsonify({"error_message": "Cuerpo de la solicitud JSON inválido o faltante"}), 402

        message = data.get("message")
        if not message:
            return jsonify({"error_message": "Falta el mensaje de feedback"}), 400
        
        space = data.get("space")
        if not space:
            return jsonify({"error_message": "Falta el espacio de Google Chat"}), 400
        
        type = data.get("type")
        if not type:
            return jsonify({"error_message": "Falta el tipo de feedback"}), 400
        
        rating = data.get("rating")
        if not rating:
            return jsonify({"error_message": "Falta la calificación"}), 400

        try:
            response = self.user_feedback_service.new_feedback(
                company_short_name=company_short_name,
                message=message,
                user_identifier=user_identifier,
                space=space,
                type=type,
                rating=rating
            )

            if "error" in response:
                return {'error_message': response["error"]}, 402

            return response, 200
        except Exception as e:
            logging.exception(
                f"Error inesperado al procesar feedback para company {company_short_name}: {e}")

            return jsonify({"error_message": str(e)}), 500

