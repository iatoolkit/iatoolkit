from flask.views import MethodView
from injector import inject
from iatoolkit.common.auth import IAuthentication
from iatoolkit.services.query_service import QueryService
from flask import jsonify
import logging

class InitContextView(MethodView):

    @inject
    def __init__(self,
                 iauthentication: IAuthentication,
                 query_service: QueryService
                 ):
        self.iauthentication = iauthentication
        self.query_service = query_service

    def get(self, company_short_name: str, external_user_id: str):
        # 1. get access credentials
        iaut = self.iauthentication.verify(company_short_name, external_user_id)
        if not iaut.get("success"):
            return jsonify(iaut), 401

        try:
            # initialize the context
            self.query_service.llm_init_context(
                company_short_name=company_short_name,
                external_user_id=external_user_id
            )

            return {'status': 'OK'}, 200
        except Exception as e:
            logging.exception(
                f"Error inesperado al inicializar el contexto durante el login para company {company_short_name}: {e}")
            return jsonify({"error_message": str(e)}), 500
