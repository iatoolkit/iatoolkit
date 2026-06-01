from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask.views import MethodView
from injector import inject

from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.mcp_token_service import McpTokenService
from iatoolkit.services.profile_service import ProfileService


class AccountView(MethodView):
    DEFAULT_SECTION = "general"
    TOKENS_SECTION = "mcp_tokens"

    @inject
    def __init__(
        self,
        profile_service: ProfileService,
        branding_service: BrandingService,
        i18n_service: I18nService,
        mcp_token_service: McpTokenService,
    ):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service
        self.mcp_token_service = mcp_token_service

    def get(self, company_short_name: str):
        resolved = self._resolve_session(company_short_name)
        if not isinstance(resolved, tuple):
            return resolved
        company, session_info = resolved
        return self._render_account_page(
            company_short_name,
            company,
            session_info,
            active_section=self._resolve_active_section(),
        )

    def post(self, company_short_name: str):
        resolved = self._resolve_session(company_short_name)
        if not isinstance(resolved, tuple):
            return resolved
        company, session_info = resolved
        user_identifier = session_info["user_identifier"]

        created_token = None
        created_token_id = None
        active_section = self._resolve_active_section(default=self.TOKENS_SECTION)
        action = str(request.form.get("action") or "").strip()
        if action == "create_token":
            result = self.mcp_token_service.create_user_token(
                company_short_name,
                user_identifier,
                name=request.form.get("name"),
                expires_in_days=request.form.get("expires_in_days"),
                created_by_identifier=user_identifier,
            )
            if result.get("error"):
                flash(result["error"], "error")
            else:
                payload = result.get("data") or {}
                created_token = (payload.get("token") or "").strip() or None
                created_token_id = payload.get("id")
                flash(self.i18n_service.t("ui.account.mcp_token_created_flash"), "success")
        elif action == "revoke_token":
            result = self.mcp_token_service.revoke_user_token(
                company_short_name,
                user_identifier,
                token_id=int(request.form.get("token_id") or 0),
            )
            if result.get("error"):
                flash(result["error"], "error")
            else:
                flash(self.i18n_service.t("ui.account.mcp_token_revoked_flash"), "success")
        else:
                flash(self.i18n_service.t("ui.account.mcp_token_unknown_action"), "error")

        return self._render_account_page(
            company_short_name,
            company,
            session_info,
            created_token=created_token,
            created_token_id=created_token_id,
            active_section=active_section,
        )

    def _resolve_active_section(self, default: str | None = None) -> str:
        allowed_sections = {self.DEFAULT_SECTION, self.TOKENS_SECTION}
        candidate = str(request.values.get("section") or default or self.DEFAULT_SECTION).strip().lower()
        return candidate if candidate in allowed_sections else self.DEFAULT_SECTION

    def _resolve_session(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template(
                "error.html",
                message=self.i18n_service.t("errors.templates.company_not_found"),
            ), 404

        session_info = self.profile_service.get_current_session_info(company_short_name=company_short_name)
        user_identifier = (session_info or {}).get("user_identifier")
        session_company = (session_info or {}).get("company_short_name")
        if not user_identifier or session_company != company_short_name:
            return redirect(url_for("home", company_short_name=company_short_name))

        return company, session_info

    def _render_account_page(
        self,
        company_short_name: str,
        company,
        session_info: dict,
        *,
        created_token: str | None = None,
        created_token_id: int | None = None,
        active_section: str | None = None,
    ):
        branding_data = self.branding_service.get_company_branding(company_short_name)
        tokens_result = self.mcp_token_service.list_user_tokens(company_short_name, session_info["user_identifier"])
        tokens = (tokens_result.get("data") or []) if not tokens_result.get("error") else []
        mcp_server_url = self.mcp_token_service.build_mcp_server_url(company_short_name)
        created_token_connection_snippet = None
        if created_token:
            created_token_connection_snippet = self.mcp_token_service.build_mcp_connection_snippet(
                company_short_name=company_short_name,
                mcp_server_url=mcp_server_url,
                bearer_token=created_token,
            )

        return render_template(
            "account.html",
            company=company,
            company_short_name=company_short_name,
            user_identifier=session_info["user_identifier"],
            branding=branding_data,
            tokens=tokens,
            created_token=created_token,
            created_token_id=created_token_id,
            mcp_server_url=mcp_server_url,
            created_token_connection_snippet=created_token_connection_snippet,
            active_section=active_section or self.DEFAULT_SECTION,
        )

    @staticmethod
    def _build_mcp_server_url(company_short_name: str) -> str:
        return McpTokenService.build_mcp_server_url(company_short_name)

    @staticmethod
    def _build_mcp_connection_snippet(
        *,
        company_short_name: str,
        mcp_server_url: str,
        bearer_token: str | None = None,
    ) -> str:
        return McpTokenService.build_mcp_connection_snippet(
            company_short_name=company_short_name,
            mcp_server_url=mcp_server_url,
            bearer_token=bearer_token,
        )
