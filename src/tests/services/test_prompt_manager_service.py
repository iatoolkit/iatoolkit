import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.common.asset_storage import AssetRepository, AssetType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import Prompt, PromptCategory, Company
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

    def test_get_user_prompts_filters_inactive_and_groups_correctly(self):
        """Prueba que los prompts inactivos se filtran y que los activos se agrupan correctamente."""
        # Usamos instancias reales de los modelos en lugar de Mocks para los datos.
        category = PromptCategory(name='General', order=1)
        active_prompt = Prompt(name='active_prompt', description='Active', active=True, order=1, category=category)
        inactive_prompt = Prompt(name='inactive_prompt', description='Inactive', active=False, order=2,
                                 category=category)

        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_prompts.return_value = [active_prompt, inactive_prompt]

        result = self.prompt_service.get_user_prompts(company_short_name='test_company')

        # Verificar que solo hay una categoría en el resultado
        assert len(result['message']) == 1
        # Verificar que dentro de esa categoría, solo hay un prompt (el activo)
        assert len(result['message'][0]['prompts']) == 1
        # Verificar que el prompt es el correcto
        assert result['message'][0]['prompts'][0]['prompt'] == 'active_prompt'

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
        assert not prompt_object.is_system_prompt
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