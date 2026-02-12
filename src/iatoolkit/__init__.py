# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

__version__ = "1.49.0"

# Expose main classes and functions at the top level of the package

# main IAToolkit class
from iatoolkit.core import IAToolkit, create_app, current_iatoolkit

# for registering the client companies
from .company_registry import register_company, set_company_registry, get_company_instance
from .base_company import BaseCompany

# --- Services ---
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.parsers.parsing_service import ParsingService
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.infra.call_service import CallServiceClient
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.mail_service import MailService
from iatoolkit.repositories.models import Base as OrmModel
from iatoolkit.base_company import BaseCompany

__all__ = [
    'IAToolkit',
    'create_app',
    'current_iatoolkit',
    'register_company',
    'set_company_registry',
    'get_company_instance',
    'BaseCompany',
    'QueryService',
    'SqlService',
    'ParsingService',
    'KnowledgeBaseService',
    'CallServiceClient',
    'ProfileService',
    'MailService',
    'EmbeddingService',
    'StorageService',
    'OrmModel',
    'BaseCompany',
]
