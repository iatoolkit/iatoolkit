# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from iatoolkit.services.history_service import HistoryService
from iatoolkit.services.profile_service import ProfileService
from injector import inject
import logging


class HistoryApiView(MethodView):
    """
    Handles requests from the web UI to fetch a user's query history.
    Authentication is based on the active Flask session.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 history_service: HistoryService):
        self.profile_service = profile_service
        self.history_service = history_service

    def post(self, company_short_name: str):
        # 1. Get the authenticated user's info from the unified session.
        session_info = self.profile_service.get_current_session_info()
        user_identifier = session_info.get("user_identifier")

        if not user_identifier:
            return jsonify({'error_message': 'Usuario no autenticado o sesión inválida'}), 401

        try:
            # 2. Call the history service with the unified identifier.
            # The service's signature should now only expect user_identifier.
            response = self.history_service.get_history(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            if "error" in response:
                # Handle errors reported by the service itself.
                return jsonify({'error_message': response["error"]}), 400

            return jsonify(response), 200

        except Exception as e:
            logging.exception(
                f"Unexpected error fetching history for {company_short_name}/{user_identifier}: {e}")
            return jsonify({"error_message": "Ha ocurrido un error inesperado en el servidor."}), 500
