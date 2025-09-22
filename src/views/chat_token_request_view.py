# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from flask import request, jsonify, current_app
from flask.views import MethodView
from injector import inject
import logging
from repositories.profile_repo import ProfileRepo
from services.jwt_service import JWTService
from typing import Optional


# Necesitaremos JWT_EXPIRATION_SECONDS_CHAT de la configuración de la app
# Se podría inyectar o acceder globalmente.

class ChatTokenRequestView(MethodView):
    @inject
    def __init__(self, profile_repo: ProfileRepo, jwt_service: JWTService):
        self.profile_repo = profile_repo
        self.jwt_service = jwt_service

    def _authenticate_requesting_company_via_api_key(self) -> tuple[
        Optional[int], Optional[str], Optional[tuple[dict, int]]]:
        """
        Autentica a la compañía que solicita el token JWT usando su API Key.
        Retorna (company_id, company_short_name, None) en éxito.
        Retorna (None, None, (error_json, status_code)) en fallo.
        """
        api_key_header = request.headers.get('Authorization')
        if not api_key_header or not api_key_header.startswith('Bearer '):
            return None, None, ({"error": "API Key faltante o mal formada en el header Authorization"}, 401)

        api_key_value = api_key_header.split('Bearer ')[1]
        try:
            api_key_entry = self.profile_repo.get_active_api_key_entry(api_key_value)
            if not api_key_entry:
                return None, None, ({"error": "API Key inválida o inactiva"}, 401)

            # api_key_entry.company ya está cargado por joinedload en get_active_api_key_entry
            if not api_key_entry.company:  # Sanity check
                logging.error(
                    f"ChatTokenRequest: API Key {api_key_value[:5]}... no tiene compañía asociada a pesar de ser válida.")
                return None, None, ({"error": "Error interno del servidor al verificar API Key"}, 500)

            return api_key_entry.company_id, api_key_entry.company.short_name, None

        except Exception as e:
            logging.exception(f"ChatTokenRequest: Error interno durante validación de API Key: {e}")
            return None, None, ({"error": "Error interno del servidor al validar API Key"}, 500)

    def post(self):
        """
        Genera un JWT para una sesión de chat.
        Autenticado por API Key de la empresa.
        Requiere JSON body:
                {"company_short_name": "target_company_name",
                "external_user_id": "user_abc"
                }
        """
        # only requests with valid api-key are allowed
        auth_company_id, auth_company_short_name, error = self._authenticate_requesting_company_via_api_key()
        if error:
            return jsonify(error[0]), error[1]

        # get the json fields from the request body
        data = request.get_json()
        if not data:
            return jsonify({"error": "Cuerpo de la solicitud JSON faltante"}), 400

        target_company_short_name = data.get('company_short_name')
        external_user_id = data.get('external_user_id')

        if not target_company_short_name or not external_user_id:
            return jsonify(
                {"error": "Faltan 'company_short_name' o 'external_user_id' en el cuerpo de la solicitud"}), 401

        # Verificar que la API Key usada pertenezca a la empresa para la cual se solicita el token
        if auth_company_short_name != target_company_short_name:
            return jsonify({
                    "error": f"API Key no autorizada para generar tokens para la compañía '{target_company_short_name}'"}), 403

        jwt_expiration_seconds = current_app.config.get('JWT_EXPIRATION_SECONDS_CHAT', 3600)

        # Aquí, auth_company_id es el ID de la compañía para la que se generará el token.
        # auth_company_short_name es su nombre corto.
        token = self.jwt_service.generate_chat_jwt(
            company_id=auth_company_id,
            company_short_name=auth_company_short_name,  # Usamos el short_name autenticado
            external_user_id=external_user_id,
            expires_delta_seconds=jwt_expiration_seconds
        )

        if token:
            return jsonify({"chat_jwt": token}), 200
        else:
            return jsonify({"error": "No se pudo generar el token de chat"}), 500
