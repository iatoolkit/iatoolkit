# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import request, redirect, render_template, url_for
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.views.base_login_view import BaseLoginView


class LoginView(BaseLoginView):
    """
    Handles login for local users.
    Authenticates and then delegates the path decision (fast/slow) to the base class.
    """

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
            branding_data = self.branding_service.get_company_branding(company)

            return render_template(
                'index.html',
                company_short_name=company_short_name,
                company=company,
                branding=branding_data,
                form_data={"email": email},
                alert_message=auth_response["message"]
            ), 400

        user_identifier = auth_response['user_identifier']

        # 2. Delegate the path decision to the centralized logic.
        try:
            return self._handle_login_path(company_short_name, user_identifier, company)
        except Exception as e:
            return render_template("error.html", company=company, company_short_name=company_short_name,
                                   message=f"Error processing login path: {str(e)}"), 500


class FinalizeContextView(MethodView):
    """
    Finalizes context loading in the slow path.
    This view is invoked by the iframe inside onboarding_shell.html.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 query_service: QueryService,
                 prompt_service: PromptService,
                 branding_service: BrandingService
                 ):
        self.profile_service = profile_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.branding_service = branding_service

    def get(self, company_short_name: str):
        # 1. Use the centralized method to get session info.
        session_info = self.profile_service.get_current_session_info()
        user_identifier = session_info.get('user_identifier')

        if not user_identifier:
            # This can happen if the session expires or is invalid.
            return redirect(url_for('login_page', company_short_name=company_short_name))

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        try:
            # 2. Finalize the context rebuild (the heavy task).
            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            # 3. render the chat page.
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            branding_data = self.branding_service.get_company_branding(company)

            return render_template(
                "chat.html",
                branding=branding_data,
                prompts=prompts,
            )

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message=f"An unexpected error occurred during context loading: {str(e)}"), 500