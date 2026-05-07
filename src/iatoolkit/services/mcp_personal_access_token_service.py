from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from injector import inject
from sqlalchemy.exc import IntegrityError

from iatoolkit.repositories.mcp_personal_access_token_repo import McpPersonalAccessTokenRepo
from iatoolkit.repositories.models import McpPersonalAccessToken
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService


class McpPersonalAccessTokenService:
    TOKEN_PREFIX = "iatmcp_"
    DEFAULT_EXPIRY_DAYS = 30
    MAX_EXPIRY_DAYS = 365

    @inject
    def __init__(
        self,
        i18n_service: I18nService,
        profile_repo: ProfileRepo,
        token_repo: McpPersonalAccessTokenRepo,
    ):
        self.i18n_service = i18n_service
        self.profile_repo = profile_repo
        self.token_repo = token_repo

    def list_tokens(self, company_short_name: str, user_identifier: str) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        tokens = self.token_repo.list_tokens_for_user(company.id, user_identifier)
        return {"data": [self._token_to_dict(item) for item in tokens]}

    def create_token(
        self,
        company_short_name: str,
        user_identifier: str,
        *,
        name: str,
        expires_in_days: int | None = None,
    ) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        normalized_name = str(name or "").strip()
        if not normalized_name:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_required"), "status_code": 400}

        expiry_days = self._normalize_expiry_days(expires_in_days)
        if expiry_days is None:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_expiry_invalid"), "status_code": 400}

        existing = self.token_repo.get_token_by_name(company.id, user_identifier, normalized_name)
        if existing and existing.revoked_at is None and existing.expires_at > datetime.now():
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_exists"), "status_code": 409}

        raw_token = self._generate_raw_token()
        expires_at = datetime.now() + timedelta(days=expiry_days)
        try:
            if existing:
                existing.token_hash = self._hash_token(raw_token)
                existing.created_at = datetime.now()
                existing.expires_at = expires_at
                existing.revoked_at = None
                existing.last_used_at = None
                created = self.token_repo.save_token(existing)
            else:
                token = McpPersonalAccessToken(
                    company_id=company.id,
                    user_identifier=user_identifier,
                    name=normalized_name,
                    token_hash=self._hash_token(raw_token),
                    expires_at=expires_at,
                )
                created = self.token_repo.create_token(token)
        except IntegrityError:
            self.token_repo.rollback()
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_exists"), "status_code": 409}
        payload = self._token_to_dict(created)
        payload["token"] = raw_token
        return {"data": payload}

    def revoke_token(self, company_short_name: str, user_identifier: str, token_id: int) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        token = self.token_repo.get_token_by_id(company.id, user_identifier, token_id)
        if not token:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_not_found"), "status_code": 404}

        if token.revoked_at is None:
            token.revoked_at = datetime.now()
            self.token_repo.save_token(token)

        return {"data": self._token_to_dict(token)}

    def authenticate_token(self, company_short_name: str, raw_token: str) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        normalized_token = str(raw_token or "").strip()
        if not normalized_token:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_invalid"), "status_code": 401}

        token_hash = self._hash_token(normalized_token)
        token = self.token_repo.get_active_token_by_hash(company.id, token_hash)
        if not token:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_invalid"), "status_code": 401}

        token.last_used_at = datetime.now()
        self.token_repo.save_token(token)
        return {
            "success": True,
            "company_short_name": company.short_name,
            "user_identifier": token.user_identifier,
            "token_id": token.id,
        }

    def _get_company(self, company_short_name: str):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, {
                "error": self.i18n_service.t("errors.company_not_found", company_short_name=company_short_name),
                "status_code": 404,
            }
        return company, None

    def _token_to_dict(self, token: McpPersonalAccessToken) -> dict:
        return {
            "id": token.id,
            "name": token.name,
            "user_identifier": token.user_identifier,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
            "is_active": token.revoked_at is None and token.expires_at > datetime.now(),
        }

    def _normalize_expiry_days(self, raw_value: int | None) -> int | None:
        if raw_value in (None, ""):
            return self.DEFAULT_EXPIRY_DAYS
        try:
            expiry_days = int(raw_value)
        except (TypeError, ValueError):
            return None
        if expiry_days <= 0 or expiry_days > self.MAX_EXPIRY_DAYS:
            return None
        return expiry_days

    @classmethod
    def _hash_token(cls, raw_token: str) -> str:
        return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()

    @classmethod
    def _generate_raw_token(cls) -> str:
        return f"{cls.TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
