from __future__ import annotations

import secrets

from flask import abort, flash, redirect, render_template, request, session, url_for
from flask.views import MethodView
from injector import inject

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.profile_service import ProfileService


class AccountView(MethodView):
    DEFAULT_SECTION = "profile"

    @inject
    def __init__(self, profile_service: ProfileService, branding_service: BrandingService,
                 i18n_service: I18nService, config_service: ConfigurationService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service
        self.config_service = config_service

    def get(self, company_short_name: str):
        company, session_info = self._resolve_session(company_short_name)
        return self._render_account_page(company_short_name, company, session_info,
                                         active_section=self._resolve_active_section())

    def post(self, company_short_name: str):
        company, session_info = self._resolve_session(company_short_name)
        action = request.form.get("action")
        if action not in {"update_profile", "update_preferences"}:
            abort(400)
        expected = session.get("account_csrf_token", "")
        if not expected or not secrets.compare_digest(expected, request.form.get("csrf_token", "")):
            abort(400)

        section = "profile" if action == "update_profile" else "preferences"
        result = self.profile_service.update_account(
            company_short_name, session_info, action=action,
            first_name=request.form.get("first_name", ""),
            last_name=request.form.get("last_name", ""),
            language=request.form.get("language", ""),
        )
        if result.get("error"):
            flash(self.i18n_service.t(result["error"]), "error")
            return self._render_account_page(company_short_name, company, session_info,
                                             active_section=section), result.get("status_code", 400)
        if action == "update_preferences":
            flash(self.i18n_service.t("ui.account.saved", lang=request.form["language"]), "success")
        else:
            flash(self.i18n_service.t("ui.account.saved"), "success")
        return redirect(url_for("account", company_short_name=company_short_name, section=section), code=303)

    def _resolve_active_section(self) -> str:
        section = request.args.get("section", self.DEFAULT_SECTION)
        return section if section in {"profile", "preferences"} else self.DEFAULT_SECTION

    def _resolve_session(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            abort(404)
        info = self.profile_service.get_current_session_info(company_short_name=company_short_name) or {}
        if not info.get("user_identifier") or info.get("company_short_name") != company_short_name or not info.get("profile"):
            abort(redirect(url_for("home", company_short_name=company_short_name)))
        return company, info

    def _render_account_page(self, company_short_name: str, company, session_info: dict, *,
                             active_section: str | None = None, template_name: str = "account.html",
                             extra_context: dict | None = None):
        # Enterprise extends this shell with the user's external connections.
        if "account_csrf_token" not in session:
            session["account_csrf_token"] = secrets.token_urlsafe(32)
        default_model, models = self.config_service.get_llm_configuration(company_short_name)
        defaults = self.config_service.get_llm_request_defaults(company_short_name) or {}
        return render_template(
            template_name, **(extra_context or {}), company=company,
            company_short_name=company_short_name, user_identifier=session_info["user_identifier"],
            branding=self.branding_service.get_company_branding(company_short_name),
            account=self.profile_service.get_account_profile(company_short_name, session_info),
            account_csrf_token=session["account_csrf_token"],
            llm_default_model=default_model,
            llm_available_models=models,
            llm_default_reasoning_effort=str((defaults.get("reasoning") or {}).get("effort") or "").strip().lower(),
            account_toolbar=True,
            active_section=active_section or self.DEFAULT_SECTION,
        )
