# src/tests/views/test_categories_api_view.py

import pytest
from unittest.mock import MagicMock
from flask import Flask
from iatoolkit.views.categories_api_view import CategoriesApiView
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import PromptType, Company, PromptCategory

class TestCategoriesView:
    @staticmethod
    def create_app():
        app = Flask(__name__)
        app.testing = True
        return app

    @pytest.fixture(autouse=True)
    def setup(self):
        self.app = self.create_app()
        self.client = self.app.test_client()
        self.auth_service = MagicMock(spec=AuthService)
        self.profile_service = MagicMock(spec=ProfileService)
        self.kb_service = MagicMock(spec=KnowledgeBaseService)
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.configuration_service = MagicMock(spec=ConfigurationService)

        # Mock Session for direct query
        self.mock_session = MagicMock()
        self.llm_query_repo.session = self.mock_session

        self.company_short_name = 'test_co'
        self.auth_service.verify.return_value = {'success': True}

        self.mock_company = Company(id=1, short_name='test_co')
        self.profile_service.get_company_by_short_name.return_value = self.mock_company

        view = CategoriesApiView.as_view('categories',
                                         auth_service=self.auth_service,
                                         profile_service=self.profile_service,
                                         knowledge_base_service=self.kb_service,
                                         configuration_service=self.configuration_service,
                                         llm_query_repo=self.llm_query_repo)

        self.app.add_url_rule('/<company_short_name>/api/categories', view_func=view)

    def test_get_categories_success(self):
        # 1. Mock collection types
        self.kb_service.get_collection_names.return_value = ["Contracts", "Manuals"]

        # 2. Mock prompt categories query
        mock_cat1 = PromptCategory(name="Sales", order=1)
        mock_cat2 = PromptCategory(name="Support", order=2)
        self.llm_query_repo.get_all_categories.return_value = [mock_cat1, mock_cat2]

        # 3. Mock LLM Configuration
        mock_llm_models = [
            {'id': 'gpt-4', 'label': 'GPT 4'},
            {'id': 'claude-3', 'label': 'Claude 3'}
        ]
        self.configuration_service.get_llm_configuration.return_value = ("gpt-4", mock_llm_models)

        # Act
        response = self.client.get(f'/{self.company_short_name}/api/categories')

        # Assert
        assert response.status_code == 200
        data = response.json

        assert "prompt_types" in data
        assert PromptType.COMPANY.value in data["prompt_types"]

        assert "prompt_categories" in data
        assert "Sales" in data["prompt_categories"]

        assert "collection_types" in data
        assert "Contracts" in data["collection_types"]

        assert "llm_models" in data
        assert "gpt-4" in data["llm_models"]
        assert "claude-3" in data["llm_models"]