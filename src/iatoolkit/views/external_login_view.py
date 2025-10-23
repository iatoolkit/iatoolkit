# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import logging
from flask import request, jsonify, render_template, url_for
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService


class InitiateExternalChatView(MethodView):
    @inject
    def __init__(self,
                 iauthentication: AuthService,
                 branding_service: BrandingService,
                 profile_service: ProfileService,
                 onboarding_service: OnboardingService,
                 query_service: QueryService,
                 prompt_service: PromptService
                 ):
        self.iauthentication = iauthentication
        self.branding_service = branding_service
        self.profile_service = profile_service
        self.onboarding_service = onboarding_service
        self.query_service = query_service
        self.prompt_service = prompt_service

    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'external_user_id' not in data:
            return jsonify({"error": "Falta external_user_id"}), 400

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Empresa no encontrada"}), 404

        external_user_id = data['external_user_id']
        if not external_user_id:
            return jsonify({"error": "missing external_user_id"}), 404

        # 1. Authenticate the API call.
        iaut = self.iauthentication.verify()
        if not iaut.get("success"):
            return jsonify(iaut), 401

        # 2. Delegate session creation to ProfileService.
        self.profile_service.create_external_user_session(company, external_user_id)

        # 3. prepare and decide the path
        prep_result = self.query_service.prepare_context(
            company_short_name=company_short_name, user_identifier=external_user_id
        )

        if prep_result.get('rebuild_needed'):
            branding_data = self.branding_service.get_company_branding(company)
            onboarding_cards = self.onboarding_service.get_onboarding_cards(company)
            target_url = url_for('login', company_short_name=company_short_name,
                                 _external=True)

            return render_template(
                "onboarding_shell.html",
                iframe_src_url=target_url,
                branding=branding_data,
                onboarding_cards=onboarding_cards
            )
        else:
            # fast path, the context is already on the cache, render the chat directly
            try:
                session_info = self.profile_service.get_current_session_info()
                user_profile = session_info.get('profile', {})

                prompts = self.prompt_service.get_user_prompts(company_short_name)
                branding_data = self.branding_service.get_company_branding(company)

                return render_template("chat.html",
                                       company_short_name=company_short_name,
                                       user_is_local=user_profile.get('user_is_local'),
                                       user_email=user_profile.get('user_email'),
                                       branding=branding_data,
                                       prompts=prompts,
                                       iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                       ), 200
            except Exception as e:
                logging.exception(f"Error en el camino rápido para {company_short_name}/{external_user_id}: {e}")
                return jsonify({"error": f"Error interno al iniciar el chat. {str(e)}"}), 500
