import pytest
from unittest.mock import MagicMock, patch
from iatoolkit.services.prompt_service import PromptService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.models import (Prompt, PromptCategory,
                                           Company)
from iatoolkit.common.exceptions import IAToolkitException


class TestPromptService:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Configura mocks y la instancia del servicio para cada test."""
        self.llm_query_repo = MagicMock(spec=LLMQueryRepo)
        self.llm_query_repo.session = MagicMock()

        self.profile_repo = MagicMock(spec=ProfileRepo)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_asset_repo = MagicMock(spec=AssetRepository)
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_configuration_service = MagicMock(spec=ConfigurationService)
        self.mock_configuration_service.get_configuration.return_value = {}

        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        self.prompt_service = PromptService(
            llm_query_repo=self.llm_query_repo,
            profile_repo=self.profile_repo,
            i18n_service=self.mock_i18n_service,
            asset_repo=self.mock_asset_repo,
            sql_service=self.mock_sql_service,
            configuration_service=self.mock_configuration_service,
        )
        self.mock_company = MagicMock(spec=Company)
        self.mock_company.id = 1
        self.mock_company.name = 'Test Company'
        self.mock_company.short_name = 'test_co'

    def test_get_prompts_company_not_found(self):
        """Prueba que se devuelve un error cuando la empresa no existe."""
        self.profile_repo.get_company_by_short_name.return_value = None
        result = self.prompt_service.get_prompts(company_short_name='nonexistent_company')
        assert result == {'error': 'translated:errors.company_not_found'}

    def test_get_prompts_no_prompts_exist(self):
        """Prueba que se devuelve una lista vacía cuando la empresa no tiene prompts."""
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_prompts.return_value = []
        result = self.prompt_service.get_prompts(company_short_name='test_company')
        assert result == {'message': []}

    # --- Tests para get_system_prompt ---

    @patch('iatoolkit.services.prompt_service.build_system_prompt_payload')
    def test_get_system_prompt_success(self, mock_build_payload):
        """Prueba la obtención exitosa de los prompts de sistema concatenados."""
        self.mock_sql_service.get_db_names.return_value = ["main_db"]
        mock_build_payload.return_value = {
            "content": "Contenido 1\nContenido 2",
            "selected_keys": ["query_main", "sql_rules"],
        }

        result = self.prompt_service.get_system_prompt(company_id=1, company_short_name="test_co")

        assert result == "Contenido 1\nContenido 2"
        mock_build_payload.assert_called_once_with({"has_sql_sources"}, query_text=None)

    @patch('iatoolkit.services.prompt_service.build_system_prompt_payload')
    def test_get_system_prompt_payload_resolves_company_short_name_from_id(self, mock_build_payload):
        self.mock_company.short_name = "resolved_short_name"
        self.profile_repo.get_company_by_id.return_value = self.mock_company
        self.mock_sql_service.get_db_names.return_value = []
        mock_build_payload.return_value = {"content": "Contenido base", "selected_keys": ["query_main"]}

        payload = self.prompt_service.get_system_prompt_payload(company_id=1)

        assert payload == {"content": "Contenido base", "selected_keys": ["query_main"]}
        self.profile_repo.get_company_by_id.assert_called_once_with(1)
        mock_build_payload.assert_called_once_with(set(), query_text=None)

    @patch('iatoolkit.services.prompt_service.build_system_prompt_payload')
    def test_get_system_prompt_payload_forwards_query_text(self, mock_build_payload):
        self.mock_sql_service.get_db_names.return_value = []
        mock_build_payload.return_value = {"content": "Contenido base", "selected_keys": ["query_main"]}

        payload = self.prompt_service.get_system_prompt_payload(
            company_id=1,
            company_short_name="test_co",
            query_text="dame una tabla html",
        )

        assert payload == {"content": "Contenido base", "selected_keys": ["query_main"]}
        mock_build_payload.assert_called_once_with(set(), query_text="dame una tabla html")

    def test_get_system_prompt_payload_raises_when_company_does_not_exist(self):
        self.profile_repo.get_company_by_id.return_value = None

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_system_prompt_payload(company_id=999)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND

    @patch('iatoolkit.services.prompt_service.build_system_prompt_payload')
    def test_get_system_prompt_handles_catalog_exception(self, mock_build_payload):
        self.mock_sql_service.get_db_names.return_value = []
        mock_build_payload.side_effect = Exception("catalog error")

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_system_prompt(company_id=1, company_short_name="test_co")

        assert exc_info.value.error_type == IAToolkitException.ErrorType.PROMPT_ERROR
        assert "catalog error" in str(exc_info.value)

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


    def test_get_prompt_content_file_not_found_in_repo(self):
        """Prueba que maneja FileNotFoundError del repositorio."""
        mock_prompt = Prompt(filename='missing.prompt')
        self.llm_query_repo.get_prompt_by_name.return_value = mock_prompt

        # Simular error del repo
        self.mock_asset_repo.read_text.side_effect = FileNotFoundError("File not found")

        with pytest.raises(IAToolkitException) as exc_info:
            self.prompt_service.get_prompt_content(self.mock_company, 'missing_prompt')

        assert exc_info.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR

    # --- Tests para save_prompt ---

    def test_save_prompt_success(self):
        """
        Prueba save_prompt.
        Verifica escritura de archivo y actualización de BD.
        Ya no verifica sincronización con configuración.
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
        # Simular lookup de categoría
        mock_category = MagicMock(spec=PromptCategory)
        mock_category.id = 10
        self.llm_query_repo.get_category_by_name.return_value = mock_category

        # Act
        self.prompt_service.save_prompt('test_co', prompt_name, input_data)

        # Assert
        # 1. Verificar escritura del archivo físico
        self.mock_asset_repo.write_text.assert_called_once_with(
            'test_co', AssetType.PROMPT, 'sales_agent.prompt', 'You are a sales expert...'
        )

        # 2. Verificar llamada a creación/actualización en BD
        # save_prompt crea una instancia de Prompt y llama a create_or_update_prompt
        self.llm_query_repo.create_or_update_prompt.assert_called_once()
        saved_prompt = self.llm_query_repo.create_or_update_prompt.call_args[0][0]
        assert isinstance(saved_prompt, Prompt)
        assert saved_prompt.name == prompt_name
        assert saved_prompt.description == 'New description'
        assert saved_prompt.category_id == 10
        assert saved_prompt.active is False

    def test_save_prompt_company_not_found(self):
        """Prueba que save_prompt lanza excepción si la compañía no existe."""
        self.profile_repo.get_company_by_short_name.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.prompt_service.save_prompt('unknown', 'p', {})

        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_NAME

    def test_save_prompt_invalid_prompt_type_falls_back_to_company(self):
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_category_by_name.return_value = None

        self.prompt_service.save_prompt(
            'test_co',
            'my_prompt',
            {
                'content': 'Prompt text',
                'prompt_type': 'system',
            }
        )

        saved_prompt = self.llm_query_repo.create_or_update_prompt.call_args[0][0]
        assert saved_prompt.prompt_type == 'company'

    def test_save_prompt_persists_structured_output_schema_yaml_and_json(self):
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_category_by_name.return_value = None

        self.prompt_service.save_prompt(
            'test_co',
            'structured_prompt',
            {
                'content': 'Prompt text',
                'output_schema_yaml': """
type: object
required:
  - customer_id
properties:
  customer_id:
    type: string
  score:
    type: number
                """,
                'output_schema_mode': 'strict',
                'output_response_mode': 'structured_only',
                'attachment_mode': 'native_only',
                'attachment_parser_provider': 'legacy',
                'attachment_fallback': 'fail',
            },
        )

        saved_prompt = self.llm_query_repo.create_or_update_prompt.call_args[0][0]
        assert saved_prompt.output_schema is not None
        assert saved_prompt.output_schema.get("type") == "object"
        assert "customer_id" in (saved_prompt.output_schema.get("properties") or {})
        assert isinstance(saved_prompt.output_schema_yaml, str)
        assert "customer_id" in saved_prompt.output_schema_yaml
        assert saved_prompt.output_schema_mode == "strict"
        assert saved_prompt.output_response_mode == "structured_only"
        assert saved_prompt.attachment_mode == "native_only"
        assert saved_prompt.attachment_parser_provider == "legacy"
        assert saved_prompt.attachment_fallback == "fail"

    def test_save_prompt_uses_company_default_attachment_policy_when_not_provided(self):
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_category_by_name.return_value = None
        self.mock_configuration_service.get_configuration.return_value = {
            "default_attachment_mode": "native_only",
            "default_attachment_fallback": "fail",
        }

        self.prompt_service.save_prompt(
            "test_co",
            "default_attachment_prompt",
            {
                "content": "Prompt text",
            },
        )

        saved_prompt = self.llm_query_repo.create_or_update_prompt.call_args[0][0]
        assert saved_prompt.attachment_mode == "native_only"
        assert saved_prompt.attachment_parser_provider == "auto"
        assert saved_prompt.attachment_fallback == "fail"

    # --- Tests para sync_company_prompts ---

    @patch('iatoolkit.services.prompt_service.current_iatoolkit')
    def test_sync_company_prompts_enterprise_mode(self, mock_current_toolkit):
        """
        Prueba que si NO es community (Enterprise), sync_company_prompts retorna
        después de registrar prompts de sistema, sin sincronizar prompts de compañía desde YAML.
        """
        # Arrange
        # Simular Enterprise (is_community = False)
        mock_current_toolkit.return_value.is_community = False

        self.profile_repo.get_company_by_short_name.return_value = self.mock_company

        # Act
        self.prompt_service.sync_company_prompts('test_co', [], [])

        # No debería intentar buscar categorías ni hacer nada más con los repos
        self.llm_query_repo.create_or_update_prompt_category.assert_not_called()
        self.llm_query_repo.create_or_update_prompt.assert_not_called()


    @patch('iatoolkit.services.prompt_service.current_iatoolkit')
    def test_sync_company_prompts_community_mode(self, mock_current_toolkit):
        """
        Prueba que si ES community, realiza la sincronización completa.
        """
        # Arrange
        mock_current_toolkit.return_value.is_community = True
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company

        categories_config = ['Sales']
        prompt_list = [{'name': 'p1', 'category': 'Sales', 'description': 'd1'}]

        # Mock category persistence
        mock_cat = MagicMock()
        mock_cat.id = 100
        self.llm_query_repo.create_or_update_prompt_category.return_value = mock_cat

        # Mock existing prompts for cleanup
        self.llm_query_repo.get_prompts.return_value = []

        # Act
        self.prompt_service.sync_company_prompts('test_co', prompt_list, categories_config)

        # Se crean categorías
        self.llm_query_repo.create_or_update_prompt_category.assert_called()
        # Se crean prompts
        self.llm_query_repo.create_or_update_prompt.assert_called()

    # --- Tests para sync_prompt_categories ---

    def test_sync_prompt_categories_success(self):
        """
        Prueba la sincronización de categorías:
        1. Crea/Actualiza las que están en la lista.
        2. Elimina las que existen en BD pero no en la lista.
        """
        # Arrange
        categories_config = ['Cat A', 'Cat B']
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company

        # Mockear las categorías existentes en BD: Cat A y Cat Old (Cat Old debería borrarse)
        cat_a_mock = MagicMock(spec=PromptCategory, id=1, name='Cat A')
        cat_old_mock = MagicMock(spec=PromptCategory, id=99, name='Cat Old')
        self.llm_query_repo.get_all_categories.return_value = [cat_a_mock, cat_old_mock]

        # Simular que create_or_update devuelve un objeto con ID para simular persistencia
        def side_effect_create_cat(cat_obj):
            cat_obj.id = 1 if cat_obj.name == 'Cat A' else 2 # ID 1 existe, ID 2 nuevo
            return cat_obj
        self.llm_query_repo.create_or_update_prompt_category.side_effect = side_effect_create_cat

        # Act
        self.prompt_service.sync_prompt_categories('test_co', categories_config)

        # Assert
        # 1. Verificar llamadas de creación/actualización (deben ser 2: Cat A y Cat B)
        assert self.llm_query_repo.create_or_update_prompt_category.call_count == 2
        calls = self.llm_query_repo.create_or_update_prompt_category.call_args_list
        assert calls[0][0][0].name == 'Cat A'
        assert calls[1][0][0].name == 'Cat B'

        # 2. Verificar eliminación (debe borrar Cat Old porque su ID (99) no estaba en los procesados)
        # IDs procesados: 1 (Cat A) y 2 (Cat B). ID existente: 99.
        self.llm_query_repo.session.delete.assert_called_once_with(cat_old_mock)

        # 3. Commit
        self.llm_query_repo.commit.assert_called_once()

    def test_sync_prompt_categories_db_error(self):
        """Prueba manejo de excepciones y rollback en sync_prompt_categories."""
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.create_or_update_prompt_category.side_effect = Exception("DB Error")

        with pytest.raises(IAToolkitException) as exc:
            self.prompt_service.sync_prompt_categories('test_co', ['C1'])

        assert exc.value.error_type == IAToolkitException.ErrorType.DATABASE_ERROR
        self.llm_query_repo.rollback.assert_called_once()

    # --- Tests para delete_prompt ---

    def test_delete_prompt_success(self):
        """Prueba borrado exitoso de un prompt."""
        # Arrange
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        mock_prompt = MagicMock(spec=Prompt)
        self.llm_query_repo.get_prompt_by_name.return_value = mock_prompt

        # Act
        self.prompt_service.delete_prompt('test_co', 'myprompt')

        # Assert
        self.llm_query_repo.delete_prompt.assert_called_once_with(mock_prompt)

    def test_delete_prompt_not_found(self):
        """Prueba error DocumentNotFound si el prompt no existe."""
        self.profile_repo.get_company_by_short_name.return_value = self.mock_company
        self.llm_query_repo.get_prompt_by_name.return_value = None

        with pytest.raises(IAToolkitException) as exc:
            self.prompt_service.delete_prompt('test_co', 'missing_prompt')

        assert exc.value.error_type == IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND
