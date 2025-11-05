# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, session, redirect, flash
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask_bcrypt import Bcrypt
from injector import inject
import os


class ChangePasswordView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service

        self.serializer = URLSafeTimedSerializer(os.getenv("PASS_RESET_KEY"))
        self.bcrypt = Bcrypt()

    def get(self, company_short_name: str, token: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        branding_data = self.branding_service.get_company_branding(company)

        try:
            # Decodificar el token
            email = self.serializer.loads(token, salt='password-reset', max_age=3600)
        except SignatureExpired as e:
            flash(self.i18n_service.t('errors.change_password.token_expired'), 'error')
            return render_template('forgot_password.html',
                                branding=branding_data)

        return render_template('change_password.html',
                               company_short_name=company_short_name,
                               company=company,
                               branding=branding_data,
                               token=token,
                               email=email)

    def post(self, company_short_name: str, token: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        branding_data = self.branding_service.get_company_branding(company)
        try:
            # Decodificar el token
            email = self.serializer.loads(token, salt='password-reset', max_age=3600)
        except SignatureExpired:
            flash(self.i18n_service.t('errors.change_password.token_expired'), 'error')

            return render_template('forgot_password.html',
                                   company_short_name=company_short_name,
                                   company=company,
                                   branding=branding_data)

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
                flash(response["error"], 'error')

                return render_template(
                    'change_password.html',
                    token=token,
                    company_short_name=company_short_name,
                    company=company,
                    branding=branding_data,
                    form_data={"temp_code": temp_code,
                               "new_password": new_password,
                               "confirm_password": confirm_password}), 400

            flash(self.i18n_service.t('flash_messages.password_changed_success'), 'success')
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            message = self.i18n_service.t('errors.templates.home_template_processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500