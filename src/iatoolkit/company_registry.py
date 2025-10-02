# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit

from typing import Dict, Type, Any
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


    def instantiate_companies(self, injector) -> Dict[str, BaseCompany]:
        """
        Instancia todas las empresas registradas con inyección de dependencias.

        Returns:
            Dict con instancias de empresas {name: instance}
        """

        for company_key, company_class in self._company_classes.items():
            if company_key not in self._company_instances:
                try:
                    # use de injector to create the instance
                    company_instance = injector.get(company_class)
                    self._company_instances[company_key] = company_instance
                    logging.info(f"company '{company_key}' instantiated")

                except Exception as e:
                    logging.error(f"Error instanciando empresa {company_key}: {e}")
                    logging.exception(e)
                    raise

        return self._company_instances.copy()

    def get_all_company_instances(self) -> Dict[str, BaseCompany]:
        """Devuelve un diccionario con todas las instancias de empresas creadas."""
        return self._company_instances.copy()

    def get_registered_companies(self) -> Dict[str, Type[BaseCompany]]:
        return self._company_classes.copy()

    def clear(self) -> None:
        """Limpia el registro (útil para tests)"""
        self._company_classes.clear()
        self._company_instances.clear()


# global instance of the company registry
_company_registry = CompanyRegistry()


def register_company(name: str, company_class: Type[BaseCompany]) -> None:
    """
    Public function to register a company.

    Args:
        name: Name of the company
        company_class: Class that inherits from BaseCompany
    """
    if not issubclass(company_class, BaseCompany):
        raise ValueError(f"La clase {company_class.__name__} debe heredar de BaseCompany")

    company_key = name.lower()
    _company_registry._company_classes[company_key] = company_class


def get_company_registry() -> CompanyRegistry:
    """get the global company registry instance"""
    return _company_registry