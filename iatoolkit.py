# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit Core
# Framework opensource para chatbots empresariales con IA

from flask import Flask, url_for
from flask_session import Session
from flask_injector import FlaskInjector
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from urllib.parse import urlparse
import redis
import logging
import os
import click
from functools import partial
from typing import Optional, Dict, Any
from injector import Binder, singleton, Injector

from repositories.database_manager import DatabaseManager
from services.dispatcher_service import Dispatcher
from common.routes import register_routes

VERSION = "2.0.0"


class IAToolkitException(Exception):
    """Excepción personalizada para IAToolkit"""
    pass


class IAToolkit:
    """
    IAToolkit main class

    Ejemplo de uso:
    ```python
    from iatoolkit import IAToolkit

    # Configuración mínima con variables de entorno
    toolkit = IAToolkit()
    app = toolkit.create_app()
    ```
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: Diccionario opcional de configuración que sobrescribe variables de entorno
        """
        self.config = config or {}
        self.app: Optional[Flask] = None
        self.db_manager: Optional[DatabaseManager] = None
        self._injector: Optional[Injector] = None
        self._startup_executed = False

    def create_iatoolkit(self):

        # 1. Configurar logging
        self._setup_logging()

        # 2. Crear instancia Flask
        self._create_flask_instance()

        # 3. Configurar Flask básico
        self._configure_flask_basic()

        # 4. Configurar base de datos
        self._setup_database()

        # 5. Configurar Redis y sesiones
        self._setup_redis_sessions()

        # 6. Configurar CORS
        self._setup_cors()

        # 7. Configurar inyección de dependencias
        self._setup_dependency_injection()

        # 8. Registrar rutas
        self._register_routes()

        # 9. Configurar servicios adicionales
        self._setup_additional_services()

        # 10. Configurar CLI commands
        self._setup_cli_commands()

        # 11. Context processors
        self._setup_context_processors()

        # 12. Auto-startup para desarrollo
        self._start_companies()

        logging.info(f"🎉 IAToolkit v{VERSION} inicializado correctamente")
        return self

    def _get_config_value(self, key: str, default=None):
        """Obtiene un valor de configuración, primero del dict config, luego de env vars"""
        return self.config.get(key, os.getenv(key, default))

    def _setup_logging(self):
        """📝 Configura el sistema de logging"""
        log_level_str = self._get_config_value('FLASK_ENV', 'production')
        log_level = logging.INFO if log_level_str == 'dev' else logging.WARNING

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - IATOOLKIT - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )

        # Configurar niveles de librerías externas
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

    def _create_flask_instance(self):
        """🏭 Crea la instancia Flask"""
        static_folder = self._get_config_value('STATIC_FOLDER') or self._get_default_static_folder()
        template_folder = self._get_config_value('TEMPLATE_FOLDER') or self._get_default_template_folder()

        self.app = Flask(__name__,
                         static_folder=static_folder,
                         template_folder=template_folder)

    def _configure_flask_basic(self):
        """⚙️ Configuraciones básicas de Flask"""
        is_https = self._get_config_value('USE_HTTPS', 'false').lower() == 'true'
        is_dev = self._get_config_value('FLASK_ENV') == 'development'

        self.app.config.update({
            'VERSION': VERSION,
            'SECRET_KEY': self._get_config_value('FLASK_SECRET_KEY', 'iatoolkit-default-secret'),
            'SESSION_COOKIE_SAMESITE': "None" if is_https else "Lax",
            'SESSION_COOKIE_SECURE': is_https,
            'SESSION_PERMANENT': False,
            'SESSION_USE_SIGNER': True,
            'JWT_SECRET_KEY': self._get_config_value('JWT_SECRET_KEY', 'iatoolkit-jwt-secret'),
            'JWT_ALGORITHM': 'HS256',
            'JWT_EXPIRATION_SECONDS_CHAT': int(self._get_config_value('JWT_EXPIRATION_SECONDS_CHAT', 3600))
        })

        # Configuración para tokenizers en desarrollo
        if is_dev:
            os.environ["TOKENIZERS_PARALLELISM"] = "false"

    def _setup_database(self):
        """🗄️ Configura el gestor de base de datos"""
        database_uri = self._get_config_value('DATABASE_URI')
        if not database_uri:
            raise IAToolkitException("DATABASE_URI es requerida (config dict o variable de entorno)")

        self.db_manager = DatabaseManager(database_uri)
        self.db_manager.create_all()
        logging.info("✅ Base de datos configurada correctamente")

    def _setup_redis_sessions(self):
        """🔄 Configura Redis y las sesiones"""
        redis_url = self._get_config_value('REDIS_URL')
        if not redis_url:
            logging.warning("⚠️ REDIS_URL no configurada, usando sesiones en memoria")
            return

        try:
            url = urlparse(redis_url)
            redis_instance = redis.Redis(
                host=url.hostname,
                port=url.port,
                password=url.password,
                ssl=(url.scheme == "rediss"),
                ssl_cert_reqs=None
            )

            self.app.config.update({
                'SESSION_TYPE': 'redis',
                'SESSION_REDIS': redis_instance
            })

            Session(self.app)
            logging.info("✅ Redis y sesiones configurados correctamente")

        except Exception as e:
            logging.error(f"❌ Error configurando Redis: {e}")
            logging.warning("⚠️ Continuando sin Redis")

    def _setup_cors(self):
        """🌐 Configura CORS"""
        # Origins por defecto para desarrollo
        default_origins = [
            "http://localhost:3000",
            "http://localhost:5001",
            "http://127.0.0.1:5001"
        ]

        # Obtener origins adicionales desde configuración/env
        extra_origins = []
        for i in range(1, 11):  # Soporte para CORS_ORIGIN_1 a CORS_ORIGIN_10
            origin = self._get_config_value(f'CORS_ORIGIN_{i}')
            if origin:
                extra_origins.append(origin)

        all_origins = default_origins + extra_origins

        CORS(self.app,
             supports_credentials=True,
             origins=all_origins,
             allow_headers=[
                 "Content-Type", "Authorization", "X-Requested-With",
                 "X-Chat-Token", "x-chat-token"
             ],
             methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

        logging.info(f"✅ CORS configurado para: {all_origins}")

    def _setup_dependency_injection(self):
        """💉 Configura el sistema de inyección de dependencias"""
        # Crear el injector y guardarlo para uso posterior
        self._injector = Injector([partial(self._configure_dependencies)])

        # Configurar FlaskInjector con el injector creado
        FlaskInjector(
            app=self.app,
            injector=self._injector
        )

    def _configure_dependencies(self, binder: Binder):
        """⚙️ Configura todas las dependencias del sistema"""
        try:
            # Core dependencies
            binder.bind(DatabaseManager, to=self.db_manager, scope=singleton)

            # Import y bind todos los servicios core
            self._bind_repositories(binder)
            self._bind_services(binder)
            self._bind_infrastructure(binder)
            self._bind_views(binder)

            logging.info("✅ Dependencias configuradas correctamente")

        except Exception as e:
            logging.error(f"❌ Error configurando dependencias: {e}")
            raise

    def _bind_repositories(self, binder: Binder):
        """Bind de todos los repositorios"""
        from repositories.document_repo import DocumentRepo
        from repositories.document_type_repo import DocumentTypeRepo
        from repositories.profile_repo import ProfileRepo
        from repositories.llm_query_repo import LLMQueryRepo
        from repositories.vs_repo import VSRepo
        from repositories.tasks_repo import TaskRepo

        binder.bind(DocumentRepo, to=DocumentRepo)
        binder.bind(DocumentTypeRepo, to=DocumentTypeRepo)
        binder.bind(ProfileRepo, to=ProfileRepo)
        binder.bind(LLMQueryRepo, to=LLMQueryRepo)
        binder.bind(VSRepo, to=VSRepo)
        binder.bind(TaskRepo, to=TaskRepo)

    def _bind_services(self, binder: Binder):
        """Bind de todos los servicios"""
        from services.query_service import QueryService
        from services.tasks_service import TaskService
        from services.benchmark_service import BenchmarkService
        from services.document_service import DocumentService
        from services.prompt_manager_service import PromptService
        from services.excel_service import ExcelService
        from services.mail_service import MailService
        from services.load_documents_service import LoadDocumentsService
        from services.profile_service import ProfileService
        from services.jwt_service import JWTService

        binder.bind(QueryService, to=QueryService)
        binder.bind(TaskService, to=TaskService)
        binder.bind(BenchmarkService, to=BenchmarkService)
        binder.bind(DocumentService, to=DocumentService)
        binder.bind(PromptService, to=PromptService)
        binder.bind(ExcelService, to=ExcelService)
        binder.bind(MailService, to=MailService)
        binder.bind(LoadDocumentsService, to=LoadDocumentsService)
        binder.bind(ProfileService, to=ProfileService)
        binder.bind(JWTService, to=JWTService)

        # El dispatcher ya maneja el descubrimiento de empresas
        binder.bind(Dispatcher, to=Dispatcher)

    def _bind_infrastructure(self, binder: Binder):
        """Bind de infraestructura y utilities"""
        from infra.llm_proxy import LLMProxy
        from infra.google_chat_app import GoogleChatApp
        from infra.llm_client import llmClient
        from infra.mail_app import MailApp
        from common.auth import IAuthentication
        from common.util import Utility

        binder.bind(LLMProxy, to=LLMProxy, scope=singleton)
        binder.bind(llmClient, to=llmClient, scope=singleton)
        binder.bind(GoogleChatApp, to=GoogleChatApp)
        binder.bind(MailApp, to=MailApp)
        binder.bind(IAuthentication, to=IAuthentication)
        binder.bind(Utility, to=Utility)

    def _bind_views(self, binder: Binder):
        """Bind de las views"""
        from views.llmquery_view import LLMQueryView
        binder.bind(LLMQueryView, to=LLMQueryView)

    def _register_routes(self):
        """🛤️ Registra todas las rutas del sistema"""
        register_routes(self.app)

    def _setup_additional_services(self):
        """🔧 Configura servicios adicionales"""
        Bcrypt(self.app)

    # 🚀 Método público para inicializar empresas manualmente
    def _start_companies(self):
        if self._startup_executed:
            return

        try:
            dispatcher = self._get_injector().get(Dispatcher)
            dispatcher.start_execution()
            self._startup_executed = True
            logging.info("🏢 Empresas inicializadas")
        except Exception as e:
            logging.exception(e)
            raise

    def _setup_cli_commands(self):
        """⌨️ Configura comandos CLI básicos"""

        @self.app.cli.command("init-db")
        def init_db():
            """🗄️ Inicializa la base de datos del sistema"""
            try:
                dispatcher = self._get_injector().get(Dispatcher)

                click.echo("🚀 Inicializando base de datos...")
                dispatcher.init_db()
                click.echo("✅ Base de datos inicializada correctamente")

            except Exception as e:
                logging.exception(e)
                click.echo(f"❌ Error: {e}")


    def _setup_context_processors(self):
        """🎭 Configura context processors para templates"""

        @self.app.context_processor
        def inject_globals():
            return {
                'url_for': url_for,
                'iatoolkit_version': VERSION,
                'app_name': 'IAToolkit'
            }

    def _setup_auto_startup(self):
        """🚀 Configura auto-startup para desarrollo"""
        if not self._get_config_value("PYTEST_CURRENT_TEST"):
            @self.app.before_request
            def startup():
                try:
                    dispatcher = self._get_injector().get(Dispatcher)
                    dispatcher.start_execution()
                    logging.info("🏢 Empresas iniciadas automáticamente")
                except Exception as e:
                    logging.exception(e)

    def _get_default_static_folder(self) -> str:
        """Obtiene la ruta por defecto de static"""
        try:
            # Buscar en el paquete src
            current_dir = os.path.dirname(__file__)
            return os.path.join(current_dir, 'static')
        except:
            return 'static'

    def _get_default_template_folder(self) -> str:
        """Obtiene la ruta por defecto de templates"""
        try:
            # Buscar en el paquete src
            current_dir = os.path.dirname(__file__)
            return os.path.join(current_dir, 'templates')
        except:
            return 'templates'

    def _get_injector(self) -> Injector:
        """Obtiene el injector actual"""
        if not self._injector:
            raise IAToolkitException("Injector no inicializado. Llame a create_app() primero")
        return self._injector

    # 📊 Métodos públicos de utilidad
    def get_dispatcher(self) -> Dispatcher:
        """Obtiene el dispatcher del sistema"""
        if not self._injector:
            raise IAToolkitException("App no inicializada. Llame a create_app() primero")
        return self._injector.get(Dispatcher)

    def get_database_manager(self) -> DatabaseManager:
        """Obtiene el database manager"""
        if not self.db_manager:
            raise IAToolkitException("Database manager no inicializado")
        return self.db_manager


# 🚀 Función de conveniencia para inicialización rápida
def create_app(config: Optional[Dict[str, Any]] = None) -> IAToolkit:
    toolkit = IAToolkit(config)
    return toolkit.create_iatoolkit()

if __name__ == "__main__":
    toolkit = IAToolkit()
    app = toolkit.create_iatoolkit()
    app.run()