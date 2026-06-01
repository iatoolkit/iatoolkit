from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta

from injector import inject
from sqlalchemy.exc import IntegrityError

from iatoolkit.common.util import Utility
from iatoolkit.repositories.mcp_token_repo import McpTokenRepo
from iatoolkit.repositories.models import McpToken
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService


class McpTokenService:
    TOKEN_PREFIX = "iatmcp_"
    DEFAULT_EXPIRY_DAYS = 30
    MAX_EXPIRY_DAYS = 730
    DEFAULT_SERVICE_SUBJECT = "service:mcp"

    @inject
    def __init__(
        self,
        i18n_service: I18nService,
        profile_repo: ProfileRepo,
        token_repo: McpTokenRepo,
        utility: Utility,
    ):
        self.i18n_service = i18n_service
        self.profile_repo = profile_repo
        self.token_repo = token_repo
        self.utility = utility

    def list_user_tokens(self, company_short_name: str, user_identifier: str) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        tokens = self.token_repo.list_tokens(
            company.id,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier=self._normalize_subject_identifier(user_identifier),
        )
        return {"data": [self._token_to_dict(item) for item in tokens]}

    def list_company_tokens(self, company_short_name: str) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        tokens = self.token_repo.list_tokens(company.id)
        return {"data": [self._token_to_dict(item) for item in tokens]}

    def create_user_token(
        self,
        company_short_name: str,
        user_identifier: str,
        *,
        name: str,
        expires_in_days: int | None = None,
        created_by_identifier: str | None = None,
    ) -> dict:
        return self._create_subject_token(
            company_short_name,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier=user_identifier,
            name=name,
            expires_in_days=expires_in_days,
            created_by_identifier=created_by_identifier or user_identifier,
        )

    def revoke_user_token(self, company_short_name: str, user_identifier: str, token_id: int) -> dict:
        return self._revoke_subject_token(
            company_short_name,
            subject_type=McpToken.SUBJECT_TYPE_USER,
            subject_identifier=user_identifier,
            token_id=token_id,
        )

    def list_service_tokens(self, company_short_name: str) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        tokens = self.token_repo.list_service_tokens(company.id)
        return {"data": [self._token_to_dict(item) for item in tokens]}

    def create_service_token(
        self,
        company_short_name: str,
        *,
        subject_identifier: str,
        name: str,
        expires_in_days: int | None = None,
        created_by_identifier: str | None = None,
    ) -> dict:
        return self._create_subject_token(
            company_short_name,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier=subject_identifier,
            name=name,
            expires_in_days=expires_in_days,
            created_by_identifier=created_by_identifier,
        )

    def revoke_service_token(self, company_short_name: str, token_id: int) -> dict:
        return self._revoke_subject_token(
            company_short_name,
            subject_type=McpToken.SUBJECT_TYPE_SERVICE,
            subject_identifier=None,
            token_id=token_id,
        )

    def revoke_company_token(self, company_short_name: str, token_id: int) -> dict:
        return self._revoke_subject_token(
            company_short_name,
            subject_type=None,
            subject_identifier=None,
            token_id=token_id,
        )

    def get_company_token_connection(self, company_short_name: str, token_id: int) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        token = self.token_repo.get_token_by_id(company.id, token_id)
        if not token:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_not_found"), "status_code": 404}
        if token.revoked_at is not None or token.expires_at <= datetime.now():
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_invalid"), "status_code": 400}
        if not token.token_encrypted:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_token_unavailable"), "status_code": 409}

        raw_token = self.utility.decrypt_key(token.token_encrypted)
        mcp_server_url = self.build_mcp_server_url(company_short_name)
        payload = self._token_to_dict(token)
        payload["token"] = raw_token
        payload["mcp_server_url"] = mcp_server_url
        payload["connection_snippet"] = self.build_mcp_connection_snippet(
            company_short_name=company_short_name,
            mcp_server_url=mcp_server_url,
            bearer_token=raw_token,
        )
        return {"data": payload}

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
            "subject_type": token.subject_type,
            "subject_identifier": token.subject_identifier,
            "user_identifier": token.subject_identifier,
            "token_id": token.id,
        }

    @staticmethod
    def build_mcp_server_url(company_short_name: str) -> str:
        public_base_url = str(
            os.getenv("IAT_MCP_PUBLIC_BASE_URL")
            or os.getenv("MCP_PUBLIC_BASE_URL")
            or "https://mcp.iatoolkit.com"
        ).strip()
        public_base_url = public_base_url.rstrip("/")
        return f"{public_base_url}/{company_short_name}/mcp/"

    @staticmethod
    def build_mcp_connection_snippet(
        *,
        company_short_name: str,
        mcp_server_url: str,
        bearer_token: str | None = None,
    ) -> str:
        resolved_token = bearer_token or "<YOUR_MCP_TOKEN>"
        return (
            '{\n'
            '  "mcpServers": {\n'
            f'    "{company_short_name}": {{\n'
            '      "type": "http",\n'
            f'      "url": "{mcp_server_url}",\n'
            '      "headers": {\n'
            f'        "Authorization": "Bearer {resolved_token}"\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}'
        )

    def _create_subject_token(
        self,
        company_short_name: str,
        *,
        subject_type: str,
        subject_identifier: str,
        name: str,
        expires_in_days: int | None = None,
        created_by_identifier: str | None = None,
    ) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        normalized_name = str(name or "").strip()
        if not normalized_name:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_required"), "status_code": 400}

        normalized_subject_identifier = self._normalize_subject_identifier(subject_identifier)
        if not normalized_subject_identifier:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_subject_required"), "status_code": 400}
        if subject_type == McpToken.SUBJECT_TYPE_SERVICE and not normalized_subject_identifier.startswith("service:"):
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_service_subject_invalid"), "status_code": 400}

        normalized_created_by_identifier = self._normalize_subject_identifier(created_by_identifier)
        if not normalized_created_by_identifier:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_created_by_required"), "status_code": 400}

        expiry_days = self._normalize_expiry_days(expires_in_days)
        if expiry_days is None:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_expiry_invalid"), "status_code": 400}

        existing = self.token_repo.get_token_by_name(
            company.id,
            normalized_name,
            subject_type=subject_type,
            subject_identifier=normalized_subject_identifier,
        )
        if existing and existing.revoked_at is None and existing.expires_at > datetime.now():
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_exists"), "status_code": 409}

        raw_token = self._generate_raw_token()
        encrypted_token = self.utility.encrypt_key(raw_token)
        expires_at = datetime.now() + timedelta(days=expiry_days)
        try:
            if existing:
                existing.token_hash = self._hash_token(raw_token)
                existing.token_encrypted = encrypted_token
                existing.created_at = datetime.now()
                existing.expires_at = expires_at
                existing.revoked_at = None
                existing.last_used_at = None
                existing.subject_type = subject_type
                existing.subject_identifier = normalized_subject_identifier
                existing.created_by_identifier = normalized_created_by_identifier
                created = self.token_repo.save_token(existing)
            else:
                token = McpToken(
                    company_id=company.id,
                    subject_type=subject_type,
                    subject_identifier=normalized_subject_identifier,
                    created_by_identifier=normalized_created_by_identifier,
                    name=normalized_name,
                    token_hash=self._hash_token(raw_token),
                    token_encrypted=encrypted_token,
                    expires_at=expires_at,
                )
                created = self.token_repo.create_token(token)
        except IntegrityError:
            self.token_repo.rollback()
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_name_exists"), "status_code": 409}

        payload = self._token_to_dict(created)
        payload["token"] = raw_token
        return {"data": payload}

    def _revoke_subject_token(
        self,
        company_short_name: str,
        *,
        subject_type: str | None,
        subject_identifier: str | None,
        token_id: int,
    ) -> dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        normalized_subject_identifier = self._normalize_subject_identifier(subject_identifier) if subject_identifier else None
        token = self.token_repo.get_token_by_id(
            company.id,
            token_id,
            subject_type=subject_type,
            subject_identifier=normalized_subject_identifier,
        )
        if not token:
            return {"error": self.i18n_service.t("errors.auth.mcp_pat_not_found"), "status_code": 404}

        if token.revoked_at is None:
            token.revoked_at = datetime.now()
            self.token_repo.save_token(token)

        return {"data": self._token_to_dict(token)}

    def _get_company(self, company_short_name: str):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, {
                "error": self.i18n_service.t("errors.company_not_found", company_short_name=company_short_name),
                "status_code": 404,
            }
        return company, None

    @staticmethod
    def _token_to_dict(token: McpToken) -> dict:
        is_active = token.revoked_at is None and token.expires_at > datetime.now()
        return {
            "id": token.id,
            "name": token.name,
            "subject_type": token.subject_type,
            "subject_identifier": token.subject_identifier,
            "user_identifier": token.subject_identifier,
            "created_by_identifier": token.created_by_identifier,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
            "is_active": is_active,
            "can_view_token": bool(token.token_encrypted) and is_active,
        }

    @staticmethod
    def _normalize_subject_identifier(raw_value: str | None) -> str:
        return str(raw_value or "").strip()

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
