# iatoolkit/services/i18n_service.py
import os
import logging
from injector import inject, singleton
from iatoolkit.common.util import Utility
from iatoolkit.services.language_service import LanguageService

@singleton
class I18nService:
    """
    Servicio centralizado para manejar la internacionalización (i18n).
    Carga todas las traducciones desde archivos YAML en memoria al iniciar.
    """
    FALLBACK_LANGUAGE = 'es'

    @inject
    def __init__(self, util: Utility, language_service: LanguageService):
        self.util = util
        self.language_service = language_service

        self.translations = {}
        self._load_translations()

    def _load_translations(self):
        """
        Carga todos los archivos .yaml del directorio 'locales' en memoria.
        """
        locales_dir = os.path.join(os.path.dirname(__file__), '..', 'locales')
        if not os.path.exists(locales_dir):
            logging.error("Directory 'locales' not found.")
            return

        for filename in os.listdir(locales_dir):
            if filename.endswith('.yaml'):
                lang_code = filename.split('.')[0]
                filepath = os.path.join(locales_dir, filename)
                try:
                    self.translations[lang_code] = self.util.load_schema_from_yaml(filepath)
                except Exception as e:
                    logging.error(f"Error while loading the translation file {filepath}: {e}")

    def _get_nested_key(self, lang: str, key: str):
        """
        Obtiene un valor de un diccionario anidado usando una clave con puntos.
        """
        data = self.translations.get(lang, {})
        keys = key.split('.')
        for k in keys:
            if isinstance(data, dict) and k in data:
                data = data[k]
            else:
                return None
        return data

    def get_locale_settings(self) -> dict:
        """
        returns the configuration ready for JS inyection
        """
        return self.language_service.get_frontend_context()


    def get_translation_block(self, key: str, lang: str = None) -> dict:
        """
        Gets a whole dictionary block from the translations.
        Useful for passing a set of translations to JavaScript.
        """
        if lang is None:
            lang = self.language_service.get_current_language()

        # 1. Try to get the block in the requested language
        block = self._get_nested_key(lang, key)

        # 2. If not found, try the fallback language
        if not isinstance(block, dict):
            block = self._get_nested_key(self.FALLBACK_LANGUAGE, key)

        return block if isinstance(block, dict) else {}

    def t(self, key: str, lang: str = None, **kwargs) -> str:
        """
        Gets the translation for a given key.
        If 'lang' is provided, it's used. Otherwise, it's determined automatically.
        """
        # If no specific language is requested, determine it from the current context.
        if lang is None:
            lang = self.language_service.get_current_language()

        # 1. Attempt to get the translation in the requested language
        message = self._get_nested_key(lang, key)

        # 2. If not found, try the fallback language
        if message is None and lang != self.FALLBACK_LANGUAGE:
            logging.warning(
                f"Translation key '{key}' not found for language '{lang}'. Attempting fallback to '{self.FALLBACK_LANGUAGE}'.")
            message = self._get_nested_key(self.FALLBACK_LANGUAGE, key)

        # 3. If still not found, return the key itself as a last resort
        if message is None:
            logging.error(
                f"Translation key '{key}' not found, even in fallback '{self.FALLBACK_LANGUAGE}'.")
            return key

        # 4. If variables are provided, format the message
        if kwargs:
            try:
                return message.format(**kwargs)
            except KeyError as e:
                logging.error(f"Error formatting key '{key}': missing variable {e} in arguments.")
                return message

        return message