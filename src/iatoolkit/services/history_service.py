# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo

from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.common.util import Utility


class HistoryService:
    @inject
    def __init__(self, llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 util: Utility):
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.util = util

    def get_history(self,
                     company_short_name: str,
                     external_user_id: str = None,
                     local_user_id: int = 0) -> dict:
        try:
            user_identifier, _ = self.util.resolve_user_identifier(external_user_id, local_user_id)
            if not user_identifier:
                return {'error': "No se pudo resolver el identificador del usuario"}

            # validate company
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {'error': f'No existe la empresa: {company_short_name}'}

            history = self.llm_query_repo.get_history(company, user_identifier)

            if not history:
                return {'message': 'Historial vacio actualmente', 'history': []}

            history_list = [query.to_dict() for query in history]

            return {'message': 'Historial obtenido correctamente', 'history': history_list}

        except Exception as e:
            return {'error': str(e)}