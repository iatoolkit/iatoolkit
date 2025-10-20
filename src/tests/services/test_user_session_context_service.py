import unittest
from unittest.mock import patch, MagicMock
import json
from iatoolkit.services.user_session_context_service import UserSessionContextService


class TestUserSessionContextService(unittest.TestCase):

    def setUp(self):
        """Configura el servicio y los mocks antes de cada test."""
        self.service = UserSessionContextService()
        self.company_short_name = "test_company"
        self.user_identifier = "test_user"

        # La clave única para el Hash de sesión
        self.session_key = f"session:{self.company_short_name}/{self.user_identifier}"

        # Patchear RedisSessionManager para aislar el servicio
        self.redis_patcher = patch("iatoolkit.services.user_session_context_service.RedisSessionManager", spec=True)
        self.mock_redis_manager = self.redis_patcher.start()
        self.mock_redis_manager.hget = MagicMock()
        self.mock_redis_manager.hset = MagicMock()

    def tearDown(self):
        """Limpia los patches después de cada test."""
        self.redis_patcher.stop()

    def test_save_last_response_id(self):
        """Prueba que se guarda el ID de la respuesta en el campo correcto del Hash."""
        response_id = "resp_xyz"
        self.service.save_last_response_id(self.company_short_name, self.user_identifier, response_id)
        self.mock_redis_manager.hset.assert_called_once_with(self.session_key, 'last_response_id', response_id)

    def test_get_last_response_id(self):
        """Prueba que se obtiene el ID de la respuesta del campo correcto del Hash."""
        self.mock_redis_manager.hget.return_value = "resp_abc"
        result = self.service.get_last_response_id(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.hget.assert_called_once_with(self.session_key, 'last_response_id')
        self.assertEqual(result, "resp_abc")

    def test_save_user_session_data(self):
        """Prueba que los datos de sesión se guardan como JSON en el campo 'user_data'."""
        data = {"role": "admin", "theme": "dark"}
        expected_json = json.dumps(data)
        self.service.save_profile_data(self.company_short_name, self.user_identifier, data)
        self.mock_redis_manager.hset.assert_called_once_with(self.session_key, 'profile_data', expected_json)

    def test_get_profile_data(self):
        """Prueba que los datos de sesión se leen y deserializan desde el campo 'user_data'."""
        expected_data = {"role": "admin", "theme": "dark"}
        self.mock_redis_manager.hget.return_value = json.dumps(expected_data)
        result = self.service.get_profile_data(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.hget.assert_called_once_with(self.session_key, 'profile_data')
        self.assertEqual(result, expected_data)

    def test_save_context_history(self):
        """Prueba que el historial de contexto se guarda como JSON en el campo 'context_history'."""
        history = [{"role": "user", "content": "hi"}]
        expected_json = json.dumps(history)
        self.service.save_context_history(self.company_short_name, self.user_identifier, history)
        self.mock_redis_manager.hset.assert_called_once_with(self.session_key, 'context_history', expected_json)

    def test_get_context_history(self):
        """Prueba que el historial se lee y deserializa desde el campo 'context_history'."""
        expected_history = [{"role": "user", "content": "hi"}]
        self.mock_redis_manager.hget.return_value = json.dumps(expected_history)
        result = self.service.get_context_history(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.hget.assert_called_once_with(self.session_key, 'context_history')
        self.assertEqual(result, expected_history)

    def test_save_context_version(self):
        """Prueba que la versión del contexto se guarda en el campo 'context_version'."""
        version = "v1.2.3"
        self.service.save_context_version(self.company_short_name, self.user_identifier, version)
        self.mock_redis_manager.hset.assert_called_once_with(self.session_key, 'context_version', version)

    def test_get_context_version(self):
        """Prueba que la versión del contexto se obtiene del campo 'context_version'."""
        self.mock_redis_manager.hget.return_value = "v1.2.3"
        result = self.service.get_context_version(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.hget.assert_called_once_with(self.session_key, 'context_version')
        self.assertEqual(result, "v1.2.3")

    def test_clear_all_context(self):
        """Prueba que se elimina la clave de sesión completa de forma atómica."""
        self.service.clear_all_context(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.remove.assert_called_once_with(self.session_key)

    def test_methods_do_nothing_with_invalid_identifiers(self):
        """
        Prueba que ningún método interactúa con Redis si el company o user_identifier son inválidos.
        """
        invalid_identifiers = [None, "", "   "]

        for user_id in invalid_identifiers:
            with self.subTest(user_id=user_id):
                # Probar métodos de escritura
                self.service.save_last_response_id(self.company_short_name, user_id, "id_1")
                self.service.save_profile_data(self.company_short_name, user_id, {"data": "value"})
                self.service.save_context_version(self.company_short_name, user_id, "v1")
                self.service.save_context_history(self.company_short_name, user_id, [])
                self.service.clear_all_context(self.company_short_name, user_id)

                # Probar métodos de lectura
                self.assertIsNone(self.service.get_last_response_id(self.company_short_name, user_id))
                self.assertEqual(self.service.get_profile_data(self.company_short_name, user_id), {})

        # Verificar que NUNCA se llamó a los métodos de Redis
        self.mock_redis_manager.hset.assert_not_called()
        self.mock_redis_manager.hget.assert_not_called()
        self.mock_redis_manager.remove.assert_not_called()
