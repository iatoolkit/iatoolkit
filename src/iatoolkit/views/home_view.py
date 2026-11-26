# iatoolkit/views/home_view.py
from flask import redirect, render_template, render_template_string, request, url_for
from flask.views import MethodView
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility
import logging
from iatoolkit.common.user_errors import unexpected_error_message

class HomeView(MethodView):
    """
    Handles the rendering of the company-specific home page with a login widget.
    If the custom template is not found or fails, it renders an error page.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService,
                 utility: Utility):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service
        self.util = utility

    def get(self, company_short_name: str):
        branding_data = {}
        try:
            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html',
                                       message=self.i18n_service.t('errors.templates.company_not_found')), 404

            self._trigger_warmup(company_short_name, "home_pre_login")

            branding_data = self.branding_service.get_company_branding(company_short_name)
            invitation_context = self.profile_service.signup_invitation_context(company_short_name, None)
            login_context = (
                {"signup_invitation_required": True}
                if isinstance(invitation_context, tuple) and invitation_context[0] is True else {}
            )

            template_name = self.util.get_template_by_language("home")
            home_template = self.util.get_company_template(company_short_name, template_name)

            # 2. No home page of its own (e.g. a company entered from its own portal).
            if not home_template:
                # Someone already signed in has nothing to do here: straight to the chat.
                session_info = self.profile_service.get_current_session_info(company_short_name=company_short_name)
                if session_info.get('user_identifier') and session_info.get('company_short_name') == company_short_name:
                    lang = request.args.get('lang')
                    return redirect(url_for('chat', company_short_name=company_short_name,
                                            **({'lang': lang} if lang else {})))

                # Hosted tenants get the onboarding home; any other company, just the sign-in.
                hosted = (
                    Utility.is_hosted_company_record(company)
                    or self.util.is_hosted_company_runtime(company_short_name)
                )
                return render_template(
                    "home_hosted_default.html" if hosted else "home_default.html",
                    company_short_name=company_short_name,
                    company=company,
                    branding=branding_data,
                    **login_context,
                )

            # 3. Si el archivo existe, intentamos leerlo y renderizarlo.
            return render_template_string(
                home_template,
                company_short_name=company_short_name,
                branding=branding_data,
                **login_context,
            )
        except Exception as e:
            message = unexpected_error_message(self.i18n_service, e, where="home_view", key="errors.templates.processing_error")
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500

    def _trigger_warmup(self, company_short_name: str, trigger: str):
        try:
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.warmup_service import WarmupService

            warmup_service = current_iatoolkit().get_injector().get(WarmupService)
            warmup_service.warmup_company(company_short_name, trigger=trigger)
        except Exception as e:
            logging.debug("Warm-up trigger skipped for company='%s' trigger='%s': %s", company_short_name, trigger, e)
