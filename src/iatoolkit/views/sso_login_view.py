# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Sign-in with the identity provider a company configured (BL-031).

``/<company>/login/sso`` sends the browser to the company's provider;
``/auth/sso/callback`` is the single return URL every company registers at its
provider. What ties the two together is a pending entry in the server-side
session, keyed by ``state``: the company, the issuer, the nonce and the PKCE
verifier. Nothing the provider sends back is trusted to name the company.
"""

import logging
import time
from urllib.parse import urljoin

from flask import flash, redirect, render_template, request, url_for
from flask.views import MethodView
from injector import inject

from iatoolkit.common.interfaces.identity_provider_resolver import IdentityProviderResolver
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.common.user_errors import unexpected_error_message
from iatoolkit.infra.oidc_client import OidcClient, OidcError, normalize_issuer
from iatoolkit.common.util import Utility
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.base_login_view import BaseLoginView
from iatoolkit.views.login_view import _normalize_safe_next_target

PENDING_KEY = "sso_oauth_states"
# A sign-in has this long to come back from the provider.
PENDING_TTL_SECONDS = 10 * 60
# Several tabs may start a sign-in at once; older entries beyond this are dropped.
MAX_PENDING = 5


def _pending_states() -> dict:
    pending = SessionManager.get(PENDING_KEY, {})
    if not isinstance(pending, dict):
        return {}
    now = time.time()
    return {state: entry for state, entry in pending.items()
            if isinstance(entry, dict) and now - float(entry.get("issued_at") or 0) < PENDING_TTL_SECONDS}


def _store_pending_states(pending: dict) -> None:
    if pending:
        SessionManager.set(PENDING_KEY, pending)
    else:
        SessionManager.remove(PENDING_KEY)


class SsoLoginStartView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 identity_provider_resolver: IdentityProviderResolver,
                 oidc_client: OidcClient,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.identity_provider_resolver = identity_provider_resolver
        self.oidc_client = oidc_client
        self.i18n_service = i18n_service

    def get(self, company_short_name: str):
        current_lang = request.args.get('lang') or 'en'
        next_target = _normalize_safe_next_target(request.args.get('next'))
        if not self.profile_service.get_company_by_short_name(company_short_name):
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        home = url_for('home', company_short_name=company_short_name, lang=current_lang)
        provider = self.identity_provider_resolver.get_provider(company_short_name)
        if provider is None:
            flash(self.i18n_service.t('errors.auth.sso_not_available'), 'error')
            return redirect(home)

        try:
            authorization = self.oidc_client.build_authorization_request(
                provider.oidc,
                url_for('login_sso_callback', _external=True),
                login_hint=(request.args.get('login_hint') or '').strip()[:254] or None,
            )
        except OidcError as exc:
            logging.warning("SSO login start failed. company=%s provider=%s reason_code=%s",
                            company_short_name, provider.provider_type, exc.reason_code)
            flash(self.i18n_service.t(exc.message_key), 'error')
            return redirect(home)

        pending = _pending_states()
        for stale in sorted(pending, key=lambda s: pending[s].get("issued_at") or 0)[:max(0, len(pending) - MAX_PENDING + 1)]:
            pending.pop(stale)
        pending[authorization.state] = {
            'company_short_name': company_short_name,
            'issuer': normalize_issuer(provider.oidc.issuer),
            'nonce': authorization.nonce,
            'code_verifier': authorization.code_verifier,
            'lang': current_lang,
            'next_target': next_target,
            'issued_at': time.time(),
        }
        _store_pending_states(pending)
        return redirect(authorization.url)


class SsoLoginCallbackView(BaseLoginView):
    @inject
    def __init__(self,
                 identity_provider_resolver: IdentityProviderResolver,
                 profile_service: ProfileService,
                 auth_service: AuthService,
                 jwt_service: JWTService,
                 branding_service: BrandingService,
                 prompt_service: PromptService,
                 config_service: ConfigurationService,
                 query_service: QueryService,
                 i18n_service: I18nService,
                 utility: Utility):
        super().__init__(profile_service, auth_service, jwt_service, branding_service, prompt_service,
                         config_service, query_service, i18n_service, utility)
        self.identity_provider_resolver = identity_provider_resolver

    def get(self):
        state = request.args.get('state') or ''
        code = request.args.get('code') or ''
        provider_error = request.args.get('error')

        pending = _pending_states()
        entry = pending.pop(state, None) if state else None
        _store_pending_states(pending)      # single use, whatever happens next

        if not entry:
            logging.warning("SSO callback with a missing or expired state.")
            flash(self.i18n_service.t('errors.auth.sso_login_failed'), 'error')
            return redirect(url_for('root_redirect', lang=request.args.get('lang') or 'en'))

        company_short_name = entry['company_short_name']
        current_lang = entry.get('lang') or 'en'
        next_target = _normalize_safe_next_target(entry.get('next_target'))
        home = url_for('home', company_short_name=company_short_name, lang=current_lang)

        if provider_error or not code:
            # The provider's error code is safe to log; its description is not shown.
            logging.warning("SSO callback returned an error. company=%s error=%s code_present=%s",
                            company_short_name, str(provider_error or '')[:60], bool(code))
            self.auth_service.log_access(company_short_name=company_short_name, auth_type='sso',
                                         outcome='failure',
                                         reason_code=f"SSO_PROVIDER_{str(provider_error or 'NO_CODE')[:40].upper()}")
            flash(self.i18n_service.t('errors.auth.sso_login_failed'), 'error')
            return redirect(home)

        # The provider must still be the one this sign-in started with: a changed
        # or removed configuration in between cancels it.
        provider = self.identity_provider_resolver.get_provider(company_short_name)
        if provider is None or normalize_issuer(provider.oidc.issuer) != entry.get('issuer'):
            logging.warning("SSO callback for a provider no longer configured. company=%s", company_short_name)
            flash(self.i18n_service.t('errors.auth.sso_not_available'), 'error')
            return redirect(home)

        auth_response = self.auth_service.login_sso_user(
            provider,
            code=code,
            redirect_uri=url_for('login_sso_callback', _external=True),
            code_verifier=entry.get('code_verifier') or '',
            nonce=entry.get('nonce') or '',
        )
        if not auth_response.get('success'):
            flash(auth_response.get('message') or self.i18n_service.t('errors.auth.sso_login_failed'), 'error')
            return redirect(home)

        if next_target:
            return redirect(urljoin(request.url_root, next_target.lstrip('/')))

        try:
            return self._handle_login_path(
                company_short_name,
                auth_response['user_identifier'],
                url_for('finalize_no_token', company_short_name=company_short_name,
                        _external=True, lang=current_lang),
            )
        except Exception as e:
            message = unexpected_error_message(self.i18n_service, e, where="sso_login_view",
                                               key="errors.templates.processing_error")
            return render_template("error.html", company_short_name=company_short_name, message=message), 500
