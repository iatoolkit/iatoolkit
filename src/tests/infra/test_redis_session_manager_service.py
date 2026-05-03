import unittest
import json
from unittest.mock import patch, MagicMock
from iatoolkit.infra.redis_session_manager import RedisSessionManager


class TestRedisSessionManager(unittest.TestCase):

    def setUp(self):
        """
        Configura los patches y mocks comunes para las pruebas.
        La clave aquí es parchear _get_client para evitar cualquier llamada de red.
        """
        # Parchear el método que obtiene el cliente Redis
        self.get_client_patcher = patch('iatoolkit.infra.redis_session_manager.RedisSessionManager._get_client')

        # Iniciar el parche y obtener el mock del método
        self.mock_get_client = self.get_client_patcher.start()

        # Crear un mock para simular el cliente Redis real (ej. redis.Redis())
        self.mock_redis_client = MagicMock()

        # Configurar el método parcheado para que siempre devuelva nuestro cliente mockeado
        self.mock_get_client.return_value = self.mock_redis_client

    def tearDown(self):
        patch.stopall()

    def test_set(self):
        """Prueba que el método set llama correctamente a `client.set`."""
        RedisSessionManager.set('my_key', 'my_value', ex=3600)

        # Verificar que se obtuvo el cliente
        self.mock_get_client.assert_called_once()

        # Verificar que se llamó al método `set` del cliente Redis con los argumentos correctos
        self.mock_redis_client.set.assert_called_once_with('my_key', 'my_value', ex=3600)

    def test_get_existing_key(self):
        """Prueba que el método get devuelve el valor correcto si la clave existe."""
        # Simular que Redis devuelve un valor
        self.mock_redis_client.get.return_value = 'retrieved_value'

        result = RedisSessionManager.get('existing_key')

        self.assertEqual(result, 'retrieved_value')
        self.mock_redis_client.get.assert_called_once_with('existing_key')

    def test_get_decodes_bytes_value(self):
        self.mock_redis_client.get.return_value = b'retrieved_value'

        result = RedisSessionManager.get('existing_key')

        self.assertEqual(result, 'retrieved_value')
        self.mock_redis_client.get.assert_called_once_with('existing_key')

    def test_get_non_existing_key(self):
        """Prueba que get devuelve el valor por defecto (string vacío) si la clave no existe."""
        # Simular que Redis no encuentra la clave
        self.mock_redis_client.get.return_value = None

        result = RedisSessionManager.get('non_existing_key')

        # El valor por defecto en la firma del método es ""
        self.assertEqual(result, "")

    def test_hget_decodes_bytes_value(self):
        self.mock_redis_client.hget.return_value = b'field_value'

        result = RedisSessionManager.hget('hash_key', 'field')

        self.assertEqual(result, 'field_value')
        self.mock_redis_client.hget.assert_called_once_with('hash_key', 'field')

    def test_remove(self):
        """Prueba que el método remove llama a `client.delete`."""
        RedisSessionManager.remove('key_to_delete')

        self.mock_get_client.assert_called_once()
        self.mock_redis_client.delete.assert_called_once_with('key_to_delete')

    def test_set_json(self):
        """Prueba que el método set_json serializa el diccionario y llama a `set`."""
        test_data = {'user': 'test', 'permissions': [1, 2, 3]}
        expected_json_string = json.dumps(test_data)

        RedisSessionManager.set_json('json_key', test_data, ex=60)

        # Verificar que se llamó a set con el string JSON correcto
        self.mock_redis_client.set.assert_called_once_with('json_key', expected_json_string, ex=60)

    def test_get_json_existing_key(self):
        """Prueba que get_json obtiene un string y lo deserializa correctamente."""
        test_data = {'user': 'test', 'id': 123}
        json_string = json.dumps(test_data)
        self.mock_redis_client.get.return_value = json_string

        result = RedisSessionManager.get_json('json_key')

        self.assertEqual(result, test_data)

    def test_get_json_non_existing_key(self):
        """Prueba que get_json devuelve el diccionario por defecto si la clave no existe."""
        self.mock_redis_client.get.return_value = ""  # Simula una clave no encontrada

        # Probar con el default por defecto ({})
        result_default = RedisSessionManager.get_json('non_existing_key')
        self.assertEqual(result_default, {})

        # Probar con un default personalizado
        custom_default = {"default": True}
        result_custom = RedisSessionManager.get_json('non_existing_key', default=custom_default)
        self.assertEqual(result_custom, custom_default)

    @patch('iatoolkit.infra.redis_session_manager.logging')
    def test_get_json_invalid_json(self, mock_logging):
        """
        Prueba que get_json maneja un string inválido, loguea una advertencia
        y devuelve el valor por defecto.
        """
        invalid_json_string = '{"key": "value",}'  # JSON mal formado
        self.mock_redis_client.get.return_value = invalid_json_string

        result = RedisSessionManager.get_json('invalid_json_key')

        self.assertEqual(result, {})

        # Verificar que se registró una advertencia
        mock_logging.warning.assert_called_once()
        # Verificar que el mensaje de log contiene información útil
        log_message = mock_logging.warning.call_args[0][0]
        self.assertIn("Invalid JSON", log_message)
        self.assertIn("invalid_json_key", log_message)
