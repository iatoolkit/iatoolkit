# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import logging

from flask import jsonify, request
from flask.views import MethodView
from injector import inject

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.query_service import QueryService


class PromptContextPreviewApiView(MethodView):
    @inject
    def __init__(
        self,
        auth_service: AuthService,
        query_service: QueryService,
    ):
        self.auth_service = auth_service
        self.query_service = query_service

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

    def post(self, company_short_name: str, prompt_name: str):
        auth = self._require_admin_auth(company_short_name)
        if isinstance(auth, tuple):
            return auth

        try:
            payload = request.get_json(silent=True) or {}
            client_data = payload.get("client_data")
            question = payload.get("question") or ""

            result = self.query_service.preview_prompt_context(
                company_short_name=company_short_name,
                user_identifier=auth.get("user_identifier"),
                prompt_name=prompt_name,
                client_data=client_data if isinstance(client_data, dict) else {},
                question=str(question or ""),
            )
            if result.get("error"):
                status_code = int(result.get("status_code") or 400)
                return jsonify({"error": result.get("error_message") or "Preview failed"}), status_code

            return jsonify(result), 200
        except Exception as exc:
            logging.exception("Fatal error building prompt context preview")
            return jsonify({"error": str(exc)}), 500
