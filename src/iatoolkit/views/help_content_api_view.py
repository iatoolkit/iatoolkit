# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from iatoolkit.services.help_content_service import HelpContentService
from iatoolkit.services.auth_service import AuthService
from injector import inject
import logging


class HelpContentApiView(MethodView):
    """
    Handles requests from the web UI to fetch a user's query history.
    Authentication is based on the active Flask session.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 help_content_service: HelpContentService):
        self.auth_service = auth_service
        self.help_content_service = help_content_service

    def post(self, company_short_name: str):
        # 1. Get the authenticated user's
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code")

        user_identifier = auth_result.get('user_identifier')
        try:
            # 2. Call the history service with the unified identifier.
            # The service's signature should now only expect user_identifier.
            response = self.help_content_service.get_content(
                company_short_name=company_short_name
            )

            if "error" in response:
                # Handle errors reported by the service itself.
                return jsonify({'error_message': response["error"]}), 400

            return jsonify(response), 200

        except Exception as e:
            logging.exception(
                f"Unexpected error fetching help_content for {company_short_name}/{user_identifier}: {e}")
            return jsonify({"error_message": "Ha ocurrido un error inesperado en el servidor."}), 500
