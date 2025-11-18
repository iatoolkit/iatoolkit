# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
import time
import jwt  # Necesario para crear tokens con payloads específicos para casos de error
from flask import Flask
from iatoolkit.services.jwt_service import JWTService # Asegúrate que la ruta de importación sea correcta
from unittest.mock import patch


# Datos comunes para los tests, pueden ser definidos a nivel de módulo o clase
COMPANY_ID = 1
COMPANY_SHORT_NAME = "testcomp"
EXTERNAL_USER_ID = "user123"
EXPIRES_DELTA_SECONDS = 300  # 5 minutos
TEST_SECRET_KEY = 'test-super-secret-key'
TEST_ALGORITHM = 'HS256'

@pytest.fixture
def app():
    """Fixture para crear una instancia de la aplicación Flask para tests."""
    flask_app = Flask(__name__)
    flask_app.config['IATOOLKIT_SECRET_KEY'] = TEST_SECRET_KEY
    flask_app.config['JWT_ALGORITHM'] = TEST_ALGORITHM
    return flask_app

@pytest.fixture
def jwt_service(app):
    """Fixture para crear una instancia de JWTService."""
    return JWTService(app)

class TestJWTService:

    def test_initialization_missing_config(self):
        """Prueba que JWTService levante RuntimeError si falta configuración."""
        app_sin_config_key = Flask(__name__)
        app_sin_config_key.config['JWT_ALGORITHM'] = TEST_ALGORITHM  # Falta IATOOLKIT_SECRET_KEY
        with pytest.raises(RuntimeError, match="missing JWT configuration variables: 'IATOOLKIT_SECRET_KEY'"):
            JWTService(app_sin_config_key)

        app_sin_config_algo = Flask(__name__)
        app_sin_config_algo.config['IATOOLKIT_SECRET_KEY'] = TEST_SECRET_KEY  # Falta JWT_ALGORITHM
        with pytest.raises(RuntimeError, match="missing JWT configuration variables: 'JWT_ALGORITHM'"):
            JWTService(app_sin_config_algo)

    def test_generate_chat_jwt_success(self, jwt_service, app):
        """Prueba la generación exitosa de un JWT."""
        token = jwt_service.generate_chat_jwt(
            COMPANY_SHORT_NAME,
            EXTERNAL_USER_ID,
            EXPIRES_DELTA_SECONDS
        )
        assert token is not None
        assert isinstance(token, str)

        # Decodificar para verificar el payload
        payload = jwt.decode(
            token,
            app.config['IATOOLKIT_SECRET_KEY'],
            algorithms=[app.config['JWT_ALGORITHM']]
        )
        assert payload['company_short_name'] == COMPANY_SHORT_NAME
        assert payload['user_identifier'] == EXTERNAL_USER_ID
        assert payload['type'] == 'chat_session'
        assert 'exp' in payload
        assert 'iat' in payload
        # Usar pytest.approx para comparar timestamps con una tolerancia
        assert payload['exp'] == pytest.approx(time.time() + EXPIRES_DELTA_SECONDS, abs=5)

    @patch('jwt.encode')
    def test_generate_chat_jwt_encode_exception(self, mock_jwt_encode, jwt_service):
        mock_jwt_encode.side_effect = Exception("JWT Encode Error")
        token = jwt_service.generate_chat_jwt(
            COMPANY_SHORT_NAME,
            EXTERNAL_USER_ID,
            EXPIRES_DELTA_SECONDS
        )
        assert token is None

    def test_validate_chat_jwt_success(self, jwt_service):
        """Prueba la validación exitosa de un JWT."""
        token = jwt_service.generate_chat_jwt(
            COMPANY_SHORT_NAME,
            EXTERNAL_USER_ID,
            EXPIRES_DELTA_SECONDS
        )
        payload = jwt_service.validate_chat_jwt(token)
        assert payload is not None
        assert payload['company_short_name'] == COMPANY_SHORT_NAME
        assert payload['user_identifier'] == EXTERNAL_USER_ID
        assert payload['type'] == 'chat_session'

    def test_validate_chat_jwt_expired(self, jwt_service):
        """Prueba la validación de un JWT expirado."""
        token = jwt_service.generate_chat_jwt(
            COMPANY_SHORT_NAME,
            EXTERNAL_USER_ID,
            expires_delta_seconds=1  # Expira en 1 segundo
        )
        time.sleep(2)  # Esperar a que expire
        payload = jwt_service.validate_chat_jwt(token)
        assert payload is None

    def test_validate_chat_jwt_invalid_signature(self, jwt_service, app):
        """Prueba la validación de un JWT con firma inválida."""
        payload_data = {
            'company_short_name': COMPANY_SHORT_NAME,
            'user_identifier': EXTERNAL_USER_ID,
            'exp': time.time() + EXPIRES_DELTA_SECONDS,
            'iat': time.time(),
            'type': 'chat_session'
        }
        # Generar token con una clave secreta diferente
        invalid_token = jwt.encode(
            payload_data,
            'another-wrong-secret-key',
            algorithm=app.config['JWT_ALGORITHM']
        )
        payload = jwt_service.validate_chat_jwt(invalid_token)
        assert payload is None

    def test_validate_chat_jwt_incorrect_type(self, jwt_service, app):
        """Prueba la validación de un JWT con un tipo incorrecto."""
        payload_data = {
            'company_short_name': COMPANY_SHORT_NAME,
            'user_identifier': EXTERNAL_USER_ID,
            'exp': time.time() + EXPIRES_DELTA_SECONDS,
            'iat': time.time(),
            'type': 'not_chat_session'  # Tipo incorrecto
        }
        token_wrong_type = jwt.encode(
            payload_data,
            app.config['IATOOLKIT_SECRET_KEY'],
            algorithm=app.config['JWT_ALGORITHM']
        )
        payload = jwt_service.validate_chat_jwt(token_wrong_type)
        assert payload is None

    def test_validate_chat_jwt_missing_user_identifier(self, jwt_service, app):
        """Prueba la validación de un JWT sin user_identifier."""
        payload_data_missing = {
            'company_short_name': COMPANY_SHORT_NAME,
            # 'user_identifier': EXTERNAL_USER_ID, # Ausente
            'exp': time.time() + EXPIRES_DELTA_SECONDS,
            'iat': time.time(),
            'type': 'chat_session'
        }
        token_missing_field = jwt.encode(
            payload_data_missing,
            app.config['IATOOLKIT_SECRET_KEY'],
            algorithm=app.config['JWT_ALGORITHM']
        )
        payload = jwt_service.validate_chat_jwt(token_missing_field)
        assert payload is None

        payload_data_empty_user_id = {
            'company_short_name': COMPANY_SHORT_NAME,
            'user_identifier': "",  # Vacío
            'exp': time.time() + EXPIRES_DELTA_SECONDS,
            'iat': time.time(),
            'type': 'chat_session'
        }
        token_empty_user_id = jwt.encode(
            payload_data_empty_user_id,
            app.config['IATOOLKIT_SECRET_KEY'],
            algorithm=app.config['JWT_ALGORITHM']
        )
        payload = jwt_service.validate_chat_jwt(token_empty_user_id)
        assert payload is None


    def test_validate_chat_jwt_empty_token(self, jwt_service):
        """Prueba la validación con un token vacío."""
        payload = jwt_service.validate_chat_jwt("")
        assert payload is None

    @patch('jwt.decode')
    def test_validate_chat_jwt_decode_exception(self, mock_jwt_decode, jwt_service):
        """Prueba que validate_chat_jwt maneje excepciones generales de jwt.decode (no InvalidTokenError)."""
        mock_jwt_decode.side_effect = Exception("JWT Decode Error")
        # Necesitamos un token, aunque será el mock el que falle.
        # Podríamos pasar cualquier string, pero generar uno real es más consistente.
        token = jwt_service.generate_chat_jwt(
            COMPANY_SHORT_NAME,
            EXTERNAL_USER_ID,
            EXPIRES_DELTA_SECONDS
        )
        payload = jwt_service.validate_chat_jwt(token)
        assert payload is None

