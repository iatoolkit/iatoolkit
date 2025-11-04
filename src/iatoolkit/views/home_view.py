# iatoolkit/views/home_view.py
from flask import render_template, session, render_template_string
from flask.views import MethodView
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService
from iatoolkit.common.util import Utility

class HomeView(MethodView):
    """
    Handles the rendering of the company-specific home page with a login widget.
    If the custom template is not found or fails, it renders an error page.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService,
                 utility: Utility):
        self.profile_service = profile_service
        self.branding_service = branding_service
        self.util = utility

    def get(self, company_short_name: str):
        company = self.profile_service.get_company_by_short_name(company_short_name)

        if not company:
            return render_template('error.html', message="Empresa no encontrada"), 404

        branding_data = self.branding_service.get_company_branding(company)
        alert_message = session.pop('alert_message', None)
        alert_icon = session.pop('alert_icon', 'error')

        home_template = self.util.get_company_template(company_short_name, "home.html")

        # 2. Verificamos si el archivo de plantilla personalizado no existe.
        if not home_template:
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=f"La plantilla de la página de inicio para la empresa '{company_short_name}' no está configurada."
            ), 500

        # 3. Si el archivo existe, intentamos leerlo y renderizarlo.
        try:
            return render_template_string(
                home_template,
                company=company,
                company_short_name=company_short_name,
                branding=branding_data,
                alert_message=alert_message,
                alert_icon=alert_icon
            )
        except Exception as e:
            return render_template(
                "error.html",
                company_short_name=company_short_name,
                branding=branding_data,
                message=f"Ocurrió un error al procesar la plantilla personalizada de la página de inicio: {str(e)}"
            ), 500