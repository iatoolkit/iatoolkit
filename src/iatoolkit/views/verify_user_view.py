# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, url_for, redirect, session, flash
from iatoolkit.services.profile_service import ProfileService
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.i18n_service import I18nService
from injector import inject
import os


class VerifyAccountView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 i18n_service: I18nService):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.i18n_service = i18n_service
        self.serializer = URLSafeTimedSerializer(os.getenv("IATOOLKIT_SECRET_KEY"))

    def get(self, company_short_name: str, token: str):
        try:
            # get company info
            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return render_template('error.html',
                                       message=self.i18n_service.t('errors.templates.company_not_found')), 404

            branding_data = self.branding_service.get_company_branding(company_short_name)
            try:
                # decode the token from the URL
                email = self.serializer.loads(token, salt='email-confirm', max_age=3600*5)
            except SignatureExpired:
                flash(self.i18n_service.t('errors.verification.token_expired'), 'error')
                return render_template('signup.html',
                                       company_short_name=company_short_name,
                                       branding=branding_data,
                                       token=token), 400

            response = self.profile_service.verify_account(email)
            if "error" in response:
                flash(response["error"], 'error')
                return render_template(
                    'signup.html',
                    company_short_name=company_short_name,
                    branding=branding_data,
                    token=token), 400

            flash(response['message'], 'success')
            return redirect(url_for('home', company_short_name=company_short_name))

        except Exception as e:
            flash(self.i18n_service.t('errors.general.unexpected_error', error=str(e)), 'error')
            return redirect(url_for('home', company_short_name=company_short_name))
