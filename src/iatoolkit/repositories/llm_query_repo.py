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

    def list_system_tools(self) -> list[Tool]:
        return (
            self.session.query(Tool)
            .filter(Tool.tool_type == Tool.TYPE_SYSTEM)
            .filter(Tool.company_id.is_(None))
            .order_by(Tool.name.asc())
            .all()
        )

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
            if new_tool.is_active is not None:
                tool.is_active = new_tool.is_active
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
        editable_types = [PromptType.COMPANY.value, PromptType.AGENT.value]
        if include_all:
            # Include all prompts (for the prompt admin dashboard)
            return self.session.query(Prompt).filter(
                Prompt.company_id == company.id,
                Prompt.prompt_type.in_(editable_types),
            ).all()
        else:
            # Only active company prompts (default behavior for end users)
            return self.session.query(Prompt).filter(
                Prompt.company_id == company.id,
                Prompt.prompt_type == PromptType.COMPANY.value,
                Prompt.active == True
            ).all()

    def delete_prompts_by_type(self, company_id: int, prompt_types: list[str]) -> int:
        if not prompt_types:
            return 0

        deleted_count = (
            self.session.query(Prompt)
            .filter(
                Prompt.company_id == company_id,
                Prompt.prompt_type.in_(prompt_types),
            )
            .delete(synchronize_session=False)
        )
        self.session.commit()
        return int(deleted_count or 0)

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
            prompt.output_schema = new_prompt.output_schema
            prompt.output_schema_yaml = new_prompt.output_schema_yaml
            prompt.output_schema_mode = new_prompt.output_schema_mode or prompt.output_schema_mode or "best_effort"
            prompt.output_response_mode = (
                new_prompt.output_response_mode or prompt.output_response_mode or "chat_compatible"
            )
            prompt.attachment_mode = new_prompt.attachment_mode or prompt.attachment_mode or "extracted_only"
            prompt.attachment_parser_provider = (
                new_prompt.attachment_parser_provider or prompt.attachment_parser_provider or "basic"
            )
            prompt.attachment_fallback = new_prompt.attachment_fallback or prompt.attachment_fallback or "extract"
            prompt.llm_model = new_prompt.llm_model
            prompt.llm_request_options = dict(new_prompt.llm_request_options or {})
            prompt.tool_policy = dict(new_prompt.tool_policy or {})
        else:
            if not new_prompt.output_schema_mode:
                new_prompt.output_schema_mode = "best_effort"
            if not new_prompt.output_response_mode:
                new_prompt.output_response_mode = "chat_compatible"
            if not new_prompt.attachment_mode:
                new_prompt.attachment_mode = "extracted_only"
            if not new_prompt.attachment_parser_provider:
                new_prompt.attachment_parser_provider = "basic"
            if not new_prompt.attachment_fallback:
                new_prompt.attachment_fallback = "extract"
            if new_prompt.llm_request_options is None:
                new_prompt.llm_request_options = {}
            if new_prompt.tool_policy is None:
                new_prompt.tool_policy = {}
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
