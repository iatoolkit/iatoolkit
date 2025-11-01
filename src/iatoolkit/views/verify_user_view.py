# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, url_for, redirect, session
from iatoolkit.services.profile_service import ProfileService
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from iatoolkit.services.branding_service import BrandingService  # ¡Importante!
from injector import inject
import os


class VerifyAccountView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService, branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.serializer = URLSafeTimedSerializer(os.getenv("USER_VERIF_KEY"))

    def get(self, company_short_name: str, token: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        branding_data = self.branding_service.get_company_branding(company)
        try:
            # decode the token from the URL
            email = self.serializer.loads(token, salt='email-confirm', max_age=3600*5)
        except SignatureExpired:
            return render_template('signup.html',
                                   company=company,
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   token=token,
                                   alert_message="El enlace de verificación ha expirado. Por favor, solicita uno nuevo."), 400

        try:
            response = self.profile_service.verify_account(email)
            if "error" in response:
                return render_template(
                    'signup.html',
                    company=company,
                    company_short_name=company_short_name,
                    branding=branding_data,
                    token=token,
                    alert_message=response["error"]), 400

            # Guardamos el mensaje y el icono en la sesión manualmente
            session['alert_message'] = response['message']
            session['alert_icon'] = "success"
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            return render_template("error.html",
                                   company_short_name=company_short_name,
                                   branding=branding_data,
                                   message="Ha ocurrido un error inesperado."), 500
