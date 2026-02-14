# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import secrets
import string
from typing import Dict
from injector import inject
from iatoolkit.repositories.models import ApiKey
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.api_key_repo import ApiKeyRepo


class ApiKeyService:
    @inject
    def __init__(self,
                 i18n_service: I18nService,
                 profile_repo: ProfileRepo,
                 api_key_repo: ApiKeyRepo):
        self.i18n_service = i18n_service
        self.profile_repo = profile_repo
        self.api_key_repo = api_key_repo

    def _api_key_to_dict(self, api_key: ApiKey) -> Dict:
        return {
            "id": api_key.id,
            "company_id": api_key.company_id,
            "key_name": api_key.key_name,
            "key": api_key.key,
            "is_active": api_key.is_active,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
            "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        }

    def _get_company(self, company_short_name: str):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return None, {
                "error": self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name),
                "status_code": 404,
            }
        return company, None

    def get_active_api_key_entry(self, api_key_value: str) -> ApiKey | None:
        return self.api_key_repo.get_active_api_key_entry(api_key_value)

    def list_api_keys(self, company_short_name: str) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        api_keys = self.api_key_repo.get_api_keys_by_company(company)
        return {"data": [self._api_key_to_dict(item) for item in api_keys]}

    def get_api_key(self, company_short_name: str, api_key_id: int) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        api_key = self.api_key_repo.get_api_key_by_id(company, api_key_id)
        if not api_key:
            return {"error": "API key not found.", "status_code": 404}

        return {"data": self._api_key_to_dict(api_key)}

    def create_api_key_entry(self, company_short_name: str, key_name: str) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        if not key_name:
            return {"error": self.i18n_service.t('errors.auth.api_key_name_required'), "status_code": 400}

        existing = self.api_key_repo.get_api_key_by_name(company, key_name)
        if existing:
            return {"error": "API key name already exists for this company.", "status_code": 409}

        length = 40
        alphabet = string.ascii_letters + string.digits
        key = ''.join(secrets.choice(alphabet) for _ in range(length))

        api_key = ApiKey(key=key, company_id=company.id, key_name=key_name)
        created = self.api_key_repo.create_api_key(api_key)
        return {"data": self._api_key_to_dict(created)}

    def update_api_key_entry(self,
                             company_short_name: str,
                             api_key_id: int,
                             key_name: str | None = None,
                             is_active: bool | None = None) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        api_key = self.api_key_repo.get_api_key_by_id(company, api_key_id)
        if not api_key:
            return {"error": "API key not found.", "status_code": 404}

        if key_name is None and is_active is None:
            return {"error": "No changes provided.", "status_code": 400}

        if key_name is not None:
            if not key_name:
                return {"error": self.i18n_service.t('errors.auth.api_key_name_required'), "status_code": 400}

            existing = self.api_key_repo.get_api_key_by_name(company, key_name)
            if existing and existing.id != api_key.id:
                return {"error": "API key name already exists for this company.", "status_code": 409}

            api_key.key_name = key_name

        if is_active is not None:
            if not isinstance(is_active, bool):
                return {"error": "Invalid value for is_active.", "status_code": 400}
            api_key.is_active = is_active

        updated = self.api_key_repo.update_api_key(api_key)
        return {"data": self._api_key_to_dict(updated)}

    def delete_api_key_entry(self, company_short_name: str, api_key_id: int) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        api_key = self.api_key_repo.get_api_key_by_id(company, api_key_id)
        if not api_key:
            return {"error": "API key not found.", "status_code": 404}

        self.api_key_repo.delete_api_key(api_key)
        return {"status": "success"}

    def new_api_key(self, company_short_name: str, key_name: str):
        result = self.create_api_key_entry(company_short_name=company_short_name, key_name=key_name)
        if "error" in result:
            return {"error": result["error"]}
        return {"api-key": result["data"]["key"]}
