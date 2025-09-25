# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

# companies/base_company.py
from abc import ABC, abstractmethod
from typing import Any


class BaseCompany(ABC):
    def __init__(self, profile_repo: Any = None, llm_query_repo: Any = None):
        self.profile_repo = profile_repo
        self.llm_query_repo = llm_query_repo

    @abstractmethod
    # initialize all the database tables  needed
    def register_company(self):
        raise NotImplementedError("La subclase debe implementar el método create_company()")

    @abstractmethod
    # get context specific for this company
    def get_company_context(self, **kwargs) -> str:
        raise NotImplementedError("La subclase debe implementar el método get_company_context()")

    @abstractmethod
    # execute the specific action configured in the intent table
    def handle_request(self, tag: str, params: dict) -> dict:
        raise NotImplementedError("La subclase debe implementar el método handle_request()")

    @abstractmethod
    # get context specific for the query
    def start_execution(self):
        raise NotImplementedError("La subclase debe implementar el método start_execution()")

    @abstractmethod
    # get context specific for the query
    def get_metadata_from_filename(self, filename: str) -> dict:
        raise NotImplementedError("La subclase debe implementar el método get_query_context()")

    def unsupported_operation(self, tag):
        raise NotImplementedError(f"La operación '{tag}' no está soportada por esta empresa.")