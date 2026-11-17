from flask.views import MethodView
from flask import request, jsonify
from injector import inject
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.i18n_service import I18nService
import logging

def build_llm_query_kwargs(data: dict) -> dict:
    """The arguments of `QueryService.llm_query` a chat/API request body carries."""
    client_data = data.get('client_data') or {}
    if not isinstance(client_data, dict):
        client_data = {}
    else:
        client_data = dict(client_data)
    client_data.setdefault("source", "chat_ui")
    kwargs = {
        "model": data.get('model', ''),
        "llm_request_options": {
            "reasoning_effort": data.get('reasoning_effort', '')
        },
        "question": data.get('question', ''),
        "prompt_name": data.get('prompt_name'),
        "client_data": client_data,
        "ignore_history": data.get('ignore_history', False),
        "files": data.get('files', []),
    }
    # The conversation the turn belongs to (BL-001); create_conversation starts
    # one when there is none yet. Only when asked: a turn without them is the
    # person's single history, as before conversations.
    conversation_id = str(data.get('conversation_id') or '').strip()
    if conversation_id:
        kwargs["conversation_id"] = conversation_id
    elif data.get('create_conversation'):
        kwargs["create_conversation"] = True
    return kwargs


def compact_llm_query_result(result: dict) -> dict:
    """Keep the response compact: expose structured_output but hide schema diagnostics."""
    result.pop('schema_valid', None)
    result.pop('schema_errors', None)
    result.pop('schema_mode', None)
    result.pop('schema_applied', None)
    return result


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
            auth_result = self.auth_service.verify_for_company(company_short_name)
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
                **build_llm_query_kwargs(data),
            )
            if 'error' in result:
                return jsonify(result), 409

            compact_llm_query_result(result)

            return jsonify(result), 200

        except Exception as e:
            logging.exception(
                f"Unexpected error: {e}")
            return jsonify({"error": True, "error_message": self.i18n_service.t('errors.general.unexpected_error')}), 500
