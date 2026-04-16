# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import jwt
import time
import logging
from injector import singleton, inject
from typing import Optional, Dict, Any
from flask import Flask


@singleton
class JWTService:
    @inject
    def __init__(self,  app: Flask):
        # Acceder a la configuración directamente desde app.config
        try:
            self.secret_key = app.config['IATOOLKIT_SECRET_KEY']
            self.algorithm = app.config['JWT_ALGORITHM']
        except KeyError as e:
            logging.error(f"missing JWT configuration: {e}.")
            raise RuntimeError(f"missing JWT configuration variables: {e}")

    def generate_chat_jwt(self,
                          company_short_name: str,
                          user_identifier: str,
                          expires_delta_seconds: int) -> Optional[str]:
        # generate a JWT for a chat session
        try:
            if not company_short_name or not user_identifier:
                logging.error(f"Missing token ID: {company_short_name}/{user_identifier}")
                return None

            payload = {
                'company_short_name': company_short_name,
                'user_identifier': user_identifier,
                'exp': time.time() + expires_delta_seconds,
                'iat': time.time(),
                'type': 'chat_session'  # Identificador del tipo de token
            }
            token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
            return token
        except Exception as e:
            logging.error(f"Error al generar JWT para {company_short_name}/{user_identifier}: {e}")
            return None

    def validate_chat_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Valida un JWT de sesión de chat.
        Retorna el payload decodificado si es válido y coincide con la empresa, o None.
        """
        if not token:
            return None
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Validaciones adicionales
            if payload.get('type') != 'chat_session':
                logging.warning(f"Invalid JWT type '{payload.get('type')}'")
                return None

            # user_identifier debe estar presente
            if not payload.get('user_identifier'):
                logging.warning(f"missing user_identifier in JWT payload.")
                return None

            if not payload.get('company_short_name'):
                logging.warning(f"missing company_short_name in JWT payload.")
                return None

            return payload

        except jwt.InvalidTokenError as e:
            logging.warning(f"Invalid JWT token:: {e}")
            return None
        except Exception as e:
            logging.error(f"unexpected error during JWT validation: {e}")
            return None
