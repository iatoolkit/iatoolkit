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
    Handles the initial, fast part of the login process.
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

        # 1. Autenticar al usuario
        auth_response = self.profile_service.login(
            company_short_name=company_short_name,
            email=email,
            password=password
        )

        if not auth_response['success']:
            return render_template(
                'login.html', company_short_name=company_short_name, company=company,
                form_data={"email": email}, alert_message=auth_response["message"]
            ), 400

        user_id = auth_response['user'].id

        # 2. PREPARAR y DECIDIR: Llamar a prepare_context para determinar el camino.
        prep_result = self.query_service.prepare_context(
            company_short_name=company_short_name, local_user_id=user_id
        )

        if prep_result.get('rebuild_needed'):
            # --- CAMINO LENTO: Se necesita reconstrucción ---
            # Mostramos el shell, que llamará a LoginView para el trabajo pesado.
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
            # --- CAMINO RÁPIDO: El contexto ya está en caché ---
            # Renderizamos el chat directamente.
            try:
                prompts = self.prompt_service.get_user_prompts(company_short_name)
                branding_data = self.branding_service.get_company_branding(company)

                return render_template("chat.html",
                                       company_short_name=company_short_name,
                                       auth_method="Session",
                                       session_jwt=None,
                                       user_email=email,
                                       branding=branding_data,
                                       prompts=prompts,
                                       iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                       ), 200
            except Exception as e:
                return render_template("error.html", company=company, company_short_name=company_short_name,
                                       message=f"Error inesperado en el camino rápido: {str(e)}"), 500


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
        """
        Handles the finalization of the context rebuild.
        """
        user_profile = self.profile_service.get_current_user_profile()
        user_id = user_profile.get('id')
        if not user_id:
            # Si la sesión expira en medio del proceso, redirigir al login
            return redirect(url_for('login_page', company_short_name=company_short_name))

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        try:
            # 1. Ejecutar la finalización (la operación potencialmente LENTA de 30s)
            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                local_user_id=user_id
            )

            # 2. Obtener datos y renderizar el chat
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            branding_data = self.branding_service.get_company_branding(company)

            return render_template("chat.html",
                                   company_short_name=company_short_name,
                                   auth_method="Session",
                                   session_jwt=None,
                                   user_email=user_profile.get('email'),
                                   branding=branding_data,
                                   prompts=prompts,
                                   iatoolkit_base_url=os.getenv('IATOOLKIT_BASE_URL'),
                                   ), 200

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message=f"Ha ocurrido un error inesperado durante la carga del contexto: {str(e)}"), 500