import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import (Prompt, PromptCategory,
                                           Company, PromptType)
from iatoolkit.common.exceptions import IAToolkitException


class TestPromptService:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura mocks y la instancia del servicio para cada test."""
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_asset_repo = MagicMock(spec=AssetRepository)

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.prompt_service = PromptService(
            llm_query_repo=self.llm_query_repo,
            profile_repo=self.profile_repo,
            i18n_service=self.mock_i18n_service,
            asset_repo=self.mock_asset_repo
        )
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.id = 1
        self.mock_company.name = 'Test Company'
        self.mock_company.short_name = 'test_co'

    def test_get_user_prompts_company_not_found(self):
        """Prueba que se devuelve un error cuando la empresa no existe."""
        self.profile_repo.get_company_by_short_name.return_value = None
        result = self.prompt_service.get_user_prompts(company_short_name='nonexistent_company')
        assert result == {'error': 'translated:errors.company_not_found'}

    def test_get_user_prompts_no_prompts_exist(self):
        """Prueba que se devuelve una lista vacía cuando la empresa no tiene prompts."""
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_prompts.return_value = []
        result = self.prompt_service.get_user_prompts(company_short_name='test_company')
        assert result == {'message': []}

    # --- Tests para get_system_prompt ---

    @patch('iatoolkit.services.prompt_service.importlib.resources.read_text')
    def test_get_system_prompt_success(self, mock_read_text):
        """Prueba la obtención exitosa de los prompts de sistema concatenados."""
        prompt1 = Prompt(filename='system1.prompt')
        prompt2 = Prompt(filename='system2.prompt')
        self.llm_query_repo.get_system_prompts.return_value = [prompt1, prompt2]

        # Configurar el mock para devolver diferentes contenidos en cada llamada
        mock_read_text.side_effect = [
            'Contenido 1',
            'Contenido 2'
        ]

        result = self.prompt_service.get_system_prompt()

        assert result == "Contenido 1\nContenido 2"
        assert mock_read_text.call_count == 2

    @patch('iatoolkit.services.prompt_service.os.path.exists', return_value=False)
    @patch('iatoolkit.services.prompt_service.logging')
    def test_get_system_prompt_file_not_found(self, mock_logging, mock_exists):
        """Prueba que se loguea una advertencia si un archivo de prompt no existe."""
        prompt1 = Prompt(filename='missing.prompt')
        self.llm_query_repo.get_system_prompts.return_value = [prompt1]

        result = self.prompt_service.get_system_prompt()

        assert result == ""
        mock_logging.warning.assert_called_once()
        assert "file does not exist" in mock_logging.warning.call_args[0][0]

    def test_get_system_prompt_handles_repo_exception(self):
        """Prueba que se maneja una excepción del repositorio."""
        self.llm_query_repo.get_system_prompts.side_effect = Exception("DB Connection Error")

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_system_prompt()

        assert exc_info.value.error_type == IAToolkitException.ErrorType.PROMPT_ERROR
        assert "DB Connection Error" in str(exc_info.value)

    # --- Tests para get_prompt_content ---

    def test_get_prompt_content_success(self):
        """Prueba la obtención exitosa del contenido de un prompt específico usando el repo."""
        mock_prompt = Prompt(filename='my_prompt.prompt')
        self.llm_query_repo.get_prompt_by_name.return_value = mock_prompt

        # Configurar el comportamiento del repo mockeado
        self.mock_asset_repo.read_text.return_value = 'Contenido específico del prompt.'

        result = self.prompt_service.get_prompt_content(self.mock_company, 'my_prompt')

        assert result == 'Contenido específico del prompt.'

        # Verificar que se llamó al repo correctamente
        self.mock_asset_repo.read_text.assert_called_once_with(
            self.mock_company.short_name,
            AssetType.PROMPT,
            'my_prompt.prompt'
        )

    def test_get_prompt_content_prompt_not_in_db(self):
        """Prueba que se lanza una excepción si el prompt no se encuentra en la BD."""
        self.llm_query_repo.get_prompt_by_name.return_value = None

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_prompt_content(self.mock_company, 'non_existent_prompt')

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND


    def test_create_prompt_success_for_company(self):
        self.mock_asset_repo.exists.return_value = True     # file exists

        """Prueba la creación exitosa de un prompt para una compañía."""
        self.prompt_service.create_prompt(
            prompt_name='new_prompt',
            description='A new prompt',
            order=1,
            company=self.mock_company,
            custom_fields = [{'data_key': 'key', 'label': ' a label'}]
        )

        self.mock_asset_repo.exists.assert_called_once_with(
            self.mock_company.short_name, AssetType.PROMPT, 'new_prompt.prompt'
        )

        self.llm_query_repo.create_or_update_prompt.assert_called_once()
        call_args = self.llm_query_repo.create_or_update_prompt.call_args[0]
        prompt_object = call_args[0]

        assert isinstance(prompt_object, Prompt)
        assert prompt_object.name == 'new_prompt'
        assert prompt_object.company_id == self.mock_company.id
        assert prompt_object.prompt_type == PromptType.COMPANY.value
        assert 'new_prompt.prompt' in prompt_object.filename
        assert prompt_object.custom_fields == [{'data_key': 'key', 'label': ' a label', 'type': 'text'}]

    def test_create_prompt_when_invalid_custom_fields(self):
        self.mock_asset_repo.exists.return_value = True
        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.create_prompt(
                prompt_name='new_prompt',
                description='A new prompt',
                order=1,
                company=self.mock_company,
                custom_fields=[{'label': ' a label'}]
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER

    def test_get_prompt_content_file_not_found_in_repo(self):
        """Prueba que maneja FileNotFoundError del repositorio."""
        mock_prompt = Prompt(filename='missing.prompt')
        self.llm_query_repo.get_prompt_by_name.return_value = mock_prompt

        # Simular error del repo
        self.mock_asset_repo.read_text.side_effect = FileNotFoundError("File not found")

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_prompt_content(self.mock_company, 'missing_prompt')

        assert exc_info.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR

    def test_create_prompt_handles_db_exception(self):
        """Prueba que se maneja una excepción de la base de datos al guardar."""
        self.llm_query_repo.create_or_update_prompt.side_effect = Exception("DB Unique Constraint Failed")
        self.mock_asset_repo.exists.return_value = True

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.create_prompt(
                prompt_name='any_prompt',
                description='Desc',
                order=1,
                company=self.mock_company
            )
        assert exc_info.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR

        # --- Tests para save_prompt (Nuevo método orquestador) ---

        @patch('iatoolkit.services.prompt_service.PromptService._sync_to_configuration')
        def test_save_prompt_success_update_existing(self, mock_sync_config):
            """
            Prueba save_prompt cuando el prompt ya existe en la BD.
            Verifica escritura de archivo, actualización de BD y llamada a sync de config.
            """
            # Arrange
            prompt_name = "sales_agent"
            input_data = {
                'content': 'You are a sales expert...',
                'description': 'New description',
                'custom_fields': [{'data_key': 'k', 'label': 'l'}],
                'active': False,
                'category': 'Sales',
                'order': 2
            }

            self.profile_repo.get_company_by_short_name.return_value = self.mock_company

            # Simular que el prompt ya existe en BD
            mock_existing_prompt = MagicMock(spec=Prompt)
            mock_existing_prompt.filename = "sales_agent.prompt"
            self.llm_query_repo.get_prompt_by_name.return_value = mock_existing_prompt

            # Act
            self.prompt_service.save_prompt('test_co', prompt_name, input_data)

            # Assert
            # 1. Verificar escritura del archivo físico
            self.mock_asset_repo.write_text.assert_called_once_with(
                'test_co', AssetType.PROMPT, 'sales_agent.prompt', 'You are a sales expert...'
            )

            # 2. Verificar actualización del objeto DB
            assert mock_existing_prompt.description == 'New description'
            assert mock_existing_prompt.custom_fields == [{'data_key': 'k', 'label': 'l'}]
            assert mock_existing_prompt.active is False
            self.llm_query_repo.create_or_update_prompt.assert_called_once_with(mock_existing_prompt)

            # 3. Verificar llamada a la sincronización de configuración
            mock_sync_config.assert_called_once()
            args, _ = mock_sync_config.call_args
            assert args[0] == 'test_co'
            assert args[1]['name'] == prompt_name
            assert args[1]['description'] == 'New description'

        @patch('iatoolkit.services.prompt_service.PromptService._sync_to_configuration')
        def test_save_prompt_success_create_new(self, mock_sync_config):
            """
            Prueba save_prompt cuando el prompt NO existe en BD (caso nuevo).
            Verifica que no falla y delega la creación a sync_config.
            """
            # Arrange
            prompt_name = "new_prompt"
            input_data = {'content': 'Hi', 'category': 'General'}

            self.profile_repo.get_company_by_short_name.return_value = self.mock_company
            self.llm_query_repo.get_prompt_by_name.return_value = None  # No existe en BD

            # Act
            self.prompt_service.save_prompt('test_co', prompt_name, input_data)

            # Assert
            # Archivo escrito
            self.mock_asset_repo.write_text.assert_called_once()

            # DB update no llamado directamente porque no tenemos el objeto,
            # confiamos en que _sync_to_configuration -> ConfigurationService maneje el ciclo.
            self.llm_query_repo.create_or_update_prompt.assert_not_called()

            # Sync llamado
            mock_sync_config.assert_called_once()

        def test_save_prompt_company_not_found(self):
            """Prueba que save_prompt lanza excepción si la compañía no existe."""
            self.profile_repo.get_company_by_short_name.return_value = None

            with pytest.raises(IAToolkitException) as exc:
                self.prompt_service.save_prompt('unknown', 'p', {})

            assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_NAME

        # --- Tests para _sync_to_configuration (Lazy Import Logic) ---

        @patch('iatoolkit.services.configuration_service.ConfigurationService')
        @patch('iatoolkit.current_iatoolkit')
        def test_sync_to_configuration_add_new(self, mock_current_toolkit, MockConfigService):
            """
            Prueba que _sync_to_configuration llama a add_configuration_key cuando el prompt es nuevo.
            """
            # Setup del Mock de inyección de dependencias
            mock_config_instance = MockConfigService.return_value
            mock_current_toolkit.return_value.get_injector.return_value.get.return_value = mock_config_instance

            # Simular configuración actual vacía
            mock_config_instance._load_and_merge_configs.return_value = {
                'prompts': {'prompt_list': [], 'prompt_categories': []}
            }

            prompt_data = {'name': 'my_new_prompt', 'description': 'desc'}

            # Act
            self.prompt_service._sync_to_configuration('test_co', prompt_data)

            # Assert
            # Debe llamar a add_configuration_key porque no encontró el nombre en la lista
            mock_config_instance.add_configuration_key.assert_called_once_with(
                'test_co', 'prompts.prompt_list', '0', prompt_data
            )
            mock_config_instance.update_configuration_key.assert_not_called()

        @patch('iatoolkit.services.configuration_service.ConfigurationService')
        @patch('iatoolkit.current_iatoolkit')
        def test_sync_to_configuration_update_existing(self, mock_current_toolkit, MockConfigService):
            """
            Prueba que _sync_to_configuration llama a update_configuration_key cuando el prompt ya existe.
            """
            # Setup
            mock_config_instance = MockConfigService.return_value
            mock_current_toolkit.return_value.get_injector.return_value.get.return_value = mock_config_instance

            # Simular configuración con un prompt existente
            existing_list = [{'name': 'other'}, {'name': 'target_prompt'}]
            mock_config_instance._load_and_merge_configs.return_value = {
                'prompts': {'prompt_list': existing_list}
            }

            prompt_data = {'name': 'target_prompt', 'description': 'updated desc'}

            # Act
            self.prompt_service._sync_to_configuration('test_co', prompt_data)

            # Assert
            # Debe llamar a update_configuration_key en el índice 1
            mock_config_instance.update_configuration_key.assert_called_once_with(
                'test_co', 'prompts.prompt_list.1', prompt_data
            )
            mock_config_instance.add_configuration_key.assert_not_called()