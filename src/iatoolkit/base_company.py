# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# companies/base_company.py
from abc import ABC, abstractmethod
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import Company
from iatoolkit.core import IAToolkit


class BaseCompany(ABC):
    def __init__(self):
        # Obtener el inyector global y resolver las dependencias internamente
        injector = IAToolkit.get_instance().get_injector()
        self.profile_repo: ProfileRepo = injector.get(ProfileRepo)
        self.llm_query_repo: LLMQueryRepo = injector.get(LLMQueryRepo)
        self.company: Company | None = None
        self.company_short_name = ''

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


    @abstractmethod
    # execute the specific action configured in the intent table
    def handle_request(self, tag: str, params: dict) -> dict:
        raise NotImplementedError("La subclase debe implementar el método handle_request()")

    @abstractmethod
    def register_cli_commands(self, app):
        """
        optional method for a company definition of it's cli commands
        """
        pass


    def unsupported_operation(self, tag):
        raise NotImplementedError(f"La operación '{tag}' no está soportada por esta empresa.")