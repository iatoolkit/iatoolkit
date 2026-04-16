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
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.repositories.models import Company
import logging


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
                 config_service: ConfigurationService,
                 query_service: QueryService,
                 i18n_service: I18nService,
                 utility: Utility
                 ):
        self.profile_service = profile_service
        self.auth_service = auth_service
        self.jwt_service = jwt_service
        self.branding_service = branding_service
        self.prompt_service = prompt_service
        self.config_service = config_service
        self.query_service = query_service
        self.i18n_service = i18n_service
        self.utility = utility


    def _handle_login_path(self,
                           company_short_name: str,
                           user_identifier: str,
                           target_url: str,
                           redeem_token: str = None):
        """
        Centralized logic to decide between the fast path and the slow path.
        """
        self._trigger_warmup(company_short_name, "post_login")

        # --- Get the company branding and onboarding_cards
        branding_data = self.branding_service.get_company_branding(company_short_name)
        onboarding_cards = self.config_service.get_configuration(company_short_name, 'onboarding_cards')

        # this service decides is the context needs to be rebuilt or not
        prep_result = self.query_service.prepare_context(
            company_short_name=company_short_name, user_identifier=user_identifier
        )

        if prep_result.get('rebuild_needed'):
            # --- SLOW PATH: Render the loading shell ---
            return render_template(
                "onboarding_shell.html",
                iframe_src_url=target_url,
                branding=branding_data,
                onboarding_cards=onboarding_cards
            )
        else:
            # --- FAST PATH: Render the chat page directly ---
            # LLM configuration: default model and availables
            default_llm_model, available_llm_models = self.config_service.get_llm_configuration(company_short_name)

            prompts = self.prompt_service.get_prompts(company_short_name)

            # Get the entire 'js_messages' block in the correct language.
            js_translations = self.i18n_service.get_translation_block('js_messages')

            return render_template(
                "chat.html",
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                prompts=prompts,
                branding=branding_data,
                onboarding_cards=onboarding_cards,
                js_translations=js_translations,
                redeem_token=redeem_token,
                llm_default_model=default_llm_model,
                llm_available_models = available_llm_models,
                )

    def _trigger_warmup(self, company_short_name: str, trigger: str):
        try:
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.warmup_service import WarmupService

            warmup_service = current_iatoolkit().get_injector().get(WarmupService)
            warmup_service.warmup_company(company_short_name, trigger=trigger)
        except Exception as e:
            logging.debug("Warm-up trigger skipped for company='%s' trigger='%s': %s", company_short_name, trigger, e)
