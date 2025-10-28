# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import logging
from flask import request, jsonify, url_for
from injector import inject
from iatoolkit.views.base_login_view import BaseLoginView

# Importar los servicios que necesita la clase base
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService

class ExternalLoginView(BaseLoginView):
    """
    Handles login for external users via API.
    Authenticates and then delegates the path decision (fast/slow) to the base class.
    """
    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'user_identifier' not in data:
            return jsonify({"error": "Falta user_identifier"}), 400

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Empresa no encontrada"}), 404

        user_identifier = data.get('user_identifier')
        if not user_identifier:
            return jsonify({"error": "missing user_identifier"}), 404

        # 1. Authenticate the API call.
        auth_response = self.auth_service.verify()
        if not auth_response.get("success"):
            return jsonify(auth_response), 401

        # 2. Create the external user session.
        self.profile_service.create_external_user_profile_context(company, user_identifier)

        # 3. create a redeem_token for create session at the end of the process
        redeem_token = self.jwt_service.generate_chat_jwt(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            expires_delta_seconds=300
        )

        if not redeem_token:
            return jsonify({"error": "Error al generar el redeem_token para login externo."}), 403

        # 4. define URL to call when slow path is finished
        target_url = url_for('finalize_with_token',
                             company_short_name=company_short_name,
                             token=redeem_token,
                             _external=True)

        # 5. Delegate the path decision to the centralized logic.
        try:
            return self._handle_login_path(company, user_identifier, target_url, redeem_token)
        except Exception as e:
            logging.exception(f"Error processing external login path for {company_short_name}/{user_identifier}: {e}")
            return jsonify({"error": f"Internal server error while starting chat. {str(e)}"}), 500


class RedeemTokenApiView(BaseLoginView):
    # this endpoint is only used ONLY by chat_main.js to redeem a chat token
    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'token' not in data:
            return jsonify({"error": "Falta token de validación"}), 400

        # get the token and validate with auth service
        token = data.get('token')
        redeem_result = self.auth_service.redeem_token_for_session(
            company_short_name=company_short_name,
            token=token
        )

        if not redeem_result['success']:
            return {"error": redeem_result['error']}, 401

        return {"status": "ok"}, 200