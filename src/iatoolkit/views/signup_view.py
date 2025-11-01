# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, session, redirect
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService # 1. Importar BrandingService
from injector import inject
from itsdangerous import URLSafeTimedSerializer
import os


class SignupView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service # 3. Guardar la instancia
        self.serializer = URLSafeTimedSerializer(os.getenv("USER_VERIF_KEY"))


    def get(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        # Obtener los datos de branding
        branding_data = self.branding_service.get_company_branding(company)

        return render_template('signup.html',
                               company=company,
                               company_short_name=company_short_name,
                               branding=branding_data)

    def post(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        try:
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            # create verification token and url for verification
            token = self.serializer.dumps(email, salt='email-confirm')
            verification_url = url_for('verify_account',
                                       company_short_name=company_short_name,
                                       token=token, _external=True)

            response = self.profile_service.signup(
                company_short_name=company_short_name,
                email=email,
                first_name=first_name, last_name=last_name,
                password=password, confirm_password=confirm_password,
                verification_url=verification_url)

            if "error" in response:
                branding_data = self.branding_service.get_company_branding(company)
                return render_template(
                    'signup.html',
                    company=company,
                    company_short_name=company_short_name,
                    branding=branding_data,
                    form_data={
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": email,
                        "password": password,
                        "confirm_password": confirm_password
                    },
                    alert_message=response["error"]), 400

            # Guardamos el mensaje de éxito en la sesión
            session['alert_message'] = response["message"]
            session['alert_icon'] = 'success'

            # Redirigimos al usuario a la página de login
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message=f"Ha ocurrido un error inesperado: {str(e)}"), 500

