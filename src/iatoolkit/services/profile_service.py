# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import User, Company, ApiKey
from flask_bcrypt import check_password_hash
from iatoolkit.common.session_manager import SessionManager
from iatoolkit.services.user_session_context_service import UserSessionContextService
from flask_bcrypt import Bcrypt
from iatoolkit.infra.mail_app import MailApp
import random
import logging
import re
import secrets
import string
from datetime import datetime, timezone


class ProfileService:
    @inject
    def __init__(self,
                 profile_repo: ProfileRepo,
                 session_context_service: UserSessionContextService,
                 mail_app: MailApp):
        self.profile_repo = profile_repo
        self.session_context = session_context_service
        self.mail_app = mail_app
        self.bcrypt = Bcrypt()


    def login(self, company_short_name: str, email: str, password: str) -> dict:
        try:
            # check if user exists
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {'success': False, "message": "Usuario no encontrado"}

            # check the encrypted password
            if not check_password_hash(user.password, password):
                return {'success': False, "message": "Contraseña inválida"}

            company = self.get_company_by_short_name(company_short_name)
            if not company:
                return {'success': False, "message": "Empresa no encontrada"}

            # check that user belongs to company
            if company not in user.companies:
                return {'success': False, "message": "Usuario no esta autorizado para esta empresa"}

            if not user.verified:
                return {'success': False,
                        "message": "Tu cuenta no ha sido verificada. Por favor, revisa tu correo."}

            # save user data into session manager
            self.set_user_session(user=user, company=company)

            return {'success': True, "user": user, "message": "Login exitoso"}
        except Exception as e:
            return {'success': False, "message": str(e)}


    def set_user_session(self, user: User, company: Company):

        # define the user data dictionary here
        user_profile = {
            "id": user.id,
            "user_id": user.id,
            "email": user.email,
            "user_fullname": f'{user.first_name} {user.last_name}',
            "company_id": company.id,
            "company": company.name,
            "company_short_name": company.short_name,
            "user_is_local": True,
            "last_activity": datetime.now(timezone.utc).timestamp(),
            "extras": {}
        }

        # save the user_profile in the persistent context
        self.session_context.save_profile_data(company.short_name, str(user.id), user_profile)

        # this should be deleted
        SessionManager.set('user', user_profile)

        # save time session was activated (in timestamp format)
        SessionManager.set('last_activity', datetime.now(timezone.utc).timestamp())

        # save minimum identifiers in the Flask session for identify the user on every request
        SessionManager.set('user_id', user.id)
        SessionManager.set('company_short_name', company.short_name)
        SessionManager.set('company_id', company.id)


    def get_current_user_profile(self) -> dict:
        """
        Devuelve el perfil del usuario para la solicitud actual, sin importar si es una sesión
        antigua (solo en Flask Session) o nueva (en Redis Hash).
        """
        user_id = SessionManager.get('user_id')
        company_short_name = SessionManager.get('company_short_name')

        if not user_id or not company_short_name:
            return {}       # No hay sesión activa

        # Prioridad 1: Leer del nuevo sistema unificado
        profile = self.session_context.get_profile_data(company_short_name, str(user_id))
        if profile:
            return profile

        # Prioridad 2 (Fallback): Es una sesión antigua, leer de Flask Session
        legacy_profile = SessionManager.get('user', {})
        if legacy_profile:
            # Auto-migración: Guardar en el nuevo sistema para la próxima vez
            self.session_context.save_profile_data(company_short_name, str(user_id), legacy_profile)
            return legacy_profile

        return {}

    def signup(self,
               company_short_name: str,
               email: str,
               first_name: str,
               last_name: str,
               password: str,
               confirm_password: str,
               verification_url: str) -> dict:
        try:

            # get company info
            company = self.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": f"la empresa {company_short_name} no existe"}

            # normalize  format's
            email = email.lower()

            # check if user exists
            existing_user = self.profile_repo.get_user_by_email(email)
            if existing_user:
                # validate password
                if not self.bcrypt.check_password_hash(existing_user.password, password):
                    return {"error": "La contraseña es incorrecta. No se puede agregar a la nueva empresa."}

                # check if register
                if company in existing_user.companies:
                    return {"error": "Usuario ya registrado en esta empresa"}
                else:
                    # add new company to existing user
                    existing_user.companies.append(company)
                    self.profile_repo.save_user(existing_user)
                    return {"message": "Usuario asociado a nueva empresa"}

            # add the new user
            if password != confirm_password:
                return {"error": "Las contraseñas no coinciden. Por favor, inténtalo de nuevo."}

            is_valid, message = self.validate_password(password)
            if not is_valid:
                return {"error": message}

            # encrypt the password
            hashed_password = self.bcrypt.generate_password_hash(password).decode('utf-8')

            # create the new user
            new_user = User(email=email,
                            password=hashed_password,
                            first_name=first_name.lower(),
                            last_name=last_name.lower(),
                            verified=False,
                            verification_url=verification_url
                            )

            # associate new company to user
            new_user.companies.append(company)

            self.profile_repo.create_user(new_user)

            # send email with verification
            self.send_verification_email(new_user, company_short_name)

            return {"message": "Registro exitoso. Por favor, revisa tu correo para verificar tu cuenta."}
        except Exception as e:
            return {"error": str(e)}

    def update_user(self, email: str, **kwargs) -> User:
        return self.profile_repo.update_user(email, **kwargs)

    def verify_account(self, email: str):
        try:
            # check if user exist
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {"error": "El usuario no existe."}

            # activate the user account
            self.profile_repo.verify_user(email)
            return {"message": "Tu cuenta ha sido verificada exitosamente. Ahora puedes iniciar sesión."}

        except Exception as e:
            return {"error": str(e)}

    def change_password(self,
                         email: str,
                         temp_code: str,
                         new_password: str,
                         confirm_password: str):
        try:
            if new_password != confirm_password:
                return {"error": "Las contraseñas no coinciden. Por favor, inténtalo nuevamente."}

            # check the temporary code
            user = self.profile_repo.get_user_by_email(email)
            if not user or user.temp_code != temp_code:
                return {"error": "El código temporal no es válido. Por favor, verifica o solicita uno nuevo."}

            # encrypt and save the password, make the temporary code invalid
            hashed_password = self.bcrypt.generate_password_hash(new_password).decode('utf-8')
            self.profile_repo.update_password(email, hashed_password)
            self.profile_repo.reset_temp_code(email)

            return {"message": "La clave se cambio correctamente"}
        except Exception as e:
            return {"error": str(e)}

    def forgot_password(self, email: str, reset_url: str):
        try:
            # Verificar si el usuario existe
            user = self.profile_repo.get_user_by_email(email)
            if not user:
                return {"error": "El usuario no existe."}

            # Gen a temporary code and store in the repositories
            temp_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6)).upper()
            self.profile_repo.set_temp_code(email, temp_code)

            # send email to the user
            self.send_forgot_password_email(user, reset_url)

            return {"message": "se envio mail para cambio de clave"}
        except Exception as e:
            return {"error": str(e)}

    def validate_password(self, password):
        """
        Valida que una contraseña cumpla con los siguientes requisitos:
        - Al menos 8 caracteres de longitud
        - Contiene al menos una letra mayúscula
        - Contiene al menos una letra minúscula
        - Contiene al menos un número
        - Contiene al menos un carácter especial
        """
        if len(password) < 8:
            return False, "La contraseña debe tener al menos 8 caracteres."

        if not any(char.isupper() for char in password):
            return False, "La contraseña debe tener al menos una letra mayúscula."

        if not any(char.islower() for char in password):
            return False, "La contraseña debe tener al menos una letra minúscula."

        if not any(char.isdigit() for char in password):
            return False, "La contraseña debe tener al menos un número."

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "La contraseña debe tener al menos un carácter especial."

        return True, "La contraseña es válida."

    def get_companies(self):
        return self.profile_repo.get_companies()

    def get_company_by_short_name(self, short_name: str) -> Company:
        return self.profile_repo.get_company_by_short_name(short_name)

    def get_active_api_key_entry(self, api_key_value: str) -> ApiKey | None:
        return self.profile_repo.get_active_api_key_entry(api_key_value)

    def new_api_key(self, company_short_name: str):
        company = self.get_company_by_short_name(company_short_name)
        if not company:
            return {"error": f"la empresa {company_short_name} no existe"}

        length = 40     # lenght of the api key
        alphabet = string.ascii_letters + string.digits
        key = ''.join(secrets.choice(alphabet) for i in range(length))

        api_key = ApiKey(key=key, company_id=company.id)
        self.profile_repo.create_api_key(api_key)
        return {"api-key": key}


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
                                        <p>¡Bienvenido a <strong>{company_short_name}</strong>! Estamos encantados de tenerte con nosotros.</p>
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
        self.mail_app.send_email(to=new_user.email, subject=subject, body=body)

    def send_forgot_password_email(self, user: User, reset_url: str):
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

        self.mail_app.send_email(to=user.email, subject=subject, body=body)
        return {"message": "se envio mail para cambio de clave"}
