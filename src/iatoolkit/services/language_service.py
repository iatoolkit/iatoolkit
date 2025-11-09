# iatoolkit/services/language_service.py

import logging
from injector import inject, singleton
from flask import g, request
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.session_manager import SessionManager

@singleton
class LanguageService:
    """
    Determines the correct language for the current request
    based on a defined priority order (session, URL, etc.)
    and caches it in the Flask 'g' object for the request's lifecycle.
    """

    FALLBACK_LANGUAGE = 'es'

    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 profile_repo: ProfileRepo):
        self.config_service = config_service
        self.profile_repo = profile_repo

    def _get_company_short_name(self) -> str | None:
        """
        Gets the company_short_name from the current request context.
        This handles different scenarios like web sessions, public URLs, and API calls.

        Priority Order:
        1. Flask Session (for logged-in web users).
        2. URL rule variable (for public pages and API endpoints).
        """
        # 1. Check session for logged-in users
        company_short_name = SessionManager.get('company_short_name')
        if company_short_name:
            return company_short_name

        # 2. Check URL arguments (e.g., /<company_short_name>/login)
        # This covers public pages and most API calls.
        if request.view_args and 'company_short_name' in request.view_args:
            return request.view_args['company_short_name']

        return None

    def get_current_language(self) -> str:
        """
        Determines and caches the language for the current request using a priority order:
        1. User's preference (from their profile).
        2. Company's default language.
        3. System-wide fallback language ('es').
        """
        if 'lang' in g:
            return g.lang

        try:
            # Priority 1: User's preferred language
            user_identifier = SessionManager.get('user_identifier')
            if user_identifier:
                user = self.profile_repo.get_user_by_email(user_identifier)
                if user and user.preferred_language:
                    logging.debug(f"Language determined by user preference: {user.preferred_language}")
                    g.lang = user.preferred_language
                    return g.lang

            # Priority 2: Company's default language
            company_short_name = self._get_company_short_name()
            if company_short_name:
                locale = self.config_service.get_company_content(company_short_name, 'locale')
                if locale:
                    company_language = locale.split('_')[0]
                    g.lang = company_language
                    return g.lang
        except Exception as e:
            logging.info(f"Could not determine language, falling back to default. Reason: {e}")
            pass

        # Priority 3: System-wide fallback
        logging.info(f"Language determined by system fallback: {self.FALLBACK_LANGUAGE}")
        g.lang = self.FALLBACK_LANGUAGE
        return g.lang