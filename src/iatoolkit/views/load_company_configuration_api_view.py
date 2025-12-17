# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import redirect, url_for, jsonify, request, g
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.configuration_service import ConfigurationService
import logging

class LoadCompanyConfigurationApiView(MethodView):
    @inject
    def __init__(self,
                 configuration_service: ConfigurationService,
                 profile_service: ProfileService,
                 auth_service: AuthService):
        self.configuration_service = configuration_service
        self.profile_service = profile_service
        self.auth_service = auth_service

    def get(self, company_short_name: str = None):
        try:
            # 1. Get the authenticated user's
            auth_result = self.auth_service.verify(anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code", 401)

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return jsonify({"error": "company not found."}), 404

            config, errors = self.configuration_service.load_configuration(company_short_name)

            # this is fo avoid serialization issues
            if 'company' in config:
                config.pop('company')

            status_code = 200 if not errors else 400
            return {'config': config, 'errors': [errors]}, status_code
        except Exception as e:
            logging.exception(f"Unexpected error: {e}")
            return {'status': 'error'}, 500


