from flask.views import MethodView
from flask import request, jsonify
from injector import inject
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.i18n_service import I18nService
import logging

class LLMQueryApiView(MethodView):
    """
    API-only endpoint for submitting queries. Authenticates via API Key.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 query_service: QueryService,
                 profile_service: ProfileService,
                 i18n_service: I18nService):
        self.auth_service = auth_service
        self.query_service = query_service
        self.profile_service = profile_service
        self.i18n_service = i18n_service

    def post(self, company_short_name: str):
        try:
            # 1. Authenticate the API request.
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            # 2. Get the user identifier from the payload.
            user_identifier = auth_result.get('user_identifier')

            data = request.get_json()
            if not data:
                return jsonify({"error": "Invalid JSON body"}), 400

            # 4. Call the unified query service method.
            result = self.query_service.llm_query(
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                model=data.get('model', ''),
                question=data.get('question', ''),
                prompt_name=data.get('prompt_name'),
                client_data=data.get('client_data', {}),
                ignore_history=data.get('ignore_history', False),
                files=data.get('files', [])
            )
            if 'error' in result:
                return jsonify(result), 409

            return jsonify(result), 200

        except Exception as e:
            logging.exception(
                f"Unexpected error: {e}")
            return jsonify({"error": True, "error_message": self.i18n_service.t('errors.general.unexpected_error')}), 500
