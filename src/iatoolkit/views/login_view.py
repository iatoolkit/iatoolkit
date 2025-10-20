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
    Handles the initial, fast part of the standard login process.
    Authenticates user credentials, sets up the server-side session,
    and immediately returns the loading shell page.
    """
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 onboarding_service: OnboardingService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.onboarding_service = onboarding_service


    def post(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message="Empresa no encontrada"), 404

        email = request.form.get('email')
        password = request.form.get('password')

        # 1. authenticate the user
        response = self.profile_service.login(
            company_short_name=company_short_name,
            email=email,
            password=password
        )

        if not response['success']:
            return render_template(
                'login.html',
                company_short_name=company_short_name,
                company=company,
                form_data={
                    "email": email,
                    "password": password,
                },
                alert_message=response["message"]), 400

        # 2. Get branding and onboarding data for the shell page
        branding_data = self.branding_service.get_company_branding(company)
        onboarding_cards = self.onboarding_service.get_onboarding_cards(company)

        target_url = url_for('login',
                        company_short_name=company_short_name,
                        _external=True)

        # 3. Render the shell page, passing the URL for the heavy lifting
        # The shell's AJAX call will now be authenticated via the session cookie.
        return render_template(
            "onboarding_shell.html",
            iframe_src_url=target_url,
            external_user_id='',
            branding=branding_data,
            onboarding_cards=onboarding_cards
        )


class LoginView(MethodView):
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
        """
        Handles the heavy-lifting part of the login, triggered by the iframe.
        The user is already authenticated via the session cookie.
        """
        # 1. Retrieve user and company info from the session.
        user_profile = self.profile_service.get_current_user_profile()
        user_id = user_profile.get('user_id')
        if not user_id:
            # This can happen if the session expires or is invalid.
            # Redirecting to home is a safe fallback.
            return redirect(url_for('home', company_short_name=company_short_name))

        user_email = user_profile.get('email')
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        try:
            # 2. Init the company/user LLM context (the long-running task).
            self.query_service.llm_init_context(
                company_short_name=company_short_name,
                local_user_id=user_id
            )

            # 3. Get the prompt list from backend.
            prompts = self.prompt_service.get_user_prompts(company_short_name)

            # 4. Get the branding data.
            branding_data = self.branding_service.get_company_branding(company)

            # 5. Render the final chat page.
            return render_template("chat.html",
                                   company_short_name=company_short_name,
                                   auth_method="Session",
                                   session_jwt=None,  # No JWT in this flow
                                   user_email=user_email,
                                   branding=branding_data,
                                   prompts=prompts,
                                   iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                   ), 200

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message="Ha ocurrido un error inesperado."), 500