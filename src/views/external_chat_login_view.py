# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import logging
from flask import request, jsonify, render_template
from flask.views import MethodView
from injector import inject
from common.auth import IAuthentication
from services.profile_service import ProfileService
from services.query_service import QueryService
from services.prompt_manager_service import PromptService
from services.jwt_service import JWTService

class ExternalChatLoginView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 query_service: QueryService,
                 prompt_service: PromptService,
                 iauthentication: IAuthentication,
                 jwt_service: JWTService
                 ):
        self.profile_service = profile_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.iauthentication = iauthentication
        self.jwt_service = jwt_service

    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'external_user_id' not in data:
            return jsonify({"error": "Falta external_user_id"}), 400

        external_user_id = data['external_user_id']
        # 1. get access credentials
        iaut = self.iauthentication.verify(
            company_short_name,
            body_external_user_id=external_user_id
        )
        if not iaut.get("success"):
            return jsonify(iaut), 401

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Empresa no encontrada"}), 404

        try:
            # 1. generate a new JWT, our secure access token.
            token = self.jwt_service.generate_chat_jwt(
                company_id=company.id,
                company_short_name=company.short_name,
                external_user_id=external_user_id,
                expires_delta_seconds=3600 * 8  # 8 horas
            )
            if not token:
                raise Exception("No se pudo generar el token de sesión (JWT).")

            # 2. init the company/user LLM context.
            self.query_service.llm_init_context(
                company_short_name=company_short_name,
                external_user_id=external_user_id
            )

            # 3. get the prompt list from backend
            prompts = self.prompt_service.get_user_prompts(company_short_name)

            # 4. render the chat page with the company/user information.
            user_agent = request.user_agent
            is_mobile = user_agent.platform in ["android", "iphone", "ipad"] or "mobile" in user_agent.string.lower()

            chat_html = render_template("chat.html",
                                        company=company,
                                        company_short_name=company_short_name,
                                        external_user_id=external_user_id,
                                        is_mobile=is_mobile,
                                        auth_method='jwt',  # login method is JWT
                                        session_jwt=token,  # pass the token to the front-end
                                        iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                        prompts=prompts,
                                        external_login=True)
            return chat_html, 200

        except Exception as e:
            logging.exception(f"Error al inicializar el chat para {company_short_name}/{external_user_id}: {e}")
            return jsonify({"error": "Error interno al iniciar el chat"}), 500