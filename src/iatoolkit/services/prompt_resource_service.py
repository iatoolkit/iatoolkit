# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import copy

from injector import inject

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from iatoolkit.repositories.models import PromptResourceBinding, PromptResourceType
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.repositories.prompt_resource_repo import PromptResourceRepo
from iatoolkit.repositories.sql_source_repo import SqlSourceRepo
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService


class PromptResourceService:
    @inject
    def __init__(
        self,
        profile_repo: ProfileRepo,
        llm_query_repo: LLMQueryRepo,
        prompt_resource_repo: PromptResourceRepo,
        sql_source_repo: SqlSourceRepo,
        knowledge_base_service: KnowledgeBaseService,
    ):
        self.profile_repo = profile_repo
        self.llm_query_repo = llm_query_repo
        self.prompt_resource_repo = prompt_resource_repo
        self.sql_source_repo = sql_source_repo
        self.knowledge_base_service = knowledge_base_service

    @staticmethod
    def _serialize_binding(binding: PromptResourceBinding) -> dict:
        return {
            "resource_type": binding.resource_type,
            "resource_key": binding.resource_key,
            "binding_order": int(binding.binding_order or 0),
            "metadata_json": copy.deepcopy(binding.metadata_json or {}),
        }

    @staticmethod
    def _normalize_metadata_json(value, field_name: str) -> dict:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"{field_name} must be an object.",
            )
        return copy.deepcopy(value)

    def _resolve_prompt(self, company_short_name: str, prompt_name: str):
        company = self.profile_repo.get_company_by_short_name(company_short_name)
        if not company:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_NAME,
                f"Company '{company_short_name}' not found",
            )

        prompt = self.llm_query_repo.get_prompt_by_name(company, prompt_name)
        if not prompt:
            raise IAToolkitException(
                IAToolkitException.ErrorType.DOCUMENT_NOT_FOUND,
                f"Prompt '{prompt_name}' not found",
            )
        return company, prompt

    @staticmethod
    def _normalize_resource_type(value: str | None) -> str:
        candidate = str(value or "").strip().lower()
        allowed = {item.value for item in PromptResourceType}
        if candidate not in allowed:
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                f"Unsupported resource_type '{candidate}'. Allowed values: {sorted(allowed)}",
            )
        return candidate

    @staticmethod
    def _normalize_resource_key(value: str | None, field_name: str) -> str:
        candidate = str(value or "").strip()
        if not candidate:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MISSING_PARAMETER,
                f"{field_name} is required.",
            )
        return candidate

    def _validate_resource_binding(self, *, company, company_short_name: str, resource_type: str, resource_key: str) -> None:
        if resource_type == PromptResourceType.SQL_SOURCE.value:
            source = self.sql_source_repo.get_by_database(company.id, resource_key)
            if not source:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.NOT_FOUND,
                    f"SQL source '{resource_key}' not found for company '{company_short_name}'",
                )
            return

        if resource_type == PromptResourceType.RAG_COLLECTION.value:
            descriptors = self.knowledge_base_service.get_collection_descriptors(company_short_name) or []
            available_names = {
                str(item.get("name") or "").strip()
                for item in descriptors
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
            if resource_key not in available_names:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.NOT_FOUND,
                    f"RAG collection '{resource_key}' not found for company '{company_short_name}'",
                )

    def get_prompt_resource_bindings(self, company_short_name: str, prompt_name: str) -> dict:
        _, prompt = self._resolve_prompt(company_short_name, prompt_name)
        bindings = self.prompt_resource_repo.list_by_prompt(prompt.id)
        return {"data": {"items": [self._serialize_binding(binding) for binding in bindings]}}

    def set_prompt_resource_bindings(
        self,
        company_short_name: str,
        prompt_name: str,
        payload: dict,
        *,
        actor_identifier: str | None = None,
    ) -> dict:
        if not isinstance(payload, dict):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "payload must be an object.",
            )

        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise IAToolkitException(
                IAToolkitException.ErrorType.INVALID_PARAMETER,
                "items must be a list.",
            )

        company, prompt = self._resolve_prompt(company_short_name, prompt_name)

        bindings: list[PromptResourceBinding] = []
        seen_bindings: set[tuple[str, str]] = set()
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    f"items[{index}] must be an object.",
                )

            resource_type = self._normalize_resource_type(item.get("resource_type"))
            resource_key = self._normalize_resource_key(item.get("resource_key"), f"items[{index}].resource_key")
            self._validate_resource_binding(
                company=company,
                company_short_name=company_short_name,
                resource_type=resource_type,
                resource_key=resource_key,
            )
            dedupe_key = (resource_type, resource_key)
            if dedupe_key in seen_bindings:
                continue
            seen_bindings.add(dedupe_key)

            bindings.append(
                PromptResourceBinding(
                    prompt_id=prompt.id,
                    resource_type=resource_type,
                    resource_key=resource_key,
                    binding_order=int(item.get("binding_order") or index),
                    metadata_json=self._normalize_metadata_json(
                        item.get("metadata_json"),
                        f"items[{index}].metadata_json",
                    ),
                    updated_by=actor_identifier,
                )
            )

        persisted = self.prompt_resource_repo.replace_bindings(prompt.id, bindings)
        return {"data": {"items": [self._serialize_binding(binding) for binding in persisted]}}
