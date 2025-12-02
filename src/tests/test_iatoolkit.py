# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import pytest
from flask import Flask
from iatoolkit.core import IAToolkit, current_iatoolkit, create_app
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.database_manager import DatabaseManager
from injector import Injector


class TestIAToolkit(unittest.TestCase):

    def setUp(self):
        """
        Reset the Singleton instance before each test to ensure isolation.
        """
        import iatoolkit.core as iat_module
        iat_module._iatoolkit_instance = None

        # Clean environment variables that might interfere
        if 'DATABASE_URI' in os.environ:
            del os.environ['DATABASE_URI']

    @patch('iatoolkit.core.DatabaseManager')
    @patch('iatoolkit.core.FlaskInjector')
    @patch('iatoolkit.core.Injector')
    def test_create_iatoolkit_initialization(self, mock_injector_cls, mock_flask_injector, mock_db_manager_cls):
        """Test that create_iatoolkit initializes the Flask app and core components correctly."""

        # Setup Mocks
        mock_injector_instance = MagicMock(spec=Injector)
        mock_injector_cls.return_value = mock_injector_instance

        mock_db_instance = MagicMock(spec=DatabaseManager)
        mock_db_manager_cls.return_value = mock_db_instance

        config = {'DATABASE_URI': 'sqlite:///:memory:', 'FLASK_ENV': 'test'}
        toolkit = IAToolkit(config)

        # Mock internal methods that depend on complex external logic or I/O
        with patch.object(toolkit, '_register_routes') as mock_register_routes, \
                patch.object(toolkit, '_instantiate_company_instances') as mock_init_companies, \
                patch.object(toolkit, '_setup_redis_sessions') as mock_setup_redis, \
                patch.object(toolkit, '_setup_cors') as mock_setup_cors, \
                patch.object(toolkit, '_setup_cli_commands') as mock_setup_cli, \
                patch.object(toolkit, '_setup_download_dir') as mock_setup_dl:
            # Act
            app = toolkit.create_iatoolkit()

            # Assert - State
            self.assertIsInstance(app, Flask)
            self.assertTrue(toolkit._initialized)

            # Assert - Database
            mock_db_manager_cls.assert_called_once_with('sqlite:///:memory:')
            mock_db_instance.create_all.assert_called_once()

            # Assert - Dependency Injection
            mock_injector_cls.assert_called_once()
            mock_flask_injector.assert_called_once_with(app=app, injector=mock_injector_instance)

            # Assert - Flow
            mock_register_routes.assert_called_once()
            mock_init_companies.assert_called_once()
            mock_setup_redis.assert_called_once()
            mock_setup_cors.assert_called_once()
            mock_setup_cli.assert_called_once()
            mock_setup_dl.assert_called_once()

    def test_singleton_pattern(self):
        """Test that IAToolkit follows the Singleton pattern strictly."""
        tk1 = IAToolkit({'key': 'value1'})
        tk2 = IAToolkit({'key': 'value2'})

        self.assertIs(tk1, tk2)

        # Verify config behavior before initialization
        # tk2's __init__ runs but shares instance, config might be overwritten if not guarded
        # In current implementation: _initialized is False initially.
        # create_iatoolkit sets _initialized = True.

        # If we haven't called create_iatoolkit, subsequent inits might overwrite config.
        # This matches the implementation provided.
        self.assertEqual(tk1.config, {'key': 'value2'})

        # Initialize tk1 (mocks needed to avoid real startup)
        with patch.object(tk1, '_create_flask_instance'), \
                patch.object(tk1, '_setup_database'), \
                patch.object(tk1, '_configure_core_dependencies'), \
                patch.object(tk1, '_register_routes'), \
                patch.object(tk1, '_instantiate_company_instances'), \
                patch.object(tk1, '_load_company_configuration'), \
                patch.object(tk1, '_setup_redis_sessions'), \
                patch.object(tk1, '_setup_cors'), \
                patch.object(tk1, '_setup_additional_services'), \
                patch.object(tk1, '_setup_cli_commands'), \
                patch.object(tk1, '_setup_download_dir'):
            # Inject dummy objects to allow flow to proceed
            tk1.app = MagicMock()
            tk1.create_iatoolkit()

        self.assertTrue(tk1._initialized)

        # Try creating a 3rd instance
        tk3 = IAToolkit({'key': 'value3'})
        self.assertIs(tk3, tk1)

        # Since _initialized is True, __init__ returns early, config NOT overwritten
        self.assertEqual(tk3.config, {'key': 'value2'})

    def test_get_config_value_priority(self):
        """Test configuration priority: Config dict > Environment Variable > Default."""
        config = {'TEST_KEY': 'config_value'}
        toolkit = IAToolkit(config)

        # 1. Priority: Config dict
        self.assertEqual(toolkit._get_config_value('TEST_KEY'), 'config_value')

        # 2. Priority: Env Var (when key not in dict)
        with patch.dict(os.environ, {'ENV_KEY': 'env_value'}):
            self.assertEqual(toolkit._get_config_value('ENV_KEY'), 'env_value')

        # 3. Priority: Default value
        self.assertEqual(toolkit._get_config_value('NON_EXISTENT', 'default'), 'default')

        # 4. Config dict should override Env Var
        with patch.dict(os.environ, {'TEST_KEY': 'env_value_override'}):
            self.assertEqual(toolkit._get_config_value('TEST_KEY'), 'config_value')

    @patch('iatoolkit.core.DatabaseManager')
    def test_setup_database_failure_missing_uri(self, mock_db_cls):
        """Test that missing DATABASE_URI raises IAToolkitException."""
        toolkit = IAToolkit({})  # Empty config

        with self.assertRaises(IAToolkitException) as cm:
            toolkit._setup_database()

        self.assertEqual(cm.exception.error_type, IAToolkitException.ErrorType.CONFIG_ERROR)

    def test_get_injector_raises_if_not_initialized(self):
        """Test get_injector raises error if app not initialized."""
        toolkit = IAToolkit({})
        with self.assertRaises(IAToolkitException):
            toolkit.get_injector()

    def test_get_database_manager_raises_if_not_initialized(self):
        """Test get_database_manager raises error if not initialized."""
        toolkit = IAToolkit({})
        with self.assertRaises(IAToolkitException):
            toolkit.get_database_manager()

    @patch('iatoolkit.core.redis.Redis')
    @patch('iatoolkit.core.Session')
    def test_setup_redis_sessions(self, mock_session_cls, mock_redis_cls):
        """Test Redis session setup when REDIS_URL is present."""
        config = {'REDIS_URL': 'redis://localhost:6379/0'}
        toolkit = IAToolkit(config)
        toolkit.app = Flask(__name__)

        toolkit._setup_redis_sessions()

        mock_redis_cls.assert_called_once()
        mock_session_cls.assert_called_once_with(toolkit.app)
        self.assertEqual(toolkit.app.config['SESSION_TYPE'], 'redis')

    @patch('iatoolkit.cli_commands.register_core_commands')
    @patch('iatoolkit.company_registry.get_company_registry')
    def test_setup_cli_commands(self, mock_get_registry, mock_register_core):
        """Test registration of core and company-specific CLI commands."""
        toolkit = IAToolkit({})
        toolkit.app = MagicMock()

        # Setup mock registry returning one mock company
        mock_company_instance = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_all_company_instances.return_value = {'test_co': mock_company_instance}
        mock_get_registry.return_value = mock_registry

        toolkit._setup_cli_commands()

        mock_register_core.assert_called_once_with(toolkit.app)
        mock_company_instance.register_cli_commands.assert_called_once_with(toolkit.app)

    def test_current_iatoolkit_helper(self):
        """Test current_iatoolkit helper function returns the singleton."""
        tk = current_iatoolkit()
        self.assertIsInstance(tk, IAToolkit)
        self.assertIs(current_iatoolkit(), tk)

    @patch('iatoolkit.core.IAToolkit')
    def test_create_app_helper(self, mock_iatoolkit_cls):
        """Test create_app helper function wraps initialization."""
        mock_instance = MagicMock()
        mock_iatoolkit_cls.return_value = mock_instance
        mock_instance.app = "flask_app_instance"

        config = {'test': 1}
        app = create_app(config)

        mock_iatoolkit_cls.assert_called_with(config)
        mock_instance.create_iatoolkit.assert_called_once()
        self.assertEqual(app, "flask_app_instance")

    @patch('iatoolkit.core.os.makedirs')
    def test_setup_download_dir_creates_directory(self, mock_makedirs):
        """Test that the download directory is created."""
        config = {'IATOOLKIT_DOWNLOAD_DIR': '/custom/path'}
        toolkit = IAToolkit(config)
        toolkit.app = Flask(__name__)

        toolkit._setup_download_dir()

        mock_makedirs.assert_called_once_with('/custom/path', exist_ok=True)
        self.assertEqual(toolkit.app.config['IATOOLKIT_DOWNLOAD_DIR'], '/custom/path')

    @patch('iatoolkit.company_registry.get_company_registry')
    @patch('iatoolkit.core.CORS')
    def test_setup_cors(self, mock_cors, mock_get_registry):
        """Test CORS setup aggregates origins from all companies."""
        toolkit = IAToolkit({})
        toolkit.app = Flask(__name__)

        # Mock registry with 2 companies having different cors_origin params
        mock_co1 = MagicMock()
        mock_co1.company.parameters = {'cors_origin': ['https://a.com']}
        mock_co2 = MagicMock()
        mock_co2.company.parameters = {'cors_origin': ['https://b.com']}

        mock_registry = MagicMock()
        mock_registry.get_all_company_instances.return_value = {
            'co1': mock_co1,
            'co2': mock_co2
        }
        mock_get_registry.return_value = mock_registry

        toolkit._setup_cors()

        # Verify CORS was initialized with combined origins
        mock_cors.assert_called_once()
        call_kwargs = mock_cors.call_args[1]
        self.assertIn('https://a.com', call_kwargs['origins'])
