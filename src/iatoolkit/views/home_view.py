# iatoolkit/views/home_view.py
import logging
import os
from flask import render_template, abort, session, render_template_string
from flask.views import MethodView
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
import logging

class HomeView(MethodView):
    """
    Handles the rendering of the company-specific home page with a login widget.
    If the custom template is not found or fails, it renders an error page.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service

    def get(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)

        if not company:
            abort(404, description=f"La empresa '{company_short_name}' no fue encontrada.")

        branding_data = self.branding_service.get_company_branding(company)
        alert_message = session.pop('alert_message', None)
        alert_icon = session.pop('alert_icon', 'error')


        # 1. Construimos la ruta al archivo de plantilla específico de la empresa.
        company_template_path = os.path.join(os.getcwd(), f'companies/{company_short_name}/templates/home.html')

        # 2. Verificamos si el archivo de plantilla personalizado no existe.
        if not os.path.exists(company_template_path):
            return render_template(
                "error.html",
                company=company,
                company_short_name=company_short_name,
                branding=branding_data,
                message=f"La plantilla de la página de inicio para la empresa '{company_short_name}' no está configurada."
            ), 500

        # 3. Si el archivo existe, intentamos leerlo y renderizarlo.
        try:
            with open(company_template_path, 'r') as f:
                template_string = f.read()

            # Usamos render_template_string, que entiende el contexto de Flask.
            return render_template_string(
                template_string,
                company=company,
                company_short_name=company_short_name,
                branding=branding_data,
                alert_message=alert_message,
                alert_icon=alert_icon
            )
        except Exception as e:
            return render_template(
                "error.html",
                company=company,
                company_short_name=company_short_name,
                branding=branding_data,
                message="Ocurrió un error al procesar la plantilla personalizada de la página de inicio."
            ), 500