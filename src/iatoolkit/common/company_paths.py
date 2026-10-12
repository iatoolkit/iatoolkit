# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from pathlib import Path


def get_company_root(company_short_name: str) -> Path:
    """
    Directory that holds a company's files: config, prompts, schemas, context,
    templates.

    A company module installed as a package declares it through
    ``BaseCompany.get_resource_root()``. Every other company keeps the classic
    layout, ``companies/<company_short_name>`` relative to the working directory,
    which is why that is the fallback and not an error.
    """
    from iatoolkit.company_registry import get_registered_companies

    company_class = get_registered_companies().get((company_short_name or "").lower())
    root = company_class.get_resource_root() if company_class else None
    if root:
        return Path(root)
    return Path("companies") / company_short_name
