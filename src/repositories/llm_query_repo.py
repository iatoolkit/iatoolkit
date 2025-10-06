# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from repositories.models import LLMQuery, Function, Company, Prompt, PromptCategory
from injector import inject
from repositories.database_manager import DatabaseManager
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

    def create_or_update_function(self, new_function: Function):
        function = self.session.query(Function).filter_by(company_id=new_function.company_id,
                                                 name=new_function.name).first()
        if function:
            function.description = new_function.description
            function.parameters = new_function.parameters
            function.system_function = new_function.system_function
        else:
            self.session.add(new_function)
            function = new_function

        self.session.commit()
        return function

    def create_or_update_prompt(self, new_prompt: Prompt):
        prompt = self.session.query(Prompt).filter_by(company_id=new_prompt.company_id,
                                                 name=new_prompt.name).first()
        if prompt:
            prompt.category_id = new_prompt.category_id
            prompt.description = new_prompt.description
            prompt.order = new_prompt.order
            prompt.active = new_prompt.active
            prompt.is_system_prompt = new_prompt.is_system_prompt
            prompt.filename = new_prompt.filename
            prompt.custom_fields = new_prompt.custom_fields
            prompt.parameters = new_prompt.parameters
        else:
            self.session.add(new_prompt)
            prompt = new_prompt

        self.session.commit()
        return prompt

    def create_or_update_prompt_category(self, new_category: PromptCategory):
        category = self.session.query(PromptCategory).filter_by(company_id=new_category.company_id,
                                                      name=new_category.name).first()
        if category:
            category.order = new_category.order
        else:
            self.session.add(new_category)
            category = new_category

        self.session.commit()
        return category

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
