# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging

from flask import jsonify, request
from flask.views import MethodView
from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.prompt_resource_service import PromptResourceService


class PromptResourceApiView(MethodView):
    @inject
    def __init__(
        self,
        auth_service: AuthService,
        prompt_resource_service: PromptResourceService,
    ):
        self.auth_service = auth_service
        self.prompt_resource_service = prompt_resource_service

    def _require_admin_auth(self, company_short_name: str) -> dict | tuple:
        auth_result = self.auth_service.verify_for_company(company_short_name)
        if not auth_result.get("success"):
            status_code = auth_result.get("status_code", 401)
            if status_code == 403:
                return jsonify({"error": "Forbidden"}), 403
            return jsonify(auth_result), status_code

        role = (auth_result.get("user_role") or "").lower()
        if role not in {"admin", "owner"}:
            return jsonify({"error": "Forbidden"}), 403

        return auth_result

    @staticmethod
    def _map_error_status(exc: IAToolkitException) -> int:
        error_type = exc.error_type
        if error_type in {IAToolkitException.ErrorType.MISSING_PARAMETER, IAToolkitException.ErrorType.INVALID_PARAMETER}:
            return 400
        if error_type in {
            IAToolkitException.ErrorType.INVALID_NAME,
            IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND,
            IAToolkitException.ErrorType.NOT_FOUND,
        }:
            return 404
        if error_type == IAToolkitException.ErrorType.PERMISSION:
            return 403
        return 400

    def get(self, company_short_name: str, prompt_name: str):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        try:
            result = self.prompt_resource_service.get_prompt_resource_bindings(company_short_name, prompt_name)
            return jsonify(result.get("data", result)), 200
        except IAToolkitException as exc:
            return jsonify({"error": exc.message or str(exc)}), self._map_error_status(exc)
        except Exception as exc:
            logging.exception("Fatal error loading prompt resources")
            return jsonify({"error": str(exc)}), 500

    def put(self, company_short_name: str, prompt_name: str):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        try:
            payload = request.get_json(silent=True) or {}
            result = self.prompt_resource_service.set_prompt_resource_bindings(
                company_short_name,
                prompt_name,
                payload,
                actor_identifier=auth.get("user_identifier"),
            )
            return jsonify(result.get("data", result)), 200
        except IAToolkitException as exc:
            return jsonify({"error": exc.message or str(exc)}), self._map_error_status(exc)
        except Exception as exc:
            logging.exception("Fatal error saving prompt resources")
            return jsonify({"error": str(exc)}), 500
