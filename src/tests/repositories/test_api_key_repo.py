# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from datetime import datetime, timedelta
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, ApiKey
from iatoolkit.repositories.api_key_repo import ApiKeyRepo


class TestApiKeyRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager('sqlite:///:memory:')
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = ApiKeyRepo(self.db_manager)

        self.company = Company(name='Acme', short_name='acme')
        self.other_company = Company(name='Other', short_name='other')
        self.session.add(self.company)
        self.session.add(self.other_company)
        self.session.commit()

    def test_create_api_key(self):
        key = ApiKey(company_id=self.company.id, key_name='default', key='k1')

        created = self.repo.create_api_key(key)

        assert created.id is not None
        assert created.key_name == 'default'

    def test_get_api_keys_by_company_returns_ordered_desc(self):
        older = ApiKey(
            company_id=self.company.id,
            key_name='older',
            key='k-old',
            created_at=datetime.now() - timedelta(days=1)
        )
        newer = ApiKey(
            company_id=self.company.id,
            key_name='newer',
            key='k-new',
            created_at=datetime.now()
        )
        foreign = ApiKey(company_id=self.other_company.id, key_name='foreign', key='k-other')

        self.session.add_all([older, newer, foreign])
        self.session.commit()

        result = self.repo.get_api_keys_by_company(self.company)

        assert len(result) == 2
        assert result[0].key_name == 'newer'
        assert result[1].key_name == 'older'

    def test_get_api_key_by_id(self):
        api_key = ApiKey(company_id=self.company.id, key_name='main', key='k-main')
        self.session.add(api_key)
        self.session.commit()

        result = self.repo.get_api_key_by_id(self.company, api_key.id)

        assert result is not None
        assert result.key_name == 'main'

    def test_get_api_key_by_id_returns_none_for_other_company(self):
        api_key = ApiKey(company_id=self.company.id, key_name='main', key='k-main')
        self.session.add(api_key)
        self.session.commit()

        result = self.repo.get_api_key_by_id(self.other_company, api_key.id)

        assert result is None

    def test_get_api_key_by_name(self):
        api_key = ApiKey(company_id=self.company.id, key_name='integration', key='k-int')
        self.session.add(api_key)
        self.session.commit()

        result = self.repo.get_api_key_by_name(self.company, 'integration')

        assert result is not None
        assert result.key == 'k-int'

    def test_update_api_key(self):
        api_key = ApiKey(company_id=self.company.id, key_name='before', key='k-1', is_active=True)
        self.session.add(api_key)
        self.session.commit()

        api_key.key_name = 'after'
        api_key.is_active = False
        updated = self.repo.update_api_key(api_key)

        assert updated.key_name == 'after'
        assert updated.is_active is False

    def test_delete_api_key(self):
        api_key = ApiKey(company_id=self.company.id, key_name='to_delete', key='k-del')
        self.session.add(api_key)
        self.session.commit()
        api_key_id = api_key.id

        self.repo.delete_api_key(api_key)

        assert self.session.query(ApiKey).filter(ApiKey.id == api_key_id).first() is None

    def test_get_active_api_key_entry(self):
        active = ApiKey(company_id=self.company.id, key_name='active', key='k-active', is_active=True)
        inactive = ApiKey(company_id=self.company.id, key_name='inactive', key='k-inactive', is_active=False)
        self.session.add_all([active, inactive])
        self.session.commit()

        assert self.repo.get_active_api_key_entry('k-active').key_name == 'active'
        assert self.repo.get_active_api_key_entry('k-inactive') is None

    def test_get_active_api_key_by_company(self):
        active = ApiKey(company_id=self.company.id, key_name='active', key='k-active', is_active=True)
        inactive = ApiKey(company_id=self.other_company.id, key_name='inactive', key='k-inactive', is_active=False)
        self.session.add_all([active, inactive])
        self.session.commit()

        result = self.repo.get_active_api_key_by_company(self.company)
        assert result is not None
        assert result.key == 'k-active'
