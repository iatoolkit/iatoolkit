# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import Company


class BrandingService:
    """
    Servicio centralizado que gestiona la configuración de branding.
    """

    def __init__(self):
        """
        Define los estilos de branding por defecto para la aplicación.
        """
        self._default_branding = {
            # --- Estilos del Encabezado Principal ---
            "header_background_color": "#FFFFFF",
            "header_text_color": "#6C757D",
            "primary_font_weight": "bold",
            "primary_font_size": "1rem",
            "secondary_font_weight": "600",
            "secondary_font_size": "0.875rem",
            "tertiary_font_weight": "normal",
            "tertiary_font_size": "0.75rem",
            "tertiary_opacity": "0.8",

            # Estilos Globales de la Marca ---
            "brand_primary_color": "#0d6efd",  # Azul de Bootstrap por defecto
            "brand_secondary_color": "#6c757d",  # Gris de Bootstrap por defecto
            "brand_text_on_primary": "#FFFFFF",  # Texto blanco sobre color primario
            "brand_text_on_secondary": "#FFFFFF",  # Texto blanco sobre color secundario

            # Estilos para Alertas de Error ---
            "brand_danger_color": "#dc3545",  # Rojo principal para alertas
            "brand_danger_bg": "#f8d7da",  # Fondo rojo pálido
            "brand_danger_text": "#842029",  # Texto rojo oscuro
            "brand_danger_border": "#f5c2c7",  # Borde rojo intermedio

            # Estilos para Alertas Informativas ---
            "brand_info_bg": "#cff4fc",  # Fondo celeste pálido
            "brand_info_text": "#055160",  # Texto azul oscuro
            "brand_info_border": "#b6effb",

            # Estilos para el Asistente de Prompts ---
            "prompt_assistant_bg": "#f8f9fa",
            "prompt_assistant_border": "#dee2e6",
            "prompt_assistant_icon_color": "#6c757d",
            "prompt_assistant_button_bg": "#FFFFFF",
            "prompt_assistant_button_text": "#495057",
            "prompt_assistant_button_border": "#ced4da",
            "prompt_assistant_dropdown_bg": "#f8f9fa",
            "prompt_assistant_header_bg": "#e9ecef",
            "prompt_assistant_header_text": "#495057",
            "prompt_assistant_item_hover_bg": None,  # Usará el primario por defecto
            "prompt_assistant_item_hover_text": None,  # Usará el texto sobre primario

            # Color para el botón de Enviar ---
            "send_button_color": "#212529"  # Gris oscuro/casi negro por defecto
        }

    def get_company_branding(self, company: Company | None) -> dict:
        """
        Retorna los estilos de branding finales para una compañía,
        fusionando los valores por defecto con los personalizados.
        """
        final_branding_values = self._default_branding.copy()

        if company and company.branding:
            final_branding_values.update(company.branding)

        # Función para convertir HEX a RGB
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

        primary_rgb = hex_to_rgb(final_branding_values['brand_primary_color'])
        secondary_rgb = hex_to_rgb(final_branding_values['brand_secondary_color'])

        # --- CONSTRUCCIÓN DE ESTILOS Y VARIABLES CSS ---
        header_style = (
            f"background-color: {final_branding_values['header_background_color']}; "
            f"color: {final_branding_values['header_text_color']};"
        )
        primary_text_style = (
            f"font-weight: {final_branding_values['primary_font_weight']}; "
            f"font-size: {final_branding_values['primary_font_size']};"
        )
        secondary_text_style = (
            f"font-weight: {final_branding_values['secondary_font_weight']}; "
            f"font-size: {final_branding_values['secondary_font_size']};"
        )
        tertiary_text_style = (
            f"font-weight: {final_branding_values['tertiary_font_weight']}; "
            f"font-size: {final_branding_values['tertiary_font_size']}; "
            f"opacity: {final_branding_values['tertiary_opacity']};"
        )

        # Generamos el bloque de variables CSS
        css_variables = f"""
            :root {{
                --brand-primary-color: {final_branding_values['brand_primary_color']};
                --brand-secondary-color: {final_branding_values['brand_secondary_color']};
                --brand-primary-color-rgb: {', '.join(map(str, primary_rgb))};
                --brand-secondary-color-rgb: {', '.join(map(str, secondary_rgb))};
                --brand-text-on-primary: {final_branding_values['brand_text_on_primary']};
                --brand-text-on-secondary: {final_branding_values['brand_text_on_secondary']};
                --brand-modal-header-bg: {final_branding_values['header_background_color']};
                --brand-modal-header-text: {final_branding_values['header_text_color']};
                --brand-danger-color: {final_branding_values['brand_danger_color']};
                --brand-danger-bg: {final_branding_values['brand_danger_bg']};
                --brand-danger-text: {final_branding_values['brand_danger_text']};
                --brand-danger-border: {final_branding_values['brand_danger_border']};
                --brand-info-bg: {final_branding_values['brand_info_bg']};
                --brand-info-text: {final_branding_values['brand_info_text']};
                --brand-info-border: {final_branding_values['brand_info_border']};
                --brand-prompt-assistant-bg: {final_branding_values['prompt_assistant_bg']};
                --brand-prompt-assistant-border: {final_branding_values['prompt_assistant_border']};
                --brand-prompt-assistant-icon-color: {final_branding_values['prompt_assistant_icon_color']};
                --brand-prompt-assistant-button-bg: {final_branding_values['prompt_assistant_button_bg']};
                --brand-prompt-assistant-button-text: {final_branding_values['prompt_assistant_button_text']};
                --brand-prompt-assistant-button-border: {final_branding_values['prompt_assistant_button_border']};
                --brand-prompt-assistant-dropdown-bg: {final_branding_values['prompt_assistant_dropdown_bg']};
                --brand-prompt-assistant-header-bg: {final_branding_values['prompt_assistant_header_bg']};
                --brand-prompt-assistant-header-text: {final_branding_values['prompt_assistant_header_text']};
                --brand-prompt-assistant-item-hover-bg: {final_branding_values['prompt_assistant_item_hover_bg'] or final_branding_values['brand_primary_color']};
                --brand-prompt-assistant-item-hover-text: {final_branding_values['prompt_assistant_item_hover_text'] or final_branding_values['brand_text_on_primary']};

            }}
        """

        return {
            "name": company.name if company else "IAToolkit",
            "header_style": header_style,
            "primary_text_style": primary_text_style,
            "secondary_text_style": secondary_text_style,
            "tertiary_text_style": tertiary_text_style,
            "header_text_color": final_branding_values['header_text_color'],
            "css_variables": css_variables,
            "send_button_color": final_branding_values['send_button_color']
        }