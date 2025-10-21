from flask.views import MethodView
from injector import inject
from iatoolkit.common.auth import IAuthentication
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.profile_service import ProfileService
from flask import jsonify, request, render_template
import logging


class InitContextView(MethodView):
    """
    Vista para forzar la limpieza y reconstrucción completa del contexto de un usuario.
    Es una operación síncrona y potencialmente lenta, accesible vía GET.
    """

    @inject
    def __init__(self, iauthentication: IAuthentication, query_service: QueryService, profile_service: ProfileService):
        self.iauthentication = iauthentication
        self.query_service = query_service
        self.profile_service = profile_service

    def get(self, company_short_name: str):
        external_user_id = request.args.get('external_user_id')
        local_user_id = None
        user_identifier = None

        if external_user_id:
            # --- Flujo para usuario externo (API o UI) ---
            user_identifier = external_user_id
            # CORRECCIÓN: Si NO es una llamada desde la webapp, entonces es una llamada de API pura y necesita autenticación.
            if request.args.get('source') != 'webapp':
                iaut = self.iauthentication.verify(company_short_name)
                if not iaut.get("success"):
                    return jsonify(iaut), 401
        else:
            # --- Flujo para usuario interno (botón en la UI) ---
            user_profile = self.profile_service.get_current_user_profile()
            local_user_id_from_session = user_profile.get('id')
            if local_user_id_from_session:
                local_user_id = local_user_id_from_session
                user_identifier = str(local_user_id)

        if not user_identifier:
            return jsonify({"error": "No se pudo identificar al usuario para la reconstrucción del contexto"}), 400

        try:
            # --- PROCESO DE RECONSTRUCCIÓN FORZADA ---
            self.query_service.session_context.clear_all_context(company_short_name, user_identifier)
            logging.info(f"Contexto para {company_short_name}/{user_identifier} ha sido limpiado.")

            self.query_service.prepare_context(
                company_short_name=company_short_name,
                external_user_id=external_user_id,
                local_user_id=local_user_id
            )

            self.query_service.finalize_context_rebuild(
                company_short_name=company_short_name,
                external_user_id=external_user_id,
                local_user_id=local_user_id
            )

            logging.info(f"Contexto para {company_short_name}/{user_identifier} reconstruido exitosamente.")

            if request.args.get('source') == 'webapp':
                return render_template('context_reloaded.html', message="El contexto ha sido recargado exitosamente.")
            else:
                return jsonify({'status': 'OK'}), 200

        except Exception as e:
            logging.exception(
                f"Error inesperado al forzar la reconstrucción del contexto para {company_short_name}/{user_identifier}: {e}")
            return jsonify({"error_message": str(e)}), 500