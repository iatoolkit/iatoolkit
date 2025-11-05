# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import jsonify
from flask.views import MethodView
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.auth_service import AuthService
from injector import inject
import logging


class PromptApiView(MethodView):
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 prompt_service: PromptService ):
        self.auth_service = auth_service
        self.prompt_service = prompt_service

    def get(self, company_short_name):
        # get access credentials
        auth_result = self.auth_service.verify(anonymous=True)
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get('status_code')

        try:
            response = self.prompt_service.get_user_prompts(company_short_name)
            if "error" in response:
                return {'error_message': response["error"]}, 402

            return response, 200
        except Exception as e:
            logging.exception(
                f"unexpected error getting company prompts  {company_short_name}: {e}")
            return jsonify({"error_message": str(e)}), 500
