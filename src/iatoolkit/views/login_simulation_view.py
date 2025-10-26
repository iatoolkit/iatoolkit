# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask.views import MethodView
from flask import render_template, request
from injector import inject
from iatoolkit.services.profile_service import ProfileService
import os


class LoginSimulationView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService):
        self.profile_service = profile_service

    def get(self, company_short_name: str = None):

        # Esta API_KEY para el login
        api_key_for_login = os.getenv("IATOOLKIT_API_KEY", "tu_api_key_por_defecto_o_error")

        return render_template('login_simulation.html',
                               company_short_name=company_short_name,
                               api_key=api_key_for_login
                               )
