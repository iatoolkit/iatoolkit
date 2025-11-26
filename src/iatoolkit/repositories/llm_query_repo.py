# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import LLMQuery, Tool, Company, Prompt, PromptCategory
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from sqlalchemy import or_

class LLMQueryRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def add_query(self, query: LLMQuery):
        self.session.add(query)
        self.session.commit()
        return query


    def get_company_tools(self, company: Company) -> list[Tool]:
        return (
            self.session.query(Tool)
            .filter(
                Tool.is_active.is_(True),
                or_(
                    Tool.company_id == company.id,
                    Tool.system_function.is_(True)
                )
            )
            .all()
        )

    def delete_system_tools(self):
        self.session.query(Tool).filter_by(system_function=True).delete(synchronize_session=False)

    def create_or_update_tool(self, new_tool: Tool):
        tool = self.session.query(Tool).filter_by(company_id=new_tool.company_id,
                                                  name=new_tool.name).first()
        if tool:
            tool.description = new_tool.description
            tool.parameters = new_tool.parameters
            tool.system_function = new_tool.system_function
        else:
            self.session.add(new_tool)
            tool = new_tool

        self.session.flush()
        return tool

    def delete_tool(self, tool: Tool):
        self.session.query(Tool).filter_by(id=tool.id).delete(synchronize_session=False)

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
        else:
            self.session.add(new_prompt)
            prompt = new_prompt

        self.session.flush()
        return prompt

    def create_or_update_prompt_category(self, new_category: PromptCategory):
        category = self.session.query(PromptCategory).filter_by(company_id=new_category.company_id,
                                                      name=new_category.name).first()
        if category:
            category.order = new_category.order
        else:
            self.session.add(new_category)
            category = new_category

        self.session.flush()
        return category

    def get_history(self, company: Company, user_identifier: str) -> list[LLMQuery]:
        return self.session.query(LLMQuery).filter(
            LLMQuery.user_identifier == user_identifier,
        ).filter_by(company_id=company.id).order_by(LLMQuery.created_at.desc()).limit(100).all()

    def get_prompts(self, company: Company) -> list[Prompt]:
        return self.session.query(Prompt).filter_by(company_id=company.id, is_system_prompt=False).all()

    def get_prompt_by_name(self, company: Company, prompt_name: str):
        return self.session.query(Prompt).filter_by(company_id=company.id, name=prompt_name).first()

    def get_system_prompts(self) -> list[Prompt]:
        return self.session.query(Prompt).filter_by(is_system_prompt=True, active=True).order_by(Prompt.order).all()

