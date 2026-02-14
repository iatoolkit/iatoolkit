# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.api_key_service import ApiKeyService


class ApiKeyApiView(MethodView):
    """
    Admin API for API Keys CRUD.
    """

    @inject
    def __init__(self, auth_service: AuthService, api_key_service: ApiKeyService):
        self.auth_service = auth_service
        self.api_key_service = api_key_service

    def _require_admin_auth(self, company_short_name: str) -> dict | tuple:
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        auth_company = auth_result.get("company_short_name")
        if auth_company != company_short_name:
            return jsonify({"error": "Forbidden"}), 403

        role = (auth_result.get("user_role") or "").lower()
        if role not in {"admin", "owner"}:
            return jsonify({"error": "Forbidden"}), 403

        return auth_result

    @staticmethod
    def _build_response(result: dict, success_status_code: int = 200):
        if "error" in result:
            return jsonify({"error": result["error"]}), result.get("status_code", 400)
        return jsonify(result.get("data", result)), success_status_code

    def get(self, company_short_name: str, api_key_id: int = None):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        if api_key_id is not None:
            result = self.api_key_service.get_api_key(company_short_name, api_key_id)
            return self._build_response(result, success_status_code=200)

        result = self.api_key_service.list_api_keys(company_short_name)
        return self._build_response(result, success_status_code=200)

    def post(self, company_short_name: str):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        data = request.get_json() or {}
        key_name = (data.get("key_name") or "").strip()
        result = self.api_key_service.create_api_key_entry(company_short_name, key_name)
        return self._build_response(result, success_status_code=201)

    def put(self, company_short_name: str, api_key_id: int):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        data = request.get_json() or {}
        key_name = data.get("key_name")
        if isinstance(key_name, str):
            key_name = key_name.strip()

        is_active = data["is_active"] if "is_active" in data else None

        result = self.api_key_service.update_api_key_entry(
            company_short_name=company_short_name,
            api_key_id=api_key_id,
            key_name=key_name,
            is_active=is_active
        )
        return self._build_response(result, success_status_code=200)

    def delete(self, company_short_name: str, api_key_id: int):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        result = self.api_key_service.delete_api_key_entry(company_short_name, api_key_id)
        if "error" in result:
            return jsonify({"error": result["error"]}), result.get("status_code", 400)
        return jsonify({"status": "success"}), 200
