from flask import jsonify, request
from flask.views import MethodView
from injector import inject

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.query_service import QueryService
import logging


class InvocationsApiView(MethodView):
    """
    Stateless API endpoint for externally invoking agents/prompts or direct questions.
    Authenticates via API Key or web session and always skips chat history.
    """

    @inject
    def __init__(
        self,
        auth_service: AuthService,
        query_service: QueryService,
        i18n_service: I18nService,
    ):
        self.auth_service = auth_service
        self.query_service = query_service
        self.i18n_service = i18n_service

    def post(self, company_short_name: str):
        try:
            auth_result = self.auth_service.verify_for_company(company_short_name)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            user_identifier = auth_result.get("user_identifier")

            data = request.get_json()
            if not data:
                return jsonify({"error": "Invalid JSON body"}), 400

            prompt_name = data.get("agent_name") or data.get("prompt_name")

            result = self.query_service.llm_query(
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                model=data.get("model", ""),
                llm_request_options={
                    "reasoning_effort": data.get("reasoning_effort", ""),
                },
                question=data.get("question", ""),
                prompt_name=prompt_name,
                client_data=data.get("client_data", {}),
                ignore_history=True,
                files=data.get("files", []),
            )
            if "error" in result:
                return jsonify(result), 409

            # keep API response compact: expose structured_output but hide schema diagnostics
            result.pop("schema_valid", None)
            result.pop("schema_errors", None)
            result.pop("schema_mode", None)
            result.pop("schema_applied", None)

            return jsonify(result), 200

        except Exception as e:
            logging.exception("Unexpected error in invocations API: %s", e)
            return jsonify(
                {
                    "error": True,
                    "error_message": self.i18n_service.t(
                        "errors.general.unexpected_error"
                    ),
                }
            ), 500
