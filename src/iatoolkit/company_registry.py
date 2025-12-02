# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from typing import Dict, Type, Any, Optional
from .base_company import BaseCompany
import logging


class CompanyRegistry:
    """
    Company registry with dependency injection support.
    Allow the client to register companies and instantiate them with dependency injection.
    """

    def __init__(self):
        self._company_classes: Dict[str, Type[BaseCompany]] = {}
        self._company_instances: Dict[str, BaseCompany] = {}

    def register(self, name: str, company_class: Type[BaseCompany]) -> None:
        """
        Registers a company in the registry.

        COMMUNITY EDITION LIMITATION:
        This base implementation enforces a strict single-tenant limit.
        It raises a RuntimeError if a second company is registered.
        """
        if not issubclass(company_class, BaseCompany):
            raise ValueError(f"The class {company_class.__name__} must be a subclass of BaseCompany")

        company_key = name.lower()

        # --- STRICT SINGLE-TENANT ENFORCEMENT ---
        # If a company is already registered (and it's not an update to the same key)
        if len(self._company_classes) > 0 and company_key not in self._company_classes:
            logging.error(f"❌ Community Edition Restriction: Cannot register '{name}'. Limit reached (1).")
            raise RuntimeError(
                "IAToolkit Community Edition allows only one company instance. "
                "Upgrade to IAToolkit Enterprise to enable multi-tenancy."
            )

        self._company_classes[company_key] = company_class
        logging.info(f"Company registered: {name}")

    def instantiate_companies(self, injector) -> Dict[str, BaseCompany]:
        """
        intantiate all registered companies using the toolkit injector
        """
        for company_key, company_class in self._company_classes.items():
            if company_key not in self._company_instances:
                try:
                    # use de injector to create the instance
                    company_instance = injector.get(company_class)

                    # save the created instance in the registry
                    self._company_instances[company_key] = company_instance

                except Exception as e:
                    logging.error(f"Error while creating company instance for {company_key}: {e}")
                    raise e

        return self._company_instances.copy()

    def get_all_company_instances(self) -> Dict[str, BaseCompany]:
        return self._company_instances.copy()

    def get_company_instance(self, company_name: str) -> Optional[BaseCompany]:
        return self._company_instances.get(company_name.lower())

    def get_registered_companies(self) -> Dict[str, Type[BaseCompany]]:
        return self._company_classes.copy()

    def clear(self) -> None:
        self._company_classes.clear()
        self._company_instances.clear()

# --- Singleton Management ---

# Global instance (Default: Community Edition)
_company_registry = CompanyRegistry()


def get_company_registry() -> CompanyRegistry:
    """Get the global company registry instance."""
    return _company_registry


def set_company_registry(registry: CompanyRegistry) -> None:
    """
    Sets the global company registry instance.
    Use this to inject an Enterprise-compatible registry implementation.
    """
    global _company_registry
    if not isinstance(registry, CompanyRegistry):
        raise ValueError("Registry must inherit from CompanyRegistry")

    _company_registry = registry
    logging.info(f"✅ Company Registry implementation swapped: {type(registry).__name__}")


def register_company(name: str, company_class: Type[BaseCompany]) -> None:
    """
    Public function to register a company.

    Args:
        name: Name of the company
        company_class: Class that inherits from BaseCompany
    """
    _company_registry.register(name, company_class)

