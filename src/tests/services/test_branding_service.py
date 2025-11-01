# tests/services/test_branding_service.py
import pytest
from unittest.mock import Mock
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.repositories.models import Company


class TestBrandingService:

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Fixture de Pytest que se ejecuta automáticamente para cada método de test.
        Crea una instancia del servicio y almacena los valores por defecto para fácil acceso.
        """
        self.branding_service = BrandingService()
        self.default_styles = self.branding_service._default_branding

    def test_get_branding_with_no_company(self):
        """
        Prueba que se retornen los estilos por defecto y el nombre 'IAToolkit' cuando company es None.
        """
        # Act
        branding = self.branding_service.get_company_branding(None)

        assert branding['name'] == "IAToolkit"


    def test_get_branding_with_company_and_no_custom_branding(self):
        """
        Prueba que se retornen los estilos por defecto cuando la compañía no tiene branding personalizado.
        """
        # Arrange
        mock_company = Mock(spec=Company)
        mock_company.name = "Test Corp"
        mock_company.branding = {}

        # Act
        branding = self.branding_service.get_company_branding(mock_company)

        # Assert
        assert branding['name'] == "Test Corp"


    def test_get_branding_with_partial_custom_branding(self):
        """
        Prueba que los estilos personalizados se fusionen correctamente con los por defecto.
        """
        # Arrange
        custom_styles = {
            "header_background_color": "#123456",
            "company_name_font_size": "1.5rem"
        }
        mock_company = Mock(spec=Company)
        mock_company.name = "Partial Brand Inc."
        mock_company.branding = custom_styles

        # Act
        branding = self.branding_service.get_company_branding(mock_company)

        # Assert
        assert branding['name'] == "Partial Brand Inc."


    def test_get_branding_with_full_custom_branding(self):
        # Arrange: Definimos solo los estilos que queremos sobreescribir para este test.
        full_custom_styles = {
            "header_background_color": "#000000",
            "header_text_color": "#FFFFFF",
            "primary_font_weight": "300",
            "primary_font_size": "1.2rem"
        }

        mock_company = Mock(spec=Company)
        mock_company.name = "Full Brand LLC"
        mock_company.branding = full_custom_styles

        # Act
        branding = self.branding_service.get_company_branding(mock_company)

        # Assert
        # 1. Validar el nombre de la compañía
        assert branding['name'] == "Full Brand LLC"

        # 3. Validar que la cadena del estilo de texto primario se construyó correctamente
        expected_primary_style = "font-weight: 300; font-size: 1.2rem;"
        assert branding['primary_text_style'] == expected_primary_style
