# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# companies/base_company.py
from abc import ABC, abstractmethod
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.services.prompt_manager_service import PromptService
from iatoolkit.repositories.models import Company, Function, PromptCategory
from iatoolkit import IAToolkit


class BaseCompany(ABC):
    def __init__(self):
        # Obtener el inyector global y resolver las dependencias internamente
        injector = IAToolkit.get_instance().get_injector()
        self.profile_repo: ProfileRepo = injector.get(ProfileRepo)
        self.llm_query_repo: LLMQueryRepo = injector.get(LLMQueryRepo)
        self.prompt_service: PromptService = injector.get(PromptService)
        self.company: Company | None = None

    def _create_company(self,
                        short_name: str,
                        name: str,
                        parameters: dict | None = None,
                        ) -> Company:
        company_obj = Company(short_name=short_name,
                              name=name,
                              parameters=parameters)
        self.company = self.profile_repo.create_company(company_obj)
        return self.company

    def _create_function(self, function_name: str, description: str, params: dict, **kwargs):
        if not self.company:
            raise ValueError("La compañía debe estar definida antes de crear una función.")

        self.llm_query_repo.create_or_update_function(
            Function(
                company_id=self.company.id,
                name=function_name,
                description=description,
                parameters=params,
                system_function=False,
                **kwargs
            )
        )

    def _create_prompt_category(self, name: str, order: int) -> PromptCategory:
        if not self.company:
            raise ValueError("La compañía debe estar definida antes de crear una categoría.")

        return self.llm_query_repo.create_or_update_prompt_category(
            PromptCategory(name=name, order=order, company_id=self.company.id)
        )

    def _create_prompt(self, prompt_name: str, description: str, category: PromptCategory, order: int, **kwargs):
        if not self.company:
            raise ValueError("La compañía debe estar definida antes de crear un prompt.")

        self.prompt_service.create_prompt(
            prompt_name=prompt_name,
            description=description,
            order=order,
            company=self.company,
            category=category,
            **kwargs
        )

    @abstractmethod
    # get context specific for this company
    def get_user_info(self, user_identifier: str) -> dict:
        raise NotImplementedError("La subclase debe implementar el método get_user_info()")

    @abstractmethod
    # execute the specific action configured in the intent table
    def handle_request(self, tag: str, params: dict) -> dict:
        raise NotImplementedError("La subclase debe implementar el método handle_request()")

    @abstractmethod
    # get context specific for the query
    def get_metadata_from_filename(self, filename: str) -> dict:
        raise NotImplementedError("La subclase debe implementar el método get_query_context()")

    def register_cli_commands(self, app):
        """
        optional method for a company definition of it's cli commands
        """
        pass


    def unsupported_operation(self, tag):
        raise NotImplementedError(f"La operación '{tag}' no está soportada por esta empresa.")