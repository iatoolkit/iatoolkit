# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.models import User, Company
from flask_bcrypt import check_password_hash
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.language_service import LanguageService
from iatoolkit.services.user_session_context_service import UserSessionContextService
from iatoolkit.services.configuration_service import ConfigurationService
from flask_bcrypt import Bcrypt
from iatoolkit.services.mail_service import MailService
import random
import re
import string
import logging
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

    def _safe_rollback(self):
        """
        Best-effort rollback to recover the scoped session after DB failures.
        """
        try:
            self.profile_repo.session.rollback()
        except Exception as rollback_error:
            logging.warning(f"ProfileService rollback failed: {rollback_error}")

    def login(self, company_short_name: str, email: str, password: str) -> dict:
        try:
            # check if user exists
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {'success': False, 'message': self.i18n_service.t('errors.auth.user_not_found')}

            # check the encrypted password
            if not check_password_hash(user.password, password):
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

            # 1. Build the local user profile dictionary here.
            # the user_profile variables are used on the LLM templates also (see in query_main.prompt)
            user_identifier = user.email
            user_profile = {
                "user_email": user.email,
                "user_fullname": f'{user.first_name} {user.last_name}',
                "user_is_local": True,
                "user_id": user.id,
                "user_role": user_role,
                "extras": {}
            }

            # 2. create user_profile in context
            self.save_user_profile(company, user_identifier, user_profile)

            # 3. create the web session
            self.set_session_for_user(company.short_name, user_identifier)

            return {'success': True, "user_identifier": user_identifier, "message": "Login ok"}
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

    def set_session_for_user(self, company_short_name: str, user_identifier:str ):
        # save a min Flask session cookie for this user
        SessionManager.set('company_short_name', company_short_name)
        SessionManager.set('user_identifier', user_identifier)

    def get_current_session_info(self) -> dict:
        """
         Gets the current web user's profile from the unified session.
         This is the standard way to access user data for web requests.
         """
        # 1. Get identifiers from the simple Flask session cookie.
        user_identifier = SessionManager.get('user_identifier')
        company_short_name = SessionManager.get('company_short_name')

        if not user_identifier or not company_short_name:
            # No authenticated web user.
            return {}

        # 2. Use the identifiers to fetch the full, authoritative profile from Redis.
        profile = self.session_context.get_profile_data(company_short_name, user_identifier)

        return {
            "user_identifier": user_identifier,
            "company_short_name": company_short_name,
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
                # validate password
                if not self.bcrypt.check_password_hash(existing_user.password, password):
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
            return {"error": self.i18n_service.t('errors.general.unexpected_error')}

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
            if not user or user.temp_code != temp_code:
                return {"error": self.i18n_service.t('errors.change_password.invalid_temp_code')}

            # encrypt and save the password, make the temporary code invalid
            hashed_password = self.bcrypt.generate_password_hash(new_password).decode('utf-8')
            self.profile_repo.update_password(email, hashed_password)
            self.profile_repo.reset_temp_code(email)

            return {"message": self.i18n_service.t('flash_messages.password_changed_success')}
        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error')}

    def forgot_password(self, company_short_name: str, email: str, reset_url: str):
        try:
            # Verificar si el usuario existe
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {"error": self.i18n_service.t('errors.forgot_password.user_not_registered', email=email)}

            # Gen a temporary code and store in the repositories
            temp_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6)).upper()
            self.profile_repo.set_temp_code(email, temp_code)

            # send email to the user
            self.send_forgot_password_email(company_short_name, user, reset_url)

            return {"message": self.i18n_service.t('flash_messages.forgot_password_success')}
        except Exception as e:
            self._safe_rollback()
            return {"error": self.i18n_service.t('errors.general.unexpected_error')}

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
