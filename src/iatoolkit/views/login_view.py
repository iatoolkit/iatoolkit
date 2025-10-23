# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import request, redirect, render_template, url_for
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.query_service import QueryService
import os
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService


class InitiateLoginView(MethodView):
    """
    Handles the initial part of the login process.
    Authenticates, decides the login path (fast or slow), and renders
    either the chat page directly or the loading shell.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 onboarding_service: OnboardingService,
                 query_service: QueryService,
                 prompt_service: PromptService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.onboarding_service = onboarding_service
        self.query_service = query_service
        self.prompt_service = prompt_service

    def post(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        email = request.form.get('email')
        password = request.form.get('password')

        # 1. Authenticate user and create the unified session.
        auth_response = self.profile_service.login(
            company_short_name=company_short_name,
            email=email,
            password=password
        )

        if not auth_response['success']:
            return render_template(
                'index.html',
                company_short_name=company_short_name,
                company=company,
                form_data={"email": email},
                alert_message=auth_response["message"]
            ), 400

        user_identifier = auth_response['user_identifier']

        # 2. PREPARE and DECIDE: Call prepare_context to determine the path.
        prep_result = self.query_service.prepare_context(
            company_short_name=company_short_name, user_identifier=user_identifier
        )

        if prep_result.get('rebuild_needed'):
            # --- SLOW PATH: Context rebuild is needed ---
            # Render the shell, which will call LoginView for the heavy lifting.
            branding_data = self.branding_service.get_company_branding(company)
            onboarding_cards = self.onboarding_service.get_onboarding_cards(company)
            target_url = url_for('login', company_short_name=company_short_name, _external=True)

            return render_template(
                "onboarding_shell.html",
                iframe_src_url=target_url,
                external_user_id='',
                branding=branding_data,
                onboarding_cards=onboarding_cards
            )
        else:
            # --- FAST PATH: Context is already cached ---
            # Render chat.html directly.
            try:
                session_info = self.profile_service.get_current_session_info()
                user_profile = session_info.get('profile', {})

                prompts = self.prompt_service.get_user_prompts(company_short_name)
                branding_data = self.branding_service.get_company_branding(company)

                return render_template("chat.html",
                                       user_is_local=user_profile.get('user_is_local'),
                                       user_email=user_profile.get('user_email'),
                                       branding=branding_data,
                                       prompts=prompts,
                                       iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                       ), 200
            except Exception as e:
                return render_template("error.html", company=company, company_short_name=company_short_name,
                                       message=f"Error in fast path: {str(e)}"), 500


class LoginView(MethodView):
    """
    Handles the heavy-lifting part of the login, ONLY triggered by the iframe
    in the slow path (when context rebuild is needed).
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 query_service: QueryService,
                 prompt_service: PromptService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.branding_service = branding_service

    def get(self, company_short_name: str):
        # 1. Use the new centralized method to get session info.
        session_info = self.profile_service.get_current_session_info()
        user_identifier = session_info.get('user_identifier')
        user_profile = session_info.get('profile', {})

        if not user_identifier:
            # This can happen if the session expires or is invalid.
            return redirect(url_for('login_page', company_short_name=company_short_name))

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        try:
            # 2. Finalize the context rebuild (the potentially long-running task).
            # We pass the identifier, and the service resolves if it's local or external.
            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            # 3. Get the necessary data for the chat page.
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            branding_data = self.branding_service.get_company_branding(company)

            # 4. Render the final chat page.
            return render_template("chat.html",
                                   user_is_local=user_profile.get('user_is_local'),
                                   user_email=user_profile.get('user_email'),
                                   branding=branding_data,
                                   prompts=prompts,
                                   iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                   ), 200

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message=f"An unexpected error occurred during context loading: {str(e)}"), 500