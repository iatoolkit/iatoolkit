# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, redirect, flash
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from injector import inject
from itsdangerous import URLSafeTimedSerializer
import os


class SignupView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.branding_service = branding_service # 3. Guardar la instancia
        self.i18n_service = i18n_service

        self.serializer = URLSafeTimedSerializer(os.getenv("IATOOLKIT_SECRET_KEY"))


    def get(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

        branding_data = self.branding_service.get_company_branding(company_short_name)
        return render_template('signup.html',
                               company_short_name=company_short_name,
                               branding=branding_data)

    def post(self, company_short_name: str):
        try:
            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html',
                                     message=self.i18n_service.t('errors.templates.company_not_found')), 404

            branding_data = self.branding_service.get_company_branding(company_short_name)

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
                flash(response["error"], 'error')
                return render_template(
                    'signup.html',
                    company_short_name=company_short_name,
                    branding=branding_data,
                    form_data={
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": email,
                        "password": password,
                        "confirm_password": confirm_password
                    }), 400

            flash(response["message"], 'success')
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message
            ), 500
