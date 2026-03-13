# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


import logging
from flask import jsonify
from flask.views import MethodView
from injector import inject

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService


class ConnectorsApiView(MethodView):
    """
    API View to list connector aliases configured for a company.
    """

    @inject
    def __init__(self,
                 configuration_service: ConfigurationService,
                 profile_service: ProfileService,
                 auth_service: AuthService):
        self.configuration_service = configuration_service
        self.profile_service = profile_service
        self.auth_service = auth_service

    def get(self, company_short_name: str):
        try:
            auth_result = self.auth_service.verify_for_company(company_short_name, anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code", 401)

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return jsonify({"error": "company not found."}), 404

            connectors = self.configuration_service.get_configuration(company_short_name, "connectors") or {}

            result = []
            for name, cfg in connectors.items():
                if not isinstance(cfg, dict):
                    continue
                result.append({
                    "name": name,
                    "type": cfg.get("type"),
                })

            result.sort(key=lambda x: (x.get("type") or "", x.get("name") or ""))

            return jsonify({"connectors": result}), 200

        except Exception as e:
            logging.exception(f"Unexpected error listing connectors: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
