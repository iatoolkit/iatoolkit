# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import logging
from flask import request, jsonify, render_template, url_for, session
from flask.views import MethodView
from injector import inject
from iatoolkit.common.auth import IAuthentication
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.branding_service import BrandingService

class InitiateExternalChatView(MethodView):
    @inject
    def __init__(self,
                 iauthentication: IAuthentication,
                 branding_service: BrandingService,
                 profile_service: ProfileService
                 ):
        self.iauthentication = iauthentication
        self.branding_service = branding_service
        self.profile_service = profile_service

    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'external_user_id' not in data:
            return jsonify({"error": "Falta external_user_id"}), 400

        external_user_id = data['external_user_id']

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Empresa no encontrada"}), 404

        # 1. verify access credentials quickly
        iaut = self.iauthentication.verify(
            company_short_name,
            body_external_user_id=external_user_id
        )
        if not iaut.get("success"):
            return jsonify(iaut), 401

        # 2. Get branding data for the shell page
        branding_data = self.branding_service.get_company_branding(company)


        # 3. Render the shell page, passing the final data URL and user id
        return render_template("login_shell.html",
                               data_source_url=url_for('external_login', company_short_name=company_short_name),
                               external_user_id=external_user_id,
                               branding=branding_data
                               )

class ExternalChatLoginView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 query_service: QueryService,
                 prompt_service: PromptService,
                 iauthentication: IAuthentication,
                 jwt_service: JWTService,
                 branding_service: BrandingService
                 ):
        self.profile_service = profile_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.iauthentication = iauthentication
        self.jwt_service = jwt_service
        self.branding_service = branding_service

    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'external_user_id' not in data:
            return jsonify({"error": "Falta external_user_id"}), 400

        external_user_id = data['external_user_id']

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

            # 4. get the branding data
            branding_data = self.branding_service.get_company_branding(company)

            # 5. render the chat page with the company/user information.
            chat_html = render_template("chat.html",
                                        company_short_name=company_short_name,
                                        auth_method='jwt',  # login method is JWT
                                        session_jwt=token,  # pass the token to the front-end
                                        external_user_id=external_user_id,
                                        branding=branding_data,
                                        prompts=prompts,
                                        iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                        )
            return chat_html, 200

        except Exception as e:
            logging.exception(f"Error al inicializar el chat para {company_short_name}/{external_user_id}: {e}")
            return jsonify({"error": "Error interno al iniciar el chat"}), 500