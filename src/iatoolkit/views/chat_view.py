from flask import render_template, redirect, url_for, request
from flask.views import MethodView
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService

class ChatView(MethodView):
    """
    Handles direct access to the chat interface.
    Validates if the user has an active session for the company.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 config_service: ConfigurationService,
                 prompt_service: PromptService,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.config_service = config_service
        self.prompt_service = prompt_service
        self.i18n_service = i18n_service

    def get(self, company_short_name: str):
        # 1. Validate Company
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        # 2. Check Session
        session_info = self.profile_service.get_current_session_info()
        user_identifier = session_info.get('user_identifier')
        session_company = session_info.get('company_short_name')

        # If no user or session belongs to another company -> Redirect to Home
        if not user_identifier or session_company != company_short_name:
            return redirect(url_for('home', company_short_name=company_short_name))

        # 3. Prepare Context for Chat
        # (This logic mirrors the FAST PATH in BaseLoginView)
        try:
            branding_data = self.branding_service.get_company_branding(company_short_name)
            onboarding_cards = self.config_service.get_configuration(company_short_name, 'onboarding_cards')
            default_llm_model, available_llm_models = self.config_service.get_llm_configuration(company_short_name)
            prompts = self.prompt_service.get_user_prompts(company_short_name)
            js_translations = self.i18n_service.get_translation_block('js_messages')

            return render_template(
                "chat.html",
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                prompts=prompts,
                branding=branding_data,
                onboarding_cards=onboarding_cards,
                js_translations=js_translations,
                llm_default_model=default_llm_model,
                llm_available_models=available_llm_models,
                # redeem_token is None for direct access
                redeem_token=None
            )
        except Exception as e:
            # Fallback error handling
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            branding_data = self.branding_service.get_company_branding(company_short_name)
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500