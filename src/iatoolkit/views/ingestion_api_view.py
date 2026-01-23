# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.repositories.document_repo import DocumentRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.ingestor_service import IngestorService
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import IngestionSource
import logging

class IngestionApiView(MethodView):
    """
    API for managing and triggering document ingestion sources.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 document_repo: DocumentRepo,
                 profile_repo: ProfileRepo,
                 ingestor_service: IngestorService):
        self.auth_service = auth_service
        self.document_repo = document_repo
        self.profile_repo = profile_repo
        self.ingestor_service = ingestor_service

    def get(self, company_short_name: str):
        """
        GET /api/{company}/ingestion-sources
        Lists all configured ingestion sources for the company.
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Company not found"}), 404

        sources = self.document_repo.session.query(IngestionSource).filter_by(company_id=company.id).all()

        response_data = []
        for src in sources:
            source_dict = src.to_dict()
            source_dict['collection_name'] = src.collection_type.name
            response_data.append(source_dict)

        return jsonify(response_data), 200

    def post(self, company_short_name: str, source_id: int = None, action: str = None):
        """
        POST /api/{company}/ingestion-sources (Create)
        POST /api/{company}/ingestion-sources/{id}/run (Trigger)
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)
        user_identifier = auth_result.get('user_identifier')

        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Company not found"}), 404

        try:
            # Case 1: Trigger Run
            if source_id and action == 'run':
                processed_count = self.ingestor_service.run_ingestion(company, source_id)
                return jsonify({
                    "message": "Ingestion completed successfully",
                    "processed_files": processed_count
                }), 200

            # Case 2: Create New Source
            if not source_id and not action:
                data = request.get_json() or {}
                new_source = self.ingestor_service.create_source(company, data)
                return jsonify(new_source.to_dict()), 201

            return jsonify({"error": "Invalid endpoint usage"}), 400

        except IAToolkitException as e:
            # Mapeo de excepciones de negocio a códigos HTTP
            status_code = 500
            if e.error_type == IAToolkitException.ErrorType.INVALID_STATE:
                status_code = 409
            elif e.error_type in [IAToolkitException.ErrorType.MISSING_PARAMETER, IAToolkitException.ErrorType.INVALID_PARAMETER]:
                status_code = 400
            elif e.error_type == IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND:
                status_code = 404

            return jsonify({"error": str(e)}), status_code

        except Exception as e:
            logging.exception(f"Ingestion API Error: {e}")
            return jsonify({"error": "Internal server error"}), 500