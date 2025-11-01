# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, redirect, session
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from itsdangerous import URLSafeTimedSerializer
import os

class ForgotPasswordView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service # 3. Guardar la instancia
        self.serializer = URLSafeTimedSerializer(os.getenv("PASS_RESET_KEY"))

    def get(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                        company_short_name=company_short_name,
                        message="Empresa no encontrada"), 404

        branding_data = self.branding_service.get_company_branding(company)
        return render_template('forgot_password.html',
                               company=company,
                               company_short_name=company_short_name,
                               branding=branding_data
                               )

    def post(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                            company_short_name=company_short_name,
                            message="Empresa no encontrada"), 404
        branding_data = self.branding_service.get_company_branding(company)

        try:
            email = request.form.get('email')

            # create a safe token and url for it
            token = self.serializer.dumps(email, salt='password-reset')
            reset_url = url_for('change_password',
                                company_short_name=company_short_name,
                                token=token, _external=True)

            response = self.profile_service.forgot_password(email=email, reset_url=reset_url)
            if "error" in response:
                return render_template(
                    'forgot_password.html',
                    company=company,
                    company_short_name=company_short_name,
                    branding=branding_data,
                    form_data={"email": email},
                    alert_message=response["error"]), 400

            # Guardamos el mensaje y el icono en la sesión manualmente
            session['alert_message'] = "Si tu correo está registrado, recibirás un enlace para restablecer tu contraseña."
            session['alert_icon'] = "success"
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            return render_template("error.html",
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   message=f"Ha ocurrido un error inesperado: {str(e)}"), 500

