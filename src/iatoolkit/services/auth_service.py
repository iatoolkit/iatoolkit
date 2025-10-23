# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from flask import request


class AuthService:
    """
    Centralized service for handling authentication for all incoming requests.
    It determines the user's identity based on either a Flask session cookie or an API Key.
    """

    @inject
    def __init__(self, profile_service: ProfileService):
        """
        Injects ProfileService to access session information and validate API keys.
        """
        self.profile_service = profile_service

    def verify(self) -> dict:
        """
        Verifies the current request and identifies the user.

        Returns a dictionary with:
        - success: bool
        - user_identifier: str (if successful)
        - company_short_name: str (if successful)
        - error_message: str (on failure)
        - status_code: int (on failure)
        """
        # --- Priority 1: Check for a valid Flask web session ---
        session_info = self.profile_service.get_current_session_info()
        if session_info and session_info.get('user_identifier'):
            # User is authenticated via a web session cookie.
            return {
                "success": True,
                "company_short_name": session_info['company_short_name'],
                "user_identifier": session_info['user_identifier']
            }

        # --- Priority 2: Check for a valid API Key in headers ---
        api_key = None
        auth = request.headers.get('Authorization', '')
        if isinstance(auth, str) and auth.lower().startswith('bearer '):
            api_key =  auth.split(' ', 1)[1].strip()

        if api_key:
            api_key_entry = self.profile_service.get_active_api_key_entry(api_key)
            if not api_key_entry:
                return {"success": False, "error": "Invalid or inactive API Key", "status_code": 401}

            # obtain the company from the api_key_entry
            company = api_key_entry.company

            # For API calls, the external_user_id must be provided in the request.
            user_identifier = ''
            if request.is_json:
                data = request.get_json() or {}
                user_identifier = data.get('external_user_id', '')

            return {
                "success": True,
                "company_short_name": company.short_name,
                "user_identifier": user_identifier
            }

        # --- Failure: No valid credentials found ---
        return {"success": False, "error": "Authentication required. No session cookie or API Key provided.",
                "status_code": 401}