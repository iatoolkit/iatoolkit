# iatoolkit/views/profile_api_view.py
from flask import request, jsonify
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService


class UserLanguageApiView(MethodView):
    """
    API endpoint for managing user language preferences.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 profile_service: ProfileService):
        self.auth_service = auth_service
        self.profile_service = profile_service

    def post(self):
        """
        Handles POST requests to update the user's preferred language.
        Expects a JSON body with a 'language' key, e.g., {"language": "en"}.
        """
        # 1. Authenticate the user from the current session.
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code")

        user_identifier = auth_result.get('user_identifier')

        # 2. Validate request body
        data = request.get_json()
        if not data or 'language' not in data:
            return jsonify({"error_message": "Missing 'language' field in request body"}), 400

        new_lang = data.get('language')

        # 3. Call the service to perform the update
        update_result = self.profile_service.update_user_language(user_identifier, new_lang)

        if not update_result.get('success'):
            return jsonify(update_result), 400

        return jsonify({"message": "Language preference updated successfully"}), 200
