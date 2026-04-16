# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# companies/base_company.py
from abc import ABC, abstractmethod

class BaseCompany(ABC):

    @abstractmethod
    # execute the specific action configured in the intent table
    def handle_request(self, tag: str, params: dict) -> dict:
        raise NotImplementedError("La subclase debe implementar el método handle_request()")

    def register_cli_commands(self, app):
        # Optional extension point. Community/Enterprise can override as needed.
        return None

    def unsupported_operation(self, tag):
        raise NotImplementedError(f"La operación '{tag}' no está soportada por esta empresa.")
