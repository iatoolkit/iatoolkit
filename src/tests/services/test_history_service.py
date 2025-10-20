# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from iatoolkit.services.history_service import HistoryService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import LLMQuery, Company
from iatoolkit.common.util import Utility
from iatoolkit.common.session_manager import SessionManager
from unittest.mock import patch


class TestHistoryService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.util = MagicMock(spec=Utility)

        # Usamos la clase Utility real para asegurar que la lógica de resolución de ID es correcta
        # self.util = Utility(self.profile_service)
        self.history_service = HistoryService(
            llm_query_repo=self.llm_query_repo,
            profile_repo=self.profile_repo,
            util=self.util
        )
        # Mock común para la compañía
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.id = 1
        self.mock_company.name = 'Test Company'
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company

        self.util.resolve_user_identifier.return_value = ('test_user', True)

    def test_get_history_company_not_found(self):
        """Prueba que el servicio devuelve un error si la empresa no se encuentra."""
        self.profile_repo.get_company_by_short_name.return_value = None

        result = self.history_service.get_history(
            company_short_name='nonexistent_company',
            external_user_id='test_user'
        )

        assert result == {'error': 'No existe la empresa: nonexistent_company'}
        self.profile_repo.get_company_by_short_name.assert_called_once_with('nonexistent_company')
        self.llm_query_repo.get_history.assert_not_called()

    def test_get_history_no_history_found(self):
        """Prueba que el servicio devuelve un error si no se encuentra historial."""
        self.llm_query_repo.get_history.return_value = []
        user_identifier = 'test_user'

        result = self.history_service.get_history(
            company_short_name='test_company',
            external_user_id=user_identifier
        )

        assert result['history'] == []
        self.profile_repo.get_company_by_short_name.assert_called_once_with('test_company')
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, user_identifier)

    def test_get_history_success_with_external_user_id(self):
        """Prueba la recuperación exitosa del historial usando un external_user_id."""
        user_identifier = 'external_user_123'
        self.util.resolve_user_identifier.return_value = (user_identifier, True)

        mock_query1 = MagicMock(spec=LLMQuery)
        mock_query1.to_dict.return_value = {'id': 1, 'query': 'q1', 'answer': 'a1', 'created_at': 't1'}
        mock_query2 = MagicMock(spec=LLMQuery)
        mock_query2.to_dict.return_value = {'id': 2, 'query': 'q2', 'answer': 'a2', 'created_at': 't2'}

        self.llm_query_repo.get_history.return_value = [mock_query1, mock_query2]

        result = self.history_service.get_history(
            company_short_name='test_company',
            external_user_id=user_identifier
        )

        assert result['message'] == 'Historial obtenido correctamente'
        assert len(result['history']) == 2
        assert result['history'][0]['id'] == 1

        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, user_identifier)

    def test_get_history_success_with_local_user_id_and_external_id_takes_precedence(self):
        """Prueba que external_user_id tiene prioridad sobre local_user_id."""
        external_user_identifier = 'external_user_abc'
        self.util.resolve_user_identifier.return_value = (external_user_identifier, True)

        mock_query = MagicMock(spec=LLMQuery)
        mock_query.to_dict.return_value = {'id': 1}
        self.llm_query_repo.get_history.return_value = [mock_query]

        result = self.history_service.get_history(
            company_short_name='test_company',
            external_user_id=external_user_identifier,
            local_user_id=123  # Este debería ser ignorado
        )

        assert 'history' in result

        # El user_identifier resuelto debe ser el ID externo.
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, external_user_identifier)

    def test_get_history_success_with_local_user_id_only(self):
        local_id = 456
        # Este es el identificador que el mock DEBE devolver y la aserción DEBE comprobar.
        resolved_user_identifier = str(local_id)
        self.util.resolve_user_identifier.return_value = (resolved_user_identifier, False)

        mock_query = MagicMock(spec=LLMQuery)
        mock_query.to_dict.return_value = {'id': 1, 'query': 'q1'}
        self.llm_query_repo.get_history.return_value = [mock_query]

        result = self.history_service.get_history(
            company_short_name='test_company',
            local_user_id=local_id
        )

        assert result['message'] == 'Historial obtenido correctamente'
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, resolved_user_identifier)

    def test_get_history_fails_when_no_user_identifier_is_provided(self):
        """Prueba que falla si no se proporciona ningún identificador de usuario."""
        self.util.resolve_user_identifier.return_value = ('', False)

        result = self.history_service.get_history(company_short_name='test_company')

        assert result == {'error': 'No se pudo resolver el identificador del usuario'}
        self.llm_query_repo.get_history.assert_not_called()

    def test_get_history_propagates_exception_from_company_lookup(self):
        """Prueba que las excepciones de la capa de repositorio se propagan."""
        self.profile_repo.get_company_by_short_name.side_effect = Exception('Database error')

        result = self.history_service.get_history(
            company_short_name='test_company',
            external_user_id='test_user'
        )

        assert result == {'error': 'Database error'}
        self.llm_query_repo.get_history.assert_not_called()

    def test_get_history_propagates_exception_from_history_lookup(self):
        """Prueba que las excepciones de la capa de repositorio se propagan."""
        user_identifier = 'test_user'
        self.llm_query_repo.get_history.side_effect = Exception('History lookup error')

        result = self.history_service.get_history(
            company_short_name='test_company',
            external_user_id=user_identifier
        )

        assert result == {'error': 'History lookup error'}
        self.llm_query_repo.get_history.assert_called_once_with(self.mock_company, user_identifier)

