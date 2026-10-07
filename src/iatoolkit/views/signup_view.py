# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request, url_for, redirect, flash, make_response
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
        current_lang = request.args.get("lang") or "en"
        invite_token = request.args.get("invite_token")
        invitation_context = self.profile_service.signup_invitation_context(company_short_name, invite_token)
        invitation_required, invited_email = (
            invitation_context if isinstance(invitation_context, tuple) else (False, None)
        )
        if invitation_required and not invited_email:
            response = make_response(render_template(
                'error.html',
                message=self.i18n_service.t('errors.signup.invitation_required'),
            ), 403)
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Cache-Control'] = 'no-store'
            return response

        template_context = {
            "company_short_name": company_short_name,
            "branding": branding_data,
            "lang": current_lang,
        }
        if invitation_required or invited_email:
            template_context.update(invite_token=invite_token, invited_email=invited_email)
        response = make_response(render_template('signup.html', **template_context))
        if invitation_required or invited_email:
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Cache-Control'] = 'no-store'
        return response

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

            # get the language from the form, then query
            current_lang = request.form.get("lang") or request.args.get("lang")
            invite_token = request.form.get("invite_token") or request.args.get("invite_token")

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
                verification_url=verification_url,
                invite_token=invite_token)

            if "error" in response:
                flash(response["error"], 'error')
                template_context = {
                    "company_short_name": company_short_name,
                    "branding": branding_data,
                    "lang": current_lang,
                    "form_data": {
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": email,
                        "password": password,
                        "confirm_password": confirm_password
                    },
                }
                if invite_token:
                    invitation_context = self.profile_service.signup_invitation_context(
                        company_short_name, invite_token,
                    )
                    if isinstance(invitation_context, tuple) and (invitation_context[0] or invitation_context[1]):
                        template_context.update(
                            invite_token=invite_token,
                            invited_email=invitation_context[1],
                        )
                response = make_response(render_template('signup.html', **template_context), 400)
                if invite_token:
                    response.headers['Referrer-Policy'] = 'no-referrer'
                    response.headers['Cache-Control'] = 'no-store'
                return response

            flash(response["message"], 'success')
            return redirect(url_for('home', company_short_name=company_short_name, lang=current_lang))

        except Exception as e:
            message = self.i18n_service.t('errors.templates.processing_error', error=str(e))
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=message,
                lang=current_lang
            ), 500
