# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.models import (LLMQuery, Tool,
                    Company, Prompt, PromptCategory, PromptType)
from injector import inject
from iatoolkit.repositories.database_manager import DatabaseManager
from sqlalchemy import or_, and_
from typing import List


class LLMQueryRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    # save new query result in the database
    def add_query(self, query: LLMQuery):
        self.session.add(query)
        self.session.commit()
        return query

    # get user query history
    def get_history(self, company: Company, user_identifier: str) -> list[LLMQuery]:
        return self.session.query(LLMQuery).filter(
            LLMQuery.user_identifier == user_identifier,
        ).filter_by(company_id=company.id).order_by(LLMQuery.created_at.desc()).limit(100).all()


    ## --- Tools related methods
    def get_company_tools(self, company: Company) -> list[Tool]:
        return (
            self.session.query(Tool)
            .filter(
                or_(
                    Tool.company_id == company.id,
                    and_(
                        Tool.company_id.is_(None),
                        Tool.tool_type == Tool.TYPE_SYSTEM
                    )
                )
            )
            # Ordenamos: Queremos SYSTEM primero.
            .order_by(Tool.tool_type.desc())
            .all()
        )

    def get_tool_definition(self, company: Company, tool_name: str) -> Tool | None:
        return self.session.query(Tool).filter_by(
            company_id=company.id,
            name=tool_name,
            is_active=True
        ).first()

    def get_system_tool(self, tool_name: str) -> Tool | None:
        return self.session.query(Tool).filter_by(
            tool_type=Tool.TYPE_SYSTEM,
            name=tool_name
        ).first()

    def get_tool_by_id(self, company_id: int, tool_id: int, include_system: bool = False) -> Tool | None:
        query = self.session.query(Tool).filter(Tool.id == tool_id)
        if include_system:
            query = query.filter(
                or_(
                    Tool.company_id == company_id,
                    and_(
                        Tool.company_id.is_(None),
                        Tool.tool_type == Tool.TYPE_SYSTEM
                    )
                )
            )
            return query.first()

        return query.filter(Tool.company_id == company_id).first()

    def add_tool(self, tool: Tool):
        """Adds a new tool to the session (without checking by name logic)."""
        self.session.add(tool)
        self.session.commit()
        return tool

    def delete_system_tools(self):
        self.session.query(Tool).filter_by(tool_type=Tool.TYPE_SYSTEM).delete(synchronize_session=False)
        self.session.commit()

    def create_or_update_tool(self, new_tool: Tool):
        # Usado principalmente por el proceso de Sync y Register System Tools
        if new_tool.tool_type == Tool.TYPE_SYSTEM:
            tool = self.session.query(Tool).filter_by(name=new_tool.name, tool_type=Tool.TYPE_SYSTEM).first()
        else:
            tool = self.session.query(Tool).filter_by(company_id=new_tool.company_id, name=new_tool.name).first()

        if tool:
            tool.name = new_tool.name
            tool.description = new_tool.description
            tool.parameters = new_tool.parameters
            tool.execution_config = new_tool.execution_config
            tool.tool_type = new_tool.tool_type
            tool.source = new_tool.source
        else:
            self.session.add(new_tool)
            tool = new_tool

        self.session.commit()
        return tool

    def delete_tool(self, tool: Tool):
        self.session.delete(tool)
        self.session.commit()

    # -- Prompt related methods

    def get_prompt_by_name(self, company: Company, prompt_name: str):
        return self.session.query(Prompt).filter_by(company_id=company.id, name=prompt_name).first()

    def get_prompts(self, company: Company, include_all: bool = False) -> list[Prompt]:
        if include_all:
            # Include all prompts (for the prompt admin dashboard)
            return self.session.query(Prompt).filter(
                Prompt.company_id == company.id,
            ).all()
        else:
            # Only active company prompts (default behavior for end users)
            return self.session.query(Prompt).filter(
                Prompt.company_id == company.id,
                Prompt.prompt_type == PromptType.COMPANY.value,
                Prompt.active == True
            ).all()

    def get_system_prompts(self) -> list[Prompt]:
        return self.session.query(Prompt).filter_by(prompt_type=PromptType.SYSTEM.value, active=True).order_by(
            Prompt.order).all()

    def create_or_update_prompt(self, new_prompt: Prompt):
        prompt = self.session.query(Prompt).filter_by(company_id=new_prompt.company_id,
                                                 name=new_prompt.name).first()
        if prompt:
            prompt.category_id = new_prompt.category_id
            prompt.description = new_prompt.description
            prompt.order = new_prompt.order
            prompt.prompt_type = new_prompt.prompt_type
            prompt.filename = new_prompt.filename
            prompt.custom_fields = new_prompt.custom_fields
        else:
            self.session.add(new_prompt)
            prompt = new_prompt

        self.session.commit()
        return prompt

    def delete_prompt(self, prompt: Prompt):
        self.session.delete(prompt)
        self.session.commit()

    # -- Prompt category methods

    def get_category_by_name(self, company_id: int, name: str) -> PromptCategory:
        return self.session.query(PromptCategory).filter_by(company_id=company_id, name=name).first()

    def get_all_categories(self, company_id: int) -> List[PromptCategory]:
        return self.session.query(PromptCategory).filter_by(company_id=company_id).order_by(PromptCategory.order).all()

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
