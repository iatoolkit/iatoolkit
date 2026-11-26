# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import secrets
import string
from datetime import timedelta
from typing import Dict
from injector import inject
from iatoolkit.repositories.models import ApiKey
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.api_key_repo import ApiKeyRepo


class ApiKeyService:
    # How many characters of a key the console shows to tell keys apart.
    KEY_PREFIX_LENGTH = 6
    # How often the last use of a key is written: enough to tell an idle key from one
    # in use (to review keys and their delegation, BL-034 R2) without a write per call.
    LAST_USED_INTERVAL = timedelta(minutes=15)

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
            # Never the key: only its first characters, to tell keys apart (BL-030).
            "key_prefix": api_key.key_prefix,
            "is_active": api_key.is_active,
            # BL-010, Fase 0: whether the key may name the user it acts for.
            "can_act_for_users": bool(getattr(api_key, "can_act_for_users", False)),
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
        api_key = self.api_key_repo.get_active_api_key_entry(api_key_value)
        if api_key is not None:
            self.api_key_repo.touch_last_used(api_key, self.LAST_USED_INTERVAL)
        return api_key

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

    def create_api_key_entry(self, company_short_name: str, key_name: str, can_act_for_users: bool = False) -> Dict:
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

        # A new key acts as itself unless the admin allows it to act for users (BL-010).
        # Only its hash and prefix are stored: this response is the one time the key
        # itself is shown (BL-030).
        api_key = ApiKey(key=None,
                         key_hash=ApiKeyRepo.hash_key(key),
                         key_prefix=key[:self.KEY_PREFIX_LENGTH],
                         company_id=company.id, key_name=key_name,
                         can_act_for_users=bool(can_act_for_users))
        created = self.api_key_repo.create_api_key(api_key)
        return {"data": {**self._api_key_to_dict(created), "key": key}}

    def update_api_key_entry(self,
                             company_short_name: str,
                             api_key_id: int,
                             key_name: str | None = None,
                             is_active: bool | None = None,
                             can_act_for_users: bool | None = None) -> Dict:
        company, error = self._get_company(company_short_name)
        if error:
            return error

        api_key = self.api_key_repo.get_api_key_by_id(company, api_key_id)
        if not api_key:
            return {"error": "API key not found.", "status_code": 404}

        if key_name is None and is_active is None and can_act_for_users is None:
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

        if can_act_for_users is not None:
            if not isinstance(can_act_for_users, bool):
                return {"error": "Invalid value for can_act_for_users.", "status_code": 400}
            api_key.can_act_for_users = can_act_for_users

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
