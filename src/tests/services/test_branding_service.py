# tests/services/test_branding_service.py
import pytest
from unittest.mock import Mock, call
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.services.configuration_service import ConfigurationService


class TestBrandingService:

    @pytest.fixture(autouse=True)
    def setup(self):
        """
        Fixture de Pytest que se ejecuta automáticamente para cada método de test.
        Crea una instancia del servicio y configura un mock base para ConfigurationService.
        """
        self.configuration_service = Mock(spec=ConfigurationService)
        self.branding_service = BrandingService(self.configuration_service)
        self.default_branding = self.branding_service._default_branding
        self.mock_company_name = "Mock Default Name"

    def test_get_branding_with_no_custom_branding(self):
        """
        Prueba que se usen los estilos por defecto cuando la compañía no tiene branding personalizado.
        """
        # Arrange
        def side_effect_for_no_branding(company_short_name, content_key):
            if content_key == 'branding':
                return {}  # Simula que el config no tiene branding personalizado
            if content_key == 'name':
                return "Test Corp"
            return None
        self.configuration_service.get_company_content.side_effect = side_effect_for_no_branding

        # Act
        branding = self.branding_service.get_company_branding("test-corp")

        # Assert
        assert branding['name'] == "Test Corp"
        # Verificamos que el valor por defecto se usó para construir la variable CSS.
        expected_css_var = f"--brand-header-bg: {self.default_branding['header_background_color']};"
        assert expected_css_var in branding['css_variables']
        # Verificar las llamadas al mock.
        expected_calls = [call("test-corp", 'branding'), call("test-corp", 'name')]
        self.configuration_service.get_company_content.assert_has_calls(expected_calls, any_order=True)

    def test_get_branding_with_partial_custom_branding(self):
        """
        Prueba que los estilos personalizados se fusionen correctamente con los por defecto.
        """
        # Arrange
        custom_styles = {
            "header_background_color": "#123456",
        }
        def side_effect_for_partial_branding(company_short_name, content_key):
            if content_key == 'branding':
                return custom_styles
            if content_key == 'name':
                return "Partial Brand Inc."
            return None
        self.configuration_service.get_company_content.side_effect = side_effect_for_partial_branding

        # Act
        branding = self.branding_service.get_company_branding("partial-brand-inc")

        # Assert
        assert branding['name'] == "Partial Brand Inc."
        # Valida que el estilo personalizado se usó en la variable CSS.
        assert "--brand-header-bg: #123456;" in branding['css_variables']
        # Valida que una variable CSS de un estilo por defecto que no fue sobreescrito todavía existe.
        expected_default_var = f"--brand-header-text: {self.default_branding['header_text_color']};"
        assert expected_default_var in branding['css_variables']

    def test_get_branding_with_full_custom_branding(self):
        """
        Prueba que un conjunto completo de estilos personalizados sobreescriba correctamente los valores por defecto.
        """
        # Arrange
        full_custom_styles = {
            "header_background_color": "#000000",
            "header_text_color": "#FFFFFF",
            "primary_font_weight": "300",
            "primary_font_size": "1.2rem"
        }
        def side_effect_for_full_branding(company_short_name, content_key):
            if content_key == 'branding':
                return full_custom_styles
            if content_key == 'name':
                return "Full Brand LLC"
            return None
        self.configuration_service.get_company_content.side_effect = side_effect_for_full_branding

        # Act
        branding = self.branding_service.get_company_branding("full-brand-llc")

        # Assert
        assert branding['name'] == "Full Brand LLC"

        # Validar que la cadena del estilo de texto primario se construyó correctamente con los valores personalizados.
        expected_primary_style = "font-weight: 300; font-size: 1.2rem;"
        assert branding['primary_text_style'] == expected_primary_style

        # Validar que la variable CSS personalizada se inyectó correctamente.
        assert "--brand-header-bg: #000000;" in branding['css_variables']

        # Validar que una variable CSS de un valor por defecto que no estaba en el conjunto personalizado sigue presente.
        expected_default_var = f"--brand-secondary-color: {self.default_branding['brand_secondary_color']};"
        assert expected_default_var in branding['css_variables']