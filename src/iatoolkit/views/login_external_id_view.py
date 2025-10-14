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
from iatoolkit.services.onboarding_service import OnboardingService
from iatoolkit.common.session_manager import SessionManager


class InitiateExternalChatView(MethodView):
    @inject
    def __init__(self,
                 iauthentication: IAuthentication,
                 branding_service: BrandingService,
                 profile_service: ProfileService,
                 onboarding_service: OnboardingService
                 ):
        self.iauthentication = iauthentication
        self.branding_service = branding_service
        self.profile_service = profile_service
        self.onboarding_service = onboarding_service

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

        # 2. Authentication successful, create a temporary server-side session using SessionManager
        SessionManager.set('external_user_id', external_user_id)
        SessionManager.set('is_external_auth_complete', True)

        # 3. Get branding and onboarding data for the shell page
        branding_data = self.branding_service.get_company_branding(company)
        onboarding_cards = self.onboarding_service.get_onboarding_cards(company)

        # 4. Generate the URL for the iframe's SRC.
        target_url = url_for('external_login',  # Apunta a la vista del chat
                             company_short_name=company_short_name,
                             _external=True)

        # 5. Render the shell.
        return render_template("onboarding_shell.html",
                               iframe_src_url=target_url,  # Le cambiamos el nombre para más claridad
                               branding=branding_data,
                               onboarding_cards=onboarding_cards
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

    def get(self, company_short_name: str):
        # 1. Check for the temporary session flag and get user ID from SessionManager
        if not SessionManager.get('is_external_auth_complete'):
            return "Acceso no autorizado.", 401

        external_user_id = SessionManager.get('external_user_id')
        if not external_user_id:
            return "Falta el ID de usuario en la sesión.", 400

        # Clear the temporary session flag to prevent reuse
        SessionManager.set('is_external_auth_complete', None)

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            logging.error(f'Company {company_short_name} not found')
            return jsonify({"error": "Empresa no encontrada"}), 404

        try:

            # 2. generate a new JWT, our secure access token.
            token = self.jwt_service.generate_chat_jwt(
                company_id=company.id,
                company_short_name=company.short_name,
                external_user_id=external_user_id,
                expires_delta_seconds=3600 * 8  # 8 horas
            )
            if not token:
                raise Exception("No se pudo generar el token de sesión (JWT).")

            # 3. init the company/user LLM context.
            self.query_service.llm_init_context(
                company_short_name=company_short_name,
                external_user_id=external_user_id
            )

            # 5. get the prompt list from backend
            prompts = self.prompt_service.get_user_prompts(company_short_name)

            # 5. get the branding data
            branding_data = self.branding_service.get_company_branding(company)

            # 6. render the chat page with the company/user information.
            return render_template("chat.html",
                                        company_short_name=company_short_name,
                                        auth_method='jwt',
                                        session_jwt=token,
                                        external_user_id=external_user_id,
                                        branding=branding_data,
                                        prompts=prompts,
                                        iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                        ), 200

        except Exception as e:
            logging.exception(f"Error al inicializar el chat para {company_short_name}/{external_user_id}: {e}")
            return jsonify({"error": "Error interno al iniciar el chat"}), 500