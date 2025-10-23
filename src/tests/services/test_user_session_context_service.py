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

        # Patchear RedisSessionManager para aislar el servicio, añadiendo los nuevos métodos al spec
        self.redis_patcher = patch("iatoolkit.services.user_session_context_service.RedisSessionManager", spec=True)
        self.mock_redis_manager = self.redis_patcher.start()

        # Añadir explícitamente los métodos de Hash y Pipeline al mock para que `spec=True` no falle
        self.mock_redis_manager.hget = MagicMock()
        self.mock_redis_manager.hset = MagicMock()
        self.mock_redis_manager.hdel = MagicMock()
        self.mock_redis_manager.pipeline = MagicMock()

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

    def test_save_profile_data(self):
        """Prueba que los datos de perfil se guardan como JSON en el campo 'profile_data'."""
        data = {"role": "admin", "theme": "dark"}
        expected_json = json.dumps(data)
        self.service.save_profile_data(self.company_short_name, self.user_identifier, data)
        self.mock_redis_manager.hset.assert_called_once_with(self.session_key, 'profile_data', expected_json)

    def test_get_profile_data(self):
        """Prueba que los datos de perfil se leen y deserializan desde el campo 'profile_data'."""
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

    def test_clear_llm_history(self):
        """Prueba que se eliminan solo los campos del historial del LLM."""
        self.service.clear_llm_history(self.company_short_name, self.user_identifier)
        self.mock_redis_manager.hdel.assert_called_once_with(self.session_key, 'last_response_id', 'context_history')

    def test_save_prepared_context(self):
        """Prueba que el contexto preparado y su versión se guardan correctamente."""
        context_str = "Este es el contexto preparado"
        version_str = "v_prep_1"
        self.service.save_prepared_context(self.company_short_name, self.user_identifier, context_str, version_str)

        # Verificar que se llamó a hset para ambos campos
        self.mock_redis_manager.hset.assert_any_call(self.session_key, 'prepared_context', context_str)
        self.mock_redis_manager.hset.assert_any_call(self.session_key, 'prepared_context_version', version_str)
        self.assertEqual(self.mock_redis_manager.hset.call_count, 2)

    def test_get_and_clear_prepared_context(self):
        """Prueba que se obtiene y limpia el contexto preparado de forma atómica usando una pipeline."""
        # Configurar el mock de la pipeline
        mock_pipe = MagicMock()
        self.mock_redis_manager.pipeline.return_value = mock_pipe

        # El resultado de pipe.execute() será una lista con los resultados de cada comando en la pipeline
        mock_pipe.execute.return_value = ["contexto_preparado", "v_prep_1"]

        # Act
        context, version = self.service.get_and_clear_prepared_context(self.company_short_name, self.user_identifier)

        # Assert
        self.assertEqual(context, "contexto_preparado")
        self.assertEqual(version, "v_prep_1")

        # Verificar que la pipeline se usó correctamente
        self.mock_redis_manager.pipeline.assert_called_once()
        mock_pipe.hget.assert_any_call(self.session_key, 'prepared_context')
        mock_pipe.hget.assert_any_call(self.session_key, 'prepared_context_version')
        mock_pipe.hdel.assert_called_once_with(self.session_key, 'prepared_context', 'prepared_context_version')
        mock_pipe.execute.assert_called_once()

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
                self.service.save_prepared_context(self.company_short_name, user_id, "ctx", "v1")
                self.service.clear_all_context(self.company_short_name, user_id)
                self.service.clear_llm_history(self.company_short_name, user_id)

                # Probar métodos de lectura
                self.assertIsNone(self.service.get_last_response_id(self.company_short_name, user_id))
                self.assertEqual(self.service.get_profile_data(self.company_short_name, user_id), {})
                self.assertEqual(self.service.get_and_clear_prepared_context(self.company_short_name, user_id),
                                 (None, None))

        # Verificar que NUNCA se llamó a los métodos de Redis
        self.mock_redis_manager.hset.assert_not_called()
        self.mock_redis_manager.hget.assert_not_called()
        self.mock_redis_manager.remove.assert_not_called()
        self.mock_redis_manager.hdel.assert_not_called()
        self.mock_redis_manager.pipeline.assert_not_called()