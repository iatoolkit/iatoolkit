# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from iatoolkit.services.history_service import HistoryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from injector import inject
import logging


class HistoryApiView(MethodView):
    """
    Handles requests from the web UI to fetch a user's query history.
    Authentication is based on the active Flask session.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 history_service: HistoryService,
                 i18n_service: I18nService):
        self.auth_service = auth_service
        self.history_service = history_service
        self.i18n_service = i18n_service


    def post(self, company_short_name: str):
        try:
            # 1. Get the authenticated user's
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            user_identifier = auth_result.get('user_identifier')

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
                f"Unexpected error: {e}")
            return jsonify({"error_message": self.i18n_service.t('errors.general.unexpected_error', error=str(e))}), 500
