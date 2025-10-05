# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template
from services.profile_service import ProfileService
from injector import inject
from itsdangerous import URLSafeTimedSerializer
from flask import url_for, request
import os


class SignupView(MethodView):
    @inject
    def __init__(self, profile_service: ProfileService):
        self.profile_service = profile_service
        self.serializer = URLSafeTimedSerializer(os.getenv("USER_VERIF_KEY"))


    def get(self, company_short_name: str):
        # get company info
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        user_agent = request.user_agent
        is_mobile = user_agent.platform in ["android", "iphone", "ipad"] or "mobile" in user_agent.string.lower()
        return render_template('signup.html',
                               company=company,
                               company_short_name=company_short_name,
                               is_mobile=is_mobile)

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
                return render_template(
                'signup.html',
                                    company=company,
                                    company_short_name=company_short_name,
                                    form_data={
                                           "first_name": first_name,
                                           "last_name": last_name,
                                           "email": email,
                                            "password": password,
                                            "confirm_password": confirm_password
                                       },
                                    alert_message=response["error"]), 400

            # all is OK
            return render_template(
                'login.html',
                            company=company,
                            company_short_name=company_short_name,
                                   alert_icon='success',
                                   alert_message=response["message"]), 200
        except Exception as e:
            return render_template("error.html",
                                   company=company,
                                   company_short_name=company_short_name,
                                   message="Ha ocurrido un error inesperado."), 500

