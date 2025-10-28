from flask.views import MethodView
from injector import inject
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService
from flask import jsonify, request
import logging


class InitContextApiView(MethodView):
    """
    API endpoint to force a full context rebuild for a user.
    Handles both web users (via session) and API users (via API Key).
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 query_service: QueryService,
                 profile_service: ProfileService):
        self.auth_service = auth_service
        self.query_service = query_service
        self.profile_service = profile_service

    def post(self, company_short_name: str):
        """
        Cleans and rebuilds the context. The user is identified either by
        an active web session or by the external_user_id in the JSON payload
        for API calls.
        """
        # 1. Authenticate the request. This handles both session and API Key.
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify({"error": auth_result.get("error_message")}), auth_result.get("status_code", 401)

        user_identifier = auth_result.get('user_identifier')
        if not user_identifier:
            return jsonify({"error": "Could not identify user from session or payload"}), 400

        try:
            # 2. Execute the forced rebuild sequence using the unified identifier.
            self.query_service.session_context.clear_all_context(company_short_name, user_identifier)
            logging.info(f"Context for {company_short_name}/{user_identifier} has been cleared.")

            # LLM context is clean, now we can load it again
            self.query_service.prepare_context(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            # logging.info(f"Context for {company_short_name}/{user_identifier} rebuilt successfully.")

            # 3. Respond with JSON, as this is an API endpoint.
            return jsonify({'status': 'OK', 'message': 'Context has been reloaded successfully.'}), 200

        except Exception as e:
            logging.exception(f"Error forcing context rebuild for {user_identifier}: {e}")
            return jsonify({"error_message": str(e)}), 500