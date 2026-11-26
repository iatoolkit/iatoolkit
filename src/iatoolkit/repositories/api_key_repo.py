# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import hashlib
import logging
from datetime import datetime, timedelta
from injector import inject
from sqlalchemy import or_
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import ApiKey, Company


class ApiKeyRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.session = db_manager.get_session()

    def create_api_key(self, new_api_key: ApiKey):
        self.session.add(new_api_key)
        self.session.commit()
        return new_api_key

    def get_api_keys_by_company(self, company: Company) -> list[ApiKey]:
        return (
            self.session.query(ApiKey)
            .filter(ApiKey.company_id == company.id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .all()
        )

    def get_api_key_by_id(self, company: Company, api_key_id: int) -> ApiKey | None:
        return (
            self.session.query(ApiKey)
            .filter(ApiKey.company_id == company.id, ApiKey.id == api_key_id)
            .first()
        )

    def get_api_key_by_name(self, company: Company, key_name: str) -> ApiKey | None:
        return (
            self.session.query(ApiKey)
            .filter(ApiKey.company_id == company.id, ApiKey.key_name == key_name)
            .first()
        )

    def update_api_key(self, api_key: ApiKey) -> ApiKey:
        self.session.add(api_key)
        self.session.commit()
        return api_key

    def delete_api_key(self, api_key: ApiKey):
        self.session.delete(api_key)
        self.session.commit()

    @staticmethod
    def hash_key(api_key_value: str) -> str:
        """What is stored and searched for a key: its SHA-256, never the key (BL-030)."""
        return hashlib.sha256(str(api_key_value or '').encode('utf-8')).hexdigest()

    def get_active_api_key_entry(self, api_key_value: str) -> ApiKey | None:
        if not api_key_value:
            return None
        return (
            self.session.query(ApiKey)
            .filter(ApiKey.key_hash == self.hash_key(api_key_value), ApiKey.is_active == True)
            .first()
        )

    def touch_last_used(self, api_key: ApiKey, min_interval: timedelta) -> None:
        """Record that the key was used, at most once per `min_interval`.

        A conditional UPDATE, so concurrent requests with the same key do not each
        write. A failure is logged and never blocks the request that used the key.
        """
        now = datetime.now()
        try:
            (
                self.session.query(ApiKey)
                .filter(ApiKey.id == api_key.id,
                        or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < now - min_interval))
                .update({ApiKey.last_used_at: now}, synchronize_session=False)
            )
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logging.warning("Could not record the last use of API key id=%s: %s", api_key.id, e)

    def get_active_api_key_by_company(self, company: Company) -> ApiKey | None:
        return (
            self.session.query(ApiKey)
            .filter(ApiKey.company == company, ApiKey.is_active == True)
            .first()
        )
