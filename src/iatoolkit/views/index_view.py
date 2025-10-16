# iatoolkit/views/index_view.py

from flask import render_template, abort, session
from flask.views import MethodView
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService


class IndexView(MethodView):
    """
    Handles the rendering of the company-specific landing page.
    """

    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service

    def get(self, company_short_name: str):
        # La vista ahora recibe el company_short_name desde la URL
        company = self.profile_service.get_company_by_short_name(company_short_name)

        if not company:
            abort(404, description=f"La empresa '{company_short_name}' no fue encontrada.")

        # Obtenemos los datos de branding para la plantilla
        branding_data = self.branding_service.get_company_branding(company)

        alert_message = session.pop('alert_message', None)
        alert_icon = session.pop('alert_icon', 'error')

        # 2. Pasamos las variables a la plantilla. Si no hay mensaje, serán None.
        return render_template(
            'index.html',
            company=company,
            company_short_name=company_short_name,
            branding=branding_data,
            alert_message=alert_message,
            alert_icon=alert_icon
        )