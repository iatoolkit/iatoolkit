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

    # 1. Definimos las reglas de formato para cada idioma/región soportado.
    # Nota: 'js_locale' debe ser un string BCP 47 válido para el navegador (usar guiones, no guiones bajos).
    LOCALE_DEFINITIONS = {
        'es': {
            'code': 'es',
            'js_locale': 'es-ES',
            'date_format_js': 'dd/MM/yyyy',
            'currency': 'EUR'
        },
        'en': {
            'code': 'en',
            'js_locale': 'en-US',
            'date_format_js': 'MM/dd/yyyy',
            'currency': 'USD'
        },
    }


    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 profile_repo: ProfileRepo):
        self.config_service = config_service
        self.profile_repo = profile_repo

    def _safe_rollback(self):
        """
        Best-effort rollback to recover the shared SQLAlchemy scoped session
        after transient DB failures (e.g. SSL/network errors).
        """
        try:
            self.profile_repo.session.rollback()
        except Exception as rollback_error:
            logging.warning(f"LanguageService rollback failed: {rollback_error}")

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
            0. Query parameter '?lang=<code>' (highest priority; e.g., 'en', 'es').
            1. User's preference (from their profile).
            2. Company's default language.
            3. System-wide fallback language ('es').
            """
        if 'locale_ctx' in g:
            return g.lang

        # returns the detected locale string, ej: "es_MX" o "en"
        detected_locale_str = self._resolve_locale_string()

        # 2. map string to definition
        # otherwise fallback  to 'es'
        definition = self.LOCALE_DEFINITIONS.get(detected_locale_str)

        if not definition:
            # Fallback al idioma base (ej: es_MX -> es)
            base_lang = detected_locale_str.split('_')[0]
            definition = self.LOCALE_DEFINITIONS.get(base_lang, self.LOCALE_DEFINITIONS[self.FALLBACK_LANGUAGE])

        # 3. Guardamos TODO el contexto en 'g' para usarlo luego
        g.lang = definition['code']
        g.locale_ctx = definition

        return g.lang

    def get_frontend_context(self) -> dict:
        """
        returns the configuration ready for JS inyection
        """
        # Asegura que se ha ejecutado la detección
        if 'locale_ctx' not in g:
            self.get_current_language()

        return g.locale_ctx

    def _resolve_locale_string(self) -> str:
        # Priority 1: Query param
        lang_arg = request.args.get('lang')
        if lang_arg:
            return lang_arg


        # Priority 2: Company Config
        company_short_name = self._get_company_short_name()
        if company_short_name:
            # cnfig returns something like 'es_ES' o 'en_US'
            try:
                conf_locale = self.config_service.get_configuration(company_short_name, 'locale')
                if conf_locale:
                    return conf_locale
            except Exception as e:
                self._safe_rollback()
                logging.warning(f"Error fetching configuration for '{company_short_name}': {e}")


        logging.debug(f"Language determined by system fallback: {self.FALLBACK_LANGUAGE}")
        return self.FALLBACK_LANGUAGE
