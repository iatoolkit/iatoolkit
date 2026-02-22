# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import jsonify, request
from flask.views import MethodView
from injector import inject
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.auth_service import AuthService
import logging


class ConfigurationApiView(MethodView):
    """
    API View to manage company configuration.
    Supports loading, updating specific keys, and validating the configuration.
    """
    @inject
    def __init__(self,
                 configuration_service: ConfigurationService,
                 profile_service: ProfileService,
                 auth_service: AuthService):
        self.configuration_service = configuration_service
        self.profile_service = profile_service
        self.auth_service = auth_service

    def get(self, company_short_name: str = None, action: str = None):
        """
        Loads the current configuration for the company.
        """
        try:
            refresh_runtime = action == "load_configuration"

            # 1. Verify authentication
            auth_result = self.auth_service.verify(anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code", 401)

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return jsonify({"error": "company not found."}), 404

            if refresh_runtime:
                self.configuration_service.invalidate_configuration_cache(company_short_name)

            config, errors = self.configuration_service.load_configuration(company_short_name)

            # Register data sources to ensure services are up to date with loaded config
            if config:
                self.configuration_service.register_data_sources(company_short_name, config=config)

            runtime_refresh = {}
            if refresh_runtime:
                runtime_refresh = self._refresh_runtime_clients(company_short_name)

            # Remove non-serializable objects
            serializable_config = dict(config or {})
            serializable_config.pop("company", None)

            response = {'config': serializable_config, 'errors': errors}
            if refresh_runtime:
                response["runtime_refresh"] = runtime_refresh

            status_code = 200 if not errors else 400
            return jsonify(response), status_code
        except Exception as e:
            logging.exception(f"Unexpected error loading config: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    def _refresh_runtime_clients(self, company_short_name: str) -> dict:
        refresh_status = {
            "llm_proxy": False,
            "embedding_clients": False,
            "sql_connections": False,
        }

        from iatoolkit import current_iatoolkit
        from iatoolkit.infra.llm_proxy import LLMProxy
        from iatoolkit.services.embedding_service import EmbeddingService
        from iatoolkit.services.sql_service import SqlService

        injector = current_iatoolkit().get_injector()

        try:
            llm_proxy = injector.get(LLMProxy)
            llm_proxy.clear_runtime_cache()
            LLMProxy.clear_low_level_clients_cache()
            refresh_status["llm_proxy"] = True
        except Exception as e:
            logging.warning(f"Error refreshing llm_proxy cache for '{company_short_name}': {e}")

        try:
            embedding_service = injector.get(EmbeddingService)
            embedding_service.client_factory.clear_runtime_cache(company_short_name)
            refresh_status["embedding_clients"] = True
        except Exception as e:
            logging.warning(f"Error refreshing embedding cache for '{company_short_name}': {e}")

        try:
            sql_service = injector.get(SqlService)
            sql_service.clear_company_connections(company_short_name)
            refresh_status["sql_connections"] = True
        except Exception as e:
            logging.warning(f"Error refreshing SQL cache for '{company_short_name}': {e}")

        return refresh_status

    def patch(self, company_short_name: str):
        """
        Updates a specific configuration key.
        Body: { "key": "llm.model", "value": "gpt-4" }
        """
        try:
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), 401

            payload = request.get_json()
            key = payload.get('key')
            value = payload.get('value')

            if not key:
                return jsonify({'error': 'Missing "key" in payload'}), 400

            logging.info(f"Updating config key '{key}' for company '{company_short_name}'")

            updated_config, errors = self.configuration_service.update_configuration_key(
                company_short_name, key, value
            )

            # Remove non-serializable objects
            if 'company' in updated_config:
                updated_config.pop('company')

            if errors:
                return jsonify({'status': 'invalid', 'errors': errors, 'config': updated_config}), 400

            return jsonify({'status': 'success', 'config': updated_config}), 200

        except FileNotFoundError:
            return jsonify({'error': 'Configuration file not found'}), 404
        except Exception as e:
            logging.exception(f"Error updating config: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    def post(self, company_short_name: str):
        """
        Adds a new configuration key.
        Body: { "parent_key": "llm", "key": "max_tokens", "value": 2048 }
        """
        try:
            auth_result = self.auth_service.verify(anonymous=False)
            if not auth_result.get("success"):
                return jsonify(auth_result), 401

            payload = request.get_json()
            parent_key = payload.get('parent_key', '')  # Optional, defaults to root
            key = payload.get('key')
            value = payload.get('value')

            if not key:
                return jsonify({'error': 'Missing "key" in payload'}), 400

            logging.info(f"Adding config key '{key}' under '{parent_key}' for company '{company_short_name}'")

            updated_config, errors = self.configuration_service.add_configuration_key(
                company_short_name, parent_key, key, value
            )

            # Remove non-serializable objects
            if 'company' in updated_config:
                updated_config.pop('company')

            if errors:
                return jsonify({'status': 'invalid', 'errors': errors, 'config': updated_config}), 400

            return jsonify({'status': 'success', 'config': updated_config}), 200

        except FileNotFoundError:
            return jsonify({'error': 'Configuration file not found'}), 404
        except Exception as e:
            logging.exception(f"Error adding config key: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

class ValidateConfigurationApiView(MethodView):
    """
    API View to trigger an explicit validation of the current configuration.
    Useful for UI to check status without modifying data.
    """
    @inject
    def __init__(self,
                 configuration_service: ConfigurationService,
                 auth_service: AuthService):
        self.configuration_service = configuration_service
        self.auth_service = auth_service

    def get(self, company_short_name: str):
        try:
            auth_result = self.auth_service.verify(anonymous=False)
            if not auth_result.get("success"):
                return jsonify(auth_result), 401

            errors = self.configuration_service.validate_configuration(company_short_name)

            if errors:
                return jsonify({'status': 'invalid', 'errors': errors}), 200  # 200 OK because check succeeded

            return jsonify({'status': 'valid', 'errors': []}), 200

        except Exception as e:
            logging.exception(f"Error validating config: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
