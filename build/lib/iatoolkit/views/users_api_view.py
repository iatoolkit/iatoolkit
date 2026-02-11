from flask.views import MethodView
from flask import jsonify
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
import logging


class UsersApiView(MethodView):
    """
    list company users and their roles
    """
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 profile_service: ProfileService):
        self.auth_service = auth_service
        self.profile_service = profile_service

    def get(self, company_short_name: str):
        try:
            auth_result = self.auth_service.verify(anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code", 401)

            # get users of the company
            users = self.profile_service.get_company_users(company_short_name)

            return jsonify(users), 200

        except Exception as e:
            logging.exception(f"Error fetching users for {company_short_name}: {e}")
            return jsonify({"error": "Unexpected error", "details": str(e)}), 500