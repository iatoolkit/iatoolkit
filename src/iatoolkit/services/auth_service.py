# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.api_key_service import ApiKeyService
from iatoolkit.services.jwt_service import JWTService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import AccessLog
from iatoolkit.infra.google_auth_client import GoogleAuthClient, GoogleAuthError
from flask import request
import logging
import re
import unicodedata
import hashlib
from iatoolkit.common import access


class AuthService:
    """
    Centralized service for handling authentication for all incoming requests.
    It determines the user's identity based on either a Flask session cookie or an API Key.
    """
    # access-log scope for logins that are not tied to a company
    GLOBAL_ACCESS_SCOPE = '*'

    @inject
    def __init__(self, profile_service: ProfileService,
                 api_key_service: ApiKeyService,
                 jwt_service: JWTService,
                 db_manager: DatabaseManager,
                 google_auth_client: GoogleAuthClient,
                 i18n_service: I18nService
                 ):
        self.profile_service = profile_service
        self.api_key_service = api_key_service
        self.jwt_service = jwt_service
        self.db_manager = db_manager
        self.google_auth_client = google_auth_client
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

    def login_google_user(
        self,
        company_short_name: str,
        code: str,
        state: str,
        nonce: str,
        redirect_uri: str,
        lang: str | None = None,
        welcome_url: str | None = None,
    ) -> dict:
        try:
            google_identity = self.google_auth_client.exchange_code_for_identity(
                code=code,
                state=state,
                nonce=nonce,
                redirect_uri=redirect_uri,
            )
            logging.debug(
                "Google identity resolved. company=%s email=%s email_verified=%s subject=%s",
                company_short_name,
                google_identity.email,
                google_identity.email_verified,
                google_identity.subject,
            )
        except GoogleAuthError as exc:
            logging.warning(
                "Google auth client rejected login. company=%s reason_code=%s",
                company_short_name,
                exc.reason_code,
            )
            self.log_access(
                company_short_name=company_short_name,
                auth_type='google',
                outcome='failure',
                reason_code=exc.reason_code,
            )
            return {
                'success': False,
                'reason_code': exc.reason_code,
                'message': self.i18n_service.t(exc.message_key),
            }
        except Exception:
            logging.exception("Unexpected Google auth client failure. company=%s", company_short_name)
            self.log_access(
                company_short_name=company_short_name,
                auth_type='google',
                outcome='failure',
                reason_code='GOOGLE_AUTH_UNEXPECTED_ERROR',
            )
            return {
                'success': False,
                'reason_code': 'GOOGLE_AUTH_UNEXPECTED_ERROR',
                'message': self.i18n_service.t('errors.auth.google_login_failed'),
            }

        auth_response = self.profile_service.login_with_google(
            company_short_name=company_short_name,
            google_identity=google_identity,
            lang=lang,
            welcome_url=welcome_url,
        )

        if not auth_response.get('success'):
            logging.warning(
                "Google login rejected by profile service. company=%s email=%s reason_code=%s",
                company_short_name,
                google_identity.email,
                auth_response.get('reason_code', 'GOOGLE_LOGIN_FAILED'),
            )
            self.log_access(
                company_short_name=company_short_name,
                auth_type='google',
                outcome='failure',
                reason_code=auth_response.get('reason_code', 'GOOGLE_LOGIN_FAILED'),
                user_identifier=google_identity.email,
            )
        else:
            self.log_access(
                company_short_name=company_short_name,
                auth_type='google',
                outcome='success',
                user_identifier=auth_response.get('user_identifier'),
            )

        return auth_response

    def login_global_local_user(self, email: str, password: str) -> dict:
        # company-less login: authenticates the person, the company is chosen later
        auth_response = self.profile_service.authenticate_local_credentials(email=email, password=password)
        if not auth_response.get('success'):
            self.log_access(
                company_short_name=self.GLOBAL_ACCESS_SCOPE,
                user_identifier=email,
                auth_type='local',
                outcome='failure',
                reason_code='INVALID_CREDENTIALS',
            )
            return auth_response

        self.profile_service.set_global_identity(auth_response['user_identifier'], 'local')
        self.log_access(
            company_short_name=self.GLOBAL_ACCESS_SCOPE,
            auth_type='local',
            outcome='success',
            user_identifier=auth_response['user_identifier'],
        )
        return auth_response

    def login_global_google_user(self, code: str, state: str, nonce: str, redirect_uri: str) -> dict:
        try:
            google_identity = self.google_auth_client.exchange_code_for_identity(
                code=code,
                state=state,
                nonce=nonce,
                redirect_uri=redirect_uri,
            )
        except GoogleAuthError as exc:
            self.log_access(
                company_short_name=self.GLOBAL_ACCESS_SCOPE,
                auth_type='google',
                outcome='failure',
                reason_code=exc.reason_code,
            )
            return {
                'success': False,
                'reason_code': exc.reason_code,
                'message': self.i18n_service.t(exc.message_key),
            }
        except Exception:
            logging.exception("Unexpected Google auth client failure in company-less login.")
            self.log_access(
                company_short_name=self.GLOBAL_ACCESS_SCOPE,
                auth_type='google',
                outcome='failure',
                reason_code='GOOGLE_AUTH_UNEXPECTED_ERROR',
            )
            return {
                'success': False,
                'reason_code': 'GOOGLE_AUTH_UNEXPECTED_ERROR',
                'message': self.i18n_service.t('errors.auth.google_login_failed'),
            }

        auth_response = self.profile_service.identify_google_user(google_identity)
        if not auth_response.get('success'):
            self.log_access(
                company_short_name=self.GLOBAL_ACCESS_SCOPE,
                auth_type='google',
                outcome='failure',
                reason_code=auth_response.get('reason_code', 'GOOGLE_LOGIN_FAILED'),
                user_identifier=google_identity.email,
            )
            return auth_response

        self.profile_service.set_global_identity(auth_response['user_identifier'], 'google')
        self.log_access(
            company_short_name=self.GLOBAL_ACCESS_SCOPE,
            auth_type='google',
            outcome='success',
            user_identifier=auth_response['user_identifier'],
        )
        return auth_response

    def verify(self, anonymous: bool = False, company_short_name: str = None) -> dict:
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
        session_info = self.profile_service.get_current_session_info(company_short_name=company_short_name)
        if session_info and session_info.get('user_identifier'):
            # User is authenticated via a web session cookie.
            return {
                "success": True,
                "company_short_name": session_info['company_short_name'],
                "user_identifier": session_info['user_identifier'],
                # From the database, never from the stored session profile: an SSO
                # hook writes that profile, and must not be able to grant admin
                # (BL-010, Fase 0).
                "user_role": self._role_in_company(session_info['company_short_name'],
                                                   session_info['user_identifier']),
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
        api_key_entry = self.api_key_service.get_active_api_key_entry(api_key)
        if not api_key_entry:
            # Never the key itself: a mistyped or just-rotated key would end up in the logs.
            logging.error("Invalid or inactive IAToolkit API Key: %s", self.key_fingerprint(api_key))
            return {"success": False,
                    "error_message": self.i18n_service.t('errors.auth.invalid_api_key'),
                    "status_code": 402}

        # get the company from the api_key_entry
        company = api_key_entry.company

        # The key is a service account (BL-010, Fase 0): it acts as itself unless it
        # was allowed to act for users. Every result says which key acted.
        principal = self.service_principal(api_key_entry)
        base = {
            "success": True,
            "company_short_name": company.short_name,
            "auth_type": "api_key",
            "auth_principal": principal,
            "api_key_id": api_key_entry.id,
        }
        # Only an explicit False: a key loaded before the column existed keeps acting for users.
        if getattr(api_key_entry, "can_act_for_users", None) is False:
            # Whatever user the request names is ignored: the key cannot pass for anyone.
            return {**base, "user_identifier": principal, "acting_for": None}

        # A key allowed to act for users must say who (unless the endpoint allows none).
        data = request.get_json(silent=True) or {}
        user_identifier = data.get('user_identifier', '')
        if not anonymous and not user_identifier:
            logging.info(f"No user_identifier provided for API call.")
            return {"success": False,
                    "error_message": self.i18n_service.t('errors.auth.no_user_identifier_api'),
                    "status_code": 403}

        return {**base, "user_identifier": user_identifier, "acting_for": user_identifier or None}

    SERVICE_PREFIX = "service:"

    @staticmethod
    def key_fingerprint(api_key: str) -> str:
        """What a log may say about a key: its first characters and a short hash, enough to
        match it against the API Keys screen without exposing it."""
        value = str(api_key or "")
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        return f"prefix={value[:4]}… len={len(value)} sha256={digest}"

    @classmethod
    def service_principal(cls, api_key_entry) -> str:
        """The identity a key acts with by itself: "service:<key name>" (lowercase, dashes)."""
        raw = unicodedata.normalize("NFKD", str(getattr(api_key_entry, "key_name", "") or ""))
        ascii_name = raw.encode("ascii", "ignore").decode("ascii").strip().lower()
        name = re.sub(r"[^a-z0-9._-]+", "-", ascii_name)
        return f"{cls.SERVICE_PREFIX}{name.strip('-') or getattr(api_key_entry, 'id', 'key')}"

    def _role_in_company(self, company_short_name: str, user_identifier: str) -> str | None:
        """What the person can do over the company, by its old role name (BL-010, Fase 1).

        Views decide with `iatoolkit.common.access`; this name stays in the result to
        tell a session from an API key and for screens that show it.
        """
        if access.Access.registered():
            return access.effective_role(company_short_name, user_identifier)
        return self.profile_service.get_role_in_company(company_short_name, user_identifier)

    def verify_for_company(self, company_short_name: str, anonymous: bool = False) -> dict:
        """
        Verifies the current request and enforces that the authenticated tenant
        matches the tenant requested by the caller.
        """
        auth_result = self.verify(anonymous=anonymous, company_short_name=company_short_name)
        if not auth_result.get("success"):
            return auth_result

        auth_company_short_name = auth_result.get("company_short_name")
        if auth_company_short_name != company_short_name:
            logging.warning(
                "Forbidden access due to company mismatch. requested=%s authenticated=%s",
                company_short_name,
                auth_company_short_name,
            )
            return {
                "success": False,
                "error_message": "Forbidden",
                "status_code": 403,
            }

        return auth_result


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
