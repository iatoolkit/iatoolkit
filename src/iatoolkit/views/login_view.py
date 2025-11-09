# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import (request, redirect, render_template, url_for,
                   render_template_string, flash)
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.views.base_login_view import BaseLoginView
import logging


class LoginView(BaseLoginView):
    """
    Handles login for local users.
    Authenticates and then delegates the path decision (fast/slow) to the base class.
    """
    def post(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        branding_data = self.branding_service.get_company_branding(company)
        email = request.form.get('email')
        password = request.form.get('password')

        # 1. Authenticate internal user
        auth_response = self.auth_service.login_local_user(
            company_short_name=company_short_name,
            email=email,
            password=password
        )

        if not auth_response['success']:
            flash(auth_response["message"], 'error')
            home_template = self.utility.get_company_template(company_short_name, "home.html")

            return render_template_string(
                home_template,
                company_short_name=company_short_name,
                company=company,
                branding=branding_data,
                form_data={"email": email},
            ), 400

        user_identifier = auth_response['user_identifier']

        # 3. define URL to call when slow path is finished
        target_url = url_for('finalize_no_token',
                             company_short_name=company_short_name,
                             _external=True)

        # 2. Delegate the path decision to the centralized logic.
        try:
            return self._handle_login_path(company, user_identifier, target_url)
        except Exception as e:
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500


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
                 branding_service: BrandingService,
                 onboarding_service: OnboardingService,
                 jwt_service: JWTService,
                 i18n_service: I18nService
                 ):
        self.profile_service = profile_service
        self.jwt_service = jwt_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.branding_service = branding_service
        self.onboarding_service = onboarding_service
        self.i18n_service = i18n_service

    def get(self, company_short_name: str, token: str = None):
        try:
            session_info = self.profile_service.get_current_session_info()
            if session_info:
                # session exists, internal user
                user_identifier = session_info.get('user_identifier')
                token = ''
            elif token:
                # user identified by api-key
                payload = self.jwt_service.validate_chat_jwt(token)
                if not payload:
                    logging.warning("Fallo crítico: No se pudo leer el auth token.")
                    return redirect(url_for('home', company_short_name=company_short_name))

                user_identifier = payload.get('user_identifier')
            else:
                logging.error("missing session information or auth token")
                return redirect(url_for('home', company_short_name=company_short_name))

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html',
                            company_short_name=company_short_name,
                            message="Empresa no encontrada"), 404
            branding_data = self.branding_service.get_company_branding(company)

            # 2. Finalize the context rebuild (the heavy task).
            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            # 3. render the chat page.
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            onboarding_cards = self.onboarding_service.get_onboarding_cards(company)

            # Get the entire 'js_messages' block in the correct language.
            js_translations = self.i18n_service.get_translation_block('js_messages')

            return render_template(
                "chat.html",
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                branding=branding_data,
                prompts=prompts,
                onboarding_cards=onboarding_cards,
                js_translations=js_translations,
                redeem_token=token
            )

        except Exception as e:
            return render_template("error.html",
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   message=f"An unexpected error occurred during context loading: {str(e)}"), 500

