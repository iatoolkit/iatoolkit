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


class PromptView(MethodView):
    @inject
    def __init__(self,
                 iauthentication: AuthService,
                 prompt_service: PromptService ):
        self.iauthentication = iauthentication
        self.prompt_service = prompt_service

    def get(self, company_short_name):
        # get access credentials
        iaut = self.iauthentication.verify()
        if not iaut.get("success"):
            return jsonify(iaut), 401

        try:
            response = self.prompt_service.get_user_prompts(company_short_name)
            if "error" in response:
                return {'error_message': response["error"]}, 402

            return response, 200
        except Exception as e:
            logging.exception(
                f"Error inesperado al obtener el historial de consultas para company {company_short_name}: {e}")
            return jsonify({"error_message": str(e)}), 500
