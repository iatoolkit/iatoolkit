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
                 auth_service: AuthService,
                 user_feedback_service: UserFeedbackService ):
        self.auth_service = auth_service
        self.user_feedback_service = user_feedback_service

    def post(self, company_short_name):
        try:
            # get access credentials
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            user_identifier = auth_result.get('user_identifier')

            data = request.get_json()
            if not data:
                return jsonify({"error_message": "invalid json body"}), 402

            # these validations are performed also in the frontend
            # the are localized in the front
            message = data.get("message")
            if not message:
                return jsonify({"error_message": "missing feedback message"}), 400

            rating = data.get("rating")
            if not rating:
                return jsonify({"error_message": "missing rating"}), 400

            response = self.user_feedback_service.new_feedback(
                company_short_name=company_short_name,
                message=message,
                user_identifier=user_identifier,
                rating=rating
            )

            if "error" in response:
                return {'error_message': response["error"]}, 402

            return response, 200
        except Exception as e:
            logging.exception(
                f"unexpected error processing feedback for {company_short_name}: {e}")
            return jsonify({"error_message": str(e)}), 500

