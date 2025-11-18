# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import requests
import json
import os
from flask.views import MethodView
from flask import render_template, request, Response
from injector import inject
from iatoolkit.services.profile_service import ProfileService
from iatoolkit.services.branding_service import BrandingService


class LoginSimulationView(MethodView):
    @inject
    def __init__(self,
                 profile_service: ProfileService,
                 branding_service: BrandingService):
        self.profile_service = profile_service
        self.branding_service = branding_service


    def get(self, company_short_name: str = None):
        company = self.profile_service.get_company_by_short_name(company_short_name)
        if not company:
            return render_template('error.html',
                                   company_short_name=company_short_name,
                                   message="Empresa no encontrada"), 404

        branding_data = self.branding_service.get_company_branding(company_short_name)

        return render_template('login_simulation.html',
                               branding=branding_data,
                               company_short_name=company_short_name
                               )

    def post(self, company_short_name: str):
        """
        Recibe el POST del formulario y actúa como un proxy servidor-a-servidor.
        Llama al endpoint 'external_login' y devuelve su respuesta (HTML y headers).
        """
        api_key = os.getenv("IATOOLKIT_API_KEY")
        if not api_key:
            return Response("Error: Es necesaria la variable de ambiente 'IATOOLKIT_API_KEY'.", status=400)

        # Obtenemos la URL base de la petición actual para construir la URL interna
        base_url = request.host_url.rstrip('/')

        # 1. Obtener el user_identifier del formulario
        user_identifier = request.form.get('external_user_id')

        if not user_identifier:
            return Response("Error: El campo 'external_user_id' es requerido.", status=400)

        # 2. Preparar la llamada a la API real de external_login
        target_url = f"{base_url}/{company_short_name}/external_login"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        # El payload debe ser un diccionario que se convertirá a JSON
        payload = {'user_identifier': user_identifier}

        try:
            # 3. Llamada POST segura desde este servidor al endpoint de IAToolkit
            internal_response = requests.post(
                target_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=120,
                stream=True  # Usamos stream para manejar la respuesta eficientemente
            )
            internal_response.raise_for_status()

            # 4. Creamos una nueva Response de Flask para el navegador del usuario.
            user_response = Response(
                internal_response.iter_content(chunk_size=1024),
                status=internal_response.status_code
            )

            # 5. Copiamos TODAS las cabeceras de la respuesta interna a la respuesta final.
            # Esto es CRUCIAL para que las cookies ('Set-Cookie') lleguen al navegador.
            for key, value in internal_response.headers.items():
                # Excluimos cabeceras que no debemos pasar (controladas por el servidor WSGI)
                if key.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                    user_response.headers[key] = value

            return user_response

        except requests.exceptions.HTTPError as e:
            error_text = f"Error en la llamada interna a la API: {e.response.status_code}. Respuesta: {e.response.text}"
            return Response(error_text, status=e.response.status_code, mimetype='text/plain')
        except requests.exceptions.RequestException as e:
            return Response(f'Error de conexión con el servicio de IA: {str(e)}', status=502, mimetype='text/plain')
