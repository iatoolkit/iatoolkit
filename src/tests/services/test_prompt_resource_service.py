from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.prompt_resource_service import PromptResourceService


class TestPromptResourceService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.profile_repo = MagicMock()
        self.llm_query_repo = MagicMock()
        self.prompt_resource_repo = MagicMock()
        self.sql_source_repo = MagicMock()
        self.knowledge_base_service = MagicMock()

        self.service = PromptResourceService(
            profile_repo=self.profile_repo,
            llm_query_repo=self.llm_query_repo,
            prompt_resource_repo=self.prompt_resource_repo,
            sql_source_repo=self.sql_source_repo,
            knowledge_base_service=self.knowledge_base_service,
        )

        self.company = SimpleNamespace(id=1, short_name="test-co")
        self.prompt = SimpleNamespace(id=11, name="research_agent")
        self.profile_repo.get_company_by_short_name.return_value = self.company
        self.llm_query_repo.get_prompt_by_name.return_value = self.prompt

    def test_get_prompt_resource_bindings_serializes_items(self):
        self.prompt_resource_repo.list_by_prompt.return_value = [
            SimpleNamespace(
                resource_type="sql_source",
                resource_key="crm",
                binding_order=0,
                metadata_json={"label": "CRM"},
            )
        ]

        result = self.service.get_prompt_resource_bindings("test-co", "research_agent")

        assert result == {
            "data": {
                "items": [
                    {
                        "resource_type": "sql_source",
                        "resource_key": "crm",
                        "binding_order": 0,
                        "metadata_json": {"label": "CRM"},
                    }
                ]
            }
        }

    def test_set_prompt_resource_bindings_validates_and_persists(self):
        self.sql_source_repo.get_by_database.return_value = SimpleNamespace(database="crm")
        self.knowledge_base_service.get_collection_descriptors.return_value = [
            {"name": "Legal", "description": "Contracts"},
        ]
        self.prompt_resource_repo.replace_bindings.side_effect = lambda prompt_id, bindings: bindings

        result = self.service.set_prompt_resource_bindings(
            "test-co",
            "research_agent",
            {
                "items": [
                    {"resource_type": "sql_source", "resource_key": "crm"},
                    {"resource_type": "rag_collection", "resource_key": "Legal", "binding_order": 7},
                ]
            },
            actor_identifier="owner@example.com",
        )

        persisted_bindings = self.prompt_resource_repo.replace_bindings.call_args.args[1]
        assert len(persisted_bindings) == 2
        assert persisted_bindings[0].prompt_id == 11
        assert persisted_bindings[0].updated_by == "owner@example.com"
        assert persisted_bindings[1].binding_order == 7
        assert result["data"]["items"][1]["resource_type"] == "rag_collection"

    def test_set_prompt_resource_bindings_rejects_unknown_resource(self):
        self.sql_source_repo.get_by_database.return_value = None

        with pytest.raises(IAToolkitException) as exc_info:
            self.service.set_prompt_resource_bindings(
                "test-co",
                "research_agent",
                {"items": [{"resource_type": "sql_source", "resource_key": "missing"}]},
            )

        assert exc_info.value.error_type == IAToolkitException.ErrorType.NOT_FOUND

    def test_set_prompt_resource_bindings_deduplicates_same_resource(self):
        self.sql_source_repo.get_by_database.return_value = SimpleNamespace(database="crm")
        self.prompt_resource_repo.replace_bindings.side_effect = lambda prompt_id, bindings: bindings

        result = self.service.set_prompt_resource_bindings(
            "test-co",
            "research_agent",
            {
                "items": [
                    {"resource_type": "sql_source", "resource_key": "crm"},
                    {"resource_type": "sql_source", "resource_key": "crm", "binding_order": 3},
                ]
            },
        )

        persisted_bindings = self.prompt_resource_repo.replace_bindings.call_args.args[1]
        assert len(persisted_bindings) == 1
        assert result["data"]["items"] == [
            {
                "resource_type": "sql_source",
                "resource_key": "crm",
                "binding_order": 0,
                "metadata_json": {},
            }
        ]
