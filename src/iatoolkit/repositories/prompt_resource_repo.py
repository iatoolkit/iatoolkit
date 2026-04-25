# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from injector import inject

from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import PromptResourceBinding


class PromptResourceRepo:
    @inject
    def __init__(self, db_manager: DatabaseManager):
        self.session = db_manager.get_session()

    def list_by_prompt(self, prompt_id: int) -> list[PromptResourceBinding]:
        return (
            self.session.query(PromptResourceBinding)
            .filter(PromptResourceBinding.prompt_id == prompt_id)
            .order_by(PromptResourceBinding.binding_order.asc(), PromptResourceBinding.id.asc())
            .all()
        )

    def replace_bindings(
        self,
        prompt_id: int,
        bindings: list[PromptResourceBinding],
    ) -> list[PromptResourceBinding]:
        (
            self.session.query(PromptResourceBinding)
            .filter(PromptResourceBinding.prompt_id == prompt_id)
            .delete(synchronize_session="fetch")
        )
        for binding in bindings:
            self.session.add(binding)
        self.session.commit()
        return bindings
