# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
import logging
from flask import request, jsonify
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.views.base_login_view import BaseLoginView

# Importar los servicios que necesita la clase base
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.onboarding_service import OnboardingService
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.prompt_manager_service import PromptService

class ExternalLoginView(BaseLoginView):
    """
    Handles login for external users via API.
    Authenticates and then delegates the path decision (fast/slow) to the base class.
    """
    @inject
    def __init__(self,
                 iauthentication: AuthService,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 prompt_service: PromptService,
                 onboarding_service: OnboardingService,
                 query_service: QueryService):
        # Pass the dependencies for the base class to its __init__
        super().__init__(
            profile_service=profile_service,
            branding_service=branding_service,
            onboarding_service=onboarding_service,
            query_service=query_service,
            prompt_service=prompt_service
        )
        # Handle the dependency specific to this child class
        self.iauthentication = iauthentication

    def post(self, company_short_name: str):
        data = request.get_json()
        if not data or 'external_user_id' not in data:
            return jsonify({"error": "Falta external_user_id"}), 400

        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return jsonify({"error": "Empresa no encontrada"}), 404

        external_user_id = data['external_user_id']
        if not external_user_id:
            return jsonify({"error": "missing external_user_id"}), 404

        # 1. Authenticate the API call.
        iaut = self.iauthentication.verify()
        if not iaut.get("success"):
            return jsonify(iaut), 401

        # 2. Create the external user session.
        self.profile_service.create_external_user_session(company, external_user_id)

        # 3. Delegate the path decision to the centralized logic.
        try:
            return self._handle_login_path(company_short_name, external_user_id, company)
        except Exception as e:
            logging.exception(f"Error processing external login path for {company_short_name}/{external_user_id}: {e}")
            return jsonify({"error": f"Internal server error while starting chat. {str(e)}"}), 500