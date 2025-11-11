"""
IAToolkit Package
"""

# Expose main classes and functions at the top level of the package

# main IAToolkit class
from .iatoolkit import IAToolkit, create_app, current_iatoolkit

# for registering the client companies
from .company_registry import register_company
from .base_company import BaseCompany

# --- Services ---
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.document_service import DocumentService
from iatoolkit.services.search_service import SearchService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.load_documents_service import LoadDocumentsService
from iatoolkit.infra.call_service import CallServiceClient

__all__ = [
    'IAToolkit',
    'create_app',
    'current_iatoolkit',
    'register_company',
    'BaseCompany',
    'QueryService',
    'SqlService',
    'DocumentService',
    'SearchService',
    'LoadDocumentsService',
    'CallServiceClient',
]
