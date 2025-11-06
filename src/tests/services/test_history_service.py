# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from iatoolkit.services.history_service import HistoryService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.models import LLMQuery, Company


class TestHistoryService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        self.history_service = HistoryService(
            llm_query_repo=self.llm_query_repo,
            profile_repo=self.profile_repo,
            i18n_service=self.mock_i18n_service
        )
        # Mock común para la compañía
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.id = 1
        self.mock_company.name = 'Test Company'
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"


    def test_get_history_company_not_found(self):
        """Prueba que el servicio devuelve un error si la empresa no se encuentra."""
        self.profile_repo.get_company_by_short_name.return_value = None

        result = self.history_service.get_history(
            company_short_name='nonexistent_company',
            user_identifier='test_user'
        )

        assert result == {'error': 'translated:errors.company_not_found'}
        self.profile_repo.get_company_by_short_name.assert_called_once_with('nonexistent_company')
        self.llm_query_repo.get_history.assert_not_called()

    def test_get_history_no_history_found(self):
        """Prueba que el servicio devuelve un error si no se encuentra historial."""
        self.llm_query_repo.get_history.return_value = []
        user_identifier = 'test_user'

        result = self.history_service.get_history(
            company_short_name='test_company',
            user_identifier=user_identifier
        )

        assert result['history'] == []
        self.profile_repo.get_company_by_short_name.assert_called_once_with('test_company')
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, user_identifier)

    def test_get_history_success(self):
        """Prueba la recuperación exitosa del historial usando un external_user_id."""
        user_identifier = 'external_user_123'

        mock_query1 = MagicMock(spec=LLMQuery)
        mock_query1.to_dict.return_value = {'id': 1, 'query': 'q1', 'answer': 'a1', 'created_at': 't1'}
        mock_query2 = MagicMock(spec=LLMQuery)
        mock_query2.to_dict.return_value = {'id': 2, 'query': 'q2', 'answer': 'a2', 'created_at': 't2'}

        self.llm_query_repo.get_history.return_value = [mock_query1, mock_query2]

        result = self.history_service.get_history(
            company_short_name='test_company',
            user_identifier=user_identifier
        )

        assert result['message'] == 'history loaded ok'
        assert len(result['history']) == 2
        assert result['history'][0]['id'] == 1

        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, user_identifier)


    def test_get_history_propagates_exception_from_company_lookup(self):
        """Prueba que las excepciones de la capa de repositorio se propagan."""
        self.profile_repo.get_company_by_short_name.side_effect = Exception('Database error')

        result = self.history_service.get_history(
            company_short_name='test_company',
            user_identifier='test_user'
        )

        assert result == {'error': 'Database error'}
        self.llm_query_repo.get_history.assert_not_called()

    def test_get_history_propagates_exception_from_history_lookup(self):
        """Prueba que las excepciones de la capa de repositorio se propagan."""
        self.llm_query_repo.get_history.side_effect = Exception('History lookup error')

        result = self.history_service.get_history(
            company_short_name='test_company',
            user_identifier='test_user'
        )

        assert result == {'error': 'History lookup error'}
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, 'test_user')

