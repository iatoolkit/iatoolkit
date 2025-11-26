# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import LLMQuery, Function, Company, Prompt, PromptCategory
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from sqlalchemy import or_

class LLMQueryRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def add_query(self, query: LLMQuery):
        self.session.add(query)
        self.session.commit()
        return query

    def get_company_functions(self, company: Company) -> list[Function]:
        return (
            self.session.query(Function)
            .filter(
                Function.is_active.is_(True),
                or_(
                    Function.company_id == company.id,
                    Function.system_function.is_(True)
                )
            )
            .all()
        )

    def create_function(self, new_function: Function):
        # create a new function(tool) associated to a company
        self.session.add(new_function)
        return new_function

    def delete_all_functions(self, company: Company):
        # delete all rows from a company's Function table
        # commit is handled by the caller
        self.session.query(Function).filter_by(company_id=company.id).delete(synchronize_session=False)

    def create_prompt(self, new_prompt: Prompt):
        self.session.add(new_prompt)
        return new_prompt

    def create_prompt_category(self, new_category: PromptCategory):
        self.session.add(new_category)
        return new_category

    def delete_all_prompts(self, company: Company):
        # delete all rows from a company's prompt and prompt_category table
        # commit is handled by the caller
        self.session.query(Prompt).filter_by(company_id=company.id).delete(synchronize_session=False)
        self.session.query(PromptCategory).filter_by(company_id=company.id).delete(synchronize_session=False)

    def get_history(self, company: Company, user_identifier: str) -> list[LLMQuery]:
        return self.session.query(LLMQuery).filter(
            LLMQuery.user_identifier == user_identifier,
        ).filter_by(company_id=company.id).order_by(LLMQuery.created_at.desc()).limit(100).all()

    def get_prompts(self, company: Company) -> list[Prompt]:
        return self.session.query(Prompt).filter_by(company_id=company.id, is_system_prompt=False).all()

    def get_system_prompts(self) -> list[Prompt]:
        return self.session.query(Prompt).filter_by(is_system_prompt=True, active=True).order_by(Prompt.order).all()

    def get_prompt_by_name(self, company: Company, prompt_name: str):
        return self.session.query(Prompt).filter_by(company_id=company.id, name=prompt_name).first()
