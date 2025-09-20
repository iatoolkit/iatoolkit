"""
iatoolkit-core: Framework opensource para chatbots empresariales con IA

Componentes principales:
- IAToolkit: Clase principal del framework
- BaseCompany: Clase base para implementaciones empresariales
- create_app: Función de conveniencia para inicialización rápida
"""

from typing import TYPE_CHECKING

# Solo importar lo esencial que no causa ciclos
from .base_company import BaseCompany

# Type hints para el IDE (no se ejecutan en runtime)
if TYPE_CHECKING:
    from .iatoolkit import IAToolkit, create_app
    from services.dispatcher_service import Dispatcher
    from services.excel_service import ExcelService
    from services.sql_service import SqlService
    from services.mail_service import MailService

# Información del paquete
__version__ = "0.2.8"
__author__ = "Fernando Libedinsky"


def __getattr__(name: str):
    """Lazy loading para evitar imports circulares"""
    if name == "IAToolkit":
        from .iatoolkit import IAToolkit
        return IAToolkit
    elif name == "create_app":
        from .iatoolkit import create_app
        return create_app
    elif name == "Dispatcher":
        from services.dispatcher_service import Dispatcher
        return Dispatcher
    elif name == "ExcelService":
        from services.excel_service import ExcelService
        return ExcelService
    elif name == "SqlService":
        from services.sql_service import SqlService
        return SqlService
    elif name == "MailService":
        from services.mail_service import MailService
        return MailService
    else:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    # Componentes principales
    "IAToolkit",
    "create_app",
    "BaseCompany",

    # Servicios disponibles
    "Dispatcher",
    "ExcelService",
    "SqlService",
    "MailService"
]