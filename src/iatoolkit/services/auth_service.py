# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import AccessLog
from flask import request
import logging
import hashlib


class AuthService:
    """
    Centralized service for handling authentication for all incoming requests.
    It determines the user's identity based on either a Flask session cookie or an API Key.
    """

    @inject
    def __init__(self, profile_service: ProfileService,
                 jwt_service: JWTService,
                 db_manager: DatabaseManager,
                 i18n_service: I18nService
                 ):
        self.profile_service = profile_service
        self.jwt_service = jwt_service
        self.db_manager = db_manager
        self.i18n_service = i18n_service

    def login_local_user(self, company_short_name: str, email: str, password: str) -> dict:
        # try to autenticate a local user, register the event and return the result
        auth_response = self.profile_service.login(
            company_short_name=company_short_name,
            email=email,
            password=password,
        )

        if not auth_response.get('success'):
            self.log_access(
                company_short_name=company_short_name,
                user_identifier=email,
                auth_type='local',
                outcome='failure',
                reason_code='INVALID_CREDENTIALS',
            )
        else:
            self.log_access(
                company_short_name=company_short_name,
                auth_type='local',
                outcome='success',
                user_identifier=auth_response.get('user_identifier')
            )

        return auth_response

    def redeem_token_for_session(self, company_short_name: str, token: str) -> dict:
        # redeem a token for a session, register the event and return the result
        payload = self.jwt_service.validate_chat_jwt(token)

        if not payload:
            self.log_access(
                company_short_name=company_short_name,
                auth_type='redeem_token',
                outcome='failure',
                reason_code='JWT_INVALID'
            )
            return {'success': False, 'error': self.i18n_service.t('errors.auth.invalid_or_expired_token')}

        # 2. if token is valid, extract the user_identifier
        user_identifier = payload.get('user_identifier')
        try:
            # create the Flask session
            self.profile_service.set_session_for_user(company_short_name, user_identifier)
            self.log_access(
                company_short_name=company_short_name,
                auth_type='redeem_token',
                outcome='success',
                user_identifier=user_identifier
            )
            return {'success': True, 'user_identifier': user_identifier}
        except Exception as e:
            logging.error(f"error creeating session for Token of {user_identifier}: {e}")
            self.log_access(
                company_short_name=company_short_name,
                auth_type='redeem_token',
                outcome='failure',
                reason_code='SESSION_CREATION_FAILED',
                user_identifier=user_identifier
            )
            return {'success': False, 'error': self.i18n_service.t('errors.auth.session_creation_failed')}

    def verify(self, anonymous: bool = False) -> dict:
        """
        Verifies the current request and identifies the user.
        If anonymous is True the non-presence of use_identifier is ignored

        Returns a dictionary with:
        - success: bool
        - user_identifier: str (if successful)
        - company_short_name: str (if successful)
        - error_message: str (on failure)
        - status_code: int (on failure)
        """
        # --- Priority 1: Check for a valid Flask web session ---
        session_info = self.profile_service.get_current_session_info()
        if session_info and session_info.get('user_identifier'):
            # User is authenticated via a web session cookie.
            return {
                "success": True,
                "company_short_name": session_info['company_short_name'],
                "user_identifier": session_info['user_identifier'],
            }

        # --- Priority 2: Check for a valid API Key in headers ---
        api_key = None
        auth = request.headers.get('Authorization', '')
        if isinstance(auth, str) and auth.lower().startswith('bearer '):
            api_key =  auth.split(' ', 1)[1].strip()

        if not api_key:
            # --- Failure: No valid credentials found ---
            logging.info(f"Authentication required. No session cookie or API Key provided.")
            return {"success": False,
                    "error_message": self.i18n_service.t('errors.auth.authentication_required'),
                    "status_code": 401}

        # check if the api-key is valid and active
        api_key_entry = self.profile_service.get_active_api_key_entry(api_key)
        if not api_key_entry:
            logging.info(f"Invalid or inactive API Key {api_key}")
            return {"success": False,
                    "error_message": self.i18n_service.t('errors.auth.invalid_api_key'),
                    "status_code": 402}

        # get the company from the api_key_entry
        company = api_key_entry.company

        # For API calls, the external_user_id must be provided in the request.
        data = request.get_json(silent=True) or {}
        user_identifier = data.get('user_identifier', '')
        if not anonymous and not user_identifier:
            logging.info(f"No user_identifier provided for API call.")
            return {"success": False,
                    "error_message": self.i18n_service.t('errors.auth.no_user_identifier_api'),
                    "status_code": 403}

        return {
            "success": True,
            "company_short_name": company.short_name,
            "user_identifier": user_identifier
        }


    def log_access(self,
                   company_short_name: str,
                   auth_type: str,
                   outcome: str,
                   user_identifier: str = None,
                   reason_code: str = None):
        """
        Registra un intento de acceso en la base de datos.
        Es "best-effort" y no debe interrumpir el flujo de autenticación.
        """
        session = self.db_manager.scoped_session()
        try:
            # Capturar datos del contexto de la petición de Flask
            source_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            path = request.path
            ua = request.headers.get('User-Agent', '')
            ua_hash = hashlib.sha256(ua.encode()).hexdigest()[:16] if ua else None

            # Crear la entrada de log
            log_entry = AccessLog(
                company_short_name=company_short_name,
                user_identifier=user_identifier,
                auth_type=auth_type,
                outcome=outcome,
                reason_code=reason_code,
                source_ip=source_ip,
                user_agent_hash=ua_hash,
                request_path=path,
            )
            session.add(log_entry)
            session.commit()

        except Exception as e:
            logging.error(f"error writting to AccessLog: {e}", exc_info=False)
            session.rollback()