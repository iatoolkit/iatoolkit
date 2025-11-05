# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, redirect, session, flash
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from itsdangerous import URLSafeTimedSerializer
import os

class ForgotPasswordView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service

        self.serializer = URLSafeTimedSerializer(os.getenv("PASS_RESET_KEY"))

    def get(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

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
                                   message=self.i18n_service.t('errors.templates.company_not_found')), 404

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
                flash(response["error"], 'error')
                return render_template(
                    'forgot_password.html',
                    company=company,
                    company_short_name=company_short_name,
                    branding=branding_data,
                    form_data={"email": email}), 400

            flash(self.i18n_service.t('flash_messages.forgot_password_success'), 'success')
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            flash(self.i18n_service.t('errors.general.unexpected_error'), 'error')
            return redirect(url_for('home', company_short_name=company_short_name))
