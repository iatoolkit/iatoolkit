# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.models import User, Company
from flask_bcrypt import check_password_hash
from flask import request, has_request_context
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.configuration_service import ConfigurationService
from flask_bcrypt import Bcrypt
from iatoolkit.services.mail_service import MailService
from iatoolkit.infra.google_auth_client import GoogleIdentity
import random
import re
import string
import logging
from datetime import datetime
from typing import List, Dict
from iatoolkit.common.interfaces.signup_policy_resolver import SignupPolicyResolver
from iatoolkit.services.signup_policy_resolver import AllowAllSignupPolicyResolver


class ProfileService:
    @inject
    def __init__(self,
                 i18n_service: I18nService,
                 profile_repo: ProfileRepo,
                 session_context_service: UserSessionContextService,
                 config_service: ConfigurationService,
                 lang_service: LanguageService,
                 dispatcher: Dispatcher,
                 mail_service: MailService,
                 signup_policy_resolver: SignupPolicyResolver = None):
        self.i18n_service = i18n_service
        self.profile_repo = profile_repo
        self.dispatcher = dispatcher
        self.session_context = session_context_service
        self.config_service = config_service
        self.lang_service = lang_service
        self.mail_service = mail_service
        self.signup_policy_resolver = signup_policy_resolver or AllowAllSignupPolicyResolver()
        self.bcrypt = Bcrypt()

    @staticmethod
    def _is_google_auth_user(user: User | None) -> bool:
        if not user:
            return False
        return str(getattr(user, "auth_method", "local") or "local").lower() == "google"

    def _safe_rollback(self):
        """
        Best-effort rollback to recover the scoped session after DB failures.
        """
        try:
            self.profile_repo.session.rollback()
        except Exception as rollback_error:
            logging.warning(f"ProfileService rollback failed: {rollback_error}")

    @staticmethod
    def _normalize_name_value(value: str | None, fallback: str) -> str:
        text = str(value or "").strip()
        if not text:
            text = fallback
        return text.lower()

    def _resolve_google_names(self, email: str, google_identity: GoogleIdentity) -> tuple[str, str]:
        given_name = str(google_identity.given_name or "").strip()
        family_name = str(google_identity.family_name or "").strip()
        full_name = str(google_identity.full_name or "").strip()

        if not given_name and full_name:
            parts = [part.strip() for part in full_name.split() if part.strip()]
            if parts:
                given_name = parts[0]
            if len(parts) > 1:
                family_name = " ".join(parts[1:])

        local_part = str(email or "user").split("@", 1)[0].strip() or "user"
        first_name = self._normalize_name_value(given_name, local_part)
        last_name = self._normalize_name_value(family_name, "user")
        return first_name, last_name

    def _build_session_user_profile(self, user: User, company: Company, user_role: str | None) -> dict:
        auth_method = str(getattr(user, "auth_method", "local") or "local").lower()
        is_local = auth_method == "local"
        user_identifier = user.email
        user_profile = {
            "user_email": user.email,
            "user_fullname": f'{user.first_name} {user.last_name}',
            "user_is_local": is_local,
            "user_id": user.id,
            "user_role": user_role,
            "extras": {
                "auth_method": auth_method,
            }
        }
        if auth_method == "google":
            user_profile["extras"]["google_email_verified"] = bool(user.google_email_verified)
            if user.google_email:
                user_profile["extras"]["google_email"] = user.google_email

        self.save_user_profile(company, user_identifier, user_profile)
        self.set_session_for_user(company.short_name, user_identifier)

        return {
            'success': True,
            'user_identifier': user_identifier,
            'message': 'Login ok',
        }

    def _link_user_to_google(self, user: User, google_identity: GoogleIdentity):
        user.auth_method = 'google'
        user.google_sub = google_identity.subject
        user.google_email = google_identity.email
        user.google_email_verified = bool(google_identity.email_verified)
        user.google_linked_at = user.google_linked_at or datetime.now()
        user.verified = True

        first_name, last_name = self._resolve_google_names(google_identity.email, google_identity)
        if not str(user.first_name or "").strip():
            user.first_name = first_name
        if not str(user.last_name or "").strip():
            user.last_name = last_name

    def login(self, company_short_name: str, email: str, password: str) -> dict:
        try:
            # check if user exists
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {'success': False, 'message': self.i18n_service.t('errors.auth.user_not_found')}

            if self._is_google_auth_user(user):
                return {
                    'success': False,
                    'message': self.i18n_service.t('errors.auth.google_account_requires_google_login')
                }

            # check the encrypted password
            if not user.password or not check_password_hash(user.password, password):
                return {'success': False, 'message': self.i18n_service.t('errors.auth.invalid_password')}

            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {'success': False, "message": "missing company"}

            # check that user belongs to company
            if company not in user.companies:
                return {'success': False, "message": self.i18n_service.t('errors.services.user_not_authorized')}

            if not user.verified:
                return {'success': False,
                        "message": self.i18n_service.t('errors.services.account_not_verified')}

            user_role = self.profile_repo.get_user_role_in_company(company.id, user.id)

            return self._build_session_user_profile(user, company, user_role)
        except Exception as e:
            self._safe_rollback()
            logging.error(f"Error in login: {e}")
            return {'success': False, "message": str(e)}

    def save_user_profile(self, company: Company, user_identifier: str, user_profile: dict):
        """
        Private helper: Takes a pre-built profile, saves it to Redis, and sets the Flask cookie.
        """
        user_profile['company_short_name'] = company.short_name
        user_profile['user_identifier'] = user_identifier
        user_profile['id'] = user_identifier
        user_profile['company_id'] = company.id
        user_profile['company'] = company.name
        user_profile['language'] = self.lang_service.get_current_language()

        # save user_profile in Redis session
        self.session_context.save_profile_data(company.short_name, user_identifier, user_profile)

    def _get_company_sessions(self) -> dict[str, dict]:
        raw_sessions = SessionManager.get('company_sessions', {})
        return raw_sessions if isinstance(raw_sessions, dict) else {}

    def _resolve_session_company_short_name(self, company_short_name: str = None) -> str | None:
        if company_short_name:
            return company_short_name

        if has_request_context() and request.view_args and request.view_args.get('company_short_name'):
            return request.view_args.get('company_short_name')

        active_company_short_name = SessionManager.get('active_company_short_name')
        if active_company_short_name:
            return active_company_short_name

        company_sessions = self._get_company_sessions()
        if len(company_sessions) == 1:
            return next(iter(company_sessions.keys()))

        return None

    def set_session_for_user(self, company_short_name: str, user_identifier:str ):
        # save a min Flask session cookie for this user
        SessionManager.set_permanent(True)
        company_sessions = self._get_company_sessions()
        company_sessions[company_short_name] = {
            'user_identifier': user_identifier,
        }
        SessionManager.set('company_sessions', company_sessions)
        SessionManager.set('active_company_short_name', company_short_name)

    def _set_active_company_short_name(self, company_short_name: str | None):
        if not company_short_name:
            return
        if SessionManager.get('active_company_short_name') == company_short_name:
            return
        SessionManager.set('active_company_short_name', company_short_name)

    def clear_session_for_company(self, company_short_name: str):
        company_sessions = self._get_company_sessions()
        if company_short_name in company_sessions:
            company_sessions.pop(company_short_name, None)

        if company_sessions:
            SessionManager.set('company_sessions', company_sessions)
        else:
            SessionManager.remove('company_sessions')

        active_company_short_name = SessionManager.get('active_company_short_name')
        if active_company_short_name == company_short_name:
            if company_sessions:
                SessionManager.set('active_company_short_name', next(iter(company_sessions.keys())))
            else:
                SessionManager.remove('active_company_short_name')

    def get_current_session_info(self, company_short_name: str = None) -> dict:
        """
         Gets the current web user's profile from the unified session.
         This is the standard way to access user data for web requests.
        """
        resolved_company_short_name = self._resolve_session_company_short_name(company_short_name)
        if not resolved_company_short_name:
            return {}

        company_sessions = self._get_company_sessions()
        session_entry = company_sessions.get(resolved_company_short_name) or {}
        user_identifier = session_entry.get('user_identifier')

        if not user_identifier:
            # No authenticated web user.
            return {}

        # Keep the fallback session pointer aligned with the company currently
        # resolved for this request. This helps any subsequent non-scoped reads.
        self._set_active_company_short_name(resolved_company_short_name)

        # 2. Use the identifiers to fetch the full, authoritative profile from Redis.
        profile = self.session_context.get_profile_data(resolved_company_short_name, user_identifier)

        return {
            "user_identifier": user_identifier,
            "company_short_name": resolved_company_short_name,
            "profile": profile
        }

    def update_user_language(self, user_identifier: str, new_lang: str) -> dict:
        """
        Business logic to update a user's preferred language.
        It validates the language and then calls the generic update method.
        """
        # 1. Validate that the language is supported by checking the loaded translations.
        if new_lang not in self.i18n_service.translations:
            return {'success': False, 'error_message': self.i18n_service.t('errors.general.unsupported_language')}

        try:
            # 2. Call the generic update_user method, passing the specific field to update.
            self.update_user(user_identifier, preferred_language=new_lang)
            return {'success': True, 'message': 'Language updated successfully.'}
        except Exception as e:
            self._safe_rollback()
            # Log the error and return a generic failure message.
            logging.error(f"Failed to update language for {user_identifier}: {e}")
            return {'success': False, 'error_message': self.i18n_service.t('errors.general.unexpected_error', error=str(e))}


    def get_profile_by_identifier(self, company_short_name: str, user_identifier: str) -> dict:
        """
        Fetches a user profile directly by their identifier, bypassing the Flask session.
        This is ideal for API-side checks.
        """
        if not company_short_name or not user_identifier:
            return {}
        return self.session_context.get_profile_data(company_short_name, user_identifier)

    def login_with_google(self, company_short_name: str, google_identity: GoogleIdentity) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {
                    "success": False,
                    "message": self.i18n_service.t('errors.signup.company_not_found', company_name=company_short_name),
                    "reason_code": "COMPANY_NOT_FOUND",
                }

            email = str(google_identity.email or "").strip().lower()
            if not email or not google_identity.email_verified:
                return {
                    "success": False,
                    "message": self.i18n_service.t('errors.auth.google_email_not_verified'),
                    "reason_code": "GOOGLE_EMAIL_NOT_VERIFIED",
                }

            user = None
            persisted = False
            user_by_google_sub = self.profile_repo.get_user_by_google_sub(google_identity.subject)

            if user_by_google_sub:
                logging.debug(
                    "Google login matched existing google_sub. company=%s email=%s user_id=%s",
                    company_short_name,
                    email,
                    user_by_google_sub.id,
                )
                user = user_by_google_sub
                if str(user.email or "").strip().lower() != email:
                    return {
                        "success": False,
                        "message": self.i18n_service.t('errors.auth.google_account_email_changed'),
                        "reason_code": "GOOGLE_EMAIL_CHANGED",
                    }
                self._link_user_to_google(user, google_identity)
                persisted = True
            else:
                user = self.profile_repo.get_user_by_email(email)
                if user:
                    logging.debug(
                        "Google login matched existing email. company=%s email=%s user_id=%s current_auth_method=%s",
                        company_short_name,
                        email,
                        user.id,
                        getattr(user, "auth_method", None),
                    )
                    if self._is_google_auth_user(user) and user.google_sub and user.google_sub != google_identity.subject:
                        return {
                            "success": False,
                            "message": self.i18n_service.t('errors.auth.google_account_conflict'),
                            "reason_code": "GOOGLE_ACCOUNT_CONFLICT",
                        }
                    self._link_user_to_google(user, google_identity)
                    persisted = True
                else:
                    logging.debug(
                        "Google login creating new user. company=%s email=%s",
                        company_short_name,
                        email,
                    )
                    first_name, last_name = self._resolve_google_names(email, google_identity)
                    user = User(
                        email=email,
                        password=None,
                        auth_method='google',
                        first_name=first_name,
                        last_name=last_name,
                        verified=True,
                        google_sub=google_identity.subject,
                        google_email=email,
                        google_email_verified=True,
                        google_linked_at=datetime.now(),
                    )

            if company not in user.companies:
                logging.debug(
                    "Google login evaluating company association. company=%s email=%s",
                    company_short_name,
                    email,
                )
                policy_decision = self.signup_policy_resolver.evaluate_signup(
                    company_short_name=company_short_name,
                    email=email,
                    invite_token=None,
                )
                if not policy_decision.allowed:
                    if policy_decision.reason_message:
                        message = policy_decision.reason_message
                    elif policy_decision.reason_key:
                        message = self.i18n_service.t(policy_decision.reason_key)
                    else:
                        message = self.i18n_service.t('errors.signup.signup_not_allowed')
                    return {
                        "success": False,
                        "message": message,
                        "reason_code": "SIGNUP_NOT_ALLOWED",
                    }
                user.companies.append(company)
                persisted = True

            if user.id is None:
                logging.debug(
                    "Google login persisting new user. company=%s email=%s",
                    company_short_name,
                    email,
                )
                self.profile_repo.create_user(user)
            elif persisted:
                logging.debug(
                    "Google login saving existing user updates. company=%s email=%s user_id=%s",
                    company_short_name,
                    email,
                    user.id,
                )
                self.profile_repo.save_user(user)

            user_role = self.profile_repo.get_user_role_in_company(company.id, user.id)
            return self._build_session_user_profile(user, company, user_role)
        except Exception as e:
            self._safe_rollback()
            return {
                "success": False,
                "message": self.i18n_service.t('errors.general.unexpected_error', error=str(e)),
                "reason_code": "UNEXPECTED_ERROR",
            }


    def signup(self,
               company_short_name: str,
               email: str,
               first_name: str,
               last_name: str,
               password: str,
               confirm_password: str,
               verification_url: str,
               invite_token: str = None) -> dict:
        try:

            # get company info
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {
                    "error": self.i18n_service.t('errors.signup.company_not_found', company_name=company_short_name)}

            # normalize  format's
            email = email.lower()

            policy_decision = self.signup_policy_resolver.evaluate_signup(
                company_short_name=company_short_name,
                email=email,
                invite_token=invite_token,
            )
            if not policy_decision.allowed:
                if policy_decision.reason_message:
                    return {"error": policy_decision.reason_message}
                if policy_decision.reason_key:
                    return {"error": self.i18n_service.t(policy_decision.reason_key)}
                return {"error": self.i18n_service.t('errors.signup.signup_not_allowed')}

            # check if user exists
            existing_user = self.profile_repo.get_user_by_email(email)
            if existing_user:
                if self._is_google_auth_user(existing_user):
                    return {"error": self.i18n_service.t('errors.signup.google_account_requires_google_login', email=email)}

                # validate password
                if not existing_user.password or not self.bcrypt.check_password_hash(existing_user.password, password):
                    return {"error": self.i18n_service.t('errors.signup.incorrect_password_for_existing_user', email=email)}

                # check if register
                if company in existing_user.companies:
                    return {"error": self.i18n_service.t('errors.signup.user_already_registered', email=email)}
                else:
                    # add new company to existing user
                    existing_user.companies.append(company)
                    self.profile_repo.save_user(existing_user)
                    return {"message": self.i18n_service.t('flash_messages.user_associated_success')}

            # add the new user
            if password != confirm_password:
                return {"error": self.i18n_service.t('errors.signup.password_mismatch')}

            is_valid, message = self.validate_password(password)
            if not is_valid:
                # Translate the key returned by validate_password
                return {"error": self.i18n_service.t(message)}

            # encrypt the password
            hashed_password = self.bcrypt.generate_password_hash(password).decode('utf-8')

            # account verification can be skiped with this security parameter
            verified = False
            cfg = self.config_service.get_configuration(company_short_name, 'parameters')
            if cfg and not cfg.get('verify_account', True):
                verified = True
                message = self.i18n_service.t('flash_messages.signup_success_no_verification')

            # create the new user
            new_user = User(email=email,
                            password=hashed_password,
                            auth_method='local',
                            first_name=first_name.lower(),
                            last_name=last_name.lower(),
                            verified=verified,
                            verification_url=verification_url
                            )

            # associate new company to user
            new_user.companies.append(company)

            # and create in the database
            self.profile_repo.create_user(new_user)

            # send email with verification
            if not cfg or cfg.get('verify_account', True):
                self.send_verification_email(new_user, company_short_name)
                message = self.i18n_service.t('flash_messages.signup_success')

            return {"message": message}
        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error', error=str(e))}

    def update_user(self, email: str, **kwargs) -> User:
        return self.profile_repo.update_user(email, **kwargs)

    def verify_account(self, email: str):
        try:
            # check if user exist
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {"error": self.i18n_service.t('errors.verification.user_not_found')}

            # activate the user account
            self.profile_repo.verify_user(email)
            return {"message": self.i18n_service.t('flash_messages.account_verified_success')}

        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error', error=str(e))}

    def change_password(self,
                         email: str,
                         temp_code: str,
                         new_password: str,
                         confirm_password: str):
        try:
            if new_password != confirm_password:
                return {"error": self.i18n_service.t('errors.change_password.password_mismatch')}

            # check the temporary code
            user = self.profile_repo.get_user_by_email(email)
            if self._is_google_auth_user(user):
                return {"error": self.i18n_service.t('errors.change_password.google_account_password_disabled')}
            if not user or user.temp_code != temp_code:
                return {"error": self.i18n_service.t('errors.change_password.invalid_temp_code')}

            # encrypt and save the password, make the temporary code invalid
            hashed_password = self.bcrypt.generate_password_hash(new_password).decode('utf-8')
            self.profile_repo.update_password(email, hashed_password)
            self.profile_repo.reset_temp_code(email)

            return {"message": self.i18n_service.t('flash_messages.password_changed_success')}
        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error', error=str(e))}

    def forgot_password(self, company_short_name: str, email: str, reset_url: str):
        try:
            # Verificar si el usuario existe
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {"error": self.i18n_service.t('errors.forgot_password.user_not_registered', email=email)}

            if self._is_google_auth_user(user):
                return {"error": self.i18n_service.t('errors.forgot_password.google_account_password_disabled')}

            # Gen a temporary code and store in the repositories
            temp_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6)).upper()
            self.profile_repo.set_temp_code(email, temp_code)

            # send email to the user
            self.send_forgot_password_email(company_short_name, user, reset_url)

            return {"message": self.i18n_service.t('flash_messages.forgot_password_success')}
        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error', error=str(e))}

    def validate_password(self, password):
        """
        Validates that a password meets all requirements.
        Returns (True, "...") on success, or (False, "translation.key") on failure.
        """
        if len(password) < 8:
            return False, "errors.validation.password_too_short"

        if not any(char.isupper() for char in password):
            return False, "errors.validation.password_no_uppercase"

        if not any(char.islower() for char in password):
            return False, "errors.validation.password_no_lowercase"

        if not any(char.isdigit() for char in password):
            return False, "errors.validation.password_no_digit"

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "errors.validation.password_no_special_char"

        return True, "Password is valid."

    def get_companies(self):
        return self.profile_repo.get_companies()

    def get_company_by_short_name(self, short_name: str) -> Company:
        return self.profile_repo.get_company_by_short_name(short_name)

    def get_company_users(self, company_short_name: str) -> List[Dict]:
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            return []

        # get the company users from the repo
        company_users =  self.profile_repo.get_company_users_with_details(company_short_name)

        users_data = []
        for user, role, last_access in company_users:
            users_data.append({
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "created": user.created_at,
                "verified": user.verified,
                "role": role or "user",
                "last_access": last_access
            })

        return users_data

    def send_verification_email(self, new_user: User, company_short_name):
        # send verification account email
        subject = f"Verificación de Cuenta - {company_short_name}"
        body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Verificación de Cuenta - {company_short_name}</title>
            </head>
            <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 0;">
                <table role="presentation" width="100%" bgcolor="#f4f4f4" cellpadding="0" cellspacing="0" border="0">
                    <tr>
                        <td align="center">
                            <table role="presentation" width="600" bgcolor="#ffffff" cellpadding="20" cellspacing="0" border="0" style="border-radius: 8px; box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);">
                                
                                <tr>
                                    <td style="text-align: left; font-size: 16px; color: #333;">
                                        <p>Hola <strong>{new_user.first_name}</strong>,</p>
                                        <p>¡Bienvenido a <strong>IAToolkit</strong>! Estamos encantados de tenerte con nosotros.</p>
                                        <p>Para comenzar, verifica tu cuenta haciendo clic en el siguiente botón:</p>
                                        <p style="text-align: center; margin: 20px 0;">
                                            <a href="{new_user.verification_url}"
                                               style="background-color: #007bff; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 5px; font-size: 16px; display: inline-block;">
                                                Verificar Cuenta
                                            </a>
                                        </p>
                                        <p>Si no puedes hacer clic en el botón, copia y pega el siguiente enlace en tu navegador:</p>
                                        <p style="word-break: break-word; color: #007bff;">
                                            <a href="{new_user.verification_url}"
                                               style="color: #007bff;">
                                                {new_user.verification_url}
                                            </a>
                                        </p>
                                        <p>Si no creaste una cuenta en {company_short_name}, simplemente ignora este correo.</p>
                                        <p>¡Gracias por unirte a nuestra comunidad!</p>
                                        <p style="margin-top: 20px;">Saludos,<br><strong>El equipo de {company_short_name}</strong></p>
                                    </td>
                                </tr>
                            </table>
                            <p style="font-size: 12px; color: #666; margin-top: 10px;">
                                Este es un correo automático, por favor no respondas a este mensaje.
                            </p>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
            """
        self.mail_service.send_mail(company_short_name=company_short_name,
                                    recipient=new_user.email,
                                    subject=subject,
                                    body=body)

    def send_forgot_password_email(self, company_short_name: str, user: User, reset_url: str):
        # send email to the user
        subject = f"Recuperación de Contraseña "
        body = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Restablecer Contraseña </title>
                </head>
                <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 0;">
                    <table role="presentation" width="100%" bgcolor="#f4f4f4" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td align="center">
                                <table role="presentation" width="600" bgcolor="#ffffff" cellpadding="20" cellspacing="0" border="0" style="border-radius: 8px; box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);">
            
                                    <tr>
                                        <td style="text-align: left; font-size: 16px; color: #333;">
                                            <p>Hola <strong>{user.first_name}</strong>,</p>
                                            <p>Hemos recibido una solicitud para restablecer tu contraseña. </p>
                                            <p>Utiliza el siguiente botón para ingresar tu código temporal y cambiar tu contraseña:</p>
                                            <p style="text-align: center; margin: 20px 0;">
                                                <a href="{reset_url}"
                                                   style="background-color: #007bff; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 5px; font-size: 16px; display: inline-block;">
                                                    Restablecer Contraseña
                                                </a>
                                            </p>
                                            <p><strong>Tu código temporal es:</strong></p>
                                            <p style="font-size: 20px; font-weight: bold; text-align: center; background-color: #f8f9fa; padding: 10px; border-radius: 5px; border: 1px solid #ccc;">
                                                {user.temp_code}
                                            </p>
                                            <p>Si el botón no funciona, también puedes copiar y pegar el siguiente enlace en tu navegador:</p>
                                            <p style="word-break: break-word; color: #007bff;">
                                                <a href="{reset_url}" style="color: #007bff;">{reset_url}</a>
                                            </p>
                                            <p>Si no solicitaste este cambio, ignora este correo. Tu cuenta permanecerá segura.</p>
                                            <p style="margin-top: 20px;">Saludos,<br><strong>El equipo de TI</strong></p>
                                        </td>
                                    </tr>
                                </table>
                                <p style="font-size: 12px; color: #666; margin-top: 10px;">
                                    Este es un correo automático, por favor no respondas a este mensaje.
                                </p>
                            </td>
                        </tr>
                    </table>
                </body>
                </html>
                """

        self.mail_service.send_mail(company_short_name=company_short_name,
                                    recipient=user.email,
                                    subject=subject,
                                    body=body)
        return {"message": self.i18n_service.t('services.mail_change_password') }
