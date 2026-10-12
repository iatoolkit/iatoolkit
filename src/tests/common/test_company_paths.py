from pathlib import Path
from unittest.mock import patch

from iatoolkit.base_company import BaseCompany
from iatoolkit.common.company_paths import get_company_root
from iatoolkit.common.interfaces.asset_storage import AssetType
from iatoolkit.common.util import Utility
from iatoolkit.repositories.filesystem_asset_repository import FileSystemAssetRepository


class _ClassicCompany(BaseCompany):
    def handle_request(self, tag, params):
        return {}


def _packaged_company(root: Path):
    class _PackagedCompany(BaseCompany):
        def handle_request(self, tag, params):
            return {}

        @classmethod
        def get_resource_root(cls):
            return root

    return _PackagedCompany


def _registered(companies: dict):
    return patch('iatoolkit.company_registry.get_registered_companies', return_value=companies)


class TestGetCompanyRoot:
    def test_an_unknown_company_keeps_the_classic_layout(self):
        with _registered({}):
            assert get_company_root('acme') == Path('companies') / 'acme'

    def test_a_company_without_its_own_root_keeps_the_classic_layout(self):
        with _registered({'acme': _ClassicCompany}):
            assert get_company_root('acme') == Path('companies') / 'acme'

    def test_a_packaged_company_answers_with_its_own_root(self, tmp_path):
        with _registered({'acme': _packaged_company(tmp_path)}):
            assert get_company_root('ACME') == tmp_path


class TestPackagedCompanyFiles:
    """A company installed as a package is found without a ./companies symlink."""

    def test_filesystem_assets_are_read_from_the_company_root(self, tmp_path):
        (tmp_path / 'config').mkdir()
        (tmp_path / 'config' / 'company.yaml').write_text('name: Acme', encoding='utf-8')
        repo = FileSystemAssetRepository()

        with _registered({'acme': _packaged_company(tmp_path)}):
            assert repo.read_text('acme', AssetType.CONFIG, 'company.yaml') == 'name: Acme'
            assert repo.list_files('acme', AssetType.CONFIG) == ['company.yaml']

    def test_company_templates_are_read_from_the_company_root(self, tmp_path):
        (tmp_path / 'templates').mkdir()
        (tmp_path / 'templates' / 'home.html').write_text('<h1>Acme</h1>', encoding='utf-8')
        util = Utility.__new__(Utility)

        with _registered({'acme': _packaged_company(tmp_path)}):
            assert util.get_company_template('acme', 'home.html') == '<h1>Acme</h1>'
            assert util.get_company_template('acme', 'missing.html') is None
