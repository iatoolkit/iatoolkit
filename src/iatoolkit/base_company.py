# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

# companies/base_company.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from flask import Blueprint

class BaseCompany(ABC):

    @abstractmethod
    # execute the specific action configured in the intent table
    def handle_request(self, tag: str, params: dict) -> dict:
        raise NotImplementedError("La subclase debe implementar el método handle_request()")

    def register_cli_commands(self, app):
        # Optional extension point. Community/Enterprise can override as needed.
        return None

    def get_blueprint(self) -> Optional[Blueprint]:
        """
        Optional extension point: the web routes, templates and static files this
        company owns. The core registers the blueprint at boot for every company
        that is loaded, so the host application never imports a company's views.

        The blueprint must be named after the company short name: that name is
        the namespace of its endpoints (``url_for('<company>.<endpoint>')``).
        URLs are not prefixed by the core; the company chooses them.
        """
        return None

    @classmethod
    def get_resource_root(cls) -> Optional[Path]:
        """
        Directory that holds this company's files (config, prompts, schemas,
        context, templates). ``None`` keeps the classic layout,
        ``companies/<company_short_name>`` under the working directory. A company
        installed as a package returns its own directory, usually
        ``Path(__file__).resolve().parent``.
        """
        return None

    def unsupported_operation(self, tag):
        raise NotImplementedError(f"La operación '{tag}' no está soportada por esta empresa.")
