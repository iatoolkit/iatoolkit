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
            # Colores del contenedor del encabezado
            "header_background_color": "#FFFFFF",  # Fondo blanco por defecto
            "header_text_color": "#6C757D",  # Color de texto 'muted' de Bootstrap

            # Estilos para el texto primario (ej. nombre de la compañía)
            "primary_font_weight": "bold",
            "primary_font_size": "1rem",

            # Estilos para el texto secundario (ej. ID de usuario)
            "secondary_font_weight": "600",  # Semibold
            "secondary_font_size": "0.875rem"  # Equivale a la clase 'small' de Bootstrap

        }

    def get_company_branding(self, company: Company | None) -> dict:
        """
        Retorna los estilos de branding finales para una compañía,
        fusionando los valores por defecto con los personalizados.

        Args:
            company: El objeto Company, que puede contener un dict de branding.

        Returns:
            Un diccionario con todos los estilos de branding listos para usar en la plantilla.
        """
        # Empezamos con una copia de los valores por defecto
        final_branding_values = self._default_branding.copy()

        # Si la compañía existe y tiene branding personalizado, lo fusionamos.
        if company and company.branding:
            final_branding_values.update(company.branding)

        # Construimos las cadenas de estilo completas
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

        return {
            "name": company.name if company else "IAToolkit",
            "header_style": header_style,
            "header_text_color": final_branding_values['header_text_color'],
            "primary_text_style": primary_text_style,
            "secondary_text_style": secondary_text_style
        }