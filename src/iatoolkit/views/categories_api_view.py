# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import jsonify
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import PromptType, PromptCategory
import logging

class CategoriesApiView(MethodView):
    """
    Endpoint to retrieve all available categories and types in the system.
    Useful for populating dropdowns in the frontend.
    """
    @inject
    def __init__(self,
                 auth_service: AuthService,
                 profile_service: ProfileService,
                 configuration_service: ConfigurationService,
                 knowledge_base_service: KnowledgeBaseService,
                 llm_query_repo: LLMQueryRepo):
        self.auth_service = auth_service
        self.profile_service = profile_service
        self.knowledge_base_service = knowledge_base_service
        self.llm_query_repo = llm_query_repo
        self.configuration_service = configuration_service

    def get(self, company_short_name):
        try:
            # 1. Verify Authentication
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), 401

            # 2. Get Company
            company = self.profile_service.get_company_by_short_name(company_short_name)
            if not company:
                return jsonify({"error": "Company not found"}), 404

            # 3. Gather Categories
            response_data = {
                "prompt_types": [t.value for t in PromptType],
                "prompt_categories": [],
                "collection_types": [],
                # Future categories can be added here (e.g., tool_types, user_roles)
            }

            # A. Prompt Categories (from DB)
            prompt_cats = self.llm_query_repo.get_all_categories(company_id=company.id)
            response_data["prompt_categories"] = [c.name for c in prompt_cats]

            # B. Collection Types (from KnowledgeBaseService)
            response_data["collection_types"] = self.knowledge_base_service.get_collection_names(company_short_name)

            # C. LLM Models (from ConfigurationService)
            _, llm_models = self.configuration_service.get_llm_configuration(company_short_name)
            # Extract only IDs
            response_data["llm_models"] = [m['id'] for m in llm_models if 'id' in m]

            return jsonify(response_data)

        except Exception as e:
            logging.exception(f"Error fetching categories for {company_short_name}: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500