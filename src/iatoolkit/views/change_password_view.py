# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, session, redirect
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask_bcrypt import Bcrypt
from injector import inject
import os


class ChangePasswordView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service # 3. Guardar la instancia

        self.serializer = URLSafeTimedSerializer(os.getenv("PASS_RESET_KEY"))
        self.bcrypt = Bcrypt()

    def get(self, company_short_name: str, token: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message=f"Empresa no encontrada: {company_short_name}"), 404

        branding_data = self.branding_service.get_company_branding(company)

        try:
            # Decodificar el token
            email = self.serializer.loads(token, salt='password-reset', max_age=3600)
        except SignatureExpired as e:
            return render_template('forgot_password.html',
                                branding=branding_data,
                                alert_message="El enlace de cambio de contraseña ha expirado. Por favor, solicita uno nuevo.")

        return render_template('change_password.html',
                               company_short_name=company_short_name,
                               company=company,
                               branding=branding_data,
                               token=token, email=email)

    def post(self, company_short_name: str, token: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message=f"Empresa no encontrada: {company_short_name}"), 404

        branding_data = self.branding_service.get_company_branding(company)
        try:
            # Decodificar el token
            email = self.serializer.loads(token, salt='password-reset', max_age=3600)
        except SignatureExpired:
            return render_template('forgot_password.html',
                                   company_short_name=company_short_name,
                                   company=company,
                                   branding=branding_data,
                                    alert_message="El enlace de cambio de contraseña ha expirado. Por favor, solicita uno nuevo.")

        try:
            # Obtener datos del formulario
            temp_code = request.form.get('temp_code')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')

            response = self.profile_service.change_password(
                email=email,
                temp_code=temp_code,
                new_password=new_password,
                confirm_password=confirm_password
            )

            if "error" in response:
                return render_template(
                    'change_password.html',
                    token=token,
                    company_short_name=company_short_name,
                    company=company,
                    branding=branding_data,
                    form_data={"temp_code": temp_code,
                               "new_password": new_password,
                               "confirm_password": confirm_password},
                    alert_message=response["error"]), 400

            # Éxito: Guardar mensaje en sesión y redirigir
            session['alert_message'] = "Tu contraseña ha sido restablecida exitosamente. Ahora puedes iniciar sesión."
            session['alert_icon'] = 'success'
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   message=f"Ha ocurrido un error inesperado: {str(e)}"), 500
