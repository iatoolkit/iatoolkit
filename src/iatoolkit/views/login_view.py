# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import request, redirect, render_template, url_for
from injector import inject
from iatoolkit.repositories.models import User
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.query_service import QueryService
import os
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.services.branding_service import BrandingService

class InitiateLoginView(MethodView):
    """
    Handles the initial, fast part of the standard login process.
    Authenticates user credentials, sets up the server-side session,
    and immediately returns the loading shell page.
    """
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,):
        self.profile_service = profile_service
        self.branding_service = branding_service

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
                alert_message=response["error"]), 400

        # 2. Get branding data for the shell page
        branding_data = self.branding_service.get_company_branding(company)

        # 3. Render the shell page, passing the URL for the heavy lifting
        # The shell's AJAX call will now be authenticated via the session cookie.
        return render_template(
            "login_shell.html",
            data_source_url=url_for('login',
                        company_short_name=company_short_name,
                        _external=True),
            external_user_id='',
            branding=branding_data,
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
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        return render_template('login.html',
                               company=company,
                               company_short_name=company_short_name)

    def post(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)

        # 1. The user is already authenticated by the session cookie set by InitiateLoginView.
        # We just retrieve the user and company IDs from the session.
        user_id = SessionManager.get('user_id')
        if not user_id:
            return render_template('error.html', message="Usuario no encontrado"), 404

        user_email = SessionManager.get('user')['email']

        try:
            # 2. init the company/user LLM context.
            self.query_service.llm_init_context(
                company_short_name=company_short_name,
                local_user_id=user_id
            )

            # 3. get the prompt list from backend
            prompts = self.prompt_service.get_user_prompts(company_short_name)

            # 4. get the branding data
            branding_data = self.branding_service.get_company_branding(company)

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

