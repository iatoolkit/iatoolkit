# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import jsonify, request
from flask.views import MethodView
from injector import inject
import logging

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.memory_service import MemoryService


class MemoryApiView(MethodView):
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 memory_service: MemoryService):
        self.auth_service = auth_service
        self.memory_service = memory_service

    def get(self, company_short_name: str, page_id: int | None = None):
        try:
            auth_result = self.auth_service.verify_for_company(company_short_name)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            user_identifier = auth_result.get("user_identifier")
            if page_id is not None:
                response = self.memory_service.get_page(company_short_name, user_identifier, page_id)
                status = 200 if response.get("status") == "success" else 404
                return jsonify(response), status

            response = self.memory_service.get_memory_dashboard(company_short_name, user_identifier)
            status = 200 if response.get("status") == "success" else 400
            return jsonify(response), status
        except Exception as exc:
            logging.exception("Unexpected memory GET error for %s: %s", company_short_name, exc)
            return jsonify({"status": "error", "error_message": str(exc)}), 500

    def post(self, company_short_name: str, page_id: int | None = None):
        try:
            auth_result = self.auth_service.verify_for_company(company_short_name)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            user_identifier = auth_result.get("user_identifier")
            payload = request.get_json() or {}

            action = str(payload.get("action") or "save").strip().lower()
            if action == "search":
                query = str(payload.get("query") or "").strip()
                limit = int(payload.get("limit") or 5)
                response = self.memory_service.search_pages(company_short_name, user_identifier, query=query, limit=limit)
                return jsonify(response), 200
            if action == "lint":
                response = self.memory_service.lint_memory_wiki(company_short_name, user_identifier)
                status = 200 if response.get("status") == "success" else 400
                return jsonify(response), status
            if action == "save_capture":
                response = self.memory_service.save_capture(
                    company_short_name=company_short_name,
                    user_identifier=user_identifier,
                    capture_text=payload.get("capture_text"),
                    title=payload.get("title"),
                    new_items=payload.get("items") or [],
                )
                status = 200 if response.get("status") == "success" else 400
                return jsonify(response), status
            if action == "update_capture":
                capture_id = int(payload.get("capture_id") or 0)
                response = self.memory_service.update_capture(
                    company_short_name=company_short_name,
                    user_identifier=user_identifier,
                    capture_id=capture_id,
                    capture_text=payload.get("capture_text"),
                    title=payload.get("title"),
                    keep_item_ids=payload.get("keep_item_ids") or [],
                    new_items=payload.get("items") or [],
                )
                status = 200 if response.get("status") == "success" else 400
                return jsonify(response), status
            if action == "delete_capture":
                capture_id = int(payload.get("capture_id") or 0)
                response = self.memory_service.delete_capture(company_short_name, user_identifier, capture_id=capture_id)
                status = 200 if response.get("status") == "success" else 404
                return jsonify(response), status
            if action == "delete_item":
                item_id = int(payload.get("item_id") or 0)
                response = self.memory_service.delete_item(company_short_name, user_identifier, item_id=item_id)
                status = 200 if response.get("status") == "success" else 404
                return jsonify(response), status

            response = self.memory_service.save_item(
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                item_type=payload.get("item_type"),
                content_text=payload.get("content_text"),
                title=payload.get("title"),
                source_url=payload.get("source_url"),
                filename=payload.get("filename"),
                mime_type=payload.get("mime_type"),
                file_base64=payload.get("file_base64"),
                source_meta=payload.get("source_meta"),
            )
            status = 200 if response.get("status") == "success" else 400
            return jsonify(response), status
        except Exception as exc:
            logging.exception("Unexpected memory POST error for %s: %s", company_short_name, exc)
            return jsonify({"status": "error", "error_message": str(exc)}), 500
