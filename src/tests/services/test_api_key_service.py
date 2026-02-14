# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock
from iatoolkit.services.api_key_service import ApiKeyService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.api_key_repo import ApiKeyRepo
from iatoolkit.repositories.models import Company, ApiKey


class TestApiKeyService:
    def setup_method(self):
        self.mock_i18n = MagicMock(spec=I18nService)
        self.mock_profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_api_key_repo = MagicMock(spec=ApiKeyRepo)
        self.mock_i18n.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.service = ApiKeyService(
            i18n_service=self.mock_i18n,
            profile_repo=self.mock_profile_repo,
            api_key_repo=self.mock_api_key_repo
        )

        self.company = Company(id=10, short_name='acme', name='ACME')

    def test_list_api_keys_company_not_found(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = None

        result = self.service.list_api_keys('missing')

        assert result['status_code'] == 404
        assert result['error'] == 'translated:errors.company_not_found'

    def test_list_api_keys_success(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        api_key = ApiKey(id=1, company_id=10, key_name='k1', key='abc', is_active=True)
        self.mock_api_key_repo.get_api_keys_by_company.return_value = [api_key]

        result = self.service.list_api_keys('acme')

        assert len(result['data']) == 1
        assert result['data'][0]['key'] == 'abc'

    def test_get_api_key_not_found(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_id.return_value = None

        result = self.service.get_api_key('acme', 99)

        assert result['status_code'] == 404
        assert result['error'] == 'API key not found.'

    def test_create_api_key_name_required(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company

        result = self.service.create_api_key_entry('acme', '')

        assert result['status_code'] == 400
        assert result['error'] == 'translated:errors.auth.api_key_name_required'

    def test_create_api_key_duplicate(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_name.return_value = ApiKey(id=1, company_id=10, key_name='dup', key='k')

        result = self.service.create_api_key_entry('acme', 'dup')

        assert result['status_code'] == 409
        assert result['error'] == 'API key name already exists for this company.'

    def test_create_api_key_success(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_name.return_value = None

        created = ApiKey(id=7, company_id=10, key_name='new_key', key='x' * 40, is_active=True)
        self.mock_api_key_repo.create_api_key.return_value = created

        result = self.service.create_api_key_entry('acme', 'new_key')

        assert result['data']['id'] == 7
        assert result['data']['key_name'] == 'new_key'
        assert result['data']['key'] == 'x' * 40

    def test_update_api_key_no_changes(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_id.return_value = ApiKey(id=1, company_id=10, key_name='k1', key='abc')

        result = self.service.update_api_key_entry('acme', 1)

        assert result['status_code'] == 400
        assert result['error'] == 'No changes provided.'

    def test_update_api_key_invalid_is_active(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_id.return_value = ApiKey(id=1, company_id=10, key_name='k1', key='abc')

        result = self.service.update_api_key_entry('acme', 1, is_active='bad')

        assert result['status_code'] == 400
        assert result['error'] == 'Invalid value for is_active.'

    def test_update_api_key_success(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        api_key = ApiKey(id=1, company_id=10, key_name='old', key='abc', is_active=True)
        self.mock_api_key_repo.get_api_key_by_id.return_value = api_key
        self.mock_api_key_repo.get_api_key_by_name.return_value = None
        self.mock_api_key_repo.update_api_key.return_value = api_key

        result = self.service.update_api_key_entry('acme', 1, key_name='new', is_active=False)

        assert result['data']['key_name'] == 'new'
        assert result['data']['is_active'] is False

    def test_delete_api_key_not_found(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_id.return_value = None

        result = self.service.delete_api_key_entry('acme', 3)

        assert result['status_code'] == 404
        assert result['error'] == 'API key not found.'

    def test_delete_api_key_success(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        api_key = ApiKey(id=3, company_id=10, key_name='x', key='abc')
        self.mock_api_key_repo.get_api_key_by_id.return_value = api_key

        result = self.service.delete_api_key_entry('acme', 3)

        assert result['status'] == 'success'
        self.mock_api_key_repo.delete_api_key.assert_called_once_with(api_key)

    def test_new_api_key_wrapper_success(self):
        self.mock_profile_repo.get_company_by_short_name.return_value = self.company
        self.mock_api_key_repo.get_api_key_by_name.return_value = None
        self.mock_api_key_repo.create_api_key.return_value = ApiKey(
            id=9, company_id=10, key_name='cli', key='y' * 40, is_active=True
        )

        result = self.service.new_api_key('acme', 'cli')

        assert result['api-key'] == 'y' * 40
