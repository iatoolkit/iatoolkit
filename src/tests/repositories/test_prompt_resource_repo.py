# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, Prompt, PromptResourceBinding
from iatoolkit.repositories.prompt_resource_repo import PromptResourceRepo


class TestPromptResourceRepo:
    def setup_method(self):
        self.db_manager = DatabaseManager("sqlite:///:memory:")
        self.db_manager.create_all()
        self.session = self.db_manager.get_session()
        self.repo = PromptResourceRepo(self.db_manager)

        self.company = Company(name="Test Company", short_name="test-co")
        self.session.add(self.company)
        self.session.commit()

        self.prompt = Prompt(
            company_id=self.company.id,
            name="research_agent",
            description="Research agent",
            filename="research_agent.prompt",
        )
        self.session.add(self.prompt)
        self.session.commit()

    def test_replace_bindings_replaces_existing_prompt_scope(self):
        initial = PromptResourceBinding(
            prompt_id=self.prompt.id,
            resource_type="sql_source",
            resource_key="crm",
            binding_order=0,
            metadata_json={"label": "CRM"},
        )
        self.session.add(initial)
        self.session.commit()

        bindings = [
            PromptResourceBinding(
                prompt_id=self.prompt.id,
                resource_type="rag_collection",
                resource_key="Legal",
                binding_order=2,
                metadata_json={},
            )
        ]

        self.repo.replace_bindings(self.prompt.id, bindings)

        persisted = self.repo.list_by_prompt(self.prompt.id)
        assert len(persisted) == 1
        assert persisted[0].resource_type == "rag_collection"
        assert persisted[0].resource_key == "Legal"
        assert persisted[0].binding_order == 2

    def test_list_by_prompt_orders_by_binding_order(self):
        self.session.add_all(
            [
                PromptResourceBinding(
                    prompt_id=self.prompt.id,
                    resource_type="rag_collection",
                    resource_key="Support",
                    binding_order=5,
                    metadata_json={},
                ),
                PromptResourceBinding(
                    prompt_id=self.prompt.id,
                    resource_type="sql_source",
                    resource_key="erp",
                    binding_order=1,
                    metadata_json={},
                ),
            ]
        )
        self.session.commit()

        rows = self.repo.list_by_prompt(self.prompt.id)

        assert [row.resource_key for row in rows] == ["erp", "Support"]
