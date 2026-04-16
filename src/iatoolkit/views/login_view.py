# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import (request, redirect, render_template, url_for,
                   render_template_string, flash)
from injector import inject
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.infra.google_auth_client import GoogleAuthClient
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.views.base_login_view import BaseLoginView
import logging
import secrets
from urllib.parse import urlparse


def _normalize_safe_next_target(raw_target: str | None) -> str | None:
    target = str(raw_target or "").strip()
    if not target:
        return None

    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/"):
        return None
    if target.startswith("//"):
        return None
    return target


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

        branding_data = self.branding_service.get_company_branding(company_short_name)
        email = request.form.get('email')
        password = request.form.get('password')
        current_lang = request.form.get('lang') or request.args.get('lang') or 'en'

        # 1. Authenticate internal user
        auth_response = self.auth_service.login_local_user(
            company_short_name=company_short_name,
            email=email,
            password=password
        )

        if not auth_response['success']:
            flash(auth_response["message"], 'error')

            # Resolve the correct template name based on language (e.g., home_en.html or home_es.html)
            template_name = self.utility.get_template_by_language("home")
            home_template = self.utility.get_company_template(company_short_name, template_name)

            if not home_template:
                if self.utility.is_hosted_company_runtime(company_short_name):
                    return render_template(
                        "home_hosted_default.html",
                        company_short_name=company_short_name,
                        company=company,
                        branding=branding_data,
                        form_data={"email": email},
                    ), 400

                return render_template('error.html',
                                       message=f'Home template ({template_name}) not found.'), 500

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
                             _external=True,
                             lang=current_lang)

        # 2. Delegate the path decision to the centralized logic.
        try:
            return self._handle_login_path(company_short_name, user_identifier, target_url)
        except Exception as e:
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500


class GoogleLoginStartView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 google_auth_client: GoogleAuthClient,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.google_auth_client = google_auth_client
        self.i18n_service = i18n_service

    def get(self, company_short_name: str):
        current_lang = request.args.get('lang') or 'en'
        next_target = _normalize_safe_next_target(request.args.get('next'))
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template(
                'error.html',
                message=self.i18n_service.t('errors.templates.company_not_found')
            ), 404

        if not self.google_auth_client.is_enabled():
            flash(self.i18n_service.t('errors.auth.google_login_not_available'), 'error')
            return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        redirect_uri = url_for(
            'login_google_callback',
            _external=True,
        )

        pending_states = SessionManager.get('google_oauth_states', {})
        if not isinstance(pending_states, dict):
            pending_states = {}

        pending_states[state] = {
            'nonce': nonce,
            'company_short_name': company_short_name,
            'lang': current_lang,
        }
        if next_target:
            pending_states[state]['next_target'] = next_target
        SessionManager.set('google_oauth_states', pending_states)

        try:
            logging.debug(
                "Google login start redirect_uri=%s request_host=%s url_root=%s company=%s",
                redirect_uri,
                request.host,
                request.url_root,
                company_short_name,
            )
            authorization_url = self.google_auth_client.build_authorization_url(
                redirect_uri=redirect_uri,
                state=state,
                nonce=nonce,
            )
        except Exception:
            flash(self.i18n_service.t('errors.auth.google_login_failed'), 'error')
            return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

        return redirect(authorization_url)


class GoogleLoginCallbackView(BaseLoginView):
    def get(self):
        state = request.args.get('state') or ''
        code = request.args.get('code') or ''
        oauth_error = request.args.get('error')

        pending_states = SessionManager.get('google_oauth_states', {})
        if not isinstance(pending_states, dict):
            pending_states = {}

        pending_state = pending_states.pop(state, None)
        if pending_states:
            SessionManager.set('google_oauth_states', pending_states)
        else:
            SessionManager.remove('google_oauth_states')

        company_short_name = (pending_state or {}).get('company_short_name')
        current_lang = (pending_state or {}).get('lang') or request.args.get('lang') or 'en'
        next_target = _normalize_safe_next_target((pending_state or {}).get('next_target'))

        if not pending_state or not company_short_name:
            logging.warning("Google login callback missing or expired oauth state. state=%s", state)
            flash(self.i18n_service.t('errors.auth.google_login_failed'), 'error')
            return redirect(url_for('root_redirect', lang=current_lang))

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template(
                'error.html',
                message=self.i18n_service.t('errors.templates.company_not_found')
            ), 404

        if oauth_error or not code:
            logging.warning(
                "Google login callback returned oauth error. company=%s error=%s code_present=%s",
                company_short_name,
                oauth_error,
                bool(code),
            )
            flash(self.i18n_service.t('errors.auth.google_login_failed'), 'error')
            return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

        redirect_uri = url_for(
            'login_google_callback',
            _external=True,
        )
        auth_response = self.auth_service.login_google_user(
            company_short_name=company_short_name,
            code=code,
            state=state,
            nonce=pending_state.get('nonce', ''),
            redirect_uri=redirect_uri,
        )

        if not auth_response.get('success'):
            logging.warning(
                "Google login callback rejected login. company=%s reason_code=%s message=%s",
                company_short_name,
                auth_response.get('reason_code'),
                auth_response.get('message'),
            )
            flash(auth_response.get('message') or self.i18n_service.t('errors.auth.google_login_failed'), 'error')
            return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

        if next_target:
            return redirect(next_target)

        target_url = url_for(
            'finalize_no_token',
            company_short_name=company_short_name,
            _external=True,
            lang=current_lang,
        )

        try:
            return self._handle_login_path(
                company_short_name,
                auth_response['user_identifier'],
                target_url,
            )
        except Exception as e:
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                message=message,
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
                 config_service: ConfigurationService,
                 jwt_service: JWTService,
                 i18n_service: I18nService
                 ):
        self.profile_service = profile_service
        self.jwt_service = jwt_service
        self.query_service = query_service
        self.prompt_service = prompt_service
        self.branding_service = branding_service
        self.config_service = config_service
        self.i18n_service = i18n_service

    def get(self, company_short_name: str, token: str = None):
        try:
            # get the languaje from the query string if it exists
            current_lang = request.args.get('lang') or 'en'

            session_info = self.profile_service.get_current_session_info(company_short_name=company_short_name)
            if session_info:
                # session exists, internal user
                user_identifier = session_info.get('user_identifier')
                token = ''
            elif token:
                # user identified by api-key
                payload = self.jwt_service.validate_chat_jwt(token)
                if not payload:
                    logging.warning("Fallo crítico: No se pudo leer el auth token.")
                    return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

                user_identifier = payload.get('user_identifier')
            else:
                logging.error("missing session information or auth token")
                return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html',
                            company_short_name=company_short_name,
                            message="Empresa no encontrada"), 404
            branding_data = self.branding_service.get_company_branding(company_short_name)

            default_llm_model, available_llm_models = self.config_service.get_llm_configuration(company_short_name)

            # 2. Finalize the context rebuild (the heavy task).
            self.query_service.set_context_for_llm(
                company_short_name=company_short_name,
                user_identifier=user_identifier
            )

            # 3. render the chat page.
            prompts = self.prompt_service.get_prompts(company_short_name)
            onboarding_cards = self.config_service.get_configuration(company_short_name, 'onboarding_cards')

            # Get the entire 'js_messages' block in the correct language.
            js_translations = self.i18n_service.get_translation_block('js_messages')

            # Importante: no envolver con make_response; dejar que Flask gestione
            # tanto strings como tuplas (string, status) que pueda devolver render_template
            return render_template(
                "chat.html",
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                branding=branding_data,
                prompts=prompts,
                onboarding_cards=onboarding_cards,
                js_translations=js_translations,
                redeem_token=token,
                llm_default_model=default_llm_model,
                llm_available_models=available_llm_models,
            )

        except Exception as e:
            return render_template("error.html",
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   message=f"An unexpected error occurred during context loading: {str(e)}"), 500
