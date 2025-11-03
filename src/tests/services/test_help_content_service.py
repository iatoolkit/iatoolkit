# tests/services/test_help_content_service.py
import pytest
from unittest.mock import Mock, patch
from iatoolkit.services.help_content_service import HelpContentService
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.util import Utility

class TestHelpContentService:
    """
    Pruebas para el HelpContentService, que se encarga de cargar
    el contenido de ayuda desde archivos YAML.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Fixture que crea una instancia del servicio con una utilidad mockeada
        antes de cada test.
        """
        self.mock_util = Mock(spec=Utility)
        self.help_service = HelpContentService(util=self.mock_util)

    @patch('os.path.exists', return_value=True)
    def test_get_content_success(self, mock_exists):
        """
        Prueba el caso exitoso: el archivo de ayuda existe y se carga correctamente.
        """
        # Arrange
        company_short_name = "sample_company"
        expected_content = {
            'example_questions': [{'category': 'Ventas', 'questions': ['Pregunta 1']}]
        }
        self.mock_util.load_schema_from_yaml.return_value = expected_content
        expected_path = f'companies/{company_short_name}/help_content.yaml'

        # Act
        result = self.help_service.get_content(company_short_name)

        # Assert
        mock_exists.assert_called_once_with(expected_path)
        self.mock_util.load_schema_from_yaml.assert_called_once_with(expected_path)
        assert result == expected_content

    @patch('os.path.exists', return_value=False)
    def test_get_content_file_not_found(self, mock_exists):
        """
        Prueba que se retorna un diccionario vacío si el archivo YAML no existe.
        """
        # Arrange
        company_short_name = "no_file_company"
        expected_path = f'companies/{company_short_name}/help_content.yaml'

        # Act
        result = self.help_service.get_content(company_short_name)

        # Assert
        mock_exists.assert_called_once_with(expected_path)
        self.mock_util.load_schema_from_yaml.assert_not_called()
        assert result == {}

    @patch('os.path.exists', return_value=True)
    def test_get_content_loading_error(self, mock_exists):
        """
        Prueba que se lanza una IAToolkitException si ocurre un error
        al cargar o parsear el archivo YAML.
        """
        # Arrange
        company_short_name = "bad_yaml_company"
        error_message = "YAML parse error"
        self.mock_util.load_schema_from_yaml.side_effect = Exception(error_message)
        expected_path = f'companies/{company_short_name}/help_content.yaml'

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.help_service.get_content(company_short_name)

        mock_exists.assert_called_once_with(expected_path)
        self.mock_util.load_schema_from_yaml.assert_called_once_with(expected_path)
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR
        assert f"Error obteniendo help de {company_short_name}" in str(excinfo.value)
        assert error_message in str(excinfo.value)

    @patch('os.path.exists', return_value=False)
    def test_get_content_with_no_company_name(self, mock_exists):
        """
        Prueba que el servicio maneja correctamente el caso donde company_short_name es None.
        """
        # Arrange
        # El path se construirá como 'companies/None/help_content.yaml',
        # para el cual os.path.exists retornará False.

        # Act
        result = self.help_service.get_content(None)

        # Assert
        mock_exists.assert_called_once_with('companies/None/help_content.yaml')
        self.mock_util.load_schema_from_yaml.assert_not_called()
        assert result == {}