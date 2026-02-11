# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import request, jsonify
from injector import inject
import base64

from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.repositories.profile_repo import ProfileRepo


class LoadDocumentApiView(MethodView):
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 knowledge_base_service: KnowledgeBaseService,
                 profile_repo: ProfileRepo):
        self.auth_service = auth_service
        self.knowledge_base_service = knowledge_base_service
        self.profile_repo = profile_repo

    def post(self):
        try:
            # 1. Authenticate the API request.
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            req_data = request.get_json()
            required_fields = ['company', 'filename', 'content']
            for field in required_fields:
                if field not in req_data:
                    return jsonify({"error": f"El campo {field} es requerido"}), 400

            company_short_name = req_data.get('company', '')
            filename = req_data.get('filename', False)
            base64_content = req_data.get('content', '')
            metadata = req_data.get('metadata', {})

            # get company
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return jsonify({"error": f"La empresa {company_short_name} no existe"}), 400

            # get the file content from base64
            content = base64.b64decode(base64_content)

            # Use KnowledgeBaseService for ingestion
            new_document = self.knowledge_base_service.ingest_document_sync(
                company=company,
                filename=filename,
                content=content,
                metadata=metadata
            )

            return jsonify({
                "document_id": new_document.id,
                "status": "active" # ingest_document_sync returns ACTIVE on success
            }), 200

        except Exception as e:
            response = jsonify({"error": str(e)})
            response.status_code = 500

            return response