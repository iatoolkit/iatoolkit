# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import jsonify, request
from flask.views import MethodView
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.auth_service import AuthService
from iatoolkit.common.exceptions import IAToolkitException
from injector import inject
import logging
from iatoolkit.common import access


class PromptApiView(MethodView):
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 prompt_service: PromptService,
                 profile_service: ProfileService,
                 llm_query_repo: LLMQueryRepo):
        self.auth_service = auth_service
        self.prompt_service = prompt_service
        self.profile_service = profile_service
        self.llm_query_repo = llm_query_repo

    def get(self, company_short_name, prompt_name=None):
        """
        GET /: Lista el árbol de prompts (Categorías > Prompts).
        GET /<name>: Devuelve detalle completo: metadata + contenido texto.
        """
        try:
            # get access credentials
            auth_result = self.auth_service.verify_for_company(company_short_name, anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get('status_code')

            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                 return jsonify({"error": "Company not found"}), 404

            if prompt_name:
                # get the prompt object from database
                prompt_obj = self.llm_query_repo.get_prompt_by_name(company, prompt_name)
                if not prompt_obj:
                     return jsonify({"error": "Prompt not found"}), 404

                # get the prompt content
                content = self.prompt_service.get_prompt_content(company, prompt_name)
                meta = prompt_obj.to_dict()
                runtime_policy = PromptService.normalize_runtime_policy(meta.get("runtime_policy"))
                agent_role = runtime_policy["role"]
                meta["runtime_policy"] = runtime_policy
                meta["agent_role"] = agent_role
                meta["execution_mode"] = PromptService.execution_mode_for_agent_role(agent_role)
                meta["queue_tier"] = runtime_policy["queue_tier"]
                meta["context_policy"] = runtime_policy["context"]
                meta["runtime_provider"] = runtime_policy["runtime_provider"]
                meta["runtime_config"] = runtime_policy["runtime_config"]
                meta["agent_type"] = (
                    PromptService.AGENT_TYPE_DECISION
                    if isinstance(prompt_obj.decision_spec, dict)
                    else PromptService.AGENT_TYPE_CONVERSATIONAL
                )
                meta["decision_spec_yaml"] = PromptService.dump_decision_spec_yaml(
                    prompt_obj.decision_spec if isinstance(prompt_obj.decision_spec, dict) else None
                )

                return jsonify({
                    "meta": meta,
                    "content": content
                })
            else:
                # Check for query param to include all prompts (admin view)
                include_all = request.args.get('all', 'false').lower() == 'true'

                # return prompts based on filter
                # The chat's list holds the agents this person may use (BL-010, Fase 1).
                user_identifier = None if include_all else auth_result.get("user_identifier")
                return jsonify(self.prompt_service.get_prompts(company_short_name, include_all=include_all,
                                                               user_identifier=user_identifier))

        except Exception as e:
            logging.exception(
                f"unexpected error getting company prompts: {e}")
            return jsonify({"error_message": str(e)}), 500

    def _require_admin_auth(self, company_short_name: str) -> dict | tuple:
        """
        Prompt content is a Jinja template rendered server-side for every user
        of the tenant, so writing it is an admin capability: even sandboxed, a
        template author can shape what every agent says and does. Regular chat
        users / plain API keys pass verify_for_company but must not get here.
        """
        auth_result = self.auth_service.verify_for_company(company_short_name)
        if not auth_result.get("success"):
            status_code = auth_result.get("status_code", 401)
            if status_code == 403:
                return jsonify({"error": "Forbidden"}), 403
            return jsonify(auth_result), status_code

        if not access.person_can(company_short_name, auth_result, access.ADMIN):
            return jsonify({"error": "Forbidden"}), 403

        return auth_result

    def put(self, company_short_name, prompt_name):
        try:
            auth_result = self._require_admin_auth(company_short_name)
            if isinstance(auth_result, tuple):
                return auth_result

            data = request.get_json()

            # The service handles file magic and YAML sync
            self.prompt_service.save_prompt(company_short_name, prompt_name, data)

            return jsonify({"status": "success"})
        except Exception as e:
            logging.exception(f"Error saving prompt {prompt_name}: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    def post(self, company_short_name, prompt_name=None):
        """Creates a new prompt."""
        try:
            auth_result = self._require_admin_auth(company_short_name)
            if isinstance(auth_result, tuple):
                return auth_result

            data = request.get_json() or {}

            if prompt_name:
                target_name = prompt_name
            else:
                raw_target_name = data.get('key') or data.get('name')
                target_name = PromptService.normalize_prompt_name(raw_target_name)

            if not target_name:
                return jsonify({"status": "error", "message": "Prompt name is required"}), 400

            if not prompt_name:
                company = self.profile_service.get_company_by_short_name(company_short_name)
                if not company:
                    return jsonify({"status": "error", "message": "Company not found"}), 404
                if self.llm_query_repo.get_prompt_by_name(company, target_name):
                    return jsonify({"status": "error", "message": f"Prompt '{target_name}' already exists"}), 409

            # Reuse save_prompt logic which handles create/update
            self.prompt_service.save_prompt(company_short_name, target_name, data)

            return jsonify({"status": "success"})
        except IAToolkitException as e:
            if e.error_type in {
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                IAToolkitException.ErrorType.INVALID_PARAMETER,
            }:
                return jsonify({"status": "error", "message": str(e)}), 400
            logging.exception(f"Error creating prompt: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
        except Exception as e:
            logging.exception(f"Error creating prompt: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    def delete(self, company_short_name, prompt_name):
        """Deletes a prompt."""
        try:
            # Deleting an agent is administering it, like creating or editing one
            # (BL-010, Fase 1: it had no check at all).
            auth_result = self._require_admin_auth(company_short_name)
            if isinstance(auth_result, tuple):
                return auth_result

            self.prompt_service.delete_prompt(company_short_name, prompt_name)

            return jsonify({"status": "success"})
        except Exception as e:
            logging.exception(f"Error deleting prompt {prompt_name}: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
