# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.i18n_service import I18nService



class HistoryService:
    @inject
    def __init__(self, llm_query_repo: LLMQueryRepo,
                 profile_repo: ProfileRepo,
                 i18n_service: I18nService):
        self.llm_query_repo = llm_query_repo
        self.profile_repo = profile_repo
        self.i18n_service = i18n_service

    def get_history(self,
                     company_short_name: str,
                     user_identifier: str) -> dict:
        try:
            company = self.profile_repo.get_company_by_short_name(company_short_name)
            if not company:
                return {"error": self.i18n_service.t('errors.company_not_found', company_short_name=company_short_name)}

            history = self.llm_query_repo.get_history(company, user_identifier)
            if not history:
                return {'message': 'empty history', 'history': []}

            history_list = [query.to_dict() for query in history]
            return {'message': 'history loaded ok', 'history': history_list}

        except Exception as e:
            return {'error': str(e)}