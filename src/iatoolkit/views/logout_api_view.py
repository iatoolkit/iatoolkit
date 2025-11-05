# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import redirect, url_for, jsonify
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.common.session_manager import SessionManager


class LogoutApiView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 auth_service: AuthService):
        self.profile_service = profile_service
        self.auth_service = auth_service

    def get(self, company_short_name: str = None):
        # 1. Get the authenticated user's
        auth_result = self.auth_service.verify(anonymous=True)
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "company not found."}), 404

        # get URL for redirection
        url_for_redirect = company.parameters.get('external_urls', {}).get('logout_url')
        if not url_for_redirect:
            url_for_redirect = url_for('home', company_short_name=company_short_name)

        # clear de session cookie
        SessionManager.clear()

        return {
            'status': 'success',
            'url': url_for_redirect,
        }


