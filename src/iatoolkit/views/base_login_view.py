# iatoolkit/views/base_login_view.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, url_for
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.repositories.models import Company


class BaseLoginView(MethodView):
    """
    Base class for views that initiate a session and decide the context
    loading path (fast or slow).
    """
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 auth_service: AuthService,
                 jwt_service: JWTService,
                 branding_service: BrandingService,
                 prompt_service: PromptService,
                 onboarding_service: OnboardingService,
                 query_service: QueryService
                 ):
        self.profile_service = profile_service
        self.auth_service = auth_service
        self.jwt_service = jwt_service
        self.branding_service = branding_service
        self.prompt_service = prompt_service
        self.onboarding_service = onboarding_service
        self.query_service = query_service


    def _handle_login_path(self,
                           company: Company,
                           user_identifier: str,
                           target_url: str,
                           redeem_token: str = None):
        """
        Centralized logic to decide between the fast path and the slow path.
        """
        # --- Get the company branding ---
        branding_data = self.branding_service.get_company_branding(company)
        company_short_name = company.short_name

        # this service decides is the context needs to be rebuilt or not
        prep_result = self.query_service.prepare_context(
            company_short_name=company.short_name, user_identifier=user_identifier
        )

        if prep_result.get('rebuild_needed'):
            # --- SLOW PATH: Render the loading shell ---
            onboarding_cards = self.onboarding_service.get_onboarding_cards(company)

            return render_template(
                "onboarding_shell.html",
                iframe_src_url=target_url,
                branding=branding_data,
                onboarding_cards=onboarding_cards
            )
        else:
            # --- FAST PATH: Render the chat page directly ---
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            onboarding_cards = self.onboarding_service.get_onboarding_cards(company)
            return render_template(
                "chat.html",
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                branding=branding_data,
                prompts=prompts,
                onboarding_cards=onboarding_cards,
                redeem_token=redeem_token
            )