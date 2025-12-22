# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import Flask, url_for, get_flashed_messages, request
from flask_session import Session
from flask_injector import FlaskInjector
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.interfaces.asset_storage import AssetRepository
from iatoolkit.company_registry import get_registered_companies
from werkzeug.middleware.proxy_fix import ProxyFix
from injector import Binder, Injector, singleton
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import redis
import logging
import os

from iatoolkit import __version__ as IATOOLKIT_VERSION
from iatoolkit.services.configuration_service import ConfigurationService

# global variable for the unique instance of IAToolkit
_iatoolkit_instance: Optional['IAToolkit'] = None

def is_bound(injector: Injector, cls) -> bool:
    return cls in injector.binder._bindings

class IAToolkit:
    """
    IAToolkit main class
    """
    def __new__(cls, config: Optional[Dict[str, Any]] = None):
        """
        Implementa el patrón Singleton
        """
        global _iatoolkit_instance
        if _iatoolkit_instance is None:
            _iatoolkit_instance = super().__new__(cls)
            _iatoolkit_instance._initialized = False
        return _iatoolkit_instance


    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: Diccionario opcional de configuración que sobrescribe variables de entorno
        """
        if self._initialized:
            return

        self.config = config or {}
        self.app = None
        self.db_manager = None
        self._injector = Injector()         # init empty injector
        self.version = IATOOLKIT_VERSION
        self.license = "Community Edition"

    @classmethod
    def get_instance(cls) -> 'IAToolkit':
        # get the global IAToolkit instance
        global _iatoolkit_instance
        if _iatoolkit_instance is None:
            _iatoolkit_instance = cls()
        return _iatoolkit_instance

    def create_iatoolkit(self, start: bool = True):
        """
            Creates, configures, and returns the Flask application instance.
            this is the main entry point for the application factory.
        """
        if self._initialized and self.app:
            return self.app

        self._setup_logging()

        # Step 1: Create the Flask app instance
        self._create_flask_instance()

        # Step 2: Set up the core components that DI depends on
        self._setup_database()

        # Step 3: Configure dependencies using the existing injector
        self._configure_core_dependencies(self._injector)

        # Step 4: Register routes using the fully configured injector
        self._register_routes()

        # Step 5: Initialize FlaskInjector. This is now primarily for request-scoped injections
        # and other integrations, as views are handled manually.
        FlaskInjector(app=self.app, injector=self._injector)

        # Step 6: initialize registered companies
        self._instantiate_company_instances()

        # Re-apply logging configuration in case it was modified by company-specific code
        self._setup_logging()

        # Step 7: load company configuration file
        self._load_company_configuration()

        # Step 8: Finalize setup within the application context
        self._setup_redis_sessions()

        self._setup_cors()
        self._setup_additional_services()
        self._setup_cli_commands()
        self._setup_request_globals()
        self._setup_context_processors()

        # Step 9: define the download_dir
        self._setup_download_dir()

        # register data source
        if start:
            self.register_data_sources()

        logging.info(f"🎉 IAToolkit {self.license} version {self.version} correctly initialized.")
        self._initialized = True

        return self.app

    def register_data_sources(self):
        # load the company configurations
        configuration_service = self._injector.get(ConfigurationService)
        for company in get_registered_companies():
            configuration_service.register_data_sources(company)

    def _get_config_value(self, key: str, default=None):
        # get a value from the config dict or the environment variable
        return self.config.get(key, os.getenv(key, default))

    def _setup_request_globals(self):
        """
        Configures functions to run before each request to set up
        request-global variables, such as language.
        """
        injector = self._injector

        @self.app.before_request
        def set_request_language():
            """
            Determines and caches the language for the current request in g.lang.
            """
            from iatoolkit.services.language_service import LanguageService
            language_service = injector.get(LanguageService)
            language_service.get_current_language()

    def _setup_logging(self):
        # Lee el nivel de log desde una variable de entorno, con 'INFO' como valor por defecto.
        log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_level = getattr(logging, log_level_name, logging.INFO)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - IATOOLKIT - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()],
            force=True
        )

        logging.getLogger("httpx").setLevel(logging.WARNING)

    def _register_routes(self):
        """Registers routes by passing the configured injector."""
        from iatoolkit.common.routes import register_views

        # Pass the injector to the view registration function
        register_views(self.app)
        logging.info("✅ Community routes registered.")

    def _create_flask_instance(self):
        static_folder = self._get_config_value('STATIC_FOLDER') or self._get_default_static_folder()
        template_folder = self._get_config_value('TEMPLATE_FOLDER') or self._get_default_template_folder()

        self.app = Flask(__name__,
                         static_folder=static_folder,
                         template_folder=template_folder)

        self.app.config.update({
            'VERSION': self.version,
            'SECRET_KEY': self._get_config_value('FLASK_SECRET_KEY', 'iatoolkit-default-secret'),
            'SESSION_COOKIE_SAMESITE': "None",
            'SESSION_COOKIE_SECURE': True,
            'SESSION_PERMANENT': False,
            'SESSION_USE_SIGNER': True,
            'IATOOLKIT_SECRET_KEY': self._get_config_value('IATOOLKIT_SECRET_KEY', 'iatoolkit-jwt-secret'),
            'JWT_ALGORITHM': 'HS256',
        })

        # 2. ProxyFix para no tener problemas con iframes y rutas
        self.app.wsgi_app = ProxyFix(self.app.wsgi_app, x_proto=1)

        # Configuración para tokenizers en desarrollo
        if self._get_config_value('FLASK_ENV') == 'dev':
            os.environ["TOKENIZERS_PARALLELISM"] = "false"

    def _setup_database(self):
        database_uri = self._get_config_value('DATABASE_URI') or self._get_config_value('DATABASE_URL')
        if not database_uri:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "DATABASE_URI is required (config dict or env. variable)"
            )

        self.db_manager = DatabaseManager(database_url=database_uri, schema='iatoolkit')
        self.db_manager.create_all()
        logging.info("✅ Database configured successfully")

        @self.app.teardown_appcontext
        def remove_session(exception=None):
            """
            Flask calls this after each request.
            It ensures the SQLAlchemy session is properly closed
            and the DB connection is returned to the pool.
            """
            self.db_manager.scoped_session.remove()

    def _setup_redis_sessions(self):
        redis_url = self._get_config_value('REDIS_URL')
        if not redis_url:
            logging.warning("⚠️ REDIS_URL not configured, will use memory sessions")
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
            logging.info("✅ Redis and sessions configured successfully")

        except Exception as e:
            logging.error(f"❌ Error configuring Redis: {e}")
            raise e

    def _setup_cors(self):
        """🌐 Configura CORS"""
        from iatoolkit.company_registry import get_company_registry

        # default CORS origin
        default_origins = []

        # Iterate through the registered company names
        extra_origins = []
        all_company_instances = get_company_registry().get_all_company_instances()
        for company_name, company_instance in all_company_instances.items():
            if company_instance.company:
                cors_origin = company_instance.company.parameters.get('cors_origin', [])
                extra_origins += cors_origin

        all_origins = default_origins + extra_origins

        CORS(self.app,
             supports_credentials=True,
             origins=all_origins,
             allow_headers=[
                 "Content-Type", "Authorization", "X-Requested-With",
                 "X-Chat-Token", "x-chat-token"
             ],
             methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

        logging.info(f"✅ CORS configured for: {all_origins}")

    def _configure_core_dependencies(self, injector: Injector):
        """⚙️ Configures all system dependencies."""

        # get the binder from injector
        binder = injector.binder
        try:
            # Core dependencies
            binder.bind(Flask, to=self.app)
            binder.bind(DatabaseManager, to=self.db_manager, scope=singleton)

            # Bind all application components by calling the specific methods
            self._bind_repositories(binder)
            self._bind_services(binder)
            self._bind_infrastructure(binder)

            logging.info("✅ Dependencies configured successfully")

        except Exception as e:
            logging.error(f"❌ Error configuring dependencies: {e}")
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"❌ Error configuring dependencies: {e}"
            )

    def _bind_repositories(self, binder: Binder):
        from iatoolkit.repositories.document_repo import DocumentRepo
        from iatoolkit.repositories.profile_repo import ProfileRepo
        from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
        from iatoolkit.repositories.vs_repo import VSRepo
        from iatoolkit.repositories.filesystem_asset_repository import FileSystemAssetRepository

        binder.bind(DocumentRepo, to=DocumentRepo)
        binder.bind(ProfileRepo, to=ProfileRepo)
        binder.bind(LLMQueryRepo, to=LLMQueryRepo)
        binder.bind(VSRepo, to=VSRepo)

        # this class can be setup befor by iatoolkit enterprise
        if not is_bound(self._injector, AssetRepository):
            binder.bind(AssetRepository, to=FileSystemAssetRepository)

    def _bind_services(self, binder: Binder):
        from iatoolkit.services.query_service import QueryService
        from iatoolkit.services.benchmark_service import BenchmarkService
        from iatoolkit.services.document_service import DocumentService
        from iatoolkit.services.prompt_service import PromptService
        from iatoolkit.services.excel_service import ExcelService
        from iatoolkit.services.mail_service import MailService
        from iatoolkit.services.load_documents_service import LoadDocumentsService
        from iatoolkit.services.profile_service import ProfileService
        from iatoolkit.services.jwt_service import JWTService
        from iatoolkit.services.dispatcher_service import Dispatcher
        from iatoolkit.services.branding_service import BrandingService
        from iatoolkit.services.i18n_service import I18nService
        from iatoolkit.services.language_service import LanguageService
        from iatoolkit.services.configuration_service import ConfigurationService
        from iatoolkit.services.embedding_service import EmbeddingService
        from iatoolkit.services.history_manager_service import HistoryManagerService
        from iatoolkit.services.tool_service import ToolService
        from iatoolkit.services.llm_client_service import llmClient
        from iatoolkit.services.auth_service import AuthService
        from iatoolkit.services.sql_service import SqlService

        binder.bind(QueryService, to=QueryService)
        binder.bind(BenchmarkService, to=BenchmarkService)
        binder.bind(DocumentService, to=DocumentService)
        binder.bind(PromptService, to=PromptService)
        binder.bind(ExcelService, to=ExcelService)
        binder.bind(MailService, to=MailService)
        binder.bind(LoadDocumentsService, to=LoadDocumentsService)
        binder.bind(ProfileService, to=ProfileService)
        binder.bind(JWTService, to=JWTService)
        binder.bind(Dispatcher, to=Dispatcher)
        binder.bind(BrandingService, to=BrandingService)
        binder.bind(I18nService, to=I18nService)
        binder.bind(LanguageService, to=LanguageService)
        binder.bind(ConfigurationService, to=ConfigurationService)
        binder.bind(EmbeddingService, to=EmbeddingService)
        binder.bind(HistoryManagerService, to=HistoryManagerService)
        binder.bind(ToolService, to=ToolService)
        binder.bind(llmClient, to=llmClient)
        binder.bind(AuthService, to=AuthService)
        binder.bind(SqlService, to=SqlService)

    def _bind_infrastructure(self, binder: Binder):
        from iatoolkit.infra.llm_proxy import LLMProxy
        from iatoolkit.infra.google_chat_app import GoogleChatApp
        from iatoolkit.infra.brevo_mail_app import BrevoMailApp
        from iatoolkit.common.util import Utility
        from iatoolkit.common.model_registry import ModelRegistry

        binder.bind(LLMProxy, to=LLMProxy)
        binder.bind(GoogleChatApp, to=GoogleChatApp)
        binder.bind(BrevoMailApp, to=BrevoMailApp)
        binder.bind(Utility, to=Utility)
        binder.bind(ModelRegistry, to=ModelRegistry)

    def _setup_additional_services(self):
        Bcrypt(self.app)

    def _instantiate_company_instances(self):
        from iatoolkit.company_registry import get_company_registry

        # instantiate all the registered companies
        get_company_registry().instantiate_companies(self._injector)

    def _load_company_configuration(self):
        from iatoolkit.services.dispatcher_service import Dispatcher

        # use the dispatcher to load the company config.yaml file and prepare the execution
        dispatcher = self._injector.get(Dispatcher)
        dispatcher.load_company_configs()

    def _setup_cli_commands(self):
        from iatoolkit.cli_commands import register_core_commands
        from iatoolkit.company_registry import get_company_registry

        # 1. Register core commands
        register_core_commands(self.app)
        logging.info("✅ Core CLI commands registered.")

        # 2. Register company-specific commands
        try:
            # Iterate through the registered company names
            all_company_instances = get_company_registry().get_all_company_instances()
            for company_name, company_instance in all_company_instances.items():
                if hasattr(company_instance, "register_cli_commands"):
                    company_instance.register_cli_commands(self.app)

        except Exception as e:
            logging.error(f"❌ error while registering company commands: {e}")

    def _setup_context_processors(self):
        # Configura context processors para templates
        @self.app.context_processor
        def inject_globals():
            from iatoolkit.common.session_manager import SessionManager
            from iatoolkit.services.profile_service import ProfileService
            from iatoolkit.services.i18n_service import I18nService

            # Get services from the injector
            profile_service = self._injector.get(ProfileService)
            i18n_service = self._injector.get(I18nService)

            # The 't' function wrapper no longer needs to determine the language itself.
            # It will be automatically handled by the refactored I18nService.
            def translate_for_template(key: str, **kwargs):
                return i18n_service.t(key, **kwargs)

            # Get user profile if a session exists
            user_profile = profile_service.get_current_session_info().get('profile', {})

            return {
                'url_for': url_for,
                'iatoolkit_version': f'{self.version}',
                'license': self.license,
                'app_name': 'IAToolkit',
                'user_identifier': SessionManager.get('user_identifier'),
                'company_short_name': SessionManager.get('company_short_name'),
                'user_role': user_profile.get('user_role'),
                'user_is_local': user_profile.get('user_is_local'),
                'user_email': user_profile.get('user_email'),
                'iatoolkit_base_url': request.url_root,
                'flashed_messages': get_flashed_messages(with_categories=True),
                't': translate_for_template,
                'google_analytics_id': self._get_config_value('GOOGLE_ANALYTICS_ID', ''),
            }

    def _get_default_static_folder(self) -> str:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/iatoolkit
            return os.path.join(current_dir, "static")
        except:
            return 'static'

    def _get_default_template_folder(self) -> str:
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/iatoolkit
            return os.path.join(current_dir, "templates")
        except:
            return 'templates'

    def get_injector(self) -> Injector:
        """Obtiene el injector actual"""
        if not self._injector:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                f"❌ injector not initialized"
            )
        return self._injector

    def get_dispatcher(self):
        from iatoolkit.services.dispatcher_service import Dispatcher
        if not self._injector:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "App no initialized. Call create_app() first"
            )
        return self._injector.get(Dispatcher)

    def get_database_manager(self) -> DatabaseManager:
        if not self.db_manager:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "Database manager not initialized."
            )
        return self.db_manager

    def _setup_download_dir(self):
        # 1. set the default download directory
        default_download_dir = os.path.join(os.getcwd(), 'iatoolkit-downloads')

        # 3. if user specified one, use it
        download_dir = self._get_config_value('IATOOLKIT_DOWNLOAD_DIR', default_download_dir)

        # 3. save it in the app config
        self.app.config['IATOOLKIT_DOWNLOAD_DIR'] = download_dir

        # 4. make sure the directory exists
        try:
            os.makedirs(download_dir, exist_ok=True)
        except OSError as e:
            raise IAToolkitException(
                IAToolkitException.ErrorType.CONFIG_ERROR,
                "No se pudo crear el directorio de descarga. Verifique que el directorio existe y tenga permisos de escritura."
            )
        logging.info(f"✅ download dir created in: {download_dir}")



def current_iatoolkit() -> IAToolkit:
    return IAToolkit.get_instance()

# Función de conveniencia para inicialización rápida
def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    toolkit = IAToolkit(config)
    toolkit.create_iatoolkit()

    return toolkit.app
