from flask.views import MethodView
from flask import request, jsonify
from injector import inject
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
import logging

class LLMQueryApiView(MethodView):
    """
    API-only endpoint for submitting queries. Authenticates via API Key.
    """

    @inject
    def __init__(self, auth_service: AuthService, query_service: QueryService, profile_service: ProfileService):
        self.auth_service = auth_service
        self.query_service = query_service
        self.profile_service = profile_service

    def post(self, company_short_name: str):
        # 1. Authenticate the API request.
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify({"error": auth_result.get("error_message")}), auth_result.get("status_code", 401)

        # 2. Get the user identifier from the payload.
        user_identifier = auth_result.get('user_identifier')
        if not user_identifier:
            return jsonify({"error": "Payload must include 'external_user_id'"}), 400

        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400

        # 3. Ensure session state exists for this API user (lazy creation).
        profile = self.profile_service.get_profile_by_identifier(company_short_name, user_identifier)
        if not profile:
            company = self.profile_service.get_company_by_short_name(company_short_name)
            self.profile_service.create_external_user_session(company, user_identifier)

        # 4. Call the unified query service method.
        result = self.query_service.llm_query(
            company_short_name=company_short_name,
            user_identifier=user_identifier,
            question=data.get('question', ''),
            prompt_name=data.get('prompt_name'),
            client_data=data.get('client_data', {}),
            files=data.get('files', [])
        )
        return jsonify(result)