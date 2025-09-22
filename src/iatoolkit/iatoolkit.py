# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit Core
# Framework opensource para chatbots empresariales con IA

from flask import Flask, url_for
from flask_session import Session
from flask_injector import FlaskInjector
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from common.auth import IAuthentication
from common.util import Utility
from common.exceptions import IAToolkitException
from common.session_manager import SessionManager
from urllib.parse import urlparse
import redis
import logging
import os
import click
from typing import Optional, Dict, Any
from repositories.database_manager import DatabaseManager
from .context import _iatoolkit_ctx_stack
from injector import Binder, singleton, Injector
from .toolkit_config import IAToolkitConfig

VERSION = "2.0.0"


class IAToolkit:
    """
    IAToolkit main class
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

    def create_iatoolkit(self):
        """
            Creates, configures, and returns the Flask application instance.
            his is the main entry point for the application factory.
        """
        self._setup_logging()

        # Step 1: Create the Flask app instance
        self._create_flask_instance()

        # Step 2: Set up the core components that DI depends on
        self._setup_database()

        # Step 3: Create the Injector with CORE dependencies (NO VIEWS)
        toolkit_config_module = IAToolkitConfig(app=self.app, db_manager=self.db_manager)
        self._injector = Injector([
            toolkit_config_module,
            self._configure_core_dependencies # This method binds services, repos, etc.

        ])

        # Step 4: Explicitly bind the views to the injector.
        self._bind_views(self._injector.binder)

        # Step 5: Register routes using the fully configured injector
        self._register_routes()

        # Step 6: Initialize FlaskInjector. This is now primarily for request-scoped injections
        # and other integrations, as views are handled manually.
        FlaskInjector(app=self.app, injector=self._injector)

        # Step 7: Finalize setup within the application context
        with self.app.app_context():
            # Push the toolkit instance to the global context stack
            _iatoolkit_ctx_stack.push(self)

            self._setup_redis_sessions()
            self._setup_cors()
            self._setup_additional_services()
            self._setup_cli_commands()
            self._setup_context_processors()

        logging.info(f"🎉 IAToolkit v{VERSION} inicializado correctamente")
        return self.app


    def _get_config_value(self, key: str, default=None):
        """Obtiene un valor de configuración, primero del dict config, luego de env vars"""
        return self.config.get(key, os.getenv(key, default))

    def _setup_logging(self):
        log_level_str = self._get_config_value('FLASK_ENV', 'production')
        log_level = logging.INFO if log_level_str in ('dev', 'development') else logging.WARNING

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - IATOOLKIT - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()],
            force=True
        )

    def _register_routes(self):
        """Registers routes by passing the configured injector."""
        from common.routes import main_bp, register_views

        # Pass the injector to the view registration function
        register_views(self._injector)

        # Register the blueprint with the app
        self.app.register_blueprint(main_bp)
        logging.info("✅ Routes and blueprint registered.")

    def _create_flask_instance(self):
        static_folder = self._get_config_value('STATIC_FOLDER') or self._get_default_static_folder()
        template_folder = self._get_config_value('TEMPLATE_FOLDER') or self._get_default_template_folder()

        self.app = Flask(__name__,
                         static_folder=static_folder,
                         template_folder=template_folder)

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
        database_uri = self._get_config_value('DATABASE_URI')
        if not database_uri:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "DATABASE_URI es requerida (config dict o variable de entorno)"
            )

        self.db_manager = DatabaseManager(database_uri)
        self.db_manager.create_all()
        logging.info("✅ Base de datos configurada correctamente")

    def _setup_redis_sessions(self):
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


    def _configure_core_dependencies(self, binder: Binder):
        """⚙️ Configures all system dependencies."""
        try:
            # Core dependencies
            binder.bind(Injector, to=self._injector, scope=singleton)

            # Bind all application components by calling the specific methods
            self._bind_repositories(binder)
            self._bind_services(binder)
            self._bind_infrastructure(binder)

            logging.info("✅ Dependencias configuradas correctamente")

        except Exception as e:
            logging.error(f"❌ Error configurando dependencias: {e}")
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"❌ Error configurando dependencias: {e}"
            )

    def _bind_repositories(self, binder: Binder):
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
        from services.dispatcher_service import Dispatcher

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
        binder.bind(Dispatcher, to=Dispatcher)

    def _bind_infrastructure(self, binder: Binder):
        from infra.llm_client import llmClient
        from infra.llm_proxy import LLMProxy
        from infra.google_chat_app import GoogleChatApp
        from infra.mail_app import MailApp

        binder.bind(LLMProxy, to=LLMProxy, scope=singleton)
        binder.bind(llmClient, to=llmClient, scope=singleton)
        binder.bind(GoogleChatApp, to=GoogleChatApp)
        binder.bind(MailApp, to=MailApp)
        binder.bind(IAuthentication, to=IAuthentication)
        binder.bind(Utility, to=Utility)

    def _bind_views(self, binder: Binder):
        from views.llmquery_view import LLMQueryView
        from views.home_view import HomeView
        from views.chat_view import ChatView
        from views.change_password_view import ChangePasswordView

        binder.bind(HomeView, to=HomeView)
        binder.bind(ChatView, to=ChatView)
        binder.bind(ChangePasswordView, to=ChangePasswordView)
        binder.bind(LLMQueryView, to=LLMQueryView)

    def _setup_additional_services(self):
        Bcrypt(self.app)

    def _setup_cli_commands(self):
        """⌨️ Configura comandos CLI básicos"""

        @self.app.cli.command("init-db")
        def init_db():
            """🗄️ Inicializa la base de datos del sistema"""
            try:
                from services.dispatcher_service import Dispatcher
                dispatcher = self._get_injector().get(Dispatcher)

                click.echo("🚀 Inicializando base de datos...")
                dispatcher.init_db()
                click.echo("✅ Base de datos inicializada correctamente")

            except Exception as e:
                logging.exception(e)
                click.echo(f"❌ Error: {e}")


    def _setup_context_processors(self):
        # Configura context processors para templates
        @self.app.context_processor
        def inject_globals():
            return {
                'url_for': url_for,
                'iatoolkit_version': VERSION,
                'app_name': 'IAToolkit',
                'user': SessionManager.get('user'),
                'user_company': SessionManager.get('company_short_name'),
            }

    def _get_default_static_folder(self) -> str:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/iatoolkit
            src_dir = os.path.dirname(current_dir)  # .../src
            return os.path.join(src_dir, "static")
        except:
            return 'static'

    def _get_default_template_folder(self) -> str:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/iatoolkit
            src_dir = os.path.dirname(current_dir)  # .../src
            return os.path.join(src_dir, "templates")
        except:
            return 'templates'

    def _get_injector(self) -> Injector:
        """Obtiene el injector actual"""
        if not self._injector:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"❌ injector not initialized"
            )
        return self._injector

    def get_dispatcher(self):
        from services.dispatcher_service import Dispatcher
        if not self._injector:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "App no inicializada. Llame a create_app() primero"
            )
        return self._injector.get(Dispatcher)

    def get_database_manager(self) -> DatabaseManager:
        if not self.db_manager:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "Database manager no inicializado"
            )
        return self.db_manager

# 🚀 Función de conveniencia para inicialización rápida
def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    toolkit = IAToolkit(config)
    toolkit.create_iatoolkit()

    return toolkit.app

if __name__ == "__main__":
    app = create_app()
    if app:
        app.run(debug=True)
